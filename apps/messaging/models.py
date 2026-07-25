import uuid

from django.db import models
from django.utils import timezone

from apps.accounts.models import User
from apps.orders.models import Order


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='conversation')
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='client_conversations')
    admin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_conversations')
    last_message_at = models.DateTimeField(default=timezone.now)
    client_last_seen = models.DateTimeField(null=True, blank=True)
    admin_last_seen = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'conversations'
        ordering = ['-last_message_at']
        indexes = [
            models.Index(fields=['order', 'last_message_at']),
            models.Index(fields=['client', 'last_message_at']),
            models.Index(fields=['admin', 'last_message_at']),
        ]

    def __str__(self):
        return f'Conversation for Order {self.order.order_number}'

    def other_participant(self, user):
        return self.admin if user == self.client else self.client

    def is_participant(self, user):
        return user == self.client or user == self.admin

    def get_unread_count(self, user):
        if not self.is_participant(user):
            return 0
        last_seen = self.client_last_seen if user == self.client else self.admin_last_seen
        qs = self.messages.exclude(sender=user).filter(is_recalled=False)
        if last_seen:
            qs = qs.filter(created_at__gt=last_seen)
        return qs.count()

    def mark_seen(self, user):
        now = timezone.now()
        if user == self.client:
            self.client_last_seen = now
            self.save(update_fields=['client_last_seen'])
        elif user == self.admin:
            self.admin_last_seen = now
            self.save(update_fields=['admin_last_seen'])


class Message(models.Model):
    TEXT = 'text'
    FILE = 'file'
    SYSTEM = 'system'
    EDITED = 'edited'
    RECALLED = 'recalled'

    MESSAGE_TYPES = [
        (TEXT, 'text'),
        (FILE, 'file'),
        (SYSTEM, 'system'),
        (EDITED, 'edited'),
        (RECALLED, 'recalled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    content = models.TextField()
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default=TEXT)
    file_url = models.URLField(blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.IntegerField(null=True, blank=True)
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    is_recalled = models.BooleanField(default=False)
    recalled_at = models.DateTimeField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'messages'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['conversation', 'is_read']),
            models.Index(fields=['sender', 'created_at']),
            models.Index(fields=['is_recalled']),
        ]

    def __str__(self):
        return f'Message {self.id} in {self.conversation_id}'

    def can_edit(self, user):
        if self.sender_id != user.id or self.is_recalled:
            return False
        return timezone.now() - self.created_at <= timezone.timedelta(minutes=5)

    def can_recall(self, user):
        if self.sender_id != user.id or self.is_recalled:
            return False
        return timezone.now() - self.created_at <= timezone.timedelta(minutes=1)

    def can_delete(self, user):
        if self.sender_id != user.id:
            return False
        return timezone.now() - self.created_at <= timezone.timedelta(minutes=5)

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    def mark_as_delivered(self):
        if not self.is_delivered:
            self.is_delivered = True
            self.delivered_at = timezone.now()
            self.save(update_fields=['is_delivered', 'delivered_at'])

    def edit(self, new_content):
        self.content = new_content
        self.is_edited = True
        self.edited_at = timezone.now()
        self.save(update_fields=['content', 'is_edited', 'edited_at'])

    def recall(self):
        self.is_recalled = True
        self.recalled_at = timezone.now()
        self.content = 'This message was recalled'
        self.message_type = self.RECALLED
        self.save(update_fields=['is_recalled', 'recalled_at', 'content', 'message_type'])


class MessageStatus(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='statuses')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'message_statuses'
        unique_together = ['message', 'user']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'is_delivered']),
        ]

    def __str__(self):
        return f'Status for {self.message_id} - {self.user.email}'

    def mark_read(self):
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=['is_read', 'read_at'])

    def mark_delivered(self):
        self.is_delivered = True
        self.delivered_at = timezone.now()
        self.save(update_fields=['is_delivered', 'delivered_at'])


class TypingStatus(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='typing_statuses')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_typing = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'typing_statuses'
        unique_together = ['conversation', 'user']
        indexes = [
            models.Index(fields=['conversation', 'updated_at']),
        ]

    def __str__(self):
        return f'{self.user.email} typing in {self.conversation_id}'