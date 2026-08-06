from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.orders.models import Order, OrderHistory
from apps.messaging.models import Message
from .models import ClientNotification

def notify_client(user, title, message, type, link=None):
    ClientNotification.objects.create(
        user=user,
        title=title,
        message=message,
        type=type,
        link=link,
    )

@receiver(post_save, sender=Order)
def order_notification_for_client(sender, instance, created, **kwargs):
    if instance.status == 'in_progress' and instance.accepted_at:
        notify_client(
            instance.client,
            'Order Accepted',
            f'Your order #{instance.order_number} has been accepted and is being worked on.',
            'order',
            f'/client/orders/{instance.id}/'
        )
    elif instance.status == 'awaiting_approval':
        notify_client(
            instance.client,
            'Order Delivered',
            f'Your order #{instance.order_number} has been delivered. Please review and approve.',
            'order',
            f'/client/orders/{instance.id}/'
        )
    elif instance.status == 'completed':
        notify_client(
            instance.client,
            'Order Completed',
            f'Order #{instance.order_number} is completed.',
            'order',
            f'/client/orders/{instance.id}/'
        )
    elif instance.status == 'cancelled':
        notify_client(
            instance.client,
            'Order Cancelled',
            f'Your order #{instance.order_number} has been cancelled.',
            'warning',
            f'/client/orders/{instance.id}/'
        )

@receiver(post_save, sender=Message)
def message_notification_for_client(sender, instance, created, **kwargs):
    if created and instance.sender.role == 'admin':
        notify_client(
            instance.conversation.order.client,
            'New Message from Admin',
            f'Admin replied to your order #{instance.conversation.order.order_number}',
            'message',
            f'/client/orders/{instance.conversation.order.id}/'
        )