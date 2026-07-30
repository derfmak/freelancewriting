from rest_framework import serializers
from django.utils import timezone
from django.db.models import Sum, Count, Q
from apps.accounts.models import User
from apps.orders.models import Order, Attachment, OrderHistory, OrderTimeline, UserPresence
from apps.payments.models import Transaction, Wallet


class AttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source='uploaded_by.full_name', default='')
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Attachment
        fields = [
            'id', 'file', 'file_url', 'filename', 'file_size', 'mime_type',
            'file_hash', 'uploaded_by', 'uploaded_by_name', 'scan_status',
            'scan_result', 'is_corrupt', 'corruption_error', 'uploaded_at'
        ]
        read_only_fields = ['id', 'uploaded_by', 'uploaded_at', 'file_hash']
    
    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


class OrderSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.full_name', default='')
    client_email = serializers.EmailField(source='client.email', default='')
    writer_name = serializers.CharField(source='writer.full_name', default='N/A')
    writer_email = serializers.EmailField(source='writer.email', default='')
    attachments = AttachmentSerializer(many=True, read_only=True)
    secure_links = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_resubmit = serializers.SerializerMethodField()
    can_reorder = serializers.SerializerMethodField()
    can_split = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'client', 'client_name', 'client_email',
            'writer', 'writer_name', 'writer_email',
            'academic_level', 'paper_type', 'subject', 'topic', 'instructions',
            'pages', 'words', 'spacing', 'slides', 'sources_count',
            'deadline', 'format', 'attachments', 'links', 'secure_links',
            'base_price', 'level_multiplier', 'level_adjusted',
            'urgency_multiplier', 'total_price',
            'status', 'progress_percentage',
            'created_at', 'accepted_at', 'started_at', 'delivered_at',
            'completed_at', 'auto_approve_at',
            'cancelled_at', 'cancelled_by', 'cancellation_reason', 'cancellation_feedback',
            'declined_at', 'declined_by', 'declined_reason', 'declined_feedback',
            'delivered_file', 'revision_count', 'last_revision_requested_at',
            'escrow_released_at', 'refund_amount', 'refund_reason',
            'refund_approved_at', 'refund_processed_at',
            'grade_received', 'rating', 'feedback',
            'parent_order', 'version', 'is_template', 'template_name',
            'order_group', 'split_part', 'split_total',
            'last_activity_at', 'updated_at',
            'can_cancel', 'can_edit', 'can_resubmit', 'can_reorder', 'can_split',
            'timeline'
        ]
        read_only_fields = [
            'id', 'order_number', 'client', 'created_at', 'updated_at',
            'last_activity_at', 'secure_links'
        ]
    
    def get_secure_links(self, obj):
        return obj.get_secure_links()
    
    def get_can_cancel(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.can_cancel(request.user)
        return False
    
    def get_can_edit(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.can_edit(request.user)
        return False
    
    def get_can_resubmit(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.can_resubmit(request.user)
        return False
    
    def get_can_reorder(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.can_reorder(request.user)
        return False
    
    def get_can_split(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.can_split(request.user)
        return False
    
    def get_timeline(self, obj):
        timeline = OrderTimeline.objects.filter(order=obj).order_by('created_at')
        return OrderTimelineSerializer(timeline, many=True).data


class OrderListSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.full_name', default='')
    writer_name = serializers.CharField(source='writer.full_name', default='N/A')
    unread_messages = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'client_name', 'writer_name',
            'topic', 'subject', 'academic_level', 'paper_type',
            'status', 'progress_percentage', 'pages', 'words',
            'deadline', 'total_price', 'created_at', 'updated_at',
            'unread_messages', 'last_message', 'rating', 'feedback'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_unread_messages(self, obj):
        try:
            conversation = getattr(obj, 'conversation', None)
            if conversation:
                request = self.context.get('request')
                if request and request.user:
                    return conversation.get_unread_count(request.user)
        except:
            pass
        return 0
    
    def get_last_message(self, obj):
        try:
            conversation = getattr(obj, 'conversation', None)
            if conversation:
                last_msg = conversation.messages.order_by('-created_at').first()
                if last_msg:
                    return {
                        'content': last_msg.content[:100],
                        'created_at': last_msg.created_at.isoformat(),
                        'sender': last_msg.sender_id
                    }
        except:
            pass
        return None


class OrderCreateSerializer(serializers.ModelSerializer):
    attachments = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        write_only=True
    )
    links = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        write_only=True
    )
    
    class Meta:
        model = Order
        fields = [
            'academic_level', 'paper_type', 'subject', 'topic', 'instructions',
            'pages', 'words', 'spacing', 'slides', 'sources_count',
            'deadline', 'format', 'attachments', 'links'
        ]
    
    def validate_deadline(self, value):
        if value < timezone.now() + timezone.timedelta(hours=12):
            raise serializers.ValidationError('Deadline must be at least 12 hours from now')
        return value
    
    def validate(self, data):
        paper_type = data.get('paper_type')
        pages = data.get('pages')
        words = data.get('words')
        slides = data.get('slides')
        
        if paper_type == 'presentation':
            if not slides:
                raise serializers.ValidationError({'slides': 'Slides are required for presentations'})
        else:
            if not pages and not words:
                raise serializers.ValidationError('Either pages or words must be provided')
        
        return data
    
    def create(self, validated_data):
        attachments_data = validated_data.pop('attachments', [])
        order = super().create(validated_data)
        for file in attachments_data:
            Attachment.objects.create(
                order=order,
                file=file,
                uploaded_by=order.client
            )
        return order


class OrderHistorySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', default='System')
    user_email = serializers.EmailField(source='user.email', default='')
    action_display = serializers.CharField(source='get_action_display')
    
    class Meta:
        model = OrderHistory
        fields = [
            'id', 'order', 'user', 'user_name', 'user_email',
            'action', 'action_display',
            'from_status', 'to_status', 'data',
            'ip_address', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class OrderTimelineSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderTimeline
        fields = [
            'id', 'order', 'status', 'title', 'description',
            'icon', 'color', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=Order.CANCELLATION_REASONS)
    feedback = serializers.CharField(required=False, allow_blank=True)


class DeclineOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True)
    feedback = serializers.CharField(required=False, allow_blank=True)


class ResubmitOrderSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True)


class SplitOrderSerializer(serializers.Serializer):
    parts = serializers.IntegerField(min_value=2, max_value=10, required=True)


class RevisionRequestSerializer(serializers.Serializer):
    notes = serializers.CharField(required=True)


class RefundRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True)


class RatingSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5, required=True)
    feedback = serializers.CharField(required=False, allow_blank=True)


class PriceQuoteSerializer(serializers.Serializer):
    academic_level = serializers.CharField(required=True)
    words = serializers.IntegerField(required=False, min_value=1)
    pages = serializers.DecimalField(required=False, max_digits=8, decimal_places=2, min_value=0.01)
    spacing = serializers.CharField(default='double')
    deadline = serializers.DateTimeField(required=True)
    slides = serializers.IntegerField(required=False, min_value=1)
    paper_type = serializers.CharField(required=False)
    
    def validate(self, data):
        paper_type = data.get('paper_type')
        slides = data.get('slides')
        words = data.get('words')
        pages = data.get('pages')
        
        if paper_type == 'presentation':
            if not slides:
                raise serializers.ValidationError({'slides': 'Slides are required for presentations'})
        else:
            if not words and not pages:
                raise serializers.ValidationError('Either words or pages must be provided')
        
        return data


class UserPresenceSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', default='')
    user_email = serializers.EmailField(source='user.email', default='')
    status = serializers.SerializerMethodField()
    
    class Meta:
        model = UserPresence
        fields = [
            'id', 'user', 'user_name', 'user_email',
            'is_online', 'last_seen_at', 'current_room',
            'status', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'updated_at']
    
    def get_status(self, obj):
        if obj.is_online:
            return 'online'
        if obj.last_seen_at:
            diff = timezone.now() - obj.last_seen_at
            if diff.total_seconds() < 300:
                return 'recently'
            if diff.total_seconds() < 3600:
                return 'away'
        return 'offline'


class UserAdminSerializer(serializers.ModelSerializer):
    wallet_balance = serializers.SerializerMethodField()
    total_orders = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()
    total_revenue = serializers.SerializerMethodField()
    active_orders = serializers.SerializerMethodField()
    completed_orders = serializers.SerializerMethodField()
    cancelled_orders = serializers.SerializerMethodField()
    declined_orders = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'full_name', 'role', 'is_active', 'is_suspended',
            'email_verified', 'phone_verified', 'institution', 'phone',
            'last_login', 'date_joined', 'created_at',
            'wallet_balance', 'total_orders', 'total_spent', 'total_revenue',
            'active_orders', 'completed_orders', 'cancelled_orders', 'declined_orders',
            'failed_login_attempts', 'account_locked_until', 'suspension_reason'
        ]
        read_only_fields = ['id', 'last_login', 'date_joined', 'created_at']

    def get_wallet_balance(self, obj):
        try:
            return float(obj.wallet.balance) if hasattr(obj, 'wallet') else 0
        except:
            return 0

    def get_total_orders(self, obj):
        return obj.orders.count()

    def get_total_spent(self, obj):
        try:
            return float(obj.wallet.total_spent) if hasattr(obj, 'wallet') else 0
        except:
            return 0

    def get_total_revenue(self, obj):
        return obj.orders.filter(status='completed').aggregate(
            total=Sum('total_price')
        )['total'] or 0

    def get_active_orders(self, obj):
        return obj.orders.filter(
            status__in=['request', 'in_progress', 'awaiting_approval']
        ).count()

    def get_completed_orders(self, obj):
        return obj.orders.filter(status='completed').count()
    
    def get_cancelled_orders(self, obj):
        return obj.orders.filter(status='cancelled').count()
    
    def get_declined_orders(self, obj):
        return obj.orders.filter(status='declined').count()


class OrderAdminSerializer(serializers.ModelSerializer):
    client = serializers.PrimaryKeyRelatedField(source='client', read_only=True)
    client_name = serializers.CharField(source='client.full_name', default='N/A')
    client_email = serializers.EmailField(source='client.email', default='N/A')
    title = serializers.CharField(source='topic')
    description = serializers.CharField(source='instructions')
    word_count = serializers.IntegerField(source='words')
    total = serializers.DecimalField(source='total_price', max_digits=10, decimal_places=2)
    can_cancel = serializers.SerializerMethodField()
    can_resubmit = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'client', 'client_name', 'client_email',
            'title', 'description', 'word_count', 'deadline', 'status',
            'total_price', 'total', 'progress_percentage',
            'paper_type', 'academic_level', 'format',
            'rating', 'feedback', 'delivered_at', 'created_at', 'updated_at',
            'cancelled_at', 'cancellation_reason', 'cancellation_feedback',
            'declined_at', 'declined_reason', 'declined_feedback',
            'can_cancel', 'can_resubmit', 'version', 'parent_order'
        ]
        read_only_fields = [
            'id', 'order_number', 'created_at', 'updated_at',
            'delivered_at', 'client'
        ]
    
    def get_can_cancel(self, obj):
        return obj.status not in ['completed', 'cancelled']
    
    def get_can_resubmit(self, obj):
        return obj.status == 'declined'


class TransactionAdminSerializer(serializers.ModelSerializer):
    client_email = serializers.EmailField(source='user.email', default='N/A')
    client_name = serializers.CharField(source='user.full_name', default='N/A')
    order_number = serializers.CharField(source='order.order_number', default='N/A')

    class Meta:
        model = Transaction
        fields = [
            'id', 'user', 'client_email', 'client_name',
            'order', 'order_number', 'amount', 'type', 'status',
            'payment_method', 'reference', 'description',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class DashboardStatsSerializer(serializers.Serializer):
    total_users = serializers.IntegerField()
    new_users_today = serializers.IntegerField()
    active_users = serializers.IntegerField()

    total_orders = serializers.IntegerField()
    pending_orders = serializers.IntegerField()
    in_progress_orders = serializers.IntegerField()
    completed_today = serializers.IntegerField()
    cancelled_today = serializers.IntegerField()

    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    revenue_today = serializers.DecimalField(max_digits=12, decimal_places=2)
    pending_payouts = serializers.DecimalField(max_digits=12, decimal_places=2)

    average_rating = serializers.DecimalField(max_digits=3, decimal_places=2)
    completion_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    overdue_orders = serializers.IntegerField()
    unread_messages = serializers.IntegerField()


class PriorityQueueSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order_number = serializers.CharField()
    client_name = serializers.CharField()
    deadline = serializers.DateTimeField()
    urgency = serializers.CharField()
    status = serializers.CharField()


class TemplateOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'academic_level', 'paper_type',
            'subject', 'topic', 'instructions', 'pages', 'words',
            'spacing', 'slides', 'sources_count', 'format',
            'links', 'template_name', 'created_at'
        ]
        read_only_fields = ['id', 'order_number', 'created_at']


class WalletAdjustSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(required=True)
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        required=True
    )
    reason = serializers.CharField(max_length=500, required=True)
    type = serializers.ChoiceField(choices=['credit', 'debit'], required=True)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value


class RefundActionSerializer(serializers.Serializer):
    order_id = serializers.UUIDField(required=True)
    reason = serializers.CharField(max_length=500, required=True)
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True
    )
    notify_client = serializers.BooleanField(default=True)

    def validate_amount(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value