from django.contrib import admin
from django.db import models
from django.utils.html import format_html
from django.utils import timezone
from .models import Order, Attachment, OrderHistory, OrderTimeline, UserPresence


class OrderTimelineInline(admin.TabularInline):
    model = OrderTimeline
    extra = 0
    fields = ['status', 'title', 'description', 'icon', 'color', 'created_at']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    max_num = 20


class OrderHistoryInline(admin.TabularInline):
    model = OrderHistory
    extra = 0
    fields = ['action', 'from_status', 'to_status', 'user', 'created_at']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    max_num = 50


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_number', 'client', 'writer', 'topic_short', 'status',
        'total_price', 'deadline_display', 'created_at'
    ]
    list_filter = [
        'status', 'academic_level', 'paper_type', 'created_at',
        'deadline', 'cancelled_at'
    ]
    search_fields = [
        'order_number', 'topic', 'subject', 'client__email',
        'client__full_name', 'writer__email', 'writer__full_name'
    ]
    readonly_fields = [
        'id', 'order_number', 'created_at', 'updated_at',
        'last_activity_at', 'escrow_released_at'
    ]
    inlines = [OrderTimelineInline, OrderHistoryInline]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'order_number', 'client', 'writer', 'status',
                'academic_level', 'paper_type', 'topic', 'subject',
                'instructions'
            )
        }),
        ('Pricing & Details', {
            'fields': (
                'pages', 'words', 'spacing', 'slides', 'sources_count',
                'deadline', 'format', 'base_price', 'level_multiplier',
                'level_adjusted', 'urgency_multiplier', 'total_price'
            )
        }),
        ('Progress & Dates', {
            'fields': (
                'progress_percentage', 'created_at', 'accepted_at',
                'started_at', 'delivered_at', 'completed_at',
                'auto_approve_at', 'last_activity_at'
            )
        }),
        ('Cancellation & Decline', {
            'fields': (
                'cancelled_at', 'cancelled_by', 'cancellation_reason',
                'cancellation_feedback', 'declined_at', 'declined_by',
                'declined_reason', 'declined_feedback'
            )
        }),
        ('Refund & Rating', {
            'fields': (
                'escrow_released_at', 'refund_amount', 'refund_reason',
                'refund_approved_at', 'refund_processed_at',
                'rating', 'feedback', 'grade_received'
            )
        }),
        ('Versioning & Splitting', {
            'fields': (
                'parent_order', 'version', 'is_template', 'template_name',
                'order_group', 'split_part', 'split_total'
            )
        }),
        ('Metadata', {
            'fields': (
                'id', 'attachments', 'links', 'delivered_file',
                'revision_count', 'last_revision_requested_at', 'updated_at'
            ),
            'classes': ('collapse',)
        }),
    )
    
    def topic_short(self, obj):
        return obj.topic[:50] + '...' if len(obj.topic) > 50 else obj.topic
    topic_short.short_description = 'Topic'
    
    def deadline_display(self, obj):
        if obj.deadline < timezone.now():
            return format_html('<span style="color: red;">{}</span>', obj.deadline.strftime('%Y-%m-%d %H:%M'))
        return obj.deadline.strftime('%Y-%m-%d %H:%M')
    deadline_display.short_description = 'Deadline'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'client', 'writer', 'cancelled_by', 'declined_by'
        )
    
    actions = ['mark_completed', 'mark_cancelled', 'refund_order']
    
    def mark_completed(self, request, queryset):
        updated = queryset.update(status='completed', completed_at=timezone.now())
        self.message_user(request, f'{updated} orders marked as completed.')
    mark_completed.short_description = 'Mark selected orders as completed'
    
    def mark_cancelled(self, request, queryset):
        updated = queryset.update(status='cancelled', cancelled_at=timezone.now())
        self.message_user(request, f'{updated} orders marked as cancelled.')
    mark_cancelled.short_description = 'Mark selected orders as cancelled'
    
    def refund_order(self, request, queryset):
        from apps.payments.services import WalletService
        count = 0
        for order in queryset:
            if order.status not in ['completed', 'cancelled']:
                WalletService.credit(
                    wallet=order.client.wallet,
                    amount=order.total_price,
                    transaction_type='refund',
                    description=f'Admin refund for order {order.order_number}',
                    order=order
                )
                count += 1
        self.message_user(request, f'{count} orders refunded.')
    refund_order.short_description = 'Refund selected orders'


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ['filename', 'uploaded_by', 'file_size', 'mime_type', 'scan_status', 'uploaded_at']
    list_filter = ['scan_status', 'is_corrupt', 'mime_type']
    search_fields = ['filename', 'uploaded_by__email', 'uploaded_by__full_name']
    readonly_fields = ['id', 'file_hash', 'uploaded_at']
    
    fieldsets = (
        ('File Information', {
            'fields': ('file', 'filename', 'file_size', 'mime_type', 'file_hash')
        }),
        ('Scan Information', {
            'fields': ('scan_status', 'scan_result', 'is_corrupt', 'corruption_error')
        }),
        ('Upload Information', {
            'fields': ('uploaded_by', 'uploaded_at')
        }),
    )


@admin.register(OrderHistory)
class OrderHistoryAdmin(admin.ModelAdmin):
    list_display = ['order', 'action', 'from_status', 'to_status', 'user', 'created_at']
    list_filter = ['action', 'from_status', 'to_status', 'created_at']
    search_fields = ['order__order_number', 'user__email', 'user__full_name']
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']


@admin.register(OrderTimeline)
class OrderTimelineAdmin(admin.ModelAdmin):
    list_display = ['order', 'status', 'title', 'color', 'created_at']
    list_filter = ['status', 'color']
    search_fields = ['order__order_number', 'title', 'description']
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']


@admin.register(UserPresence)
class UserPresenceAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_online', 'last_seen_at', 'current_room', 'updated_at']
    list_filter = ['is_online']
    search_fields = ['user__email', 'user__full_name', 'current_room']
    readonly_fields = ['id', 'updated_at']
    ordering = ['-last_seen_at']