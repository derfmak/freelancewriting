from django.contrib import admin

from .models import Conversation, Message, MessageStatus, TypingStatus


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['id', 'order', 'client', 'admin', 'last_message_at']
    search_fields = ['order__order_number', 'client__email', 'admin__email']
    list_filter = ['created_at']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'conversation', 'sender', 'message_type', 'is_read', 'is_recalled', 'created_at']
    list_filter = ['message_type', 'is_read', 'is_recalled']
    search_fields = ['content', 'sender__email']


@admin.register(MessageStatus)
class MessageStatusAdmin(admin.ModelAdmin):
    list_display = ['id', 'message', 'user', 'is_read', 'is_delivered']


@admin.register(TypingStatus)
class TypingStatusAdmin(admin.ModelAdmin):
    list_display = ['id', 'conversation', 'user', 'is_typing', 'updated_at']