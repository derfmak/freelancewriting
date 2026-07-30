import uuid
import secrets
import random
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone
from django.core.cache import cache
from .managers import UserManager


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    ROLE_CHOICES = [
        ('client', 'Client'),
        ('admin', 'Admin'),
    ]
    
    username = None
    email = models.EmailField(unique=True, db_index=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='client', db_index=True)
    
    full_name = models.CharField(max_length=100)
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$')
    phone = models.CharField(validators=[phone_regex], max_length=17, blank=True)
    phone_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False, db_index=True)
    
    institution = models.CharField(max_length=100, blank=True)
    
    otp_secret = models.CharField(max_length=100, blank=True)
    otp_expires = models.DateTimeField(null=True, blank=True)
    password_reset_token = models.CharField(max_length=100, blank=True, db_index=True)
    password_reset_expires = models.DateTimeField(null=True, blank=True)
    
    password_change_code = models.CharField(max_length=6, blank=True, db_index=True)
    password_change_code_expires = models.DateTimeField(null=True, blank=True)
    password_change_temp = models.CharField(max_length=128, blank=True)
    
    is_suspended = models.BooleanField(default=False, db_index=True)
    suspension_reason = models.TextField(blank=True)
    suspended_until = models.DateTimeField(null=True, blank=True)
    
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_login_user_agent = models.TextField(blank=True)
    failed_login_attempts = models.IntegerField(default=0)
    last_failed_login = models.DateTimeField(null=True, blank=True)
    account_locked_until = models.DateTimeField(null=True, blank=True)
    
    deletion_requested_at = models.DateTimeField(null=True, blank=True)
    deletion_scheduled_for = models.DateTimeField(null=True, blank=True)
    
    google_id = models.CharField(max_length=100, blank=True, db_index=True)
    picture = models.URLField(max_length=500, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        indexes = [
            models.Index(fields=['email', 'role']),
            models.Index(fields=['is_suspended', 'email_verified']),
            models.Index(fields=['password_reset_token']),
            models.Index(fields=['password_change_code']),
            models.Index(fields=['deletion_scheduled_for']),
            models.Index(fields=['created_at']),
            models.Index(fields=['last_login']),
            models.Index(fields=['google_id']),
        ]
        db_table = 'users'
        
    def __str__(self):
        return f"{self.email}"
        
    def lock_account(self, minutes=30):
        self.account_locked_until = timezone.now() + timezone.timedelta(minutes=minutes)
        self.save(update_fields=['account_locked_until'])
        
    def increment_failed_login(self):
        self.failed_login_attempts += 1
        self.last_failed_login = timezone.now()
        if self.failed_login_attempts >= 5:
            self.lock_account()
        self.save(update_fields=['failed_login_attempts', 'last_failed_login', 'account_locked_until'])
        
    def reset_failed_login(self):
        self.failed_login_attempts = 0
        self.account_locked_until = None
        self.save(update_fields=['failed_login_attempts', 'account_locked_until'])
    
    def generate_otp(self):
        otp = ''.join(str(random.randint(0, 9)) for _ in range(6))
        self.otp_secret = otp
        self.otp_expires = timezone.now() + timezone.timedelta(minutes=10)
        self.save(update_fields=['otp_secret', 'otp_expires'])
        return otp
    
    def verify_otp(self, otp):
        if not self.otp_secret or not self.otp_expires:
            return False
        if timezone.now() > self.otp_expires:
            return False
        if self.otp_secret != otp:
            return False
        self.otp_secret = ''
        self.otp_expires = None
        self.email_verified = True
        self.save(update_fields=['otp_secret', 'otp_expires', 'email_verified'])
        return True
    
    def generate_password_change_code(self):
        code = ''.join(str(random.randint(0, 9)) for _ in range(6))
        self.password_change_code = code
        self.password_change_code_expires = timezone.now() + timezone.timedelta(minutes=5)
        self.save(update_fields=['password_change_code', 'password_change_code_expires'])
        return code
    
    def verify_password_change_code(self, code):
        if not self.password_change_code or not self.password_change_code_expires:
            return False
        if timezone.now() > self.password_change_code_expires:
            return False
        if self.password_change_code != code:
            return False
        return True
    
    def clear_password_change_code(self):
        self.password_change_code = ''
        self.password_change_code_expires = None
        self.password_change_temp = ''
        self.save(update_fields=['password_change_code', 'password_change_code_expires', 'password_change_temp'])
    
    def set_temp_password(self, password):
        from django.contrib.auth.hashers import make_password
        self.password_change_temp = make_password(password)
        self.save(update_fields=['password_change_temp'])
    
    def apply_temp_password(self):
        if self.password_change_temp:
            self.password = self.password_change_temp
            self.password_change_temp = ''
            self.save(update_fields=['password', 'password_change_temp'])
            return True
        return False


class PendingUser(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=100)
    password = models.CharField(max_length=128)
    phone = models.CharField(max_length=17, blank=True)
    institution = models.CharField(max_length=100, blank=True)
    otp_code = models.CharField(max_length=6)
    otp_expires = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        db_table = 'pending_users'
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['otp_code']),
            models.Index(fields=['created_at']),
        ]
    
    def is_expired(self):
        return timezone.now() > self.otp_expires
    
    def __str__(self):
        return f"{self.email}"


class LoginLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='login_logs')
    email = models.EmailField(db_index=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    success = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'login_logs'
        indexes = [
            models.Index(fields=['email', 'created_at']),
            models.Index(fields=['ip_address', 'created_at']),
            models.Index(fields=['success']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.email} - {self.success} - {self.created_at}"


class RateLimit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=255, unique=True, db_index=True)
    count = models.IntegerField(default=0)
    window_start = models.DateTimeField(auto_now_add=True, db_index=True)
    window_end = models.DateTimeField()
    
    class Meta:
        db_table = 'rate_limits'
        indexes = [
            models.Index(fields=['key', 'window_end']),
        ]
    
    @classmethod
    def is_allowed(cls, key, limit, window_seconds):
        now = timezone.now()
        window_start = now - timezone.timedelta(seconds=window_seconds)
        
        try:
            record = cls.objects.get(key=key)
        except cls.DoesNotExist:
            cls.objects.create(key=key, count=1, window_end=now + timezone.timedelta(seconds=window_seconds))
            return True
        
        if record.window_end < now:
            record.count = 1
            record.window_end = now + timezone.timedelta(seconds=window_seconds)
            record.save()
            return True
        
        if record.count >= limit:
            return False
        
        record.count += 1
        record.save()
        return True


class PasswordChangeVerification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_verifications')
    code = models.CharField(max_length=6)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'password_change_verifications'
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['code']),
            models.Index(fields=['expires_at']),
        ]
    
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    def __str__(self):
        return f"{self.user.email} - {self.code}"


class SecurityEvent(models.Model):
    EVENT_TYPES = [
        ('rate_limit_hit', 'Rate Limit Hit'),
        ('register_attempt', 'Registration Attempt'),
        ('register_success', 'Registration Success'),
        ('register_duplicate', 'Duplicate Registration'),
        ('otp_verification_failed', 'OTP Verification Failed'),
        ('email_send_failed', 'Email Send Failed'),
        ('login_success', 'Login Success'),
        ('login_failed', 'Login Failed'),
        ('login_user_not_found', 'Login User Not Found'),
        ('account_locked', 'Account Locked'),
        ('token_refresh_failed', 'Token Refresh Failed'),
        ('password_reset', 'Password Reset'),
        ('password_changed', 'Password Changed'),
        ('google_callback_no_code', 'Google Callback No Code'),
        ('google_token_exchange_failed', 'Google Token Exchange Failed'),
        ('google_token_verification_failed', 'Google Token Verification Failed'),
        ('google_login_success', 'Google Login Success'),
        ('google_signup_redirect', 'Google Signup Redirect'),
        ('google_signup_success', 'Google Signup Success'),
        ('google_signup_rollback', 'Google Signup Rollback'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, db_index=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='security_events')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'security_events'
        ordering = ['-created_at']
        verbose_name = 'Security Event'
        verbose_name_plural = 'Security Events'
        indexes = [
            models.Index(fields=['event_type', '-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['ip_address', '-created_at']),
        ]

    def __str__(self):
        return f"{self.event_type} - {self.ip_address} - {self.created_at}"