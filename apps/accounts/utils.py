import secrets
import string
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone

def generate_verification_code():
    return ''.join(secrets.choice(string.digits) for _ in range(6))

def generate_reset_token():
    return secrets.token_urlsafe(32)

def send_verification_email(email, code):
    subject = 'verify your email'
    message = f'your verification code is: {code}\nthis code expires in 24 hours.'
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])

def send_password_reset_email(email, token):
    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    subject = 'reset your password'
    message = f'click here to reset your password: {reset_link}\nthis link expires in 1 hour.'
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def get_client_user_agent(request):
    return request.META.get('HTTP_USER_AGENT', '')