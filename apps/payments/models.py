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
    currency = models.CharField(max_length=3, default='USD')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wallets'
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        return f"{self.user.email} - Balance: ${self.balance}"

    @property
    def balance(self):
        from django.db.models import Sum
        credits = Transaction.objects.filter(
            wallet=self,
            direction='credit',
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        debits = Transaction.objects.filter(
            wallet=self,
            direction='debit',
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        return credits - debits

    @property
    def total_in(self):
        from django.db.models import Sum
        return Transaction.objects.filter(
            wallet=self,
            direction='credit',
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    @property
    def total_out(self):
        from django.db.models import Sum
        return Transaction.objects.filter(
            wallet=self,
            direction='debit',
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')


class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('payment', 'Payment'),
        ('payout', 'Payout'),
        ('refund', 'Refund'),
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
        ('adjustment', 'Adjustment'),
    ]

    DIRECTION_CHOICES = [
        ('credit', 'Credit'),
        ('debit', 'Debit'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    PAYMENT_METHODS = [
        ('paypal', 'PayPal'),
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
    direction = models.CharField(max_length=20, choices=DIRECTION_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='paypal')

    description = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict)

    paypal_transaction_id = models.CharField(max_length=255, blank=True)
    paypal_response = models.JSONField(default=dict)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    signature = models.CharField(max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'transactions'
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['wallet', 'type']),
            models.Index(fields=['wallet', 'direction']),
            models.Index(fields=['user', 'type', 'status']),
            models.Index(fields=['transaction_id']),
            models.Index(fields=['paypal_transaction_id']),
            models.Index(fields=['order', 'type']),
            models.Index(fields=['signature']),
        ]
        ordering = ['-created_at']

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
    PAYPAL_ACCOUNT_TYPES = [
        ('personal', 'Personal'),
        ('business', 'Business'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_methods')
    
    paypal_email = models.EmailField(db_index=True)
    paypal_account_type = models.CharField(max_length=20, choices=PAYPAL_ACCOUNT_TYPES, default='personal')
    paypal_verified = models.BooleanField(default=False)
    
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payment_methods'
        unique_together = ['user', 'paypal_email']
        indexes = [
            models.Index(fields=['user', 'is_default']),
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['paypal_email']),
        ]

    def __str__(self):
        return f"PayPal: {self.paypal_email}"


class PaymentIntent(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    intent_id = models.CharField(max_length=100, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_intents')

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')

    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.SET_NULL, null=True)
    transaction = models.ForeignKey(Transaction, on_delete=models.SET_NULL, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    return_url = models.URLField(blank=True)
    cancel_url = models.URLField(blank=True)

    metadata = models.JSONField(default=dict)
    paypal_response = models.JSONField(default=dict)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'payment_intents'
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['intent_id']),
            models.Index(fields=['expires_at']),
        ]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    def is_expired(self):
        return timezone.now() > self.expires_at


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
    
    paypal_email = models.EmailField()
    paypal_payout_id = models.CharField(max_length=255, blank=True)
    paypal_response = models.JSONField(default=dict)
    
    metadata = models.JSONField(default=dict)
    
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_payouts')
    rejection_reason = models.TextField(blank=True)
    
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payouts'
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['payout_id']),
            models.Index(fields=['paypal_payout_id']),
        ]

    def __str__(self):
        return f"{self.payout_id} - ${self.amount} - {self.status}"

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
        db_table = 'paypal_webhooks'
        indexes = [
            models.Index(fields=['event_type', 'processed']),
            models.Index(fields=['resource_id']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.webhook_id} - {self.event_type} - {self.resource_id}"

    def mark_processed(self, errors=''):
        self.processed = True
        self.processed_at = timezone.now()
        self.processing_errors = errors
        self.save(update_fields=['processed', 'processed_at', 'processing_errors'])