import uuid
from django.db import models
from django.utils import timezone
from apps.accounts.models import User
from apps.orders.models import Order

class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='conversation', db_index=True)
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='student_conversations')
    admin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_conversations')
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)
    student_last_seen = models.DateTimeField(null=True, blank=True)
    admin_last_seen = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['order', 'last_message_at']),
            models.Index(fields=['student', 'last_message_at']),
            models.Index(fields=['admin', 'last_message_at']),
        ]
        db_table = 'conversations'

    def __str__(self):
        return f"Conversation for Order {self.order.order_number}"

    def get_unread_count(self, user):
        if user == self.student:
            last_seen = self.student_last_seen
        elif user == self.admin:
            last_seen = self.admin_last_seen
        else:
            return 0
        
        if not last_seen:
            return self.messages.exclude(sender=user).count()
        
        return self.messages.filter(
            created_at__gt=last_seen
        ).exclude(sender=user).count()

    def mark_seen(self, user):
        if user == self.student:
            self.student_last_seen = timezone.now()
        elif user == self.admin:
            self.admin_last_seen = timezone.now()
        self.save(update_fields=['student_last_seen', 'admin_last_seen'])

class Message(models.Model):
    MESSAGE_TYPES = [
        ('text', 'text'),
        ('file', 'file'),
        ('system', 'system'),
        ('edited', 'edited'),
        ('recalled', 'recalled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages', db_index=True)
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    content = models.TextField()
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default='text')
    file_url = models.URLField(blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.IntegerField(null=True, blank=True)
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    is_recalled = models.BooleanField(default=False)
    recalled_at = models.DateTimeField(null=True, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    is_delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['conversation', 'is_read']),
            models.Index(fields=['sender', 'created_at']),
            models.Index(fields=['is_recalled']),
        ]
        ordering = ['created_at']
        db_table = 'messages'

    def __str__(self):
        return f"Message {self.id} in {self.conversation}"

    def mark_as_read(self):
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=['is_read', 'read_at'])

    def mark_as_delivered(self):
        self.is_delivered = True
        self.delivered_at = timezone.now()
        self.save(update_fields=['is_delivered', 'delivered_at'])

    def edit(self, new_content):
        self.content = new_content
        self.is_edited = True
        self.edited_at = timezone.now()
        self.message_type = 'edited'
        self.save(update_fields=['content', 'is_edited', 'edited_at', 'message_type'])

    def recall(self):
        self.is_recalled = True
        self.recalled_at = timezone.now()
        self.content = 'This message was recalled'
        self.message_type = 'recalled'
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
        unique_together = ['message', 'user']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'is_delivered']),
        ]
        db_table = 'message_statuses'

    def __str__(self):
        return f"Status for {self.message} - User {self.user.email}"

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
        unique_together = ['conversation', 'user']
        indexes = [
            models.Index(fields=['conversation', 'updated_at']),
        ]
        db_table = 'typing_statuses'

    def __str__(self):
        return f"{self.user.email} typing in {self.conversation}"