import secrets
import string
import logging
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

def generate_otp():
    return ''.join(secrets.choice(string.digits) for _ in range(6))

def generate_reset_token():
    return secrets.token_urlsafe(32)

def send_otp_email(email, otp, full_name):
    subject = 'Verify Your Email - AcademicWrite'
    context = {
        'email': email,
        'otp': otp,
        'full_name': full_name,
        'expiry_minutes': 10
    }
    
    try:
        html_message = render_to_string('emails/otp_verification.html', context)
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            html_message=html_message,
            fail_silently=False
        )
        logger.info(f"OTP email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send OTP email to {email}: {str(e)}")
        return False

def send_password_reset_email(email, token, full_name):
    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    subject = 'Reset Your Password - AcademicWrite'
    context = {
        'email': email,
        'reset_link': reset_link,
        'full_name': full_name,
        'expiry_hours': 1
    }
    
    try:
        html_message = render_to_string('emails/password_reset.html', context)
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            html_message=html_message,
            fail_silently=False
        )
        logger.info(f"Password reset email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send password reset email to {email}: {str(e)}")
        return False

def send_welcome_email(email, full_name):
    subject = 'Welcome to AcademicWrite!'
    context = {
        'email': email,
        'full_name': full_name
    }
    
    try:
        html_message = render_to_string('emails/welcome.html', context)
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            html_message=html_message,
            fail_silently=False
        )
        logger.info(f"Welcome email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send welcome email to {email}: {str(e)}")
        return False

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def get_client_user_agent(request):
    return request.META.get('HTTP_USER_AGENT', '')

def is_rate_limited(key, limit, window_seconds, cache):
    """
    Simple rate limiting using cache
    """
    cache_key = f'rate_limit_{key}'
    current = cache.get(cache_key, 0)
    
    if current >= limit:
        return True
    
    if current == 0:
        cache.set(cache_key, 1, window_seconds)
    else:
        cache.incr(cache_key)
    
    return False