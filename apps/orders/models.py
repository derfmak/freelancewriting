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

    SPACING_CHOICES = [
        ('single', 'single'),
        ('one_point_five', 'one_point_five'),
        ('double', 'double'),
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
    pages = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0.01)])
    words = models.IntegerField(validators=[MinValueValidator(1)], null=True, blank=True)
    spacing = models.CharField(max_length=20, choices=SPACING_CHOICES, default='double')
    slides = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    sources_count = models.IntegerField(default=0)
    deadline = models.DateTimeField(db_index=True)
    format = models.CharField(max_length=20, choices=FORMATS)

    attachments = models.ManyToManyField(Attachment, blank=True, related_name='orders')
    links = models.JSONField(default=list, blank=True)

    base_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    level_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1.00)
    level_adjusted = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    urgency_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1.00)
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
    def get_spacing_data(spacing):
        spacing_data = {
            'single': {'multiplier': 1.0, 'words_per_page': 550, 'cost_per_page': Decimal('20.00')},
            'one_point_five': {'multiplier': 1.5, 'words_per_page': 367, 'cost_per_page': Decimal('15.00')},
            'double': {'multiplier': 2.0, 'words_per_page': 275, 'cost_per_page': Decimal('10.00')}
        }
        return spacing_data.get(spacing, spacing_data['double'])

    @staticmethod
    def get_level_multiplier(academic_level):
        level_multipliers = {
            'high_school': Decimal('1.00'),
            'undergraduate': Decimal('1.10'),
            'masters': Decimal('1.20'),
            'phd': Decimal('1.30'),
        }
        return level_multipliers.get(academic_level, Decimal('1.00'))

    @staticmethod
    def get_urgency_multiplier(deadline):
        hours_remaining = (deadline - timezone.now()).total_seconds() / 3600
        if hours_remaining <= 12:
            return Decimal('1.30')
        elif hours_remaining <= 24:
            return Decimal('1.25')
        elif hours_remaining <= 48:
            return Decimal('1.20')
        elif hours_remaining <= 72:
            return Decimal('1.15')
        elif hours_remaining <= 120:
            return Decimal('1.10')
        elif hours_remaining <= 312:
            return Decimal('1.05')
        return Decimal('1.00')

    @classmethod
    def words_to_pages(cls, words, spacing):
        data = cls.get_spacing_data(spacing)
        return Decimal(str(words)) / Decimal(str(data['words_per_page']))

    @classmethod
    def pages_to_words(cls, pages, spacing):
        data = cls.get_spacing_data(spacing)
        return int(Decimal(str(pages)) * Decimal(str(data['words_per_page'])))

    @classmethod
    def calculate_price(cls, academic_level, words, spacing, deadline):
        data = cls.get_spacing_data(spacing)
        pages = cls.words_to_pages(words, spacing)
        
        base_price = pages * data['cost_per_page']
        
        level_mult = cls.get_level_multiplier(academic_level)
        level_adjusted = base_price * level_mult
        
        urgency_mult = cls.get_urgency_multiplier(deadline)
        total_price = (level_adjusted * urgency_mult).quantize(Decimal('0.01'))
        
        return {
            'pages': pages.quantize(Decimal('0.01')),
            'words_per_page': data['words_per_page'],
            'cost_per_page': data['cost_per_page'],
            'base_price': base_price.quantize(Decimal('0.01')),
            'level_multiplier': level_mult,
            'level_adjusted': level_adjusted.quantize(Decimal('0.01')),
            'urgency_multiplier': urgency_mult,
            'total_price': total_price
        }

    def save(self, *args, **kwargs):
        if not self.order_number:
            import random
            import string
            from datetime import datetime
            year = datetime.now().strftime('%y')
            random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            self.order_number = f"ORD-{year}-{random_part}"
        
        if self.paper_type == 'presentation':
            if self.slides and not self.words:
                self.words = self.slides * 50
        else:
            if self.words and not self.pages:
                self.pages = self.words_to_pages(self.words, self.spacing)
            elif self.pages and not self.words:
                self.words = self.pages_to_words(self.pages, self.spacing)
            elif not self.words and not self.pages:
                self.words = 275
                self.pages = Decimal('1.00')
        
        if not self.base_price:
            price_data = self.calculate_price(
                self.academic_level,
                self.words,
                self.spacing,
                self.deadline
            )
            self.base_price = price_data['base_price']
            self.level_multiplier = price_data['level_multiplier']
            self.level_adjusted = price_data['level_adjusted']
            self.urgency_multiplier = price_data['urgency_multiplier']
            self.total_price = price_data['total_price']
        
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