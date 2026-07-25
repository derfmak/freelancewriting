import uuid
import secrets
import hashlib
import hmac
from datetime import timedelta
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.utils import timezone
from apps.accounts.models import User
from apps.orders.models import Order


class Wallet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet', db_index=True)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    held_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    total_deposited = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_spent = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_refunded = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_withdrawn = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='USD')
    is_active = models.BooleanField(default=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.IntegerField(default=0)
    last_failed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['balance']),
            models.Index(fields=['held_balance']),
        ]
        db_table = 'wallets'

    def __str__(self):
        return f"{self.user.email} - ${self.balance}"

    @property
    def available_balance(self):
        return self.balance - self.held_balance

    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())

    def has_sufficient_balance(self, amount):
        return self.balance >= amount

    def has_sufficient_available_balance(self, amount):
        return self.available_balance >= amount

    def lock(self, minutes=30):
        self.locked_until = timezone.now() + timedelta(minutes=minutes)
        self.save(update_fields=['locked_until'])

    def unlock(self):
        self.locked_until = None
        self.failed_attempts = 0
        self.save(update_fields=['locked_until', 'failed_attempts'])

    def register_failed_attempt(self):
        self.failed_attempts += 1
        self.last_failed_at = timezone.now()
        if self.failed_attempts >= 5:
            self.lock(60)
        self.save(update_fields=['failed_attempts', 'last_failed_at', 'locked_until'])

    def hold_funds(self, amount):
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')
        if not self.has_sufficient_available_balance(amount):
            raise ValueError('Insufficient available balance')
        self.held_balance += amount
        self.save(update_fields=['held_balance'])

    def release_held_funds(self, amount):
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')
        if self.held_balance < amount:
            raise ValueError('Insufficient held balance')
        self.held_balance -= amount
        self.save(update_fields=['held_balance'])

    def settle_held_funds(self, amount):
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')
        if self.held_balance < amount:
            raise ValueError('Insufficient held balance')
        self.held_balance -= amount
        self.balance -= amount
        self.total_spent += amount
        self.save(update_fields=['held_balance', 'balance', 'total_spent'])


class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('deposit', 'Deposit'),
        ('hold', 'Hold'),
        ('release', 'Release'),
        ('settle', 'Settle'),
        ('refund', 'Refund'),
        ('payout', 'Payout'),
        ('withdrawal', 'Withdrawal'),
        ('adjustment', 'Adjustment'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    PAYMENT_METHODS = [
        ('stripe', 'Stripe'),
        ('paypal', 'PayPal'),
        ('wallet', 'Wallet'),
        ('admin', 'Admin'),
        ('system', 'System'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction_id = models.CharField(max_length=50, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions', db_index=True)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)

    description = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict)

    balance_before = models.DecimalField(max_digits=10, decimal_places=2)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)
    held_before = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    held_after = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    provider_transaction_id = models.CharField(max_length=255, blank=True)
    provider_response = models.JSONField(default=dict)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    signature = models.CharField(max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['user', 'type', 'status']),
            models.Index(fields=['transaction_id']),
            models.Index(fields=['provider_transaction_id']),
            models.Index(fields=['order', 'type']),
            models.Index(fields=['signature']),
        ]
        ordering = ['-created_at']
        db_table = 'transactions'

    def __str__(self):
        return f"{self.transaction_id} - {self.type} - {self.amount}"

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = self.generate_transaction_id()
        if not self.signature:
            self.signature = self.generate_signature()
        if self.fee_amount and not self.net_amount:
            self.net_amount = self.amount - self.fee_amount
        super().save(*args, **kwargs)

    def generate_transaction_id(self):
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random_part = secrets.token_hex(4).upper()
        return f"TXN-{timestamp}-{random_part}"

    def generate_signature(self):
        data = f"{self.transaction_id}{self.user.id}{self.amount}{self.type}{self.created_at}"
        return hashlib.sha256(data.encode()).hexdigest()

    def verify_signature(self):
        data = f"{self.transaction_id}{self.user.id}{self.amount}{self.type}{self.created_at}"
        expected = hashlib.sha256(data.encode()).hexdigest()
        return hmac.compare_digest(self.signature, expected)

    def complete(self):
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at'])

    def fail(self, reason):
        self.status = 'failed'
        self.metadata['failure_reason'] = reason
        self.save(update_fields=['status', 'metadata'])


class PaymentMethod(models.Model):
    CARD_BRANDS = [
        ('visa', 'Visa'),
        ('mastercard', 'Mastercard'),
        ('amex', 'American Express'),
        ('discover', 'Discover'),
        ('jcb', 'JCB'),
        ('diners', 'Diners Club'),
    ]

    PAYPAL_ACCOUNT_TYPES = [
        ('personal', 'Personal'),
        ('business', 'Business'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_methods')
    provider = models.CharField(max_length=20)
    provider_method_id = models.CharField(max_length=255, db_index=True)

    last_four = models.CharField(max_length=4, validators=[RegexValidator(r'^\d{4}$')])
    card_brand = models.CharField(max_length=20, choices=CARD_BRANDS, blank=True)
    cardholder_name = models.CharField(max_length=255, default='')

    expiry_month = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    expiry_year = models.IntegerField(validators=[MinValueValidator(2020), MaxValueValidator(2100)])

    fingerprint = models.CharField(max_length=255, blank=True, db_index=True)

    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_valid = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    billing_address_line1 = models.CharField(max_length=255, blank=True)
    billing_address_line2 = models.CharField(max_length=255, blank=True)
    billing_city = models.CharField(max_length=100, blank=True)
    billing_state = models.CharField(max_length=100, blank=True)
    billing_postal_code = models.CharField(max_length=20, blank=True)
    billing_country = models.CharField(max_length=2, default='US')

    paypal_email = models.EmailField(null=True, blank=True, db_index=True)
    paypal_account_type = models.CharField(max_length=20, choices=PAYPAL_ACCOUNT_TYPES, default='personal')
    paypal_verified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'provider_method_id']
        indexes = [
            models.Index(fields=['user', 'is_default']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['fingerprint']),
            models.Index(fields=['expiry_year', 'expiry_month']),
            models.Index(fields=['paypal_email']),
        ]
        db_table = 'payment_methods'

    def __str__(self):
        if self.paypal_email:
            return f"PayPal: {self.paypal_email}"
        return f"{self.card_brand} *{self.last_four}"

    def is_expired(self):
        now = timezone.now()
        return (self.expiry_year < now.year) or (self.expiry_year == now.year and self.expiry_month < now.month)

    def mask_card(self):
        return f"{self.card_brand} **** **** **** {self.last_four}"


class PaymentIntent(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('requires_action', 'Requires Action'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    intent_id = models.CharField(max_length=100, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_intents')

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')

    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.SET_NULL, null=True)
    transaction = models.ForeignKey(Transaction, on_delete=models.SET_NULL, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    client_secret = models.CharField(max_length=255)
    return_url = models.URLField(blank=True)

    metadata = models.JSONField(default=dict)
    provider_response = models.JSONField(default=dict)
    next_action = models.JSONField(default=dict)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['intent_id']),
            models.Index(fields=['expires_at']),
        ]
        db_table = 'payment_intents'

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    def is_expired(self):
        return timezone.now() > self.expires_at


class OrderPayment(models.Model):
    STATUS_CHOICES = [
        ('held', 'Held'),
        ('released', 'Released'),
        ('refunded', 'Refunded'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='payment')
    hold_transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name='order_payment_holds')
    release_transaction = models.ForeignKey(Transaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='order_payment_releases')

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='held')

    held_at = models.DateTimeField(auto_now_add=True)
    auto_release_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='released_order_payments')

    class Meta:
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['auto_release_at']),
        ]
        db_table = 'order_payments'

    def __str__(self):
        return f"{self.order.order_number} - {self.status}"

    def mark_released(self, release_transaction, admin_user=None):
        self.status = 'released'
        self.released_at = timezone.now()
        self.release_transaction = release_transaction
        self.released_by = admin_user
        self.save(update_fields=['status', 'released_at', 'release_transaction', 'released_by'])

    def mark_refunded(self, release_transaction, admin_user=None):
        self.status = 'refunded'
        self.released_at = timezone.now()
        self.release_transaction = release_transaction
        self.released_by = admin_user
        self.save(update_fields=['status', 'released_at', 'release_transaction', 'released_by'])


class FraudCheck(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, null=True, blank=True, related_name='fraud_checks')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='fraud_checks')

    risk_score = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    risk_level = models.CharField(max_length=20)

    ip_risk = models.FloatField(default=0)
    device_risk = models.FloatField(default=0)
    amount_risk = models.FloatField(default=0)
    velocity_risk = models.FloatField(default=0)

    flags = models.JSONField(default=list)

    is_blocked = models.BooleanField(default=False)
    requires_review = models.BooleanField(default=False)

    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_frauds')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['risk_level']),
            models.Index(fields=['requires_review']),
        ]
        db_table = 'fraud_checks'


class Payout(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payout_id = models.CharField(max_length=50, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payouts')
    transaction = models.ForeignKey(Transaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='payout')
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fee_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=2.00)
    net_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20)
    account_details = models.JSONField()
    metadata = models.JSONField(default=dict)
    provider_payout_id = models.CharField(max_length=255, blank=True)
    provider_response = models.JSONField(default=dict)
    
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_payouts')
    rejection_reason = models.TextField(blank=True)
    
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['payout_id']),
            models.Index(fields=['provider_payout_id']),
        ]
        db_table = 'payouts'

    def __str__(self):
        return f"{self.payout_id} - {self.amount} - {self.status}"

    def save(self, *args, **kwargs):
        if not self.payout_id:
            timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
            self.payout_id = f"PO-{timestamp}-{secrets.token_hex(3).upper()}"
        if self.fee_amount and not self.net_amount:
            self.net_amount = self.amount - self.fee_amount
        super().save(*args, **kwargs)

    def calculate_fees(self):
        from decimal import Decimal
        self.fee_amount = (self.amount * Decimal(str(self.fee_percentage))) / Decimal('100')
        self.net_amount = self.amount - self.fee_amount
        self.save(update_fields=['fee_amount', 'net_amount'])
        return {
            'fee_amount': self.fee_amount,
            'net_amount': self.net_amount
        }

    def complete(self):
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at'])

    def fail(self, reason):
        self.status = 'failed'
        self.metadata['failure_reason'] = reason
        self.save(update_fields=['status', 'metadata'])


class PayPalWebhook(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    webhook_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type = models.CharField(max_length=100, db_index=True)
    resource_id = models.CharField(max_length=255, db_index=True)
    payload = models.JSONField()
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_errors = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['event_type', 'processed']),
            models.Index(fields=['resource_id']),
            models.Index(fields=['created_at']),
        ]
        db_table = 'paypal_webhooks'

    def __str__(self):
        return f"{self.webhook_id} - {self.event_type} - {self.resource_id}"

    def mark_processed(self, errors=''):
        self.processed = True
        self.processed_at = timezone.now()
        self.processing_errors = errors
        self.save(update_fields=['processed', 'processed_at', 'processing_errors'])