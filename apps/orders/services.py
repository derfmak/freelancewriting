import secrets
import string
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
from apps.payments.services import WalletService


class OrderNumberGenerator:
    
    @staticmethod
    def generate():
        now = timezone.now()
        year = now.strftime('%Y')
        month = now.strftime('%m')
        day = now.strftime('%d')
        
        from apps.orders.models import Order
        
        last_order = Order.objects.filter(
            order_number__startswith=f'#{year}{month}{day}'
        ).order_by('-order_number').first()
        
        if last_order:
            try:
                sequence = int(last_order.order_number[-4:]) + 1
            except ValueError:
                sequence = 1
        else:
            sequence = 1
        
        if sequence > 9999:
            timestamp = int(now.timestamp() * 1000) % 10000
            return f'#{year}{month}{day}{timestamp:04d}'
        
        return f'#{year}{month}{day}{sequence:04d}'


class PricingEngine:
    
    ACADEMIC_RATES = {
        'high_school': Decimal('10.00'),
        'undergraduate': Decimal('12.00'),
        'masters': Decimal('18.00'),
        'phd': Decimal('25.00'),
    }
    
    ACADEMIC_MULTIPLIERS = {
        'high_school': Decimal('1.00'),
        'undergraduate': Decimal('1.10'),
        'masters': Decimal('1.20'),
        'phd': Decimal('1.30'),
    }
    
    SPACING_DATA = {
        'single': {'multiplier': 1.0, 'words_per_page': 550, 'cost_per_page': Decimal('20.00')},
        'one_point_five': {'multiplier': 1.5, 'words_per_page': 367, 'cost_per_page': Decimal('15.00')},
        'double': {'multiplier': 2.0, 'words_per_page': 275, 'cost_per_page': Decimal('10.00')},
    }
    
    URGENCY_MULTIPLIERS = [
        (12, Decimal('1.30')),
        (24, Decimal('1.25')),
        (48, Decimal('1.20')),
        (72, Decimal('1.15')),
        (120, Decimal('1.10')),
        (312, Decimal('1.05')),
    ]
    
    EXTRAS = {
        'plagiarism_report': Decimal('10.00'),
        'abstract': Decimal('15.00'),
        'proofreading': Decimal('8.00'),
        'one_page_summary': Decimal('12.00'),
    }
    
    SLIDE_PRICE = Decimal('8.00')
    
    @classmethod
    def calculate(cls, academic_level, words, spacing, deadline, slides=None, paper_type=None, extras=None):
        
        if paper_type == 'presentation' and slides:
            base_price = Decimal(str(slides)) * cls.SLIDE_PRICE
            level_mult = Decimal('1.00')
            level_adjusted = base_price
            urgency_mult = cls._get_urgency_multiplier(deadline)
            total_price = (level_adjusted * urgency_mult).quantize(Decimal('0.01'))
            
            extras_price = cls._calculate_extras(extras)
            final_price = total_price + extras_price
            
            return {
                'pages': Decimal('0.00'),
                'words_per_page': 0,
                'cost_per_page': float(cls.SLIDE_PRICE),
                'base_price': base_price.quantize(Decimal('0.01')),
                'level_multiplier': level_mult,
                'level_adjusted': level_adjusted.quantize(Decimal('0.01')),
                'urgency_multiplier': urgency_mult,
                'extras_price': extras_price,
                'total_price': final_price.quantize(Decimal('0.01')),
                'slides': slides,
                'paper_type': 'presentation'
            }
        
        data = cls.SPACING_DATA.get(spacing, cls.SPACING_DATA['double'])
        pages = Decimal(str(words)) / Decimal(str(data['words_per_page']))
        
        base_price = pages * data['cost_per_page']
        level_mult = cls.ACADEMIC_MULTIPLIERS.get(academic_level, Decimal('1.00'))
        level_adjusted = base_price * level_mult
        urgency_mult = cls._get_urgency_multiplier(deadline)
        total_price = (level_adjusted * urgency_mult).quantize(Decimal('0.01'))
        
        extras_price = cls._calculate_extras(extras)
        final_price = total_price + extras_price
        
        return {
            'pages': pages.quantize(Decimal('0.01')),
            'words_per_page': data['words_per_page'],
            'cost_per_page': data['cost_per_page'],
            'base_price': base_price.quantize(Decimal('0.01')),
            'level_multiplier': level_mult,
            'level_adjusted': level_adjusted.quantize(Decimal('0.01')),
            'urgency_multiplier': urgency_mult,
            'extras_price': extras_price,
            'total_price': final_price.quantize(Decimal('0.01')),
            'slides': None,
            'paper_type': paper_type
        }
    
    @classmethod
    def _get_urgency_multiplier(cls, deadline):
        now = timezone.now()
        hours_remaining = (deadline - now).total_seconds() / 3600
        
        for hours, multiplier in cls.URGENCY_MULTIPLIERS:
            if hours_remaining <= hours:
                return multiplier
        
        return Decimal('1.00')
    
    @classmethod
    def _calculate_extras(cls, extras):
        if not extras:
            return Decimal('0.00')
        
        total = Decimal('0.00')
        for extra in extras:
            if extra in cls.EXTRAS:
                total += cls.EXTRAS[extra]
        
        return total
    
    @classmethod
    def estimate_delivery_time(cls, pages, paper_type):
        if paper_type == 'presentation':
            return max(24, pages * 2)
        
        if pages <= 3:
            return 12
        elif pages <= 5:
            return 24
        elif pages <= 10:
            return 48
        elif pages <= 20:
            return 72
        else:
            return 96


class OrderWorkflow:
    
    TRANSITIONS = {
        'request': ['in_progress', 'cancelled', 'declined'],
        'in_progress': ['awaiting_approval', 'cancelled'],
        'awaiting_approval': ['completed', 'in_progress', 'refund_pending'],
        'completed': ['refund_pending'],
        'cancelled': [],
        'declined': ['request'],
        'refund_pending': ['completed', 'cancelled'],
    }
    
    STUDENT_ACTIONS = {
        'request': ['cancel'],
        'in_progress': ['cancel', 'message'],
        'awaiting_approval': ['approve', 'request_revision', 'cancel', 'message'],
        'completed': ['request_refund', 'rate', 'reorder', 'message'],
        'cancelled': ['reorder'],
        'declined': ['resubmit', 'cancel'],
        'refund_pending': ['message'],
    }
    
    WRITER_ACTIONS = {
        'request': ['accept', 'decline', 'message'],
        'in_progress': ['deliver', 'message'],
        'awaiting_approval': ['message'],
        'completed': ['message'],
        'cancelled': [],
        'declined': [],
        'refund_pending': ['message'],
    }
    
    ADMIN_ACTIONS = {
        'request': ['assign', 'decline', 'message'],
        'in_progress': ['reassign', 'message'],
        'awaiting_approval': ['force_approve', 'message'],
        'completed': ['refund', 'message'],
        'cancelled': ['message'],
        'declined': ['message'],
        'refund_pending': ['approve_refund', 'deny_refund', 'message'],
    }
    
    @classmethod
    def can_transition(cls, order, new_status):
        if order.status == new_status:
            return False
        return new_status in cls.TRANSITIONS.get(order.status, [])
    
    @classmethod
    def get_student_actions(cls, order):
        return cls.STUDENT_ACTIONS.get(order.status, [])
    
    @classmethod
    def get_writer_actions(cls, order):
        if order.writer:
            return cls.WRITER_ACTIONS.get(order.status, [])
        return []
    
    @classmethod
    def get_admin_actions(cls, order):
        return cls.ADMIN_ACTIONS.get(order.status, [])
    
    @classmethod
    def get_allowed_actions(cls, order, user):
        from apps.accounts.models import User
        
        if user.role == 'admin':
            return cls.get_admin_actions(order)
        elif user.role == 'writer' and order.writer_id == user.id:
            return cls.get_writer_actions(order)
        elif user.role == 'student' and order.student_id == user.id:
            return cls.get_student_actions(order)
        
        return []
    
    @classmethod
    def get_status_display(cls, status):
        display_map = {
            'request': 'Request',
            'in_progress': 'In Progress',
            'awaiting_approval': 'Awaiting Approval',
            'completed': 'Completed',
            'cancelled': 'Cancelled',
            'declined': 'Declined',
            'refund_pending': 'Refund Pending',
        }
        return display_map.get(status, status.replace('_', ' ').title())
    
    @classmethod
    def get_status_color(cls, status):
        color_map = {
            'request': 'yellow',
            'in_progress': 'blue',
            'awaiting_approval': 'purple',
            'completed': 'green',
            'cancelled': 'red',
            'declined': 'red',
            'refund_pending': 'orange',
        }
        return color_map.get(status, 'gray')
    
    @classmethod
    def get_status_icon(cls, status):
        icon_map = {
            'request': 'fa-clock',
            'in_progress': 'fa-spinner',
            'awaiting_approval': 'fa-hourglass-half',
            'completed': 'fa-check-circle',
            'cancelled': 'fa-ban',
            'declined': 'fa-times-circle',
            'refund_pending': 'fa-hand-holding-usd',
        }
        return icon_map.get(status, 'fa-circle')


class OrderValidationService:
    
    @classmethod
    def validate_deadline(cls, deadline):
        if not deadline:
            raise ValidationError('Deadline is required')
        
        if deadline < timezone.now():
            raise ValidationError('Deadline cannot be in the past')
        
        min_deadline = timezone.now() + timedelta(hours=12)
        if deadline < min_deadline:
            raise ValidationError('Deadline must be at least 12 hours from now')
        
        return True
    
    @classmethod
    def validate_order_data(cls, data):
        errors = {}
        
        paper_type = data.get('paper_type')
        pages = data.get('pages')
        words = data.get('words')
        slides = data.get('slides')
        deadline = data.get('deadline')
        
        if paper_type == 'presentation':
            if not slides:
                errors['slides'] = 'Number of slides is required for presentations'
            elif slides < 1:
                errors['slides'] = 'Must have at least 1 slide'
        else:
            if not pages and not words:
                errors['non_field_errors'] = 'Either pages or words must be provided'
            
            if pages and pages < 0.5:
                errors['pages'] = 'Minimum pages is 0.5'
            
            if words and words < 1:
                errors['words'] = 'Minimum words is 1'
        
        if deadline:
            try:
                cls.validate_deadline(deadline)
            except ValidationError as e:
                errors['deadline'] = str(e)
        
        return errors
    
    @classmethod
    def validate_cancellation(cls, order, user):
        from apps.orders.models import is_owner
        
        if not is_owner(order, user):
            raise ValidationError('You are not authorized to cancel this order')
        
        if order.status == 'completed':
            raise ValidationError('Completed orders cannot be cancelled')
        
        if order.status == 'cancelled':
            raise ValidationError('Order is already cancelled')
        
        return True
    
    @classmethod
    def validate_resubmission(cls, order, user):
        from apps.orders.models import is_owner
        
        if not is_owner(order, user):
            raise ValidationError('You are not authorized to resubmit this order')
        
        if order.status != 'declined':
            raise ValidationError('Only declined orders can be resubmitted')
        
        return True
    
    @classmethod
    def validate_reorder(cls, order, user):
        from apps.orders.models import is_owner
        
        if not is_owner(order, user):
            raise ValidationError('You are not authorized to reorder this order')
        
        if order.status not in ['completed', 'cancelled']:
            raise ValidationError('Only completed or cancelled orders can be reordered')
        
        return True
    
    @classmethod
    def validate_split(cls, order, user, parts):
        from apps.orders.models import is_owner
        
        if not is_owner(order, user):
            raise ValidationError('You are not authorized to split this order')
        
        if order.status not in ['request', 'in_progress']:
            raise ValidationError('Only pending or in-progress orders can be split')
        
        if parts < 2:
            raise ValidationError('Must split into at least 2 parts')
        
        if parts > 10:
            raise ValidationError('Cannot split into more than 10 parts')
        
        if order.pages and order.pages < 5:
            raise ValidationError('Order must have at least 5 pages to split')
        
        if order.words and order.words < 1500:
            raise ValidationError('Order must have at least 1500 words to split')
        
        return True


class OrderNotificationService:
    
    @classmethod
    def send_order_created(cls, order):
        from apps.messaging.services import NotificationService
        
        NotificationService.send(
            user=order.student,
            type='order_created',
            title='Order Created',
            message=f'Your order #{order.order_number} has been created successfully.',
            data={'order_id': str(order.id), 'order_number': order.order_number}
        )
        
        NotificationService.send_admin(
            type='new_order',
            title='New Order Created',
            message=f'New order #{order.order_number} from {order.student.full_name}',
            data={'order_id': str(order.id), 'order_number': order.order_number}
        )
    
    @classmethod
    def send_order_accepted(cls, order):
        from apps.messaging.services import NotificationService
        
        NotificationService.send(
            user=order.student,
            type='order_accepted',
            title='Order Accepted',
            message=f'Your order #{order.order_number} has been accepted and is now in progress.',
            data={'order_id': str(order.id), 'order_number': order.order_number}
        )
    
    @classmethod
    def send_order_delivered(cls, order):
        from apps.messaging.services import NotificationService
        
        NotificationService.send(
            user=order.student,
            type='order_delivered',
            title='Order Delivered',
            message=f'Your order #{order.order_number} has been delivered. Please review and approve.',
            data={'order_id': str(order.id), 'order_number': order.order_number}
        )
    
    @classmethod
    def send_order_completed(cls, order):
        from apps.messaging.services import NotificationService
        
        NotificationService.send(
            user=order.student,
            type='order_completed',
            title='Order Completed',
            message=f'Your order #{order.order_number} has been completed.',
            data={'order_id': str(order.id), 'order_number': order.order_number}
        )
        
        if order.writer:
            NotificationService.send(
                user=order.writer,
                type='payment_received',
                title='Payment Received',
                message=f'Payment of ${order.total_price} for order #{order.order_number} has been released.',
                data={'order_id': str(order.id), 'order_number': order.order_number}
            )
    
    @classmethod
    def send_order_cancelled(cls, order):
        from apps.messaging.services import NotificationService
        
        NotificationService.send(
            user=order.student,
            type='order_cancelled',
            title='Order Cancelled',
            message=f'Your order #{order.order_number} has been cancelled. Refund has been processed.',
            data={'order_id': str(order.id), 'order_number': order.order_number}
        )
        
        if order.writer:
            NotificationService.send(
                user=order.writer,
                type='order_cancelled',
                title='Order Cancelled',
                message=f'Order #{order.order_number} has been cancelled.',
                data={'order_id': str(order.id), 'order_number': order.order_number}
            )
    
    @classmethod
    def send_order_declined(cls, order):
        from apps.messaging.services import NotificationService
        
        NotificationService.send(
            user=order.student,
            type='order_declined',
            title='Order Declined',
            message=f'Your order #{order.order_number} has been declined. Reason: {order.declined_reason}',
            data={'order_id': str(order.id), 'order_number': order.order_number}
        )
    
    @classmethod
    def send_order_resubmitted(cls, order):
        from apps.messaging.services import NotificationService
        
        NotificationService.send(
            user=order.student,
            type='order_resubmitted',
            title='Order Resubmitted',
            message=f'Your order #{order.order_number} has been resubmitted successfully.',
            data={'order_id': str(order.id), 'order_number': order.order_number}
        )
        
        NotificationService.send_admin(
            type='order_resubmitted',
            title='Order Resubmitted',
            message=f'Order #{order.order_number} has been resubmitted by {order.student.full_name}',
            data={'order_id': str(order.id), 'order_number': order.order_number}
        )
    
    @classmethod
    def send_revision_requested(cls, order):
        from apps.messaging.services import NotificationService
        
        if order.writer:
            NotificationService.send(
                user=order.writer,
                type='revision_requested',
                title='Revision Requested',
                message=f'Revision requested for order #{order.order_number}. Please review the notes.',
                data={'order_id': str(order.id), 'order_number': order.order_number}
            )
    
    @classmethod
    def send_refund_requested(cls, order):
        from apps.messaging.services import NotificationService
        
        NotificationService.send_admin(
            type='refund_requested',
            title='Refund Requested',
            message=f'Refund requested for order #{order.order_number} by {order.student.full_name}',
            data={'order_id': str(order.id), 'order_number': order.order_number}
        )


class OrderAnalyticsService:
    
    @classmethod
    def get_student_stats(cls, student):
        from apps.orders.models import Order
        
        orders = Order.objects.filter(student=student)
        
        total_orders = orders.count()
        completed = orders.filter(status='completed').count()
        active = orders.filter(status__in=['request', 'in_progress', 'awaiting_approval']).count()
        cancelled = orders.filter(status='cancelled').count()
        declined = orders.filter(status='declined').count()
        
        total_spent = orders.filter(status__in=['completed']).aggregate(
            total=models.Sum('total_price')
        )['total'] or Decimal('0.00')
        
        avg_rating = orders.filter(rating__isnull=False).aggregate(
            avg=models.Avg('rating')
        )['avg'] or 0
        
        return {
            'total_orders': total_orders,
            'completed': completed,
            'active': active,
            'cancelled': cancelled,
            'declined': declined,
            'total_spent': float(total_spent),
            'average_rating': float(avg_rating),
            'completion_rate': (completed / total_orders * 100) if total_orders > 0 else 0
        }
    
    @classmethod
    def get_writer_stats(cls, writer):
        from apps.orders.models import Order
        
        orders = Order.objects.filter(writer=writer)
        
        total = orders.count()
        completed = orders.filter(status='completed').count()
        in_progress = orders.filter(status='in_progress').count()
        
        total_earned = orders.filter(status='completed').aggregate(
            total=models.Sum('total_price')
        )['total'] or Decimal('0.00')
        
        avg_rating = orders.filter(rating__isnull=False).aggregate(
            avg=models.Avg('rating')
        )['avg'] or 0
        
        return {
            'total_orders': total,
            'completed': completed,
            'in_progress': in_progress,
            'total_earned': float(total_earned),
            'average_rating': float(avg_rating),
            'completion_rate': (completed / total * 100) if total > 0 else 0
        }
    
    @classmethod
    def get_platform_stats(cls):
        from apps.orders.models import Order
        from apps.accounts.models import User
        
        total_orders = Order.objects.count()
        active_orders = Order.objects.filter(status__in=['request', 'in_progress', 'awaiting_approval']).count()
        completed_orders = Order.objects.filter(status='completed').count()
        
        total_revenue = Order.objects.filter(status='completed').aggregate(
            total=models.Sum('total_price')
        )['total'] or Decimal('0.00')
        
        total_users = User.objects.count()
        active_writers = User.objects.filter(role='writer', is_active=True).count()
        
        avg_rating = Order.objects.filter(rating__isnull=False).aggregate(
            avg=models.Avg('rating')
        )['avg'] or 0
        
        return {
            'total_orders': total_orders,
            'active_orders': active_orders,
            'completed_orders': completed_orders,
            'total_revenue': float(total_revenue),
            'total_users': total_users,
            'active_writers': active_writers,
            'average_rating': float(avg_rating),
            'completion_rate': (completed_orders / total_orders * 100) if total_orders > 0 else 0
        }