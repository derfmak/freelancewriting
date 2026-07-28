from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from .models import User, PendingUser, LoginLog, RateLimit, PasswordChangeVerification


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = (
        'email', 'full_name', 'role', 'email_verified', 
        'is_active', 'is_suspended', 'last_login', 'created_at'
    )
    list_filter = (
        'role', 'is_suspended', 'email_verified', 'is_active', 
        'is_staff', 'is_superuser', 'phone_verified'
    )
    search_fields = ('email', 'full_name', 'phone', 'google_id')
    ordering = ('-created_at',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal Info'), {
            'fields': ('full_name', 'phone', 'phone_verified', 'institution', 'picture')
        }),
        (_('Permissions'), {
            'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
        }),
        (_('Verification'), {
            'fields': ('email_verified', 'otp_secret', 'otp_expires')
        }),
        (_('Security'), {
            'fields': (
                'is_suspended', 'suspension_reason', 'suspended_until',
                'failed_login_attempts', 'account_locked_until',
                'last_login_ip', 'last_login_user_agent'
            )
        }),
        (_('Password Change'), {
            'fields': ('password_change_code', 'password_change_code_expires', 'password_change_temp')
        }),
        (_('Google OAuth'), {
            'fields': ('google_id',)
        }),
        (_('Account Management'), {
            'fields': ('deletion_requested_at', 'deletion_scheduled_for')
        }),
        (_('Important Dates'), {
            'fields': ('last_login', 'created_at', 'updated_at')
        }),
    )
    
    readonly_fields = (
        'created_at', 'updated_at', 'last_login', 
        'failed_login_attempts', 'last_login_ip', 'last_login_user_agent',
        'otp_secret', 'otp_expires', 'password_change_code', 
        'password_change_code_expires', 'password_change_temp',
        'google_id', 'picture'
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'full_name', 'password1', 'password2', 'role'),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related()

    def status_badge(self, obj):
        if obj.is_suspended:
            return format_html('<span style="color: #dc2626; font-weight: bold;">Suspended</span>')
        if not obj.email_verified:
            return format_html('<span style="color: #f59e0b; font-weight: bold;">Unverified</span>')
        if obj.is_active:
            return format_html('<span style="color: #059669; font-weight: bold;">Active</span>')
        return format_html('<span style="color: #6b7280; font-weight: bold;">Inactive</span>')
    status_badge.short_description = 'Status'

    def account_locked(self, obj):
        if obj.account_locked_until and obj.account_locked_until > obj.updated_at:
            return format_html('<span style="color: #dc2626;">Locked</span>')
        return format_html('<span style="color: #059669;">Unlocked</span>')
    account_locked.short_description = 'Lock Status'


@admin.register(PendingUser)
class PendingUserAdmin(admin.ModelAdmin):
    list_display = ('email', 'full_name', 'created_at', 'expires_at_display', 'is_expired_display')
    list_filter = ('created_at',)
    search_fields = ('email', 'full_name')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)

    def expires_at_display(self, obj):
        return obj.otp_expires
    expires_at_display.short_description = 'Expires At'

    def is_expired_display(self, obj):
        if obj.is_expired():
            return format_html('<span style="color: #dc2626;">Expired</span>')
        return format_html('<span style="color: #059669;">Active</span>')
    is_expired_display.short_description = 'Status'

    def has_add_permission(self, request):
        return False


@admin.register(LoginLog)
class LoginLogAdmin(admin.ModelAdmin):
    list_display = ('email', 'success', 'ip_address', 'created_at')
    list_filter = ('success', 'created_at')
    search_fields = ('email', 'ip_address')
    readonly_fields = ('email', 'ip_address', 'user_agent', 'success', 'created_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RateLimit)
class RateLimitAdmin(admin.ModelAdmin):
    list_display = ('key', 'count', 'window_start', 'window_end')
    list_filter = ('window_start', 'window_end')
    search_fields = ('key',)
    readonly_fields = ('key', 'count', 'window_start', 'window_end')
    ordering = ('-window_start',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PasswordChangeVerification)
class PasswordChangeVerificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'code', 'expires_at', 'used', 'created_at')
    list_filter = ('used', 'created_at', 'expires_at')
    search_fields = ('user__email', 'code')
    readonly_fields = ('user', 'code', 'expires_at', 'used', 'created_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False