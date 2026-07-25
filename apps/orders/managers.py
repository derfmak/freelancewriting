from django.db import models
from django.utils import timezone
from datetime import timedelta


class OrderQuerySet(models.QuerySet):
    
    def pending(self):
        return self.filter(status='request')
    
    def in_progress(self):
        return self.filter(status='in_progress')
    
    def awaiting_approval(self):
        return self.filter(status='awaiting_approval')
    
    def completed(self):
        return self.filter(status='completed')
    
    def cancelled(self):
        return self.filter(status='cancelled')
    
    def declined(self):
        return self.filter(status='declined')
    
    def refund_pending(self):
        return self.filter(status='refund_pending')
    
    def active(self):
        return self.exclude(status__in=['completed', 'cancelled', 'declined'])
    
    def for_student(self, student):
        return self.filter(student=student)
    
    def for_writer(self, writer):
        return self.filter(writer=writer)
    
    def urgent(self):
        return self.filter(deadline__lte=timezone.now() + timedelta(hours=24))
    
    def overdue(self):
        return self.filter(
            deadline__lt=timezone.now()
        ).exclude(
            status__in=['completed', 'cancelled', 'declined']
        )
    
    def ready_for_auto_approve(self):
        return self.filter(
            status='awaiting_approval',
            auto_approve_at__lte=timezone.now(),
            auto_approve_at__isnull=False
        )
    
    def requires_writer(self):
        return self.filter(status='request', writer__isnull=True)
    
    def search(self, query):
        from django.db.models import Q
        return self.filter(
            Q(order_number__icontains=query) |
            Q(topic__icontains=query) |
            Q(subject__icontains=query)
        )
    
    def by_status(self, status):
        if status:
            return self.filter(status=status)
        return self
    
    def by_date_range(self, start_date, end_date):
        if start_date and end_date:
            return self.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        if start_date:
            return self.filter(created_at__date__gte=start_date)
        if end_date:
            return self.filter(created_at__date__lte=end_date)
        return self
    
    def with_timeline(self):
        return self.prefetch_related('timeline')
    
    def with_history(self):
        return self.prefetch_related('history')
    
    def with_attachments(self):
        return self.prefetch_related('attachments')
    
    def with_writer(self):
        return self.select_related('writer')
    
    def with_student(self):
        return self.select_related('student')
    
    def with_all_relations(self):
        return self.select_related('student', 'writer', 'cancelled_by', 'declined_by').prefetch_related(
            'attachments', 'history', 'timeline'
        )
    
    def stats_by_status(self):
        from django.db.models import Count
        return self.values('status').annotate(count=Count('id'))
    
    def stats_by_academic_level(self):
        from django.db.models import Count
        return self.values('academic_level').annotate(count=Count('id'))
    
    def stats_by_paper_type(self):
        from django.db.models import Count
        return self.values('paper_type').annotate(count=Count('id'))
    
    def revenue_total(self):
        from django.db.models import Sum
        return self.aggregate(total=Sum('total_price'))['total'] or 0
    
    def revenue_completed(self):
        return self.completed().revenue_total()
    
    def average_rating(self):
        from django.db.models import Avg
        return self.filter(rating__isnull=False).aggregate(avg=Avg('rating'))['avg'] or 0


class OrderManager(models.Manager):
    
    def get_queryset(self):
        return OrderQuerySet(self.model, using=self._db)
    
    def pending(self):
        return self.get_queryset().pending()
    
    def in_progress(self):
        return self.get_queryset().in_progress()
    
    def awaiting_approval(self):
        return self.get_queryset().awaiting_approval()
    
    def completed(self):
        return self.get_queryset().completed()
    
    def cancelled(self):
        return self.get_queryset().cancelled()
    
    def declined(self):
        return self.get_queryset().declined()
    
    def refund_pending(self):
        return self.get_queryset().refund_pending()
    
    def active(self):
        return self.get_queryset().active()
    
    def for_student(self, student):
        return self.get_queryset().for_student(student)
    
    def for_writer(self, writer):
        return self.get_queryset().for_writer(writer)
    
    def urgent(self):
        return self.get_queryset().urgent()
    
    def overdue(self):
        return self.get_queryset().overdue()
    
    def ready_for_auto_approve(self):
        return self.get_queryset().ready_for_auto_approve()
    
    def requires_writer(self):
        return self.get_queryset().requires_writer()
    
    def search(self, query):
        return self.get_queryset().search(query)
    
    def by_status(self, status):
        return self.get_queryset().by_status(status)
    
    def by_date_range(self, start_date, end_date):
        return self.get_queryset().by_date_range(start_date, end_date)
    
    def with_all_relations(self):
        return self.get_queryset().with_all_relations()
    
    def stats_by_status(self):
        return self.get_queryset().stats_by_status()
    
    def stats_by_academic_level(self):
        return self.get_queryset().stats_by_academic_level()
    
    def stats_by_paper_type(self):
        return self.get_queryset().stats_by_paper_type()
    
    def revenue_total(self):
        return self.get_queryset().revenue_total()
    
    def revenue_completed(self):
        return self.get_queryset().revenue_completed()
    
    def average_rating(self):
        return self.get_queryset().average_rating()


class AttachmentQuerySet(models.QuerySet):
    
    def clean(self):
        return self.filter(scan_status='clean')
    
    def infected(self):
        return self.filter(scan_status='infected')
    
    def corrupt(self):
        return self.filter(is_corrupt=True)
    
    def pending_scan(self):
        return self.filter(scan_status='pending')
    
    def by_uploader(self, user):
        return self.filter(uploaded_by=user)
    
    def for_order(self, order):
        return self.filter(orders=order)


class AttachmentManager(models.Manager):
    
    def get_queryset(self):
        return AttachmentQuerySet(self.model, using=self._db)
    
    def clean(self):
        return self.get_queryset().clean()
    
    def infected(self):
        return self.get_queryset().infected()
    
    def corrupt(self):
        return self.get_queryset().corrupt()
    
    def pending_scan(self):
        return self.get_queryset().pending_scan()
    
    def by_uploader(self, user):
        return self.get_queryset().by_uploader(user)
    
    def for_order(self, order):
        return self.get_queryset().for_order(order)


class OrderHistoryQuerySet(models.QuerySet):
    
    def by_order(self, order):
        return self.filter(order=order)
    
    def by_user(self, user):
        return self.filter(user=user)
    
    def by_action(self, action):
        return self.filter(action=action)
    
    def recent(self, limit=10):
        return self.order_by('-created_at')[:limit]
    
    def status_changes(self):
        return self.filter(action__in=['create', 'accept', 'start', 'deliver', 'complete', 'cancel', 'decline', 'resubmit', 'reorder', 'split'])


class OrderHistoryManager(models.Manager):
    
    def get_queryset(self):
        return OrderHistoryQuerySet(self.model, using=self._db)
    
    def by_order(self, order):
        return self.get_queryset().by_order(order)
    
    def by_user(self, user):
        return self.get_queryset().by_user(user)
    
    def by_action(self, action):
        return self.get_queryset().by_action(action)
    
    def recent(self, limit=10):
        return self.get_queryset().recent(limit)
    
    def status_changes(self):
        return self.get_queryset().status_changes()


class OrderTimelineQuerySet(models.QuerySet):
    
    def by_order(self, order):
        return self.filter(order=order)
    
    def by_status(self, status):
        return self.filter(status=status)
    
    def recent(self, limit=10):
        return self.order_by('-created_at')[:limit]


class OrderTimelineManager(models.Manager):
    
    def get_queryset(self):
        return OrderTimelineQuerySet(self.model, using=self._db)
    
    def by_order(self, order):
        return self.get_queryset().by_order(order)
    
    def by_status(self, status):
        return self.get_queryset().by_status(status)
    
    def recent(self, limit=10):
        return self.get_queryset().recent(limit)


class UserPresenceQuerySet(models.QuerySet):
    
    def online(self):
        return self.filter(is_online=True)
    
    def offline(self):
        return self.filter(is_online=False)
    
    def recently_active(self, minutes=5):
        cutoff = timezone.now() - timedelta(minutes=minutes)
        return self.filter(last_seen_at__gte=cutoff)
    
    def by_user(self, user):
        return self.filter(user=user)


class UserPresenceManager(models.Manager):
    
    def get_queryset(self):
        return UserPresenceQuerySet(self.model, using=self._db)
    
    def online(self):
        return self.get_queryset().online()
    
    def offline(self):
        return self.get_queryset().offline()
    
    def recently_active(self, minutes=5):
        return self.get_queryset().recently_active(minutes)
    
    def by_user(self, user):
        return self.get_queryset().by_user(user)