from rest_framework import serializers
from .models import Wallet, Transaction, PaymentMethod, Payout, OrderPayment, PaymentIntent, FraudCheck

class WalletSerializer(serializers.ModelSerializer):
    available_balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    total_holdings = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Wallet
        fields = ['id', 'balance', 'pending_balance', 'held_balance', 'available_balance', 'total_holdings',
                  'total_deposited', 'total_spent', 'total_refunded', 'total_withdrawn',
                  'currency', 'is_active', 'locked_until', 'created_at', 'updated_at']
        read_only_fields = ['id', 'balance', 'pending_balance', 'held_balance', 'total_deposited',
                           'total_spent', 'total_refunded', 'total_withdrawn', 'created_at', 'updated_at']

    def get_available_balance(self, obj):
        return obj.balance - obj.held_balance

    def get_total_holdings(self, obj):
        return obj.balance + obj.held_balance + obj.pending_balance

class TransactionSerializer(serializers.ModelSerializer):
    amount_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)

    class Meta:
        model = Transaction
        fields = ['id', 'transaction_id', 'amount', 'amount_display', 'type', 'type_display',
                  'status', 'status_display', 'payment_method', 'description', 'metadata',
                  'balance_before', 'balance_after', 'held_before', 'held_after',
                  'provider_transaction_id', 'ip_address', 'created_at', 'completed_at']
        read_only_fields = ['id', 'transaction_id', 'balance_before', 'balance_after',
                           'held_before', 'held_after', 'created_at', 'completed_at']

    def get_amount_display(self, obj):
        return f"${abs(obj.amount)}"

class DepositSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=5)
    payment_method = serializers.ChoiceField(choices=['stripe', 'paypal'])
    payment_method_id = serializers.CharField(required=False, allow_blank=True)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value < 5:
            raise serializers.ValidationError('minimum deposit is $5')
        if value > 10000:
            raise serializers.ValidationError('maximum deposit is $10000')
        return value

class WithdrawSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=10)
    payment_method = serializers.CharField()
    account_details = serializers.JSONField()
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, value):
        if value < 10:
            raise serializers.ValidationError('minimum withdrawal is $10')
        if value > 5000:
            raise serializers.ValidationError('maximum withdrawal is $5000')
        return value

class PaymentMethodSerializer(serializers.ModelSerializer):
    card_display = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = PaymentMethod
        fields = ['id', 'provider', 'last_four', 'card_brand', 'cardholder_name',
                  'expiry_month', 'expiry_year', 'is_expired', 'is_default',
                  'is_active', 'card_display', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_card_display(self, obj):
        return obj.mask_card()

class AddPaymentMethodSerializer(serializers.Serializer):
    provider_method_id = serializers.CharField()
    last_four = serializers.CharField(min_length=4, max_length=4)
    card_brand = serializers.ChoiceField(choices=PaymentMethod.CARD_BRANDS)
    cardholder_name = serializers.CharField(max_length=255)
    expiry_month = serializers.IntegerField(min_value=1, max_value=12)
    expiry_year = serializers.IntegerField(min_value=2020, max_value=2100)

class PayoutSerializer(serializers.ModelSerializer):
    amount_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Payout
        fields = ['id', 'payout_id', 'amount', 'amount_display', 'status', 'status_display',
                  'payment_method', 'account_details', 'metadata', 'provider_payout_id',
                  'created_at', 'completed_at']
        read_only_fields = ['id', 'payout_id', 'status', 'created_at', 'completed_at']

    def get_amount_display(self, obj):
        return f"${obj.amount}"

class OrderPaymentSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    transaction_id = serializers.CharField(source='transaction.transaction_id', read_only=True)
    amount_display = serializers.SerializerMethodField()
    auto_release_display = serializers.SerializerMethodField()

    class Meta:
        model = OrderPayment
        fields = ['id', 'order_id', 'order_number', 'transaction_id', 'amount', 'amount_display',
                  'status', 'held_at', 'released_at', 'auto_release_at', 'auto_release_display']
        read_only_fields = ['id', 'held_at', 'released_at', 'auto_release_at']

    def get_amount_display(self, obj):
        return f"${obj.amount}"

    def get_auto_release_display(self, obj):
        if obj.auto_release_at > timezone.now():
            delta = obj.auto_release_at - timezone.now()
            hours = int(delta.total_seconds() / 3600)
            return f"auto-releases in {hours} hours"
        return "pending release"

class PaymentIntentSerializer(serializers.ModelSerializer):
    amount_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = PaymentIntent
        fields = ['id', 'intent_id', 'amount', 'amount_display', 'currency', 'status',
                  'status_display', 'client_secret', 'metadata', 'next_action',
                  'is_expired', 'created_at', 'expires_at']
        read_only_fields = ['id', 'intent_id', 'client_secret', 'created_at', 'expires_at']

    def get_amount_display(self, obj):
        return f"${obj.amount}"

class FraudCheckSerializer(serializers.ModelSerializer):
    risk_level_display = serializers.CharField(source='get_risk_level_display', read_only=True)

    class Meta:
        model = FraudCheck
        fields = ['id', 'risk_score', 'risk_level', 'risk_level_display', 'flags',
                  'is_blocked', 'requires_review', 'reviewed_at', 'review_notes']
        read_only_fields = ['id', 'created_at']