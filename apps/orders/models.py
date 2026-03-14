import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from apps.accounts.models import User

class Attachment(models.Model):
    SCAN_STATUS = [
        ('pending', 'pending'),
        ('scanning', 'scanning'),
        ('clean', 'clean'),
        ('infected', 'infected'),
        ('corrupt', 'corrupt'),
        ('failed', 'failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to='attachments/%Y/%m/%d/')
    filename = models.CharField(max_length=255)
    file_size = models.IntegerField()
    mime_type = models.CharField(max_length=100)
    file_hash = models.CharField(max_length=64, blank=True, db_index=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attachments')
    scan_status = models.CharField(max_length=20, choices=SCAN_STATUS, default='pending')
    scan_result = models.JSONField(default=dict)
    is_corrupt = models.BooleanField(default=False)
    corruption_error = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['uploaded_by', 'uploaded_at']),
            models.Index(fields=['scan_status']),
            models.Index(fields=['is_corrupt']),
            models.Index(fields=['file_hash']),
        ]
        db_table = 'attachments'

    def __str__(self):
        return self.filename

class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'pending'),
        ('ongoing', 'ongoing'),
        ('awaiting_review', 'awaiting_review'),
        ('completed', 'completed'),
        ('cancelled', 'cancelled'),
        ('refund_pending', 'refund_pending'),
    ]
    
    ACADEMIC_LEVELS = [
        ('high_school', 'high_school'),
        ('undergraduate', 'undergraduate'),
        ('masters', 'masters'),
        ('phd', 'phd'),
    ]
    
    PAPER_TYPES = [
        ('essay', 'essay'),
        ('research_paper', 'research_paper'),
        ('term_paper', 'term_paper'),
        ('thesis', 'thesis'),
        ('dissertation', 'dissertation'),
        ('case_study', 'case_study'),
        ('coursework', 'coursework'),
        ('lab_report', 'lab_report'),
        ('book_review', 'book_review'),
        ('article', 'article'),
    ]
    
    FORMATS = [
        ('apa', 'apa'),
        ('mla', 'mla'),
        ('chicago', 'chicago'),
        ('harvard', 'harvard'),
        ('ieee', 'ieee'),
    ]

    WRITER_LEVELS = [
        ('any', 'any'),
        ('master', 'master'),
        ('phd', 'phd'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=20, unique=True, db_index=True)
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', db_index=True)
    
    academic_level = models.CharField(max_length=20, choices=ACADEMIC_LEVELS)
    paper_type = models.CharField(max_length=20, choices=PAPER_TYPES)
    subject = models.CharField(max_length=200)
    topic = models.CharField(max_length=500)
    instructions = models.TextField()
    pages = models.IntegerField(validators=[MinValueValidator(1)])
    words = models.IntegerField(validators=[MinValueValidator(1)], null=True, blank=True)
    sources_count = models.IntegerField(default=0)
    deadline = models.DateTimeField(db_index=True)
    format = models.CharField(max_length=20, choices=FORMATS)
    preferred_writer_level = models.CharField(max_length=20, choices=WRITER_LEVELS, default='any')
    
    attachments = models.ManyToManyField(Attachment, blank=True, related_name='orders')
    links = models.JSONField(default=list, blank=True)
    
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    writer_premium = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    extras_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    plagiarism_report = models.BooleanField(default=False)
    abstract = models.BooleanField(default=False)
    proofreading = models.BooleanField(default=False)
    one_page_summary = models.BooleanField(default=False)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    progress_percentage = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    auto_approve_at = models.DateTimeField(null=True, blank=True)
    
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='cancelled_orders')
    cancellation_reason = models.TextField(blank=True)
    
    delivered_file = models.ForeignKey(Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivered_orders')
    plagiarism_report_file = models.ForeignKey(Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name='plagiarism_orders')
    
    revision_count = models.IntegerField(default=0)
    last_revision_requested_at = models.DateTimeField(null=True, blank=True)
    
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refund_reason = models.TextField(blank=True)
    refund_approved_at = models.DateTimeField(null=True, blank=True)
    grade_received = models.CharField(max_length=10, blank=True)
    
    rating = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    feedback = models.TextField(blank=True)
    
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['student', 'created_at']),
            models.Index(fields=['status', 'deadline']),
            models.Index(fields=['auto_approve_at']),
        ]
        db_table = 'orders'

    def __str__(self):
        return self.order_number
        
    def save(self, *args, **kwargs):
        if not self.words and self.pages:
            self.words = self.pages * 275
        if not self.order_number:
            import random
            import string
            from datetime import datetime
            year = datetime.now().strftime('%y')
            random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            self.order_number = f"ORD-{year}-{random_part}"
        super().save(*args, **kwargs)

class OrderHistory(models.Model):
    ACTIONS = [
        ('create', 'create'),
        ('approve', 'approve'),
        ('start', 'start'),
        ('deliver', 'deliver'),
        ('complete', 'complete'),
        ('cancel', 'cancel'),
        ('reject', 'reject'),
        ('refund_request', 'refund_request'),
        ('refund_approve', 'refund_approve'),
        ('refund_deny', 'refund_deny'),
        ('revise', 'revise'),
        ('update', 'update'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='history')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=20, choices=ACTIONS)
    from_status = models.CharField(max_length=20, null=True, blank=True)
    to_status = models.CharField(max_length=20, null=True, blank=True)
    data = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['order', 'created_at']),
            models.Index(fields=['action']),
        ]
        db_table = 'order_history'

    def __str__(self):
        return f"{self.order.order_number} - {self.action}"