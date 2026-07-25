import uuid
from decimal import Decimal
from datetime import datetime
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
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
        ('declined', 'declined'),
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

    CANCELLATION_REASONS = [
        ('deadline_passed', 'Deadline passed with no response'),
        ('unsatisfied_quality', 'Unsatisfied with quality'),
        ('found_elsewhere', 'Found help elsewhere'),
        ('change_of_requirements', 'Changed requirements'),
        ('writer_communication', 'Poor writer communication'),
        ('other', 'Other reason'),
    ]

    REVISION_WINDOW_HOURS = 48
    SLIDE_PRICE = Decimal('8.00')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=20, unique=True, db_index=True)
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', db_index=True)
    writer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='writer_orders', db_index=True)

    academic_level = models.CharField(max_length=20, choices=ACADEMIC_LEVELS)
    paper_type = models.CharField(max_length=30, choices=PAPER_TYPES)
    subject = models.CharField(max_length=200, db_index=True)
    topic = models.CharField(max_length=500, db_index=True)
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
    cancellation_reason = models.CharField(max_length=30, choices=CANCELLATION_REASONS, null=True, blank=True)
    cancellation_feedback = models.TextField(blank=True)

    declined_at = models.DateTimeField(null=True, blank=True)
    declined_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='declined_orders')
    declined_reason = models.TextField(blank=True)
    declined_feedback = models.TextField(blank=True)

    delivered_file = models.ForeignKey(Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivered_orders')

    revision_count = models.IntegerField(default=0)
    last_revision_requested_at = models.DateTimeField(null=True, blank=True)

    escrow_released_at = models.DateTimeField(null=True, blank=True)

    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refund_reason = models.TextField(blank=True)
    refund_approved_at = models.DateTimeField(null=True, blank=True)
    refund_processed_at = models.DateTimeField(null=True, blank=True)

    grade_received = models.CharField(max_length=10, blank=True)

    rating = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    feedback = models.TextField(blank=True)

    parent_order = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    version = models.IntegerField(default=1)
    is_template = models.BooleanField(default=False)
    template_name = models.CharField(max_length=200, blank=True)

    order_group = models.UUIDField(null=True, blank=True, db_index=True)
    split_part = models.IntegerField(default=0)
    split_total = models.IntegerField(default=0)

    last_activity_at = models.DateTimeField(auto_now=True, db_index=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['student', 'created_at']),
            models.Index(fields=['writer', 'status']),
            models.Index(fields=['status', 'deadline']),
            models.Index(fields=['auto_approve_at']),
            models.Index(fields=['parent_order']),
            models.Index(fields=['order_group']),
            models.Index(fields=['status', 'cancelled_at']),
            models.Index(fields=['last_activity_at']),
            models.Index(fields=['order_number', 'topic']),
            models.Index(fields=['student', 'order_number', 'topic']),
        ]
        db_table = 'orders'

    def __str__(self):
        return self.order_number

    def generate_order_number(self):
        year = datetime.now().strftime('%Y')
        month = datetime.now().strftime('%m')
        day = datetime.now().strftime('%d')
        
        sequence = 1
        last_order = Order.objects.filter(
            order_number__startswith=f'#{year}{month}{day}'
        ).order_by('-order_number').first()
        
        if last_order:
            try:
                sequence = int(last_order.order_number[-4:]) + 1
            except ValueError:
                sequence = 1
        
        if sequence > 9999:
            sequence = 1
            timestamp = int(datetime.now().timestamp() * 1000) % 10000
            return f'#{year}{month}{day}{timestamp:04d}'
        
        return f'#{year}{month}{day}{sequence:04d}'

    def clean(self):
        if self.paper_type == 'presentation':
            if not self.slides:
                raise ValidationError({'slides': 'Number of slides is required for presentations'})
        else:
            if not self.words and not self.pages:
                raise ValidationError('Either words or pages must be provided')
        
        if not self.deadline:
            raise ValidationError({'deadline': 'Deadline is required'})
        
        if self.deadline and self.deadline < timezone.now():
            raise ValidationError({'deadline': 'Deadline cannot be in the past'})

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
    def calculate_price(cls, academic_level, words, spacing, deadline, slides=None, paper_type=None):
        if paper_type == 'presentation' and slides:
            base_price = Decimal(str(slides)) * cls.SLIDE_PRICE
            level_mult = Decimal('1.00')
            level_adjusted = base_price
            urgency_mult = cls.get_urgency_multiplier(deadline)
            total_price = (level_adjusted * urgency_mult).quantize(Decimal('0.01'))
            
            return {
                'pages': Decimal('0.00'),
                'words_per_page': 0,
                'cost_per_page': float(cls.SLIDE_PRICE),
                'base_price': base_price.quantize(Decimal('0.01')),
                'level_multiplier': level_mult,
                'level_adjusted': level_adjusted.quantize(Decimal('0.01')),
                'urgency_multiplier': urgency_mult,
                'total_price': total_price,
                'slides': slides,
                'paper_type': 'presentation'
            }
        
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
            'total_price': total_price,
            'slides': None,
            'paper_type': paper_type
        }

    def can_cancel(self, user):
        if self.student_id != user.id:
            return False
        if self.status == 'completed':
            return False
        if self.status == 'cancelled':
            return False
        if self.status == 'declined':
            return True
        if self.status == 'awaiting_approval':
            return True
        if self.status == 'in_progress' and self.deadline < timezone.now():
            return True
        return False

    def can_edit(self, user):
        if self.student_id != user.id:
            return False
        if self.status in ['cancelled', 'completed']:
            return False
        if self.status == 'declined':
            return True
        if self.status == 'request':
            return True
        return False

    def can_resubmit(self, user):
        if self.student_id != user.id:
            return False
        return self.status == 'declined'

    def can_reorder(self, user):
        if self.student_id != user.id:
            return False
        return self.status in ['completed', 'cancelled']

    def can_split(self, user):
        if self.student_id != user.id:
            return False
        if self.status not in ['request', 'in_progress']:
            return False
        if self.pages and self.pages > 5:
            return True
        if self.words and self.words > 1500:
            return True
        return False

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()
        
        if self.paper_type == 'presentation':
            if self.slides and not self.words:
                self.words = self.slides * 50
                self.pages = None
            elif self.slides and not self.pages:
                self.pages = None
            elif not self.slides:
                self.slides = 1
                self.words = 50
                self.pages = None
        else:
            if self.words and not self.pages:
                self.pages = self.words_to_pages(self.words, self.spacing)
            elif self.pages and not self.words:
                self.words = self.pages_to_words(self.pages, self.spacing)
            elif not self.words and not self.pages:
                self.words = 275
                self.pages = Decimal('1.00')
            self.slides = None
        
        if not self.base_price:
            price_data = self.calculate_price(
                self.academic_level,
                self.words,
                self.spacing,
                self.deadline,
                self.slides,
                self.paper_type
            )
            self.base_price = price_data['base_price']
            self.level_multiplier = price_data['level_multiplier']
            self.level_adjusted = price_data['level_adjusted']
            self.urgency_multiplier = price_data['urgency_multiplier']
            self.total_price = price_data['total_price']
        
        if self.pk and not self.order_group:
            self.order_group = self.id
        
        super().save(*args, **kwargs)

    def get_secure_links(self):
        if not self.links:
            return []
        sanitized_links = []
        dangerous_protocols = ['javascript:', 'data:', 'vbscript:', 'file:']
        for link in self.links:
            if isinstance(link, dict):
                url = link.get('url', '')
                for protocol in dangerous_protocols:
                    if url.lower().startswith(protocol):
                        url = ''
                        break
                url = url.replace('<', '&lt;').replace('>', '&gt;')
                link['url'] = url
                sanitized_links.append(link)
            elif isinstance(link, str):
                for protocol in dangerous_protocols:
                    if link.lower().startswith(protocol):
                        link = ''
                        break
                link = link.replace('<', '&lt;').replace('>', '&gt;')
                sanitized_links.append({'url': link, 'title': ''})
        return sanitized_links


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
        ('decline', 'decline'),
        ('resubmit', 'resubmit'),
        ('reorder', 'reorder'),
        ('split', 'split'),
        ('edit', 'edit'),
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


class OrderTimeline(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='timeline')
    status = models.CharField(max_length=20, choices=Order.STATUS_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)
    color = models.CharField(max_length=20, default='gray')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['order', 'created_at']),
        ]
        db_table = 'order_timeline'

    def __str__(self):
        return f"{self.order.order_number} - {self.status}"


class UserPresence(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='presence')
    is_online = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(default=timezone.now)
    current_room = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'is_online']),
            models.Index(fields=['last_seen_at']),
        ]
        db_table = 'user_presence'

    def __str__(self):
        return f"{self.user.email} - {'Online' if self.is_online else 'Offline'}"