import secrets
import string
from datetime import datetime
from django.utils import timezone
from django.db import transaction
from decimal import Decimal

class OrderNumberGenerator:
    @staticmethod
    def generate():
        from .utils import generate_order_number
        return generate_order_number()

class PricingEngine:
    BASE_RATES = {
        'high_school': Decimal('10.00'),
        'undergraduate': Decimal('12.00'),
        'masters': Decimal('18.00'),
        'phd': Decimal('25.00'),
    }
    
    URGENCY_MULTIPLIERS = [
        (14, Decimal('1.0')),
        (7, Decimal('1.1')),
        (5, Decimal('1.2')),
        (3, Decimal('1.3')),
        (2, Decimal('1.5')),
        (1, Decimal('2.0')),
        (0.5, Decimal('2.5')),
    ]
    
    EXTRAS = {
        'plagiarism_report': Decimal('10.00'),
        'abstract': Decimal('15.00'),
    }
    
    @classmethod
    def calculate(cls, academic_level, pages, deadline, extras=None):
        base_rate = cls.BASE_RATES[academic_level]
        base_price = Decimal(pages) * base_rate
        
        now = timezone.now()
        days_until = (deadline - now).total_seconds() / 86400
        
        multiplier = Decimal('2.5')
        for days, mult in cls.URGENCY_MULTIPLIERS:
            if days_until >= days:
                multiplier = mult
                break
        
        extras_price = Decimal('0')
        if extras:
            for extra in extras:
                extras_price += cls.EXTRAS.get(extra, Decimal('0'))
        
        total = (base_price * multiplier) + extras_price
        
        return {
            'base_price': base_price.quantize(Decimal('0.01')),
            'urgency_multiplier': multiplier,
            'extras_price': extras_price.quantize(Decimal('0.01')),
            'total_price': total.quantize(Decimal('0.01')),
        }

class OrderWorkflow:
    TRANSITIONS = {
        'pending': ['ongoing', 'cancelled'],
        'ongoing': ['awaiting_review', 'cancelled'],
        'awaiting_review': ['completed', 'ongoing'],
        'completed': ['ongoing', 'refund_pending'],
        'refund_pending': ['cancelled', 'completed'],
        'cancelled': [],
    }
    
    STUDENT_ACTIONS = {
        'pending': [],
        'ongoing': ['message', 'cancel'],
        'awaiting_review': ['approve', 'request_revision'],
        'completed': ['request_revision', 'request_refund'],
        'cancelled': [],
        'refund_pending': ['message'],
    }
    
    ADMIN_ACTIONS = {
        'pending': ['approve', 'reject', 'message'],
        'ongoing': ['deliver', 'message'],
        'awaiting_review': ['message'],
        'completed': ['message'],
        'cancelled': [],
        'refund_pending': ['approve_refund', 'deny_refund', 'message'],
    }
    
    @classmethod
    def can_transition(cls, order, new_status):
        return new_status in cls.TRANSITIONS.get(order.status, [])
    
    @classmethod
    def get_student_actions(cls, order):
        return cls.STUDENT_ACTIONS.get(order.status, [])
    
    @classmethod
    def get_admin_actions(cls, order):
        return cls.ADMIN_ACTIONS.get(order.status, [])