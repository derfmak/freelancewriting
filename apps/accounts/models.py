import uuid
import secrets
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone
from django.core.cache import cache
from .managers import UserManager

class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    ROLE_CHOICES = [
        ('client', 'client'),
        ('admin', 'admin'),
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
            models.Index(fields=['deletion_scheduled_for']),
            models.Index(fields=['created_at']),
            models.Index(fields=['last_login']),
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
        import random
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