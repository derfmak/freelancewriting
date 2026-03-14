import json
import uuid
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from .models import Conversation, Message, MessageStatus

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.order_id = self.scope['url_route']['kwargs']['order_id']
        self.user = self.scope['user']
        
        if isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            await self.close()
            return
        
        self.room_group_name = f'chat_{self.order_id}'
        
        is_authorized = await self.check_authorization()
        if not is_authorized:
            await self.close()
            return
        
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        await self.mark_messages_delivered()
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message_type = text_data_json.get('type', 'message')
        
        if message_type == 'message':
            content = text_data_json['content']
            message_id = str(uuid.uuid4())
            
            message_data = await self.save_message(content, message_id)
            
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': message_data
                }
            )
        
        elif message_type == 'read':
            message_ids = text_data_json.get('message_ids', [])
            await self.mark_messages_read(message_ids)
    
    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message']
        }))
    
    async def message_read(self, event):
        await self.send(text_data=json.dumps({
            'type': 'read',
            'message_id': event['message_id'],
            'read_at': event['read_at']
        }))
    
    @database_sync_to_async
    def check_authorization(self):
        from apps.orders.models import Order
        try:
            order = Order.objects.get(id=self.order_id)
            return order.student_id == self.user.id or self.user.role == 'admin'
        except Order.DoesNotExist:
            return False
    
    @database_sync_to_async
    def get_conversation(self):
        conversation, created = Conversation.objects.get_or_create(
            order_id=self.order_id,
            defaults={
                'student_id': self.get_student_id(),
                'admin_id': self.get_admin_id()
            }
        )
        return conversation
    
    @database_sync_to_async
    def get_student_id(self):
        from apps.orders.models import Order
        order = Order.objects.get(id=self.order_id)
        return order.student_id
    
    @database_sync_to_async
    def get_admin_id(self):
        from apps.accounts.models import User
        return User.objects.filter(role='admin').first().id
    
    @database_sync_to_async
    def save_message(self, content, message_id):
        conversation = Conversation.objects.get(order_id=self.order_id)
        
        message = Message.objects.create(
            id=message_id,
            conversation=conversation,
            sender=self.user,
            content=content
        )
        
        conversation.last_message_at = timezone.now()
        conversation.save(update_fields=['last_message_at'])
        
        MessageStatus.objects.create(
            message=message,
            user=conversation.student if self.user.role == 'admin' else conversation.admin,
            is_delivered=True,
            delivered_at=timezone.now()
        )
        
        return {
            'id': str(message.id),
            'content': message.content,
            'sender': str(message.sender.id),
            'sender_name': message.sender.full_name,
            'sender_role': message.sender.role,
            'created_at': message.created_at.isoformat()
        }
    
    @database_sync_to_async
    def mark_messages_delivered(self):
        conversation = Conversation.objects.get(order_id=self.order_id)
        messages = Message.objects.filter(
            conversation=conversation
        ).exclude(
            sender=self.user
        ).filter(
            statuses__user=self.user,
            statuses__is_delivered=False
        )
        
        for message in messages:
            status = message.statuses.get(user=self.user)
            status.is_delivered = True
            status.delivered_at = timezone.now()
            status.save(update_fields=['is_delivered', 'delivered_at'])
    
    @database_sync_to_async
    def mark_messages_read(self, message_ids):
        conversation = Conversation.objects.get(order_id=self.order_id)
        messages = Message.objects.filter(
            id__in=message_ids,
            conversation=conversation
        ).exclude(sender=self.user)
        
        for message in messages:
            status = message.statuses.get(user=self.user)
            status.is_read = True
            status.read_at = timezone.now()
            status.save(update_fields=['is_read', 'read_at'])
            
            all_read = not message.statuses.filter(is_read=False).exists()
            if all_read:
                message.is_read = True
                message.read_at = timezone.now()
                message.save(update_fields=['is_read', 'read_at'])