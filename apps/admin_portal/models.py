import uuid
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from apps.accounts.models import User
from apps.orders.models import Order


class AdminActionLog(models.Model):
    ACTION_TYPES = [
        ('user_suspend', 'Suspend User'),
        ('user_reactivate', 'Reactivate User'),
        ('user_delete', 'Delete User'),
        ('order_approve', 'Approve Order'),
        ('order_reject', 'Reject Order'),
        ('order_start', 'Start Order'),
        ('order_deliver', 'Deliver Order'),
        ('order_complete', 'Complete Order'),
        ('refund_approve', 'Approve Refund'),
        ('refund_deny', 'Deny Refund'),
        ('payment_release', 'Release Payment'),
        ('content_edit', 'Edit Content'),
        ('settings_change', 'Change Setting'),
        ('wallet_adjust', 'Adjust Wallet'),
        ('announcement_create', 'Create Announcement'),
        ('announcement_update', 'Update Announcement'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='admin_actions',
        db_index=True
    )
    action_type = models.CharField(
        max_length=25, 
        choices=ACTION_TYPES, 
        db_index=True
    )
    target_user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='targeted_actions'
    )
    target_order = models.ForeignKey(
        Order, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['admin', 'created_at']),
            models.Index(fields=['action_type', 'created_at']),
            models.Index(fields=['target_user']),
            models.Index(fields=['target_order']),
            models.Index(fields=['created_at']),
        ]
        ordering = ['-created_at']
        db_table = 'admin_action_logs'

    def __str__(self):
        return f"{self.admin.email} - {self.action_type} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    @classmethod
    def log_action(cls, admin, action_type, **kwargs):
        return cls.objects.create(
            admin=admin,
            action_type=action_type,
            target_user=kwargs.get('target_user'),
            target_order=kwargs.get('target_order'),
            details=kwargs.get('details', {}),
            ip_address=kwargs.get('ip_address'),
            user_agent=kwargs.get('user_agent', '')
        )


class SystemSetting(models.Model):
    SETTING_TYPES = [
        ('text', 'Text'),
        ('number', 'Number'),
        ('boolean', 'Boolean'),
        ('json', 'JSON'),
        ('email', 'Email'),
        ('url', 'URL'),
    ]
    
    CACHE_KEY_PREFIX = 'system_setting_'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=100, unique=True, db_index=True)
    value = models.TextField()
    type = models.CharField(max_length=20, choices=SETTING_TYPES, default='text')
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'system_settings'
        indexes = [
            models.Index(fields=['key']),
            models.Index(fields=['is_public']),
        ]

    def __str__(self):
        return f"{self.key} = {self.value[:50]}"

    def get_typed_value(self):
        if self.type == 'number':
            return float(self.value) if '.' in self.value else int(self.value)
        elif self.type == 'boolean':
            return self.value.lower() in ('true', '1', 'yes', 'on')
        elif self.type == 'json':
            import json
            try:
                return json.loads(self.value)
            except:
                return {}
        elif self.type == 'email':
            return self.value.strip()
        elif self.type == 'url':
            return self.value.strip()
        return self.value

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from django.core.cache import cache
        cache.delete(f'{self.CACHE_KEY_PREFIX}{self.key}')

    @classmethod
    def get_setting(cls, key, default=None):
        from django.core.cache import cache
        cache_key = f'{cls.CACHE_KEY_PREFIX}{key}'
        value = cache.get(cache_key)
        
        if value is not None:
            return value
        
        try:
            setting = cls.objects.get(key=key)
            value = setting.get_typed_value()
            cache.set(cache_key, value, 3600)
            return value
        except cls.DoesNotExist:
            return default


class SiteContent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.CharField(max_length=50, db_index=True)
    section = models.CharField(max_length=50)
    title = models.CharField(max_length=200)
    content = models.TextField()
    meta_data = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True, db_index=True)
    updated_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True
    )
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['page', 'section']
        indexes = [
            models.Index(fields=['page', 'is_active']),
            models.Index(fields=['section']),
        ]
        db_table = 'site_content'

    def __str__(self):
        return f"{self.page} - {self.section}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from django.core.cache import cache
        cache.delete(f'site_content_{self.page}_{self.section}')

    @classmethod
    def get_content(cls, page, section):
        from django.core.cache import cache
        cache_key = f'site_content_{page}_{section}'
        content = cache.get(cache_key)
        
        if content is not None:
            return content
        
        try:
            content_obj = cls.objects.get(page=page, section=section, is_active=True)
            cache.set(cache_key, content_obj, 3600)
            return content_obj
        except cls.DoesNotExist:
            return None


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
    overdue_orders = models.IntegerField(default=0)
    
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deposits = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_refunds = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pending_payments = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    average_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['date', 'created_at']),
        ]
        db_table = 'platform_stats'
        ordering = ['-date']

    def __str__(self):
        return f"Stats for {self.date}"

    @classmethod
    def get_today_stats(cls):
        from django.core.cache import cache
        cache_key = 'platform_stats_today'
        stats = cache.get(cache_key)
        
        if stats is not None:
            return stats
        
        today = timezone.now().date()
        stats, created = cls.objects.get_or_create(date=today)
        
        if created:
            stats.update_stats()
        
        cache.set(cache_key, stats, 300)
        return stats

    def update_stats(self):
        from django.db.models import Count, Sum, Avg, Q
        from apps.accounts.models import User
        from apps.orders.models import Order
        
        today = timezone.now().date()
        
        self.total_users = User.objects.filter(is_active=True).count()
        self.new_users = User.objects.filter(
            created_at__date=today,
            is_active=True
        ).count()
        self.active_users = User.objects.filter(
            last_login__date=today,
            is_active=True
        ).count()
        
        order_stats = Order.objects.filter(
            created_at__date=today
        ).aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(status='pending')),
            ongoing=Count('id', filter=Q(status='in_progress')),
            completed=Count('id', filter=Q(status='completed')),
            cancelled=Count('id', filter=Q(status='cancelled')),
            overdue=Count('id', filter=Q(deadline__lt=timezone.now(), status__in=['pending', 'in_progress'])),
            avg_value=Avg('total_price'),
            total_revenue=Sum('total_price', filter=Q(status='completed')),
        )
        
        self.total_orders = order_stats['total'] or 0
        self.pending_orders = order_stats['pending'] or 0
        self.ongoing_orders = order_stats['ongoing'] or 0
        self.completed_orders = order_stats['completed'] or 0
        self.cancelled_orders = order_stats['cancelled'] or 0
        self.overdue_orders = order_stats['overdue'] or 0
        self.average_order_value = order_stats['avg_value'] or 0
        self.total_revenue = order_stats['total_revenue'] or 0
        
        self.save()


class Announcement(models.Model):
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    TARGET_CHOICES = [
        ('all', 'All Users'),
        ('clients', 'Clients Only'),
        ('admin', 'Admin Only'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    content = models.TextField()
    priority = models.CharField(
        max_length=10, 
        choices=PRIORITY_CHOICES, 
        default='medium',
        db_index=True
    )
    target_audience = models.CharField(
        max_length=10,
        choices=TARGET_CHOICES,
        default='all'
    )
    is_active = models.BooleanField(default=True, db_index=True)
    starts_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True
    )
    viewed_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['is_active', 'priority']),
            models.Index(fields=['starts_at', 'expires_at']),
            models.Index(fields=['target_audience']),
        ]
        db_table = 'announcements'
        ordering = ['-starts_at']

    def __str__(self):
        return self.title

    def is_current(self):
        now = timezone.now()
        return (
            self.is_active and 
            self.starts_at <= now and 
            (self.expires_at is None or self.expires_at > now)
        )

    @classmethod
    def get_active_announcements(cls, user=None):
        from django.core.cache import cache
        cache_key = 'active_announcements'
        announcements = cache.get(cache_key)
        
        if announcements is not None:
            return announcements
        
        now = timezone.now()
        queryset = cls.objects.filter(
            is_active=True,
            starts_at__lte=now
        ).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        ).order_by('-priority', '-starts_at')
        
        if user:
            if user.role == 'admin':
                queryset = queryset.filter(
                    models.Q(target_audience='all') | models.Q(target_audience='admin')
                )
            else:
                queryset = queryset.filter(
                    models.Q(target_audience='all') | models.Q(target_audience='clients')
                )
        
        announcements = list(queryset[:10])
        cache.set(cache_key, announcements, 300)
        return announcements

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from django.core.cache import cache
        cache.delete('active_announcements')


class AdminNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='admin_notes'
    )
    title = models.CharField(max_length=200)
    content = models.TextField()
    order = models.ForeignKey(
        Order, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    client = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='admin_notes_about'
    )
    is_pinned = models.BooleanField(default=False, db_index=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['admin', 'is_pinned']),
            models.Index(fields=['admin', 'is_archived']),
            models.Index(fields=['order']),
            models.Index(fields=['client']),
        ]
        db_table = 'admin_notes'
        ordering = ['-is_pinned', '-created_at']

    def __str__(self):
        return f"{self.title} - {self.admin.email}"