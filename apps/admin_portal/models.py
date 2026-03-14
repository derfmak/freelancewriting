import uuid
from django.db import models
from django.utils import timezone
from apps.accounts.models import User
from apps.orders.models import Order

class AdminActionLog(models.Model):
    ACTION_TYPES = [
        ('user_suspend', 'user_suspend'),
        ('user_reactivate', 'user_reactivate'),
        ('user_delete', 'user_delete'),
        ('order_approve', 'order_approve'),
        ('order_reject', 'order_reject'),
        ('order_deliver', 'order_deliver'),
        ('refund_approve', 'refund_approve'),
        ('refund_deny', 'refund_deny'),
        ('content_edit', 'content_edit'),
        ('settings_change', 'settings_change'),
        ('wallet_adjust', 'wallet_adjust'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_actions')
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES, db_index=True)
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='targeted_actions')
    target_order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True)
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['admin', 'created_at']),
            models.Index(fields=['action_type', 'created_at']),
            models.Index(fields=['target_user']),
            models.Index(fields=['target_order']),
        ]
        ordering = ['-created_at']
        db_table = 'admin_action_logs'

class SystemSetting(models.Model):
    SETTING_TYPES = [
        ('text', 'text'),
        ('number', 'number'),
        ('boolean', 'boolean'),
        ('json', 'json'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=100, unique=True, db_index=True)
    value = models.TextField()
    type = models.CharField(max_length=20, choices=SETTING_TYPES, default='text')
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=False)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'system_settings'

class SiteContent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.CharField(max_length=50, db_index=True)
    section = models.CharField(max_length=50)
    title = models.CharField(max_length=200)
    content = models.TextField()
    meta_data = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['page', 'section']
        indexes = [
            models.Index(fields=['page', 'is_active']),
        ]
        db_table = 'site_content'

class PlatformStats(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date = models.DateField(unique=True, db_index=True)
    
    total_users = models.IntegerField(default=0)
    new_users = models.IntegerField(default=0)
    active_users = models.IntegerField(default=0)
    
    total_orders = models.IntegerField(default=0)
    pending_orders = models.IntegerField(default=0)
    ongoing_orders = models.IntegerField(default=0)
    completed_orders = models.IntegerField(default=0)
    cancelled_orders = models.IntegerField(default=0)
    
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deposits = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_refunds = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    average_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['date']),
        ]
        db_table = 'platform_stats'

class Announcement(models.Model):
    PRIORITY_CHOICES = [
        ('low', 'low'),
        ('medium', 'medium'),
        ('high', 'high'),
        ('urgent', 'urgent'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    content = models.TextField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['is_active', 'priority']),
            models.Index(fields=['starts_at', 'expires_at']),
        ]
        db_table = 'announcements'