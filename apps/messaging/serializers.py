from rest_framework import serializers

from apps.accounts.models import User

from .models import Conversation, Message


class MessageSenderSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email', 'role']


class MessageSerializer(serializers.ModelSerializer):
    sender = MessageSenderSerializer(read_only=True)

    class Meta:
        model = Message
        fields = [
            'id', 'conversation', 'sender', 'content', 'message_type',
            'file_url', 'file_name', 'file_size', 'is_edited', 'edited_at',
            'is_recalled', 'recalled_at', 'is_read', 'read_at',
            'is_delivered', 'delivered_at', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


class MessageCreateSerializer(serializers.Serializer):
    content = serializers.CharField(required=False, allow_blank=True, default='')
    message_type = serializers.ChoiceField(choices=Message.MESSAGE_TYPES, default=Message.TEXT)
    file_url = serializers.URLField(required=False, allow_blank=True, default='')
    file_name = serializers.CharField(required=False, allow_blank=True, default='')
    file_size = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate(self, data):
        if data.get('message_type') == Message.TEXT and not data.get('content', '').strip():
            raise serializers.ValidationError('content is required for text messages')
        if data.get('message_type') == Message.FILE and not data.get('file_url'):
            raise serializers.ValidationError('file_url is required for file messages')
        return data


class MessageEditSerializer(serializers.Serializer):
    content = serializers.CharField()

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError('content cannot be empty')
        return value


class ConversationLastMessageSerializer(serializers.ModelSerializer):
    sender = MessageSenderSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'content', 'message_type', 'sender', 'created_at']


class ConversationSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_email = serializers.EmailField(source='student.email', read_only=True)
    admin_name = serializers.SerializerMethodField()
    order = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'order', 'student_name', 'student_email', 'admin_name',
            'last_message_at', 'unread_count', 'last_message', 'created_at',
        ]

    def get_student_name(self, obj):
        return f'{obj.student.first_name} {obj.student.last_name}'.strip() or obj.student.email

    def get_admin_name(self, obj):
        return f'{obj.admin.first_name} {obj.admin.last_name}'.strip() or obj.admin.email

    def get_order(self, obj):
        return {
            'id': str(obj.order.id),
            'order_number': obj.order.order_number,
            'topic': getattr(obj.order, 'topic', ''),
            'status': getattr(obj.order, 'status', ''),
        }

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if not request:
            return 0
        return obj.get_unread_count(request.user)

    def get_last_message(self, obj):
        message = obj.messages.order_by('-created_at').first()
        if not message:
            return None
        return ConversationLastMessageSerializer(message).data