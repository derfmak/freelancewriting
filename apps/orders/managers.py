from django.db import models
from django.utils import timezone

class OrderQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(status='pending')
    
    def ongoing(self):
        return self.filter(status='ongoing')
    
    def awaiting_review(self):
        return self.filter(status='awaiting_review')
    
    def completed(self):
        return self.filter(status='completed')
    
    def for_student(self, student):
        return self.filter(student=student)
    
    def urgent(self):
        return self.filter(deadline__lte=timezone.now() + timezone.timedelta(hours=24))
    
    def ready_for_auto_approve(self):
        return self.filter(
            status='awaiting_review',
            auto_approve_at__lte=timezone.now(),
            auto_approve_at__isnull=False
        )

class OrderManager(models.Manager):
    def get_queryset(self):
        return OrderQuerySet(self.model, using=self._db)
    
    def pending(self):
        return self.get_queryset().pending()
    
    def ongoing(self):
        return self.get_queryset().ongoing()
    
    def awaiting_review(self):
        return self.get_queryset().awaiting_review()
    
    def completed(self):
        return self.get_queryset().completed()