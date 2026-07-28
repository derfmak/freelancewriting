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
    
    verification_code = models.CharField(max_length=6, null=True, blank=True)
    verification_code_created_at = models.DateTimeField(null=True, blank=True)
    verification_attempts = models.IntegerField(default=0)
    verification_locked_until = models.DateTimeField(null=True, blank=True)
    
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

    def generate_verification_code(self):
        import random
        code = ''.join(random.choices('0123456789', k=6))
        self.verification_code = code
        self.verification_code_created_at = timezone.now()
        self.save(update_fields=['verification_code', 'verification_code_created_at'])
        return code

    def is_verification_code_expired(self):
        if not self.verification_code_created_at:
            return True
        elapsed = (timezone.now() - self.verification_code_created_at).total_seconds()
        return elapsed > 300

    def clear_verification_code(self):
        self.verification_code = None
        self.verification_code_created_at = None
        self.save(update_fields=['verification_code', 'verification_code_created_at'])


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


class AdminSetting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=100, unique=True, db_index=True)
    value = models.JSONField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'admin_settings'
        indexes = [
            models.Index(fields=['key', 'is_active']),
        ]

    def __str__(self):
        return f"{self.key}: {self.value}"

    @classmethod
    def get_value(cls, key, default=None):
        try:
            setting = cls.objects.get(key=key, is_active=True)
            return setting.value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set_value(cls, key, value, description=''):
        setting, created = cls.objects.update_or_create(
            key=key,
            defaults={
                'value': value,
                'description': description,
                'is_active': True
            }
        )
        return setting


class AdminWalletManager:
    
    @staticmethod
    def get_admin_user():
        from apps.accounts.models import User
        admin_user, created = User.objects.get_or_create(
            role='admin',
            is_superuser=True,
            defaults={
                'email': 'admin@academicwrite.com',
                'full_name': 'System Admin',
                'is_active': True,
                'is_staff': True
            }
        )
        if created:
            admin_user.set_password(secrets.token_urlsafe(16))
            admin_user.save()
        return admin_user
    
    @staticmethod
    def get_admin_wallet():
        admin_user = AdminWalletManager.get_admin_user()
        wallet, created = Wallet.objects.get_or_create(
            user=admin_user,
            defaults={
                'currency': 'USD',
                'is_active': True
            }
        )
        return wallet
    
    @staticmethod
    def get_admin_paypal_email():
        return AdminSetting.get_value(
            'admin_paypal_email',
            'admin@academicwrite.com'
        )
    
    @staticmethod
    def set_admin_paypal_email(email):
        return AdminSetting.set_value(
            'admin_paypal_email',
            email,
            'Primary PayPal email for receiving client payments'
        )
    
    @staticmethod
    def get_default_payment_method():
        return AdminSetting.get_value(
            'default_payment_method',
            'paypal'
        )
    
    @staticmethod
    def get_platform_fee_percentage():
        return Decimal(str(AdminSetting.get_value(
            'platform_fee_percentage',
            0.00
        )))
    
    @staticmethod
    def record_admin_credit(user, amount, order, description, payment_method='paypal'):
        admin_wallet = AdminWalletManager.get_admin_wallet()
        admin_user = admin_wallet.user
        
        Transaction.objects.create(
            user=admin_user,
            wallet=admin_wallet,
            amount=amount,
            type='payment',
            direction='credit',
            status='completed',
            payment_method=payment_method,
            description=f'Received {description} from {user.email}',
            order=order,
            completed_at=timezone.now()
        )
    
    @staticmethod
    def record_admin_debit(user, amount, order, description, payment_method='paypal'):
        admin_wallet = AdminWalletManager.get_admin_wallet()
        admin_user = admin_wallet.user
        
        Transaction.objects.create(
            user=admin_user,
            wallet=admin_wallet,
            amount=amount,
            type='payout',
            direction='debit',
            status='completed',
            payment_method=payment_method,
            description=f'Paid {description} to {user.email}',
            order=order,
            completed_at=timezone.now()
        )
    
    @staticmethod
    def record_client_debit(client, amount, order, description, payment_method='paypal'):
        Transaction.objects.create(
            user=client,
            wallet=client.wallet,
            amount=amount,
            type='payment',
            direction='debit',
            status='completed',
            payment_method=payment_method,
            description=description,
            order=order,
            completed_at=timezone.now()
        )
    
    @staticmethod
    def record_client_credit(client, amount, order, description, payment_method='paypal'):
        Transaction.objects.create(
            user=client,
            wallet=client.wallet,
            amount=amount,
            type='refund',
            direction='credit',
            status='completed',
            payment_method=payment_method,
            description=description,
            order=order,
            completed_at=timezone.now()
        )
    
    @staticmethod
    def record_writer_credit(writer, amount, order, description, payment_method='paypal'):
        Transaction.objects.create(
            user=writer,
            wallet=writer.wallet,
            amount=amount,
            type='payout',
            direction='credit',
            status='completed',
            payment_method=payment_method,
            description=description,
            order=order,
            completed_at=timezone.now()
        )
    
    @staticmethod
    def get_admin_balance():
        admin_wallet = AdminWalletManager.get_admin_wallet()
        return admin_wallet.balance
    
    @staticmethod
    def get_admin_total_received():
        admin_wallet = AdminWalletManager.get_admin_wallet()
        return admin_wallet.total_in
    
    @staticmethod
    def get_admin_total_paid_out():
        admin_wallet = AdminWalletManager.get_admin_wallet()
        return admin_wallet.total_out