import hashlib
import secrets
import string
import uuid
import re
from datetime import datetime, timedelta
from decimal import Decimal
from django.utils import timezone
from django.core.exceptions import ValidationError
from urllib.parse import urlparse


def generate_order_number():
    year = timezone.now().strftime('%Y')
    month = timezone.now().strftime('%m')
    day = timezone.now().strftime('%d')
    
    from apps.orders.models import Order
    
    last_order = Order.objects.filter(
        order_number__startswith=f'#{year}{month}{day}'
    ).order_by('-order_number').first()
    
    if last_order:
        try:
            sequence = int(last_order.order_number[-4:]) + 1
        except ValueError:
            sequence = 1
    else:
        sequence = 1
    
    if sequence > 9999:
        timestamp = int(timezone.now().timestamp() * 1000) % 10000
        return f'#{year}{month}{day}{timestamp:04d}'
    
    return f'#{year}{month}{day}{sequence:04d}'


def calculate_file_hash(file):
    hasher = hashlib.sha256()
    for chunk in file.chunks():
        hasher.update(chunk)
    file.seek(0)
    return hasher.hexdigest()


def check_file_integrity(file, mime_type):
    try:
        file.seek(0)
        
        if mime_type.startswith('image/'):
            return check_image_integrity(file)
        elif mime_type == 'application/pdf':
            return check_pdf_integrity(file)
        elif mime_type in ['application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
            return check_word_integrity(file)
        elif mime_type in ['application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']:
            return check_excel_integrity(file)
        elif mime_type == 'text/plain':
            return check_text_integrity(file)
        
        return False, None
        
    except Exception as e:
        return True, str(e)


def check_image_integrity(file):
    try:
        from PIL import Image
        file.seek(0)
        img = Image.open(file)
        img.verify()
        file.seek(0)
        return False, None
    except Exception as e:
        return True, f"Corrupt image: {str(e)}"


def check_pdf_integrity(file):
    try:
        from PyPDF2 import PdfReader
        file.seek(0)
        pdf = PdfReader(file)
        if len(pdf.pages) == 0:
            return True, "PDF has no pages"
        return False, None
    except Exception as e:
        return True, f"Corrupt PDF: {str(e)}"


def check_word_integrity(file):
    try:
        import docx
        file.seek(0)
        doc = docx.Document(file)
        return False, None
    except Exception as e:
        return True, f"Corrupt Word document: {str(e)}"


def check_excel_integrity(file):
    try:
        import openpyxl
        file.seek(0)
        wb = openpyxl.load_workbook(file)
        return False, None
    except Exception as e:
        return True, f"Corrupt Excel file: {str(e)}"


def check_text_integrity(file):
    try:
        file.seek(0)
        content = file.read().decode('utf-8')
        return False, None
    except UnicodeDecodeError:
        return True, "File is not valid UTF-8 text"
    except Exception as e:
        return True, f"Corrupt text file: {str(e)}"


def scan_file_for_viruses(file_data):
    try:
        import clamd
        cd = clamd.ClamdUnix()
        result = cd.instream(file_data)
        
        if result and result.get('stream') and result['stream'][0] == 'FOUND':
            virus_name = result['stream'][1]
            return True, virus_name
        return False, None
        
    except ImportError:
        try:
            import requests
            from django.conf import settings
            response = requests.post(
                'https://www.virustotal.com/api/v3/files',
                headers={'x-apikey': settings.VIRUSTOTAL_API_KEY},
                files={'file': file_data}
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('data', {}).get('attributes', {}).get('last_analysis_stats', {}).get('malicious', 0) > 0:
                    return True, "Malware detected"
            return False, None
        except:
            return False, None
        
    except Exception as e:
        return False, None


def sanitize_url(url):
    if not url:
        return ''
    
    dangerous_protocols = ['javascript:', 'data:', 'vbscript:', 'file:']
    for protocol in dangerous_protocols:
        if url.lower().startswith(protocol):
            return ''
    
    url = url.replace('<', '&lt;').replace('>', '&gt;')
    url = url.replace('"', '&quot;').replace("'", '&#039;')
    
    return url


def validate_url(url):
    if not url:
        return False
    
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        
        dangerous_protocols = ['javascript:', 'data:', 'vbscript:', 'file:']
        for protocol in dangerous_protocols:
            if url.lower().startswith(protocol):
                return False
        
        return True
    except:
        return False


def sanitize_links(links):
    if not links:
        return []
    
    sanitized = []
    for link in links:
        if isinstance(link, dict):
            url = link.get('url', '')
            title = link.get('title', '')
            url = sanitize_url(url)
            if url:
                sanitized.append({'url': url, 'title': title})
        elif isinstance(link, str):
            url = sanitize_url(link)
            if url:
                sanitized.append({'url': url, 'title': ''})
    
    return sanitized


def get_deadline_display(deadline):
    if not deadline:
        return 'No deadline'
    
    now = timezone.now()
    diff = deadline - now
    
    if diff.total_seconds() < 0:
        return 'Overdue'
    
    days = diff.days
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60
    
    if days > 0:
        return f'{days}d {hours}h remaining'
    elif hours > 0:
        return f'{hours}h {minutes}m remaining'
    else:
        return f'{minutes}m remaining'


def get_urgency_level(deadline):
    if not deadline:
        return 'normal'
    
    now = timezone.now()
    hours_remaining = (deadline - now).total_seconds() / 3600
    
    if hours_remaining <= 12:
        return 'emergency'
    elif hours_remaining <= 24:
        return 'urgent'
    elif hours_remaining <= 48:
        return 'high'
    elif hours_remaining <= 72:
        return 'medium'
    else:
        return 'normal'


def get_urgency_color(deadline):
    urgency = get_urgency_level(deadline)
    colors = {
        'emergency': '#dc2626',
        'urgent': '#f59e0b',
        'high': '#f97316',
        'medium': '#3b82f6',
        'normal': '#22c55e'
    }
    return colors.get(urgency, '#22c55e')


def get_urgency_label(deadline):
    urgency = get_urgency_level(deadline)
    labels = {
        'emergency': 'Emergency',
        'urgent': 'Urgent',
        'high': 'High Priority',
        'medium': 'Medium Priority',
        'normal': 'Normal'
    }
    return labels.get(urgency, 'Normal')


def calculate_deadline_from_pages(pages, paper_type):
    if paper_type == 'presentation':
        return max(24, pages * 2)
    
    if pages <= 3:
        return 12
    elif pages <= 5:
        return 24
    elif pages <= 10:
        return 48
    elif pages <= 20:
        return 72
    else:
        return 96


def format_price(amount):
    if amount is None:
        return '$0.00'
    return f'${float(amount):.2f}'


def format_percentage(value):
    if value is None:
        return '0%'
    return f'{int(value)}%'


def get_status_display(status):
    display_map = {
        'request': 'Request',
        'in_progress': 'In Progress',
        'awaiting_approval': 'Awaiting Approval',
        'completed': 'Completed',
        'cancelled': 'Cancelled',
        'declined': 'Declined',
        'refund_pending': 'Refund Pending',
    }
    return display_map.get(status, status.replace('_', ' ').title())


def get_status_color(status):
    color_map = {
        'request': 'yellow',
        'in_progress': 'blue',
        'awaiting_approval': 'purple',
        'completed': 'green',
        'cancelled': 'red',
        'declined': 'red',
        'refund_pending': 'orange',
    }
    return color_map.get(status, 'gray')


def get_status_icon(status):
    icon_map = {
        'request': 'fa-clock',
        'in_progress': 'fa-spinner',
        'awaiting_approval': 'fa-hourglass-half',
        'completed': 'fa-check-circle',
        'cancelled': 'fa-ban',
        'declined': 'fa-times-circle',
        'refund_pending': 'fa-hand-holding-usd',
    }
    return icon_map.get(status, 'fa-circle')


def truncate_text(text, max_length=100):
    if not text:
        return ''
    if len(text) <= max_length:
        return text
    return text[:max_length] + '...'


def extract_topic_summary(topic, max_length=50):
    if not topic:
        return 'No topic'
    return truncate_text(topic, max_length)


def get_order_progress(status):
    progress_map = {
        'request': 0,
        'in_progress': 50,
        'awaiting_approval': 80,
        'completed': 100,
        'cancelled': 0,
        'declined': 0,
        'refund_pending': 90,
    }
    return progress_map.get(status, 0)


def is_order_editable(status):
    return status in ['request', 'declined']


def is_order_cancellable(status):
    return status not in ['completed', 'cancelled']


def is_order_resubmittable(status):
    return status == 'declined'


def is_order_reorderable(status):
    return status in ['completed', 'cancelled']


def is_order_splittable(status, pages, words):
    if status not in ['request', 'in_progress']:
        return False
    if pages and pages >= 5:
        return True
    if words and words >= 1500:
        return True
    return False


def generate_uuid():
    return str(uuid.uuid4())


def parse_order_number(order_number):
    if not order_number or not order_number.startswith('#'):
        return None
    
    try:
        year = order_number[1:5]
        month = order_number[5:7]
        day = order_number[7:9]
        sequence = order_number[9:13]
        return {
            'year': year,
            'month': month,
            'day': day,
            'sequence': sequence,
            'date': f'{year}-{month}-{day}'
        }
    except:
        return None