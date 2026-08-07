import uuid
import secrets
import hashlib
import hmac
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
    phone_regex = RegexValidator(regex=r'^\+?[1-9]\d{1,14}$')
    phone = models.CharField(validators=[phone_regex], max_length=17, blank=True)
    phone_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False, db_index=True)

    institution = models.CharField(max_length=100, blank=True)

    otp_secret_hash = models.CharField(max_length=64, blank=True)
    otp_expires = models.DateTimeField(null=True, blank=True)

    password_reset_token_hash = models.CharField(max_length=64, blank=True, db_index=True)
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

    google_id = models.CharField(max_length=100, unique=True, null=True, blank=True, db_index=True)
    apple_id = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
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
            models.Index(fields=['password_reset_token_hash']),
            models.Index(fields=['deletion_scheduled_for']),
            models.Index(fields=['created_at']),
            models.Index(fields=['last_login']),
            models.Index(fields=['google_id']),
            models.Index(fields=['apple_id']),
        ]
        db_table = 'users'

    def __str__(self):
        return f"{self.email}"

    def _hash_value(self, value):
        return hashlib.sha256(value.encode()).hexdigest()

    def _verify_hash(self, plain, hashed):
        return hmac.compare_digest(self._hash_value(plain), hashed)

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
        otp = ''.join(secrets.choice('0123456789') for _ in range(6))
        self.otp_secret_hash = self._hash_value(otp)
        self.otp_expires = timezone.now() + timezone.timedelta(minutes=10)
        self.save(update_fields=['otp_secret_hash', 'otp_expires'])
        return otp

    def verify_otp(self, otp):
        if not self.otp_secret_hash or not self.otp_expires:
            return False
        if timezone.now() > self.otp_expires:
            return False
        if not self._verify_hash(otp, self.otp_secret_hash):
            return False
        self.otp_secret_hash = ''
        self.otp_expires = None
        self.email_verified = True
        self.save(update_fields=['otp_secret_hash', 'otp_expires', 'email_verified'])
        return True

    def generate_reset_token(self):
        token = secrets.token_urlsafe(32)
        self.password_reset_token_hash = self._hash_value(token)
        self.password_reset_expires = timezone.now() + timezone.timedelta(hours=1)
        self.save(update_fields=['password_reset_token_hash', 'password_reset_expires'])
        return token

    def verify_reset_token(self, token):
        if not self.password_reset_token_hash or not self.password_reset_expires:
            return False
        if timezone.now() > self.password_reset_expires:
            return False
        return self._verify_hash(token, self.password_reset_token_hash)

    def clear_reset_token(self):
        self.password_reset_token_hash = ''
        self.password_reset_expires = None
        self.save(update_fields=['password_reset_token_hash', 'password_reset_expires'])


class PendingUser(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=100)
    password = models.CharField(max_length=128)
    phone = models.CharField(max_length=17, blank=True)
    institution = models.CharField(max_length=100, blank=True)
    otp_code_hash = models.CharField(max_length=64)
    otp_expires = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'pending_users'
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['otp_code_hash']),
            models.Index(fields=['created_at']),
        ]

    def _hash_value(self, value):
        return hashlib.sha256(value.encode()).hexdigest()

    def _verify_hash(self, plain, hashed):
        return hmac.compare_digest(self._hash_value(plain), hashed)

    def set_otp(self, otp):
        self.otp_code_hash = self._hash_value(otp)
        self.otp_expires = timezone.now() + timezone.timedelta(minutes=10)
        self.save(update_fields=['otp_code_hash', 'otp_expires'])

    def verify_otp(self, otp):
        if not self.otp_code_hash or not self.otp_expires:
            return False
        if timezone.now() > self.otp_expires:
            return False
        return self._verify_hash(otp, self.otp_code_hash)

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
        from django.core.cache import cache
        cache_key = f'rate_limit_{key}'

        try:
            current = cache.get(cache_key, 0)
            if current >= limit:
                return False

            new_count = cache.incr(cache_key)
            if new_count == 1:
                cache.expire(cache_key, window_seconds)
            return True
        except ValueError:
            cache.set(cache_key, 1, window_seconds)
            return True


class PasswordChangeVerification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_verifications')
    code_hash = models.CharField(max_length=64, default='')
    temp_password_hash = models.CharField(max_length=128, blank=True, null=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'password_change_verifications'
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['code_hash']),
            models.Index(fields=['expires_at']),
        ]

    def _hash_value(self, value):
        return hashlib.sha256(value.encode()).hexdigest()

    def _verify_hash(self, plain, hashed):
        return hmac.compare_digest(self._hash_value(plain), hashed)

    def set_code(self, code):
        self.code_hash = self._hash_value(code)
        self.expires_at = timezone.now() + timezone.timedelta(minutes=5)
        self.used = False
        self.save(update_fields=['code_hash', 'expires_at', 'used'])

    def verify_code(self, code):
        if self.used:
            return False
        if timezone.now() > self.expires_at:
            return False
        if not self._verify_hash(code, self.code_hash):
            return False
        self.used = True
        self.save(update_fields=['used'])
        return True

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"{self.user.email} - {self.created_at}"


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
        ('apple_callback_no_code', 'Apple Callback No Code'),
        ('apple_token_exchange_failed', 'Apple Token Exchange Failed'),
        ('apple_token_verification_failed', 'Apple Token Verification Failed'),
        ('apple_login_success', 'Apple Login Success'),
        ('apple_signup_redirect', 'Apple Signup Redirect'),
        ('apple_signup_success', 'Apple Signup Success'),
        ('apple_signup_rollback', 'Apple Signup Rollback'),
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


class ClientNotification(models.Model):
    TYPES = (
        ('order', 'Order'),
        ('message', 'Message'),
        ('system', 'System'),
        ('warning', 'Warning'),
        ('info', 'Info'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='client_notifications', db_index=True)
    title = models.CharField(max_length=200)
    message = models.TextField()
    type = models.CharField(max_length=20, choices=TYPES, default='info')
    link = models.CharField(max_length=500, blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'created_at']),
        ]
        db_table = 'client_notifications'

    def __str__(self):
        return f"{self.title} - {self.user.email}"