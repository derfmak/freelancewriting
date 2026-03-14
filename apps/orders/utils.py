import hashlib
import secrets
import string
from PyPDF2 import PdfReader
from PIL import Image
import docx
import openpyxl
from django.utils import timezone

def generate_order_number():
    year = timezone.now().strftime('%y')
    random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"ORD-{year}-{random_part}"

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
        file.seek(0)
        img = Image.open(file)
        img.verify()
        file.seek(0)
        return False, None
    except Exception as e:
        return True, f"Corrupt image: {str(e)}"

def check_pdf_integrity(file):
    try:
        file.seek(0)
        pdf = PdfReader(file)
        if len(pdf.pages) == 0:
            return True, "PDF has no pages"
        return False, None
    except Exception as e:
        return True, f"Corrupt PDF: {str(e)}"

def check_word_integrity(file):
    try:
        file.seek(0)
        doc = docx.Document(file)
        return False, None
    except Exception as e:
        return True, f"Corrupt Word document: {str(e)}"

def check_excel_integrity(file):
    try:
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