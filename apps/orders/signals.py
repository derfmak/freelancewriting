from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from .models import Order, OrderHistory, OrderTimeline, UserPresence
from .services import OrderNotificationService


@receiver(post_save, sender=Order)
def create_order_timeline(sender, instance, created, **kwargs):
    if created:
        OrderTimeline.objects.create(
            order=instance,
            status='request',
            title='Order Created',
            description='Your order has been submitted and is waiting for a writer',
            icon='fa-file-alt',
            color='green'
        )
        
        OrderNotificationService.send_order_created(instance)


@receiver(post_save, sender=Order)
def update_order_activity(sender, instance, **kwargs):
    if instance.pk:
        instance.last_activity_at = timezone.now()
        instance.save(update_fields=['last_activity_at'])


@receiver(post_save, sender=UserPresence)
def update_presence_activity(sender, instance, **kwargs):
    if instance.is_online:
        instance.last_seen_at = timezone.now()
        instance.save(update_fields=['last_seen_at'])