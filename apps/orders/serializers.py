from rest_framework import serializers
from django.utils import timezone
from django.db.models import Sum, Count, Q
from apps.accounts.models import User
from apps.orders.models import Order
from apps.payments.models import Transaction, Wallet
from .models import AdminActionLog, SystemSetting, SiteContent, Announcement, AdminNote, PlatformStats


class UserAdminSerializer(serializers.ModelSerializer):
    wallet_balance = serializers.SerializerMethodField()
    total_orders = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()
    total_revenue = serializers.SerializerMethodField()
    active_orders = serializers.SerializerMethodField()
    completed_orders = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'full_name', 'role', 'is_active', 'is_suspended',
            'email_verified', 'phone_verified', 'institution', 'phone',
            'last_login', 'date_joined', 'created_at',
            'wallet_balance', 'total_orders', 'total_spent', 'total_revenue',
            'active_orders', 'completed_orders',
            'failed_login_attempts', 'account_locked_until', 'suspension_reason'
        ]
        read_only_fields = ['id', 'last_login', 'date_joined', 'created_at']

    def get_wallet_balance(self, obj):
        try:
            return float(obj.wallet.balance) if hasattr(obj, 'wallet') else 0
        except:
            return 0

    def get_total_orders(self, obj):
        return obj.orders.count()

    def get_total_spent(self, obj):
        try:
            return float(obj.wallet.total_spent) if hasattr(obj, 'wallet') else 0
        except:
            return 0

    def get_total_revenue(self, obj):
        return obj.orders.filter(status='completed').aggregate(
            total=Sum('total_price')
        )['total'] or 0

    def get_active_orders(self, obj):
        return obj.orders.filter(
            status__in=['pending', 'ongoing', 'awaiting_review']
        ).count()

    def get_completed_orders(self, obj):
        return obj.orders.filter(status='completed').count()


class OrderAdminSerializer(serializers.ModelSerializer):
    client = serializers.PrimaryKeyRelatedField(source='student', read_only=True)
    client_name = serializers.CharField(source='student.full_name', default='N/A')
    client_email = serializers.EmailField(source='student.email', default='N/A')
    title = serializers.CharField(source='topic')
    description = serializers.CharField(source='instructions')
    word_count = serializers.IntegerField(source='words')
    total = serializers.DecimalField(source='total_price', max_digits=10, decimal_places=2)

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'client', 'client_name', 'client_email',
            'title', 'description', 'word_count', 'deadline', 'status',
            'total_price', 'total', 'progress_percentage',
            'paper_type', 'academic_level', 'format',
            'rating', 'feedback', 'delivered_at', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'order_number', 'created_at', 'updated_at',
            'delivered_at', 'client'
        ]


class TransactionAdminSerializer(serializers.ModelSerializer):
    client_email = serializers.EmailField(source='user.email', default='N/A')
    client_name = serializers.CharField(source='user.full_name', default='N/A')
    order_number = serializers.CharField(source='order.order_number', default='N/A')

    class Meta:
        model = Transaction
        fields = [
            'id', 'user', 'client_email', 'client_name',
            'order', 'order_number', 'amount', 'type', 'status',
            'payment_method', 'reference', 'description',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class DashboardStatsSerializer(serializers.Serializer):
    total_users = serializers.IntegerField()
    new_users_today = serializers.IntegerField()
    active_users = serializers.IntegerField()

    total_orders = serializers.IntegerField()
    pending_orders = serializers.IntegerField()
    in_progress_orders = serializers.IntegerField()
    completed_today = serializers.IntegerField()

    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    revenue_today = serializers.DecimalField(max_digits=12, decimal_places=2)
    pending_payouts = serializers.DecimalField(max_digits=12, decimal_places=2)

    average_rating = serializers.DecimalField(max_digits=3, decimal_places=2)
    completion_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    overdue_orders = serializers.IntegerField()
    unread_messages = serializers.IntegerField()


class PriorityQueueSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order_number = serializers.CharField()
    client_name = serializers.CharField()
    deadline = serializers.CharField()
    urgency = serializers.CharField()
    status = serializers.CharField()


class SystemSettingSerializer(serializers.ModelSerializer):
    typed_value = serializers.SerializerMethodField()

    class Meta:
        model = SystemSetting
        fields = [
            'id', 'key', 'value', 'typed_value', 'type',
            'description', 'is_public', 'updated_at', 'created_at'
        ]
        read_only_fields = ['id', 'updated_at', 'created_at']

    def get_typed_value(self, obj):
        return obj.get_typed_value()


class SiteContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteContent
        fields = [
            'id', 'page', 'section', 'title', 'content',
            'meta_data', 'is_active', 'updated_at', 'created_at'
        ]
        read_only_fields = ['id', 'updated_at', 'created_at']


class AnnouncementSerializer(serializers.ModelSerializer):
    is_current = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.full_name', default='System')

    class Meta:
        model = Announcement
        fields = [
            'id', 'title', 'content', 'priority', 'target_audience',
            'is_active', 'is_current', 'starts_at', 'expires_at',
            'created_by', 'created_by_name', 'viewed_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'viewed_count', 'created_at', 'updated_at']

    def get_is_current(self, obj):
        return obj.is_current()


class AdminActionLogSerializer(serializers.ModelSerializer):
    admin_name = serializers.CharField(source='admin.full_name', default='System')
    admin_email = serializers.EmailField(source='admin.email', default='')
    target_user_email = serializers.EmailField(source='target_user.email', default=None)
    target_order_number = serializers.CharField(source='target_order.order_number', default=None)
    action_display = serializers.CharField(source='get_action_type_display')

    class Meta:
        model = AdminActionLog
        fields = [
            'id', 'admin', 'admin_name', 'admin_email',
            'action_type', 'action_display',
            'target_user', 'target_user_email',
            'target_order', 'target_order_number',
            'details', 'ip_address', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class WalletAdjustSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(required=True)
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        required=True
    )
    reason = serializers.CharField(max_length=500, required=True)
    type = serializers.ChoiceField(choices=['credit', 'debit'], required=True)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value


class AdminNoteSerializer(serializers.ModelSerializer):
    admin_name = serializers.CharField(source='admin.full_name', default='')
    order_number = serializers.CharField(source='order.order_number', default=None)
    client_name = serializers.CharField(source='client.full_name', default=None)
    client_email = serializers.EmailField(source='client.email', default=None)

    class Meta:
        model = AdminNote
        fields = [
            'id', 'admin', 'admin_name', 'title', 'content',
            'order', 'order_number', 'client', 'client_name', 'client_email',
            'is_pinned', 'is_archived', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'admin', 'created_at', 'updated_at']


class PlatformStatsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformStats
        fields = '__all__'
        read_only_fields = ['id', 'created_at']


class RefundActionSerializer(serializers.Serializer):
    order_id = serializers.UUIDField(required=True)
    reason = serializers.CharField(max_length=500, required=True)
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True
    )
    notify_client = serializers.BooleanField(default=True)

    def validate_amount(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value