from rest_framework import serializers
from decimal import Decimal
from django.utils import timezone
from django.db.models import Q
from .models import Wallet, Transaction, PaymentMethod, Payout, PaymentIntent


class WalletSerializer(serializers.ModelSerializer):
    balance_display = serializers.SerializerMethodField()
    total_in_display = serializers.SerializerMethodField()
    total_out_display = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = [
            'id', 'currency', 'is_active',
            'balance', 'balance_display',
            'total_in', 'total_in_display',
            'total_out', 'total_out_display',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_balance_display(self, obj):
        return f"${obj.balance:.2f}"

    def get_total_in_display(self, obj):
        return f"${obj.total_in:.2f}"

    def get_total_out_display(self, obj):
        return f"${obj.total_out:.2f}"


class TransactionSerializer(serializers.ModelSerializer):
    amount_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    direction_display = serializers.CharField(source='get_direction_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    fee_display = serializers.SerializerMethodField()
    net_display = serializers.SerializerMethodField()
    is_verified = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_id', 'amount', 'amount_display',
            'fee_amount', 'fee_display', 'net_amount', 'net_display',
            'type', 'type_display', 'direction', 'direction_display',
            'status', 'status_display',
            'payment_method', 'payment_method_display',
            'description', 'metadata',
            'paypal_transaction_id', 'paypal_response',
            'ip_address', 'user_agent',
            'signature', 'is_verified',
            'created_at', 'updated_at', 'completed_at'
        ]
        read_only_fields = [
            'id', 'transaction_id', 'signature',
            'created_at', 'updated_at', 'completed_at'
        ]

    def get_amount_display(self, obj):
        sign = '+' if obj.direction == 'credit' else '-'
        return f"{sign}${abs(obj.amount):.2f}"

    def get_fee_display(self, obj):
        if obj.fee_amount:
            return f"${obj.fee_amount:.2f}"
        return "$0.00"

    def get_net_display(self, obj):
        if obj.net_amount:
            return f"${obj.net_amount:.2f}"
        return None

    def get_is_verified(self, obj):
        return obj.verify_signature() if obj.signature else False


class TransactionDetailSerializer(TransactionSerializer):
    order_number = serializers.CharField(source='order.order_number', read_only=True, default=None)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_full_name = serializers.CharField(source='user.full_name', read_only=True, default='')

    class Meta(TransactionSerializer.Meta):
        fields = TransactionSerializer.Meta.fields + [
            'order_number', 'user_email', 'user_full_name'
        ]


class PaymentMethodSerializer(serializers.ModelSerializer):
    is_paypal = serializers.SerializerMethodField()

    class Meta:
        model = PaymentMethod
        fields = [
            'id', 'paypal_email', 'paypal_account_type',
            'paypal_verified', 'is_default', 'is_active',
            'is_paypal', 'last_used_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_is_paypal(self, obj):
        return True


class AddPayPalMethodSerializer(serializers.Serializer):
    paypal_email = serializers.EmailField(required=True)
    paypal_account_type = serializers.ChoiceField(
        choices=PaymentMethod.PAYPAL_ACCOUNT_TYPES,
        default='personal'
    )
    set_default = serializers.BooleanField(default=False)


class PayPalDepositSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=5,
        max_value=10000
    )
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value < 5:
            raise serializers.ValidationError('Minimum deposit amount is $5.00')
        if value > 10000:
            raise serializers.ValidationError('Maximum deposit amount is $10,000.00')
        return value


class PayPalWithdrawSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=10,
        max_value=5000
    )
    paypal_email = serializers.EmailField(required=True)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value < 10:
            raise serializers.ValidationError('Minimum withdrawal amount is $10.00')
        if value > 5000:
            raise serializers.ValidationError('Maximum withdrawal amount is $5,000.00')
        return value


class PayoutSerializer(serializers.ModelSerializer):
    amount_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    fee_display = serializers.SerializerMethodField()
    net_display = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = [
            'id', 'payout_id', 'amount', 'amount_display',
            'fee_amount', 'fee_display', 'fee_percentage',
            'net_amount', 'net_display',
            'status', 'status_display',
            'paypal_email', 'paypal_payout_id', 'paypal_response',
            'metadata',
            'approved_at', 'approved_by',
            'rejection_reason',
            'created_at', 'updated_at', 'completed_at'
        ]
        read_only_fields = [
            'id', 'payout_id', 'status', 'created_at', 'updated_at', 'completed_at'
        ]

    def get_amount_display(self, obj):
        return f"${obj.amount:.2f}"

    def get_fee_display(self, obj):
        if obj.fee_amount:
            return f"${obj.fee_amount:.2f}"
        return "$0.00"

    def get_net_display(self, obj):
        if obj.net_amount:
            return f"${obj.net_amount:.2f}"
        return None


class PaymentIntentSerializer(serializers.ModelSerializer):
    amount_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = PaymentIntent
        fields = [
            'id', 'intent_id', 'amount', 'amount_display',
            'currency', 'status', 'status_display',
            'return_url', 'cancel_url',
            'metadata', 'paypal_response',
            'is_expired',
            'created_at', 'updated_at', 'expires_at'
        ]
        read_only_fields = [
            'id', 'intent_id', 'created_at', 'updated_at', 'expires_at'
        ]

    def get_amount_display(self, obj):
        return f"${obj.amount:.2f}"


class WalletStatsSerializer(serializers.Serializer):
    total_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_in = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_out = serializers.DecimalField(max_digits=12, decimal_places=2)
    transaction_count = serializers.IntegerField()
    active_users = serializers.IntegerField()
    currency = serializers.CharField(default='USD')


class PaymentStatsSerializer(serializers.Serializer):
    total_deposits = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_withdrawals = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_payouts = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_refunds = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_users = serializers.IntegerField()
    currency = serializers.CharField(default='USD')