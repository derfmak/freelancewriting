from rest_framework import serializers
from django.db import models
from .models import Conversation, Message, MessageStatus, TypingStatus
from apps.orders.serializers import OrderListSerializer

class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='sender.full_name', read_only=True)
    sender_role = serializers.CharField(source='sender.role', read_only=True)
    sender_email = serializers.EmailField(source='sender.email', read_only=True)
    is_edited = serializers.BooleanField(read_only=True)
    is_recalled = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Message
        fields = [
            'id', 'conversation', 'sender', 'sender_name', 'sender_role', 'sender_email',
            'content', 'message_type', 'file_url', 'file_name', 'file_size',
            'is_edited', 'edited_at', 'is_recalled', 'recalled_at',
            'is_read', 'read_at', 'is_delivered', 'delivered_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

class MessageCreateSerializer(serializers.Serializer):
    content = serializers.CharField(required=True)
    message_type = serializers.ChoiceField(choices=['text', 'file', 'system'], default='text')
    file_url = serializers.URLField(required=False, allow_blank=True)
    file_name = serializers.CharField(required=False, allow_blank=True)
    file_size = serializers.IntegerField(required=False, allow_null=True)

class MessageEditSerializer(serializers.Serializer):
    content = serializers.CharField(required=True)

class MessageRecallSerializer(serializers.Serializer):
    message_id = serializers.UUIDField(required=True)

class ConversationSerializer(serializers.ModelSerializer):
    order = OrderListSerializer(read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    student_name = serializers.CharField(source='student.full_name', read_only=True)
    student_email = serializers.EmailField(source='student.email', read_only=True)
    admin_name = serializers.CharField(source='admin.full_name', read_only=True)
    
    class Meta:
        model = Conversation
        fields = [
            'id', 'order', 'student', 'student_name', 'student_email',
            'admin', 'admin_name', 'last_message_at', 'created_at', 'updated_at',
            'last_message', 'unread_count'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_last_message(self, obj):
        last_message = obj.messages.order_by('-created_at').first()
        if last_message:
            return MessageSerializer(last_message).data
        return None
    
    def get_unread_count(self, obj):
        user = self.context['request'].user
        if user == obj.student:
            last_seen = obj.student_last_seen
        elif user == obj.admin:
            last_seen = obj.admin_last_seen
        else:
            return 0
        
        if not last_seen:
            return obj.messages.exclude(sender=user).count()
        
        return obj.messages.filter(
            created_at__gt=last_seen
        ).exclude(sender=user).count()

class MessageStatusSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    
    class Meta:
        model = MessageStatus
        fields = [
            'id', 'message', 'user', 'user_name',
            'is_read', 'read_at', 'is_delivered', 'delivered_at'
        ]

class TypingStatusSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    
    class Meta:
        model = TypingStatus
        fields = [
            'id', 'conversation', 'user', 'user_name',
            'is_typing', 'updated_at'
        ]