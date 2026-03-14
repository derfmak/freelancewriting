from rest_framework import serializers
from django.utils import timezone
from .models import Order, Attachment, OrderHistory
from .services import OrderNumberGenerator, PricingEngine, OrderWorkflow

class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ['id', 'filename', 'file_size', 'mime_type', 'uploaded_at']
        read_only_fields = ['id', 'filename', 'file_size', 'mime_type', 'uploaded_at']

class OrderCreateSerializer(serializers.Serializer):
    academic_level = serializers.ChoiceField(choices=Order.ACADEMIC_LEVELS)
    paper_type = serializers.ChoiceField(choices=Order.PAPER_TYPES)
    subject = serializers.CharField(max_length=200)
    topic = serializers.CharField(max_length=500)
    instructions = serializers.CharField()
    pages = serializers.IntegerField(min_value=1)
    sources_count = serializers.IntegerField(default=0, min_value=0)
    deadline = serializers.DateTimeField()
    format = serializers.ChoiceField(choices=Order.FORMATS)
    preferred_writer_level = serializers.ChoiceField(choices=Order.WRITER_LEVELS, default='any')
    links = serializers.JSONField(default=list, required=False)
    attachment_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    
    plagiarism_report = serializers.BooleanField(default=False)
    abstract = serializers.BooleanField(default=False)
    proofreading = serializers.BooleanField(default=False)
    one_page_summary = serializers.BooleanField(default=False)
    
    def validate_deadline(self, value):
        min_deadline = timezone.now() + timezone.timedelta(hours=6)
        if value < min_deadline:
            raise serializers.ValidationError('Deadline must be at least 6 hours from now')
        return value
    
    def validate(self, data):
        request = self.context.get('request')
        user = request.user
        
        extras = []
        if data.get('plagiarism_report'):
            extras.append('plagiarism_report')
        if data.get('abstract'):
            extras.append('abstract')
        if data.get('proofreading'):
            extras.append('proofreading')
        if data.get('one_page_summary'):
            extras.append('one_page_summary')
        
        pricing = PricingEngine.calculate(
            data['academic_level'],
            data['pages'],
            data['deadline'],
            extras
        )
        
        try:
            wallet = user.wallet
            balance = wallet.balance
        except:
            from apps.payments.models import Wallet
            wallet, created = Wallet.objects.get_or_create(user=user)
            balance = wallet.balance
        
        total_price = pricing['total_price']
        
        if balance < total_price:
            raise serializers.ValidationError({
                'wallet': f'Insufficient funds. Required: ${total_price}, Available: ${balance}'
            })
        
        data['calculated_price'] = pricing
        return data
    
    def create(self, validated_data):
        request = self.context.get('request')
        attachment_ids = validated_data.pop('attachment_ids', [])
        pricing = validated_data.pop('calculated_price')
        
        from apps.payments.services import WalletService
        
        order = Order.objects.create(
            order_number=OrderNumberGenerator.generate(),
            student=request.user,
            **validated_data,
            base_price=pricing['base_price'],
            urgency_multiplier=pricing['urgency_multiplier'],
            extras_price=pricing['extras_price'],
            total_price=pricing['total_price']
        )
        
        try:
            WalletService.debit(
                wallet=request.user.wallet,
                amount=pricing['total_price'],
                transaction_type='order_payment',
                description=f'Payment for order {order.order_number}',
                order=order
            )
        except Exception as e:
            order.delete()
            raise serializers.ValidationError({
                'payment': f'Payment failed: {str(e)}'
            })
        
        if attachment_ids:
            attachments = Attachment.objects.filter(id__in=attachment_ids, uploaded_by=request.user)
            order.attachments.set(attachments)
        
        return order

class OrderDetailSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.full_name', read_only=True)
    student_email = serializers.EmailField(source='student.email', read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)
    available_actions = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ['order_number', 'created_at', 'approved_at', 'started_at', 
                           'delivered_at', 'completed_at', 'updated_at']
    
    def get_available_actions(self, obj):
        return OrderWorkflow.get_student_actions(obj)

class OrderListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['id', 'order_number', 'topic', 'status', 'pages', 'total_price', 
                 'deadline', 'created_at', 'progress_percentage']

class OrderUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['instructions', 'attachments']
        extra_kwargs = {
            'instructions': {'required': False},
            'attachments': {'required': False}
        }

class OrderActionSerializer(serializers.Serializer):
    ACTION_CHOICES = [
        ('cancel', 'cancel'),
        ('request_revision', 'request_revision'),
        ('approve', 'approve'),
        ('request_refund', 'request_refund'),
    ]
    
    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    reason = serializers.CharField(required=False, allow_blank=True)
    grade = serializers.CharField(required=False, allow_blank=True)

class OrderRatingSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    feedback = serializers.CharField(required=False, allow_blank=True)

class OrderHistorySerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    
    class Meta:
        model = OrderHistory
        fields = ['id', 'action', 'from_status', 'to_status', 'data', 'created_at', 'user_email']

class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    
    def validate_file(self, value):
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError('File size cannot exceed 10MB')
        
        allowed_types = [
            'image/jpeg', 'image/png', 'image/gif',
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text/plain'
        ]
        
        if value.content_type not in allowed_types:
            raise serializers.ValidationError(f'File type {value.content_type} is not allowed')
        
        return value