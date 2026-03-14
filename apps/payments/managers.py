from django.db import models
from django.utils import timezone

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
    
    def held(self):
        return self.filter(status='held')
    
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
    
    def for_user(self, user):
        return self.filter(user=user)
    
    def for_wallet(self, wallet):
        return self.filter(wallet=wallet)
    
    def for_order(self, order):
        return self.filter(order=order)
    
    def today(self):
        return self.filter(created_at__date=timezone.now().date())
    
    def this_week(self):
        start = timezone.now() - timezone.timedelta(days=7)
        return self.filter(created_at__gte=start)
    
    def this_month(self):
        return self.filter(created_at__month=timezone.now().month)
    
    def this_year(self):
        return self.filter(created_at__year=timezone.now().year)
    
    def between_dates(self, start, end):
        return self.filter(created_at__range=[start, end])
    
    def total_amount(self):
        return self.aggregate(total=models.Sum('amount'))['total'] or 0
    
    def total_positive(self):
        return self.filter(amount__gt=0).aggregate(total=models.Sum('amount'))['total'] or 0
    
    def total_negative(self):
        return self.filter(amount__lt=0).aggregate(total=models.Sum('amount'))['total'] or 0

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
    
    def held(self):
        return self.get_queryset().held()
    
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
    
    def create_transaction(self, **kwargs):
        return self.create(**kwargs)

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

class WalletQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)
    
    def locked(self):
        return self.filter(locked_until__gt=timezone.now())
    
    def with_balance_gt(self, amount):
        return self.filter(balance__gt=amount)
    
    def with_held_gt(self, amount):
        return self.filter(held_balance__gt=amount)

class WalletManager(models.Manager):
    def get_queryset(self):
        return WalletQuerySet(self.model, using=self._db)
    
    def active(self):
        return self.get_queryset().active()
    
    def locked(self):
        return self.get_queryset().locked()
    
    def with_balance_gt(self, amount):
        return self.get_queryset().with_balance_gt(amount)

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
            auto_release_at__lte=timezone.now()
        )

class OrderPaymentManager(models.Manager):
    def get_queryset(self):
        return OrderPaymentQuerySet(self.model, using=self._db)
    
    def held(self):
        return self.get_queryset().held()
    
    def released(self):
        return self.get_queryset().released()
    
    def pending_auto_release(self):
        return self.get_queryset().pending_auto_release()