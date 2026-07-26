from rest_framework import serializers
from decimal import Decimal
from django.utils import timezone
from django.db.models import Q
from .models import Wallet, Transaction, PaymentMethod, Payout, OrderPayment, PaymentIntent, FraudCheck


class WalletSerializer(serializers.ModelSerializer):
    available_balance = serializers.SerializerMethodField()
    total_holdings = serializers.SerializerMethodField()
    is_locked = serializers.BooleanField(read_only=True)
    balance_display = serializers.SerializerMethodField()
    held_balance_display = serializers.SerializerMethodField()
    available_balance_display = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = [
            'id', 'balance', 'balance_display', 'held_balance', 'held_balance_display',
            'available_balance', 'available_balance_display', 'total_holdings',
            'total_deposited', 'total_spent', 'total_refunded', 'total_withdrawn',
            'currency', 'is_active', 'is_locked', 'locked_until',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'balance', 'held_balance', 'total_deposited',
            'total_spent', 'total_refunded', 'total_withdrawn',
            'created_at', 'updated_at'
        ]

    def get_available_balance(self, obj):
        return obj.available_balance

    def get_total_holdings(self, obj):
        return obj.balance + obj.held_balance

    def get_balance_display(self, obj):
        return f"${obj.balance:.2f}"

    def get_held_balance_display(self, obj):
        return f"${obj.held_balance:.2f}"

    def get_available_balance_display(self, obj):
        return f"${obj.available_balance:.2f}"


class TransactionSerializer(serializers.ModelSerializer):
    amount_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    fee_display = serializers.SerializerMethodField()
    net_display = serializers.SerializerMethodField()
    is_verified = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_id', 'amount', 'amount_display',
            'fee_amount', 'fee_display', 'net_amount', 'net_display',
            'type', 'type_display', 'status', 'status_display',
            'payment_method', 'payment_method_display',
            'description', 'metadata',
            'balance_before', 'balance_after', 'held_before', 'held_after',
            'provider_transaction_id', 'provider_response',
            'ip_address', 'user_agent',
            'signature', 'is_verified',
            'created_at', 'updated_at', 'completed_at'
        ]
        read_only_fields = [
            'id', 'transaction_id', 'balance_before', 'balance_after',
            'held_before', 'held_after', 'signature',
            'created_at', 'updated_at', 'completed_at'
        ]

    def get_amount_display(self, obj):
        sign = '+' if obj.amount > 0 else ''
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


class DepositSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=5)
    payment_method = serializers.ChoiceField(choices=['stripe', 'paypal'])
    payment_method_id = serializers.CharField(required=False, allow_blank=True)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value < 5:
            raise serializers.ValidationError('Minimum deposit amount is $5.00')
        if value > 10000:
            raise serializers.ValidationError('Maximum deposit amount is $10,000.00')
        return value


class DepositConfirmSerializer(serializers.Serializer):
    payment_intent_id = serializers.CharField(required=True)


class WithdrawSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=10)
    payment_method = serializers.ChoiceField(choices=['paypal', 'bank'])
    account_details = serializers.JSONField()
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value < 10:
            raise serializers.ValidationError('Minimum withdrawal amount is $10.00')
        if value > 5000:
            raise serializers.ValidationError('Maximum withdrawal amount is $5,000.00')
        return value

    def validate_account_details(self, value):
        payment_method = self.initial_data.get('payment_method')
        
        if payment_method == 'paypal':
            if not value.get('email'):
                raise serializers.ValidationError('PayPal email is required')
        elif payment_method == 'bank':
            required = ['holder', 'routing', 'account']
            missing = [f for f in required if not value.get(f)]
            if missing:
                raise serializers.ValidationError(f'Missing bank details: {", ".join(missing)}')
        
        return value


class PaymentMethodSerializer(serializers.ModelSerializer):
    card_display = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)
    brand_display = serializers.CharField(source='get_card_brand_display', read_only=True)
    expiry_display = serializers.SerializerMethodField()
    payment_type = serializers.SerializerMethodField()
    is_paypal = serializers.SerializerMethodField()

    class Meta:
        model = PaymentMethod
        fields = [
            'id', 'provider', 'provider_method_id',
            'last_four', 'card_brand', 'brand_display',
            'cardholder_name', 'expiry_month', 'expiry_year',
            'expiry_display', 'is_expired',
            'is_default', 'is_active', 'is_valid',
            'last_used_at', 'card_display',
            'payment_type', 'is_paypal',
            'paypal_email', 'paypal_account_type', 'paypal_verified',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_card_display(self, obj):
        if obj.paypal_email:
            return f"PayPal: {obj.paypal_email}"
        return obj.mask_card()

    def get_expiry_display(self, obj):
        if obj.paypal_email:
            return 'N/A'
        return f"{obj.expiry_month:02d}/{obj.expiry_year}"

    def get_payment_type(self, obj):
        if obj.paypal_email:
            return 'paypal'
        return 'card'

    def get_is_paypal(self, obj):
        return bool(obj.paypal_email)


class AddPaymentMethodSerializer(serializers.Serializer):
    provider_method_id = serializers.CharField(required=False, allow_blank=True)
    last_four = serializers.CharField(min_length=4, max_length=4, required=False, allow_blank=True)
    card_brand = serializers.ChoiceField(choices=PaymentMethod.CARD_BRANDS, required=False, allow_blank=True)
    cardholder_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    expiry_month = serializers.IntegerField(min_value=1, max_value=12, required=False)
    expiry_year = serializers.IntegerField(min_value=2024, max_value=2100, required=False)
    set_default = serializers.BooleanField(default=False, required=False)
    payment_type = serializers.ChoiceField(choices=['card', 'paypal'], default='card')
    paypal_email = serializers.EmailField(required=False, allow_blank=True)
    paypal_account_type = serializers.ChoiceField(choices=PaymentMethod.PAYPAL_ACCOUNT_TYPES, default='personal', required=False)

    def validate(self, data):
        payment_type = data.get('payment_type', 'card')
        
        if payment_type == 'paypal':
            if not data.get('paypal_email'):
                raise serializers.ValidationError('PayPal email is required')
        else:
            required = ['last_four', 'card_brand', 'cardholder_name', 'expiry_month', 'expiry_year']
            missing = [f for f in required if not data.get(f)]
            if missing:
                raise serializers.ValidationError(f'Missing card details: {", ".join(missing)}')
            
            month = data.get('expiry_month')
            year = data.get('expiry_year')
            now = timezone.now()
            
            if year < now.year or (year == now.year and month < now.month):
                raise serializers.ValidationError('Card has expired')
        
        return data


class AddPayPalMethodSerializer(serializers.Serializer):
    paypal_email = serializers.EmailField(required=True)
    paypal_account_type = serializers.ChoiceField(choices=PaymentMethod.PAYPAL_ACCOUNT_TYPES, default='personal')
    set_default = serializers.BooleanField(default=False)


class PayPalDepositSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=5, max_value=10000)
    paypal_email = serializers.EmailField(required=False)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value < 5:
            raise serializers.ValidationError('Minimum deposit amount is $5.00')
        if value > 10000:
            raise serializers.ValidationError('Maximum deposit amount is $10,000.00')
        return value


class PayPalWithdrawSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=10, max_value=5000)
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
    payment_method_display = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = [
            'id', 'payout_id', 'amount', 'amount_display',
            'fee_amount', 'fee_display', 'fee_percentage',
            'net_amount', 'net_display',
            'status', 'status_display',
            'payment_method', 'payment_method_display',
            'account_details', 'metadata', 'provider_payout_id',
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

    def get_payment_method_display(self, obj):
        if obj.payment_method == 'paypal':
            email = obj.account_details.get('email', 'N/A')
            return f"PayPal ({email})"
        return obj.payment_method.title()


class OrderPaymentSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    hold_transaction_id = serializers.CharField(source='hold_transaction.transaction_id', read_only=True)
    release_transaction_id = serializers.CharField(source='release_transaction.transaction_id', read_only=True, default=None)
    amount_display = serializers.SerializerMethodField()
    status_display = serializers.SerializerMethodField()
    auto_release_display = serializers.SerializerMethodField()
    is_auto_releasable = serializers.SerializerMethodField()
    time_remaining = serializers.SerializerMethodField()

    class Meta:
        model = OrderPayment
        fields = [
            'id', 'order_id', 'order_number',
            'hold_transaction_id', 'release_transaction_id',
            'amount', 'amount_display',
            'status', 'status_display',
            'held_at', 'released_at',
            'auto_release_at', 'auto_release_display',
            'is_auto_releasable', 'time_remaining',
            'released_by'
        ]
        read_only_fields = [
            'id', 'held_at', 'released_at', 'auto_release_at', 'released_by'
        ]

    def get_amount_display(self, obj):
        return f"${obj.amount:.2f}"

    def get_status_display(self, obj):
        status_map = {
            'held': 'Held in Escrow',
            'released': 'Released',
            'refunded': 'Refunded'
        }
        return status_map.get(obj.status, obj.status.title())

    def get_auto_release_display(self, obj):
        if obj.auto_release_at:
            if obj.auto_release_at <= timezone.now():
                return 'Ready for auto-release'
            return f'Will auto-release at {obj.auto_release_at.strftime("%Y-%m-%d %H:%M")}'
        return 'No auto-release set'

    def get_is_auto_releasable(self, obj):
        return bool(obj.auto_release_at and obj.auto_release_at <= timezone.now())

    def get_time_remaining(self, obj):
        if obj.auto_release_at and obj.auto_release_at > timezone.now():
            delta = obj.auto_release_at - timezone.now()
            hours = int(delta.total_seconds() / 3600)
            minutes = int((delta.total_seconds() % 3600) / 60)
            if hours > 24:
                days = hours // 24
                return f"{days}d {hours % 24}h remaining"
            return f"{hours}h {minutes}m remaining"
        return None


class PaymentIntentSerializer(serializers.ModelSerializer):
    amount_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    next_action_display = serializers.SerializerMethodField()
    payment_method_type = serializers.SerializerMethodField()

    class Meta:
        model = PaymentIntent
        fields = [
            'id', 'intent_id', 'amount', 'amount_display',
            'currency', 'status', 'status_display',
            'client_secret', 'return_url',
            'metadata', 'next_action', 'next_action_display',
            'is_expired', 'payment_method_type',
            'created_at', 'updated_at', 'expires_at'
        ]
        read_only_fields = [
            'id', 'intent_id', 'client_secret', 'created_at', 'updated_at', 'expires_at'
        ]

    def get_amount_display(self, obj):
        return f"${obj.amount:.2f}"

    def get_next_action_display(self, obj):
        if obj.next_action:
            action_type = obj.next_action.get('type', '')
            if action_type == 'redirect_to_url':
                return 'Redirect to payment page'
            elif action_type == 'use_stripe_sdk':
                return 'Use Stripe SDK'
        return None

    def get_payment_method_type(self, obj):
        if obj.metadata and obj.metadata.get('paypal_payment_id'):
            return 'paypal'
        return 'stripe'


class FraudCheckSerializer(serializers.ModelSerializer):
    risk_level_display = serializers.CharField(source='get_risk_level_display', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    transaction_id = serializers.CharField(source='transaction.transaction_id', read_only=True, default=None)
    reviewed_by_name = serializers.CharField(source='reviewed_by.full_name', read_only=True, default='')

    class Meta:
        model = FraudCheck
        fields = [
            'id', 'transaction_id', 'user', 'user_email',
            'risk_score', 'risk_level', 'risk_level_display',
            'ip_risk', 'device_risk', 'amount_risk', 'velocity_risk',
            'flags', 'is_blocked', 'requires_review',
            'reviewed_by', 'reviewed_by_name',
            'reviewed_at', 'review_notes',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class TransferSerializer(serializers.Serializer):
    recipient_email = serializers.EmailField(required=True)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=1)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value < 1:
            raise serializers.ValidationError('Minimum transfer amount is $1.00')
        if value > 10000:
            raise serializers.ValidationError('Maximum transfer amount is $10,000.00')
        return value


class WalletStatsSerializer(serializers.Serializer):
    total_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_held = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_available = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_deposited = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_withdrawn = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_spent = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_refunded = serializers.DecimalField(max_digits=12, decimal_places=2)
    transaction_count = serializers.IntegerField()
    active_users = serializers.IntegerField()
    currency = serializers.CharField(default='USD')


class PaymentStatsSerializer(serializers.Serializer):
    total_deposits = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_withdrawals = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_payouts = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_refunds = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_fees = serializers.DecimalField(max_digits=12, decimal_places=2)
    success_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    pending_count = serializers.IntegerField()
    processing_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    paypal_deposits = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    paypal_withdrawals = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    stripe_deposits = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)


class WebhookSerializer(serializers.Serializer):
    event_type = serializers.CharField(required=True)
    resource_id = serializers.CharField(required=True)
    payload = serializers.JSONField(required=True)
    signature = serializers.CharField(required=True)
    timestamp = serializers.DateTimeField(required=False)

    def validate_signature(self, value):
        if len(value) < 32:
            raise serializers.ValidationError('Invalid signature format')
        return value