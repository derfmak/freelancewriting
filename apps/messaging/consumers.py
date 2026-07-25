import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from .models import Conversation, Message, MessageStatus, TypingStatus
from .serializers import MessageSerializer


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.order_id = self.scope['url_route']['kwargs']['order_id']
        self.user = self.scope['user']

        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        self.conversation = await self.get_conversation()
        if self.conversation is None or not await self.is_participant():
            await self.close()
            return

        self.group_name = f'chat_{self.conversation.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.set_typing(False)
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except ValueError:
            return

        event_type = data.get('type')

        if event_type == 'message':
            await self.handle_message(data)
        elif event_type == 'typing':
            await self.handle_typing(data)
        elif event_type == 'edit':
            await self.handle_edit(data)
        elif event_type == 'recall':
            await self.handle_recall(data)
        elif event_type == 'delete':
            await self.handle_delete(data)

    async def handle_message(self, data):
        content = (data.get('content') or '').strip()
        if not content:
            return

        message = await self.create_message(content)
        payload = MessageSerializer(message).data
        await self.channel_layer.group_send(self.group_name, {
            'type': 'message.sent',
            'payload': payload,
        })

    async def handle_typing(self, data):
        is_typing = bool(data.get('is_typing'))
        await self.set_typing(is_typing)
        await self.channel_layer.group_send(self.group_name, {
            'type': 'typing.start' if is_typing else 'typing.stop',
            'payload': {'user': str(self.user.id)},
        })

    async def handle_edit(self, data):
        message_id = data.get('message_id')
        content = (data.get('content') or '').strip()
        if not message_id or not content:
            return

        message = await self.edit_message(message_id, content)
        if message is None:
            return

        payload = MessageSerializer(message).data
        await self.channel_layer.group_send(self.group_name, {
            'type': 'message.edited',
            'payload': payload,
        })

    async def handle_recall(self, data):
        message_id = data.get('message_id')
        message = await self.recall_message(message_id)
        if message is None:
            return

        payload = MessageSerializer(message).data
        await self.channel_layer.group_send(self.group_name, {
            'type': 'message.recalled',
            'payload': payload,
        })

    async def handle_delete(self, data):
        message_id = data.get('message_id')
        deleted_id = await self.delete_message(message_id)
        if deleted_id is None:
            return

        await self.channel_layer.group_send(self.group_name, {
            'type': 'message.deleted',
            'payload': {'message_id': deleted_id},
        })

    async def message_sent(self, event):
        await self.send(text_data=json.dumps({'type': 'message', 'message': event['payload']}))

    async def message_edited(self, event):
        await self.send(text_data=json.dumps({'type': 'edited', 'message': event['payload']}))

    async def message_recalled(self, event):
        await self.send(text_data=json.dumps({'type': 'recalled', 'message': event['payload']}))

    async def message_deleted(self, event):
        await self.send(text_data=json.dumps({'type': 'deleted', 'message_id': event['payload']['message_id']}))

    async def message_read(self, event):
        await self.send(text_data=json.dumps({'type': 'read', **event['payload']}))

    async def typing_start(self, event):
        if event['payload']['user'] != str(self.user.id):
            await self.send(text_data=json.dumps({'type': 'typing', 'is_typing': True}))

    async def typing_stop(self, event):
        if event['payload']['user'] != str(self.user.id):
            await self.send(text_data=json.dumps({'type': 'typing', 'is_typing': False}))

    @database_sync_to_async
    def get_conversation(self):
        return Conversation.objects.select_related('order', 'student', 'admin').filter(
            order_id=self.order_id,
        ).first()

    @database_sync_to_async
    def is_participant(self):
        return self.user in (self.conversation.student, self.conversation.admin)

    @database_sync_to_async
    def create_message(self, content):
        message = Message.objects.create(
            conversation=self.conversation,
            sender=self.user,
            content=content,
            message_type=Message.TEXT,
            is_delivered=True,
            delivered_at=timezone.now(),
        )
        self.conversation.last_message_at = message.created_at
        self.conversation.save(update_fields=['last_message_at'])

        recipient = self.conversation.admin if self.user == self.conversation.student else self.conversation.student
        MessageStatus.objects.create(
            message=message, user=recipient, is_delivered=True, delivered_at=timezone.now(),
        )
        return message

    @database_sync_to_async
    def edit_message(self, message_id, content):
        message = Message.objects.filter(id=message_id, sender=self.user).first()
        if message is None or not message.can_edit(self.user):
            return None
        message.edit(content)
        return message

    @database_sync_to_async
    def recall_message(self, message_id):
        if message_id:
            message = Message.objects.filter(id=message_id, sender=self.user).first()
        else:
            message = Message.objects.filter(
                conversation=self.conversation, sender=self.user, is_recalled=False,
            ).order_by('-created_at').first()

        if message is None or not message.can_recall(self.user):
            return None
        message.recall()
        return message

    @database_sync_to_async
    def delete_message(self, message_id):
        message = Message.objects.filter(id=message_id, sender=self.user).first()
        if message is None or not message.can_delete(self.user):
            return None
        deleted_id = str(message.id)
        message.delete()
        return deleted_id

    @database_sync_to_async
    def set_typing(self, is_typing):
        TypingStatus.objects.update_or_create(
            conversation=self.conversation, user=self.user,
            defaults={'is_typing': is_typing},
        )