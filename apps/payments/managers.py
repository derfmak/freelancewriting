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
    
    def holds(self):
        return self.filter(type='hold')
    
    def releases(self):
        return self.filter(type='release')
    
    def settlements(self):
        return self.filter(type='settle')
    
    def payouts(self):
        return self.filter(type='payout')
    
    def adjustments(self):
        return self.filter(type='adjustment')
    
    def paypal(self):
        return self.filter(payment_method='paypal')
    
    def stripe(self):
        return self.filter(payment_method='stripe')
    
    def wallet(self):
        return self.filter(payment_method='wallet')
    
    def for_user(self, user):
        return self.filter(user=user)
    
    def for_wallet(self, wallet):
        return self.filter(wallet=wallet)
    
    def for_order(self, order):
        return self.filter(order=order)
    
    def by_payment_method(self, method):
        return self.filter(payment_method=method)
    
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
    
    def total_positive(self):
        result = self.filter(amount__gt=0).aggregate(total=models.Sum('amount'))
        return result['total'] or Decimal('0.00')
    
    def total_negative(self):
        result = self.filter(amount__lt=0).aggregate(total=models.Sum('amount'))
        return result['total'] or Decimal('0.00')
    
    def count_by_type(self):
        return self.values('type').annotate(count=models.Count('id'))
    
    def count_by_status(self):
        return self.values('status').annotate(count=models.Count('id'))
    
    def daily_summary(self, days=7):
        from datetime import timedelta
        start = timezone.now() - timedelta(days=days)
        return self.filter(created_at__gte=start).extra(
            select={'date': 'DATE(created_at)'}
        ).values('date').annotate(
            total=models.Sum('amount'),
            count=models.Count('id')
        ).order_by('date')


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
    
    def holds(self):
        return self.get_queryset().holds()
    
    def releases(self):
        return self.get_queryset().releases()
    
    def settlements(self):
        return self.get_queryset().settlements()
    
    def payouts(self):
        return self.get_queryset().payouts()
    
    def paypal(self):
        return self.get_queryset().paypal()
    
    def stripe(self):
        return self.get_queryset().stripe()
    
    def wallet(self):
        return self.get_queryset().wallet()
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)
    
    def for_wallet(self, wallet):
        return self.get_queryset().for_wallet(wallet)
    
    def for_order(self, order):
        return self.get_queryset().for_order(order)
    
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
    
    def create_hold(self, wallet, amount, order=None, description=None):
        return self.create(
            user=wallet.user,
            wallet=wallet,
            amount=amount,
            type='hold',
            status='completed',
            payment_method='wallet',
            description=description or 'Funds held in escrow',
            order=order,
            balance_before=wallet.balance,
            balance_after=wallet.balance,
            held_before=wallet.held_balance - amount,
            held_after=wallet.held_balance
        )
    
    def create_settlement(self, wallet, amount, order=None, description=None):
        return self.create(
            user=wallet.user,
            wallet=wallet,
            amount=amount,
            type='settle',
            status='completed',
            payment_method='wallet',
            description=description or 'Escrow settlement',
            order=order,
            balance_before=wallet.balance,
            balance_after=wallet.balance - amount,
            held_before=wallet.held_balance + amount,
            held_after=wallet.held_balance
        )
    
    def create_refund(self, wallet, amount, order=None, description=None):
        return self.create(
            user=wallet.user,
            wallet=wallet,
            amount=amount,
            type='refund',
            status='completed',
            payment_method='wallet',
            description=description or 'Refund processed',
            order=order,
            balance_before=wallet.balance - amount,
            balance_after=wallet.balance,
            held_before=wallet.held_balance + amount,
            held_after=wallet.held_balance
        )
    
    def create_paypal_deposit(self, wallet, amount, payment_id, transaction_id=None):
        return self.create(
            user=wallet.user,
            wallet=wallet,
            amount=amount,
            type='deposit',
            status='pending',
            payment_method='paypal',
            description=f'PayPal deposit of ${amount}',
            provider_transaction_id=payment_id,
            balance_before=wallet.balance,
            balance_after=wallet.balance + amount,
        )
    
    def complete_paypal_deposit(self, transaction_obj):
        transaction_obj.status = 'completed'
        transaction_obj.completed_at = timezone.now()
        transaction_obj.balance_after = transaction_obj.wallet.balance
        transaction_obj.save()
        return transaction_obj


class PaymentMethodQuerySet(models.QuerySet):
    
    def active(self):
        return self.filter(is_active=True)
    
    def default(self):
        return self.filter(is_default=True)
    
    def for_user(self, user):
        return self.filter(user=user)
    
    def not_expired(self):
        now = timezone.now()
        return self.filter(
            models.Q(expiry_year__gt=now.year) |
            models.Q(expiry_year=now.year, expiry_month__gte=now.month)
        )
    
    def by_brand(self, brand):
        return self.filter(card_brand=brand)
    
    def paypal(self):
        return self.filter(provider='paypal')
    
    def stripe(self):
        return self.filter(provider='stripe')
    
    def recently_used(self, days=30):
        cutoff = timezone.now() - timezone.timedelta(days=days)
        return self.filter(last_used_at__gte=cutoff)


class PaymentMethodManager(models.Manager):
    
    def get_queryset(self):
        return PaymentMethodQuerySet(self.model, using=self._db)
    
    def active(self):
        return self.get_queryset().active()
    
    def default(self):
        return self.get_queryset().default()
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)
    
    def not_expired(self):
        return self.get_queryset().not_expired()
    
    def by_brand(self, brand):
        return self.get_queryset().by_brand(brand)
    
    def paypal(self):
        return self.get_queryset().paypal()
    
    def stripe(self):
        return self.get_queryset().stripe()
    
    def get_default(self, user):
        return self.get_queryset().for_user(user).default().first()
    
    def get_or_create_default(self, user, **defaults):
        method = self.get_default(user)
        if not method:
            method = self.create(user=user, is_default=True, **defaults)
        return method
    
    def get_paypal_method(self, user, paypal_email):
        return self.get_queryset().for_user(user).filter(
            paypal_email=paypal_email,
            provider='paypal',
            is_active=True
        ).first()
    
    def get_default_paypal(self, user):
        return self.get_queryset().for_user(user).filter(
            provider='paypal',
            is_active=True
        ).default().first()


class WalletQuerySet(models.QuerySet):
    
    def active(self):
        return self.filter(is_active=True)
    
    def locked(self):
        return self.filter(locked_until__gt=timezone.now())
    
    def unlocked(self):
        return self.filter(models.Q(locked_until__isnull=True) | models.Q(locked_until__lte=timezone.now()))
    
    def with_balance_gt(self, amount):
        return self.filter(balance__gt=amount)
    
    def with_balance_lt(self, amount):
        return self.filter(balance__lt=amount)
    
    def with_held_gt(self, amount):
        return self.filter(held_balance__gt=amount)
    
    def has_available_balance(self, amount):
        return self.filter(balance__gt=models.F('held_balance') + amount)
    
    def for_user(self, user):
        return self.filter(user=user)
    
    def total_balance(self):
        result = self.aggregate(total=models.Sum('balance'))
        return result['total'] or Decimal('0.00')
    
    def total_held(self):
        result = self.aggregate(total=models.Sum('held_balance'))
        return result['total'] or Decimal('0.00')
    
    def total_available(self):
        result = self.aggregate(total=models.Sum(models.F('balance') - models.F('held_balance')))
        return result['total'] or Decimal('0.00')


class WalletManager(models.Manager):
    
    def get_queryset(self):
        return WalletQuerySet(self.model, using=self._db)
    
    def active(self):
        return self.get_queryset().active()
    
    def locked(self):
        return self.get_queryset().locked()
    
    def unlocked(self):
        return self.get_queryset().unlocked()
    
    def with_balance_gt(self, amount):
        return self.get_queryset().with_balance_gt(amount)
    
    def with_held_gt(self, amount):
        return self.get_queryset().with_held_gt(amount)
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)
    
    def total_balance(self):
        return self.get_queryset().total_balance()
    
    def total_held(self):
        return self.get_queryset().total_held()
    
    def get_or_create_wallet(self, user):
        wallet, created = self.get_or_create(user=user)
        return wallet


class OrderPaymentQuerySet(models.QuerySet):
    
    def held(self):
        return self.filter(status='held')
    
    def released(self):
        return self.filter(status='released')
    
    def refunded(self):
        return self.filter(status='refunded')
    
    def pending_auto_release(self):
        return self.filter(
            status='held',
            auto_release_at__lte=timezone.now(),
            auto_release_at__isnull=False
        )
    
    def for_order(self, order):
        return self.filter(order=order)
    
    def for_user(self, user):
        return self.filter(models.Q(order__student=user) | models.Q(order__writer=user))
    
    def total_held(self):
        result = self.filter(status='held').aggregate(total=models.Sum('amount'))
        return result['total'] or Decimal('0.00')
    
    def total_released(self):
        result = self.filter(status='released').aggregate(total=models.Sum('amount'))
        return result['total'] or Decimal('0.00')
    
    def total_refunded(self):
        result = self.filter(status='refunded').aggregate(total=models.Sum('amount'))
        return result['total'] or Decimal('0.00')


class OrderPaymentManager(models.Manager):
    
    def get_queryset(self):
        return OrderPaymentQuerySet(self.model, using=self._db)
    
    def held(self):
        return self.get_queryset().held()
    
    def released(self):
        return self.get_queryset().released()
    
    def refunded(self):
        return self.get_queryset().refunded()
    
    def pending_auto_release(self):
        return self.get_queryset().pending_auto_release()
    
    def for_order(self, order):
        return self.get_queryset().for_order(order)
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)
    
    def total_held(self):
        return self.get_queryset().total_held()
    
    def create_hold_payment(self, order, hold_transaction, amount, auto_release_at=None):
        return self.create(
            order=order,
            hold_transaction=hold_transaction,
            amount=amount,
            status='held',
            auto_release_at=auto_release_at
        )


class FraudCheckQuerySet(models.QuerySet):
    
    def high_risk(self):
        return self.filter(risk_level='high')
    
    def medium_risk(self):
        return self.filter(risk_level='medium')
    
    def low_risk(self):
        return self.filter(risk_level='low')
    
    def blocked(self):
        return self.filter(is_blocked=True)
    
    def requires_review(self):
        return self.filter(requires_review=True)
    
    def reviewed(self):
        return self.filter(reviewed_at__isnull=False)
    
    def pending_review(self):
        return self.filter(reviewed_at__isnull=True, requires_review=True)
    
    def for_user(self, user):
        return self.filter(user=user)
    
    def for_transaction(self, transaction):
        return self.filter(transaction=transaction)
    
    def by_risk_score(self, min_score, max_score):
        return self.filter(risk_score__gte=min_score, risk_score__lte=max_score)


class FraudCheckManager(models.Manager):
    
    def get_queryset(self):
        return FraudCheckQuerySet(self.model, using=self._db)
    
    def high_risk(self):
        return self.get_queryset().high_risk()
    
    def medium_risk(self):
        return self.get_queryset().medium_risk()
    
    def low_risk(self):
        return self.get_queryset().low_risk()
    
    def blocked(self):
        return self.get_queryset().blocked()
    
    def requires_review(self):
        return self.get_queryset().requires_review()
    
    def pending_review(self):
        return self.get_queryset().pending_review()
    
    def for_user(self, user):
        return self.get_queryset().for_user(user)
    
    def create_fraud_check(self, user, risk_score, risk_level, flags=None, transaction=None, **kwargs):
        return self.create(
            user=user,
            transaction=transaction,
            risk_score=risk_score,
            risk_level=risk_level,
            flags=flags or [],
            **kwargs
        )


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
    
    def by_method(self, method):
        return self.filter(payment_method=method)
    
    def paypal(self):
        return self.filter(payment_method='paypal')
    
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
    
    def by_method(self, method):
        return self.get_queryset().by_method(method)
    
    def paypal(self):
        return self.get_queryset().paypal()
    
    def pending_total(self):
        return self.get_queryset().pending_total()
    
    def completed_total(self):
        return self.get_queryset().completed_total()
    
    def create_payout(self, user, amount, payment_method, account_details, **kwargs):
        return self.create(
            user=user,
            amount=amount,
            payment_method=payment_method,
            account_details=account_details,
            status='pending',
            **kwargs
        )
    
    def create_paypal_payout(self, user, amount, paypal_email, **kwargs):
        return self.create(
            user=user,
            amount=amount,
            payment_method='paypal',
            account_details={'email': paypal_email},
            status='pending',
            **kwargs
        )


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