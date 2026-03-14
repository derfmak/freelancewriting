from rest_framework import serializers
from django.utils import timezone
from apps.accounts.models import User
from apps.orders.models import Order
from apps.payments.models import Transaction, Wallet
from .models import AdminActionLog, SystemSetting, SiteContent, Announcement

class UserAdminSerializer(serializers.ModelSerializer):
    wallet_balance = serializers.SerializerMethodField()
    total_orders = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'role', 'is_active', 'is_suspended',
                  'email_verified', 'phone_verified', 'institution', 'course',
                  'last_login', 'date_joined', 'wallet_balance', 'total_orders',
                  'total_spent', 'failed_login_attempts', 'account_locked_until']
        read_only_fields = ['id', 'last_login', 'date_joined']
    
    def get_wallet_balance(self, obj):
        try:
            return float(obj.wallet.balance)
        except:
            return 0
    
    def get_total_orders(self, obj):
        return obj.orders.count()
    
    def get_total_spent(self, obj):
        try:
            return float(obj.wallet.total_spent)
        except:
            return 0

class OrderAdminSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.full_name')
    student_email = serializers.EmailField(source='student.email')
    
    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ['order_number', 'created_at', 'updated_at']

class TransactionAdminSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email')
    user_name = serializers.CharField(source='user.full_name')
    order_number = serializers.CharField(source='order.order_number', default=None)
    
    class Meta:
        model = Transaction
        fields = '__all__'

class DashboardStatsSerializer(serializers.Serializer):
    total_users = serializers.IntegerField()
    new_users_today = serializers.IntegerField()
    active_users = serializers.IntegerField()
    
    total_orders = serializers.IntegerField()
    pending_orders = serializers.IntegerField()
    ongoing_orders = serializers.IntegerField()
    completed_today = serializers.IntegerField()
    
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    revenue_today = serializers.DecimalField(max_digits=12, decimal_places=2)
    pending_payouts = serializers.DecimalField(max_digits=12, decimal_places=2)
    
    average_rating = serializers.DecimalField(max_digits=3, decimal_places=2)
    completion_rate = serializers.DecimalField(max_digits=5, decimal_places=2)

class SystemSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSetting
        fields = ['id', 'key', 'value', 'type', 'description', 'is_public', 'updated_at']
        read_only_fields = ['id', 'updated_at']

class SiteContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteContent
        fields = ['id', 'page', 'section', 'title', 'content', 'meta_data', 'is_active', 'updated_at']

class AnnouncementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Announcement
        fields = ['id', 'title', 'content', 'priority', 'is_active', 'starts_at', 'expires_at', 'created_at']

class AdminActionLogSerializer(serializers.ModelSerializer):
    admin_name = serializers.CharField(source='admin.full_name')
    target_user_email = serializers.EmailField(source='target_user.email', default=None)
    target_order_number = serializers.CharField(source='target_order.order_number', default=None)
    
    class Meta:
        model = AdminActionLog
        fields = ['id', 'admin_name', 'action_type', 'target_user_email', 
                  'target_order_number', 'details', 'ip_address', 'created_at']

class WalletAdjustSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    reason = serializers.CharField()
    type = serializers.ChoiceField(choices=['credit', 'debit'])