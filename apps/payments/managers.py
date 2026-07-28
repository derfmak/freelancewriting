from django.db import models
from django.utils import timezone
from decimal import Decimal


class TransactionQuerySet(models.QuerySet):
    
    def pending(self):
        return self.filter(status='pending')
    
    def processing(self):
        return self.filter(status='processing')
    
    def completed(self):
        return self.filter(status='completed')
    
    def failed(self):
        return self.filter(status='failed')
    
    def cancelled(self):
        return self.filter(status='cancelled')
    
    def deposits(self):
        return self.filter(type='deposit')
    
    def payments(self):
        return self.filter(type='payment')
    
    def refunds(self):
        return self.filter(type='refund')
    
    def withdrawals(self):
        return self.filter(type='withdrawal')
    
    def payouts(self):
        return self.filter(type='payout')
    
    def adjustments(self):
        return self.filter(type='adjustment')
    
    def paypal(self):
        return self.filter(payment_method='paypal')
    
    def admin(self):
        return self.filter(payment_method='admin')
    
    def system(self):
        return self.filter(payment_method='system')
    
    def for_user(self, user):
        return self.filter(user=user)
    
    def for_wallet(self, wallet):
        return self.filter(wallet=wallet)
    
    def for_order(self, order):
        return self.filter(order=order)
    
    def by_payment_method(self, method):
        return self.filter(payment_method=method)
    
    def credit(self):
        return self.filter(direction='credit')
    
    def debit(self):
        return self.filter(direction='debit')
    
    def today(self):
        return self.filter(created_at__date=timezone.now().date())
    
    def this_week(self):
        start = timezone.now() - timezone.timedelta(days=7)
        return self.filter(created_at__gte=start)
    
    def this_month(self):
        return self.filter(created_at__month=timezone.now().month, created_at__year=timezone.now().year)
    
    def this_year(self):
        return self.filter(created_at__year=timezone.now().year)
    
    def between_dates(self, start, end):
        return self.filter(created_at__range=[start, end])
    
    def total_amount(self):
        result = self.aggregate(total=models.Sum('amount'))
        return result['total'] or Decimal('0.00')
    
    def total_fees(self):
        result = self.aggregate(total=models.Sum('fee_amount'))
        return result['total'] or Decimal('0.00')
    
    def total_net(self):
        result = self.aggregate(total=models.Sum('net_amount'))
        return result['total'] or Decimal('0.00')
    
    def count_by_type(self):
        return self.values('type').annotate(count=models.Count('id'))
    
    def count_by_status(self):
        return self.values('status').annotate(count=models.Count('id'))
    
    def count_by_direction(self):
        return self.values('direction').annotate(count=models.Count('id'))
    
    def daily_summary(self, days=7):
        from datetime import timedelta
        start = timezone.now() - timedelta(days=days)
        return self.filter(created_at__gte=start).extra(
            select={'date': 'DATE(created_at)'}
        ).values('date').annotate(
            total=models.Sum('amount'),
            count=models.Count('id')
        ).order_by('date')
    
    def admin_credits(self):
        return self.filter(
            wallet__user__role='admin',
            direction='credit',
            status='completed'
        )
    
    def admin_debits(self):
        return self.filter(
            wallet__user__role='admin',
            direction='debit',
            status='completed'
        )
    
    def admin_balance(self):
        credits = self.admin_credits().total_amount()
        debits = self.admin_debits().total_amount()
        return credits - debits
    
    def by_wallet_and_direction(self, wallet, direction):
        return self.filter(wallet=wallet, direction=direction)


class TransactionManager(models.Manager):
    
    def get_queryset(self):
        return TransactionQuerySet(self.model, using=self._db)
    
    def pending(self):
        return self.get_queryset().pending()
    
    def processing(self):
        return self.get_queryset().processing()
    
    def completed(self):
        return self.get_queryset().completed()
    
    def failed(self):
        return self.get_queryset().failed()
    
    def cancelled(self):
        return self.get_queryset().cancelled()
    
    def deposits(self):
        return self.get_queryset().deposits()
    
    def payments(self):
        return self.get_queryset().payments()
    
    def refunds(self):
        return self.get_queryset().refunds()
    
    def withdrawals(self):
        return self.get_queryset().withdrawals()
    
    def payouts(self):
        return self.get_queryset().payouts()
    
    def paypal(self):
        return self.get_queryset().paypal()
    
    def admin(self):
        return self.get_queryset().admin()
    
    def system(self):
        return self.get_queryset().system()
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)
    
    def for_wallet(self, wallet):
        return self.get_queryset().for_wallet(wallet)
    
    def for_order(self, order):
        return self.get_queryset().for_order(order)
    
    def credit(self):
        return self.get_queryset().credit()
    
    def debit(self):
        return self.get_queryset().debit()
    
    def today(self):
        return self.get_queryset().today()
    
    def this_week(self):
        return self.get_queryset().this_week()
    
    def this_month(self):
        return self.get_queryset().this_month()
    
    def total_amount(self):
        return self.get_queryset().total_amount()
    
    def total_fees(self):
        return self.get_queryset().total_fees()
    
    def daily_summary(self, days=7):
        return self.get_queryset().daily_summary(days)
    
    def create_transaction(self, **kwargs):
        return self.create(**kwargs)
    
    def admin_credits(self):
        return self.get_queryset().admin_credits()
    
    def admin_debits(self):
        return self.get_queryset().admin_debits()
    
    def admin_balance(self):
        return self.get_queryset().admin_balance()
    
    def by_wallet_and_direction(self, wallet, direction):
        return self.get_queryset().by_wallet_and_direction(wallet, direction)


class PaymentMethodQuerySet(models.QuerySet):
    
    def active(self):
        return self.filter(is_active=True)
    
    def default(self):
        return self.filter(is_default=True)
    
    def for_user(self, user):
        return self.filter(user=user)
    
    def paypal(self):
        return self.filter(paypal_email__isnull=False)
    
    def recently_used(self, days=30):
        cutoff = timezone.now() - timezone.timedelta(days=days)
        return self.filter(last_used_at__gte=cutoff)
    
    def verified(self):
        return self.filter(paypal_verified=True)
    
    def unverified(self):
        return self.filter(paypal_verified=False)
    
    def pending_verification(self):
        return self.filter(
            is_active=False,
            paypal_verified=False,
            verification_code__isnull=False,
            verification_code_created_at__isnull=False
        )
    
    def verification_expired(self):
        from django.db.models import Q
        cutoff = timezone.now() - timezone.timedelta(seconds=300)
        return self.filter(
            is_active=False,
            paypal_verified=False,
            verification_code__isnull=False,
            verification_code_created_at__lt=cutoff
        )
    
    def locked(self):
        return self.filter(
            verification_locked_until__isnull=False,
            verification_locked_until__gt=timezone.now()
        )
    
    def not_locked(self):
        from django.db.models import Q
        return self.filter(
            Q(verification_locked_until__isnull=True) |
            Q(verification_locked_until__lte=timezone.now())
        )
    
    def business(self):
        return self.filter(paypal_account_type='business')
    
    def personal(self):
        return self.filter(paypal_account_type='personal')


class PaymentMethodManager(models.Manager):
    
    def get_queryset(self):
        return PaymentMethodQuerySet(self.model, using=self._db)
    
    def active(self):
        return self.get_queryset().active()
    
    def default(self):
        return self.get_queryset().default()
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)
    
    def paypal(self):
        return self.get_queryset().paypal()
    
    def verified(self):
        return self.get_queryset().verified()
    
    def unverified(self):
        return self.get_queryset().unverified()
    
    def pending_verification(self):
        return self.get_queryset().pending_verification()
    
    def verification_expired(self):
        return self.get_queryset().verification_expired()
    
    def locked(self):
        return self.get_queryset().locked()
    
    def not_locked(self):
        return self.get_queryset().not_locked()
    
    def business(self):
        return self.get_queryset().business()
    
    def personal(self):
        return self.get_queryset().personal()
    
    def get_default(self, user):
        return self.get_queryset().for_user(user).default().first()
    
    def get_paypal_method(self, user, paypal_email):
        return self.get_queryset().for_user(user).filter(
            paypal_email=paypal_email,
            is_active=True
        ).first()
    
    def get_verified_method(self, user, method_id):
        return self.get_queryset().for_user(user).filter(
            id=method_id,
            is_active=True,
            paypal_verified=True
        ).first()
    
    def clear_expired_verifications(self):
        expired = self.verification_expired()
        count = expired.count()
        expired.update(
            verification_code=None,
            verification_code_created_at=None
        )
        return count


class WalletQuerySet(models.QuerySet):
    
    def active(self):
        return self.filter(is_active=True)
    
    def for_user(self, user):
        return self.filter(user=user)
    
    def total_balance(self):
        from django.db.models import Sum
        result = self.aggregate(total=Sum('balance'))
        return result['total'] or Decimal('0.00')
    
    def admin_wallets(self):
        return self.filter(user__role='admin')
    
    def client_wallets(self):
        return self.filter(user__role='client')
    
    def writer_wallets(self):
        return self.filter(user__role='writer')


class WalletManager(models.Manager):
    
    def get_queryset(self):
        return WalletQuerySet(self.model, using=self._db)
    
    def active(self):
        return self.get_queryset().active()
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)
    
    def total_balance(self):
        return self.get_queryset().total_balance()
    
    def get_or_create_wallet(self, user):
        wallet, created = self.get_or_create(user=user)
        return wallet
    
    def admin_wallets(self):
        return self.get_queryset().admin_wallets()
    
    def client_wallets(self):
        return self.get_queryset().client_wallets()
    
    def writer_wallets(self):
        return self.get_queryset().writer_wallets()
    
    def get_admin_wallet(self):
        return self.get_queryset().admin_wallets().first()


class PayoutQuerySet(models.QuerySet):
    
    def pending(self):
        return self.filter(status='pending')
    
    def processing(self):
        return self.filter(status='processing')
    
    def completed(self):
        return self.filter(status='completed')
    
    def failed(self):
        return self.filter(status='failed')
    
    def cancelled(self):
        return self.filter(status='cancelled')
    
    def for_user(self, user):
        return self.filter(user=user)
    
    def paypal(self):
        return self.filter(paypal_email__isnull=False)
    
    def today(self):
        return self.filter(created_at__date=timezone.now().date())
    
    def pending_total(self):
        result = self.filter(status='pending').aggregate(total=models.Sum('amount'))
        return result['total'] or Decimal('0.00')
    
    def completed_total(self):
        result = self.filter(status='completed').aggregate(total=models.Sum('amount'))
        return result['total'] or Decimal('0.00')
    
    def failed_total(self):
        result = self.filter(status='failed').aggregate(total=models.Sum('amount'))
        return result['total'] or Decimal('0.00')
    
    def this_week(self):
        start = timezone.now() - timezone.timedelta(days=7)
        return self.filter(created_at__gte=start)
    
    def this_month(self):
        return self.filter(created_at__month=timezone.now().month, created_at__year=timezone.now().year)
    
    def by_status(self, status):
        return self.filter(status=status)
    
    def total_amount(self):
        result = self.aggregate(total=models.Sum('amount'))
        return result['total'] or Decimal('0.00')
    
    def total_fees(self):
        result = self.aggregate(total=models.Sum('fee_amount'))
        return result['total'] or Decimal('0.00')
    
    def total_net(self):
        result = self.aggregate(total=models.Sum('net_amount'))
        return result['total'] or Decimal('0.00')


class PayoutManager(models.Manager):
    
    def get_queryset(self):
        return PayoutQuerySet(self.model, using=self._db)
    
    def pending(self):
        return self.get_queryset().pending()
    
    def processing(self):
        return self.get_queryset().processing()
    
    def completed(self):
        return self.get_queryset().completed()
    
    def failed(self):
        return self.get_queryset().failed()
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)
    
    def paypal(self):
        return self.get_queryset().paypal()
    
    def pending_total(self):
        return self.get_queryset().pending_total()
    
    def completed_total(self):
        return self.get_queryset().completed_total()
    
    def create_payout(self, user, amount, paypal_email, **kwargs):
        return self.create(
            user=user,
            amount=amount,
            paypal_email=paypal_email,
            status='pending',
            **kwargs
        )
    
    def this_week(self):
        return self.get_queryset().this_week()
    
    def this_month(self):
        return self.get_queryset().this_month()
    
    def by_status(self, status):
        return self.get_queryset().by_status(status)
    
    def total_amount(self):
        return self.get_queryset().total_amount()
    
    def total_fees(self):
        return self.get_queryset().total_fees()


class PayPalWebhookQuerySet(models.QuerySet):
    
    def pending(self):
        return self.filter(processed=False)
    
    def processed(self):
        return self.filter(processed=True)
    
    def by_event_type(self, event_type):
        return self.filter(event_type=event_type)
    
    def by_resource_id(self, resource_id):
        return self.filter(resource_id=resource_id)
    
    def today(self):
        return self.filter(created_at__date=timezone.now().date())
    
    def with_errors(self):
        return self.filter(processing_errors__isnull=False, processing_errors__gt='')
    
    def this_week(self):
        start = timezone.now() - timezone.timedelta(days=7)
        return self.filter(created_at__gte=start)
    
    def this_month(self):
        return self.filter(created_at__month=timezone.now().month, created_at__year=timezone.now().year)
    
    def unprocessed_older_than(self, minutes=5):
        cutoff = timezone.now() - timezone.timedelta(minutes=minutes)
        return self.filter(processed=False, created_at__lte=cutoff)


class PayPalWebhookManager(models.Manager):
    
    def get_queryset(self):
        return PayPalWebhookQuerySet(self.model, using=self._db)
    
    def pending(self):
        return self.get_queryset().pending()
    
    def processed(self):
        return self.get_queryset().processed()
    
    def by_event_type(self, event_type):
        return self.get_queryset().by_event_type(event_type)
    
    def by_resource_id(self, resource_id):
        return self.get_queryset().by_resource_id(resource_id)
    
    def create_webhook(self, webhook_id, event_type, resource_id, payload):
        return self.create(
            webhook_id=webhook_id,
            event_type=event_type,
            resource_id=resource_id,
            payload=payload,
            processed=False
        )
    
    def get_unprocessed(self):
        return self.get_queryset().pending().order_by('created_at')
    
    def with_errors(self):
        return self.get_queryset().with_errors()
    
    def unprocessed_older_than(self, minutes=5):
        return self.get_queryset().unprocessed_older_than(minutes)