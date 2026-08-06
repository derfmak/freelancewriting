from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.orders.models import Order

from .models import Conversation, Message


@receiver(post_save, sender=Order)
def create_conversation_for_order(sender, instance, created, **kwargs):
    if not created:
        return
    if not instance.client_id or not instance.writer_id:
        return

    conversation, was_created = Conversation.objects.get_or_create(
        order=instance,
        defaults={'student': instance.client, 'admin': instance.writer},
    )

    if was_created:
        Message.objects.create(
            conversation=conversation,
            sender=instance.client,
            content=f'Order #{instance.order_number} conversation started',
            message_type=Message.SYSTEM,
        )


@receiver(post_save, sender=Order)
def assign_conversation_admin(sender, instance, created, **kwargs):
    if created:
        return
    if not instance.writer_id:
        return

    Conversation.objects.filter(order=instance).exclude(admin_id=instance.writer_id).update(
        admin=instance.writer,
    )