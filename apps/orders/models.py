import uuid
from decimal import Decimal
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
        ('request', 'request'),
        ('in_progress', 'in_progress'),
        ('awaiting_approval', 'awaiting_approval'),
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
        ('dissertation', 'dissertation'),
        ('thesis', 'thesis'),
        ('case_study', 'case_study'),
        ('literature_review', 'literature_review'),
        ('article_review', 'article_review'),
        ('book_report', 'book_report'),
        ('speech', 'speech'),
        ('presentation', 'presentation'),
    ]

    FORMATS = [
        ('apa', 'apa'),
        ('mla', 'mla'),
        ('chicago', 'chicago'),
        ('harvard', 'harvard'),
        ('turabian', 'turabian'),
        ('vancouver', 'vancouver'),
        ('oscola', 'oscola'),
        ('ieee', 'ieee'),
    ]

    PRICE_PER_PAGE = Decimal('15.00')
    PRICE_PER_SLIDE = Decimal('5.00')
    REVISION_WINDOW_HOURS = 48

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=20, unique=True, db_index=True)
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', db_index=True)
    writer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='writer_orders', db_index=True)

    academic_level = models.CharField(max_length=20, choices=ACADEMIC_LEVELS)
    paper_type = models.CharField(max_length=30, choices=PAPER_TYPES)
    subject = models.CharField(max_length=200)
    topic = models.CharField(max_length=500)
    instructions = models.TextField()
    pages = models.IntegerField(validators=[MinValueValidator(1)])
    words = models.IntegerField(validators=[MinValueValidator(1)], null=True, blank=True)
    slides = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    sources_count = models.IntegerField(default=0)
    deadline = models.DateTimeField(db_index=True)
    format = models.CharField(max_length=20, choices=FORMATS)

    attachments = models.ManyToManyField(Attachment, blank=True, related_name='orders')
    links = models.JSONField(default=list, blank=True)

    total_price = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='request', db_index=True)
    progress_percentage = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    auto_approve_at = models.DateTimeField(null=True, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='cancelled_orders')
    cancellation_reason = models.TextField(blank=True)

    delivered_file = models.ForeignKey(Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivered_orders')

    revision_count = models.IntegerField(default=0)
    last_revision_requested_at = models.DateTimeField(null=True, blank=True)

    escrow_released_at = models.DateTimeField(null=True, blank=True)

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
            models.Index(fields=['writer', 'status']),
            models.Index(fields=['status', 'deadline']),
            models.Index(fields=['auto_approve_at']),
        ]
        db_table = 'orders'

    def __str__(self):
        return self.order_number

    @staticmethod
    def urgency_multiplier(deadline):
        hours_remaining = (deadline - timezone.now()).total_seconds() / 3600
        if hours_remaining <= 6:
            return Decimal('0.25')
        if hours_remaining <= 12:
            return Decimal('0.20')
        if hours_remaining <= 24:
            return Decimal('0.15')
        if hours_remaining <= 72:
            return Decimal('0.10')
        if hours_remaining <= 168:
            return Decimal('0.05')
        return Decimal('0.00')

    @classmethod
    def calculate_price(cls, paper_type, pages, slides, deadline):
        if paper_type == 'presentation' and slides:
            base_price = cls.PRICE_PER_SLIDE * slides
        else:
            base_price = cls.PRICE_PER_PAGE * pages
        multiplier = cls.urgency_multiplier(deadline)
        total_price = (base_price + (base_price * multiplier)).quantize(Decimal('0.01'))
        return base_price.quantize(Decimal('0.01')), multiplier, total_price

    def save(self, *args, **kwargs):
        if not self.words and self.pages and self.paper_type != 'presentation':
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
        ('accept', 'accept'),
        ('reject', 'reject'),
        ('start', 'start'),
        ('deliver', 'deliver'),
        ('complete', 'complete'),
        ('auto_approve', 'auto_approve'),
        ('cancel', 'cancel'),
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