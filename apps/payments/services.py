import secrets
import string
import hashlib
import hmac
import logging
from decimal import Decimal
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from .models import Wallet, Transaction, PaymentMethod, PaymentIntent, OrderPayment, FraudCheck

logger = logging.getLogger(__name__)

class TransactionIdGenerator:
    @staticmethod
    def generate():
        prefix = 'TXN'
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        return f"{prefix}{timestamp}{random}"

class WalletService:
    @staticmethod
    def get_or_create_wallet(user):
        wallet, created = Wallet.objects.get_or_create(
            user=user,
            defaults={
                'balance': 0,
                'pending_balance': 0,
                'held_balance': 0,
                'total_deposited': 0,
                'total_spent': 0,
                'total_refunded': 0,
                'total_withdrawn': 0
            }
        )
        return wallet
    
    @staticmethod
    @transaction.atomic
    def credit(wallet, amount, transaction_type, description, order=None, metadata=None):
        if wallet.locked_until and wallet.locked_until > timezone.now():
            raise ValueError('wallet is locked')
        
        balance_before = wallet.balance
        balance_after = wallet.balance + amount
        
        wallet.balance = balance_after
        
        if transaction_type == 'deposit':
            wallet.total_deposited += amount
        elif transaction_type == 'refund':
            wallet.total_refunded += amount
        
        wallet.save()
        
        transaction_obj = Transaction.objects.create(
            transaction_id=TransactionIdGenerator.generate(),
            user=wallet.user,
            wallet=wallet,
            order=order,
            amount=amount,
            type=transaction_type,
            status='completed',
            payment_method='wallet',
            description=description,
            metadata=metadata or {},
            balance_before=balance_before,
            balance_after=balance_after,
            held_before=wallet.held_balance,
            held_after=wallet.held_balance,
            completed_at=timezone.now()
        )
        
        EmailService.send_transaction_notification(wallet.user, transaction_obj)
        
        return transaction_obj
    
    @staticmethod
    @transaction.atomic
    def debit(wallet, amount, transaction_type, description, order=None, metadata=None):
        if wallet.locked_until and wallet.locked_until > timezone.now():
            raise ValueError('wallet is locked')
        
        if wallet.balance < amount:
            raise ValueError('insufficient balance')
        
        balance_before = wallet.balance
        balance_after = wallet.balance - amount
        
        wallet.balance = balance_after
        
        if transaction_type == 'payment':
            wallet.total_spent += amount
        
        wallet.save()
        
        transaction_obj = Transaction.objects.create(
            transaction_id=TransactionIdGenerator.generate(),
            user=wallet.user,
            wallet=wallet,
            order=order,
            amount=-amount,
            type=transaction_type,
            status='completed',
            payment_method='wallet',
            description=description,
            metadata=metadata or {},
            balance_before=balance_before,
            balance_after=balance_after,
            held_before=wallet.held_balance,
            held_after=wallet.held_balance,
            completed_at=timezone.now()
        )
        
        EmailService.send_transaction_notification(wallet.user, transaction_obj)
        
        return transaction_obj
    
    @staticmethod
    @transaction.atomic
    def hold_funds(wallet, amount, order, description, metadata=None):
        if wallet.locked_until and wallet.locked_until > timezone.now():
            raise ValueError('wallet is locked')
        
        if wallet.balance < amount:
            raise ValueError('insufficient balance')
        
        balance_before = wallet.balance
        balance_after = wallet.balance - amount
        held_before = wallet.held_balance
        held_after = wallet.held_balance + amount
        
        wallet.balance = balance_after
        wallet.held_balance = held_after
        
        wallet.save()
        
        transaction_obj = Transaction.objects.create(
            transaction_id=TransactionIdGenerator.generate(),
            user=wallet.user,
            wallet=wallet,
            order=order,
            amount=-amount,
            type='hold',
            status='held',
            payment_method='wallet',
            description=description,
            metadata=metadata or {},
            balance_before=balance_before,
            balance_after=balance_after,
            held_before=held_before,
            held_after=held_after
        )
        
        OrderPayment.objects.create(
            order=order,
            transaction=transaction_obj,
            amount=amount
        )
        
        EmailService.send_order_payment_notification(wallet.user, order, amount)
        
        return transaction_obj
    
    @staticmethod
    @transaction.atomic
    def release_funds(wallet, amount, order, description, metadata=None):
        if wallet.held_balance < amount:
            raise ValueError('insufficient held balance')
        
        held_before = wallet.held_balance
        held_after = wallet.held_balance - amount
        
        wallet.held_balance = held_after
        
        wallet.save()
        
        transaction_obj = Transaction.objects.create(
            transaction_id=TransactionIdGenerator.generate(),
            user=wallet.user,
            wallet=wallet,
            order=order,
            amount=amount,
            type='release',
            status='completed',
            payment_method='wallet',
            description=description,
            metadata=metadata or {},
            balance_before=wallet.balance,
            balance_after=wallet.balance,
            held_before=held_before,
            held_after=held_after,
            completed_at=timezone.now()
        )
        
        order_payment = OrderPayment.objects.get(order=order)
        order_payment.release()
        
        EmailService.send_order_completion_notification(wallet.user, order, amount)
        
        return transaction_obj
    
    @staticmethod
    @transaction.atomic
    def refund_funds(wallet, amount, order, description, metadata=None):
        if wallet.held_balance < amount:
            raise ValueError('insufficient held balance')
        
        balance_before = wallet.balance
        balance_after = wallet.balance + amount
        held_before = wallet.held_balance
        held_after = wallet.held_balance - amount
        
        wallet.balance = balance_after
        wallet.held_balance = held_after
        wallet.total_refunded += amount
        
        wallet.save()
        
        transaction_obj = Transaction.objects.create(
            transaction_id=TransactionIdGenerator.generate(),
            user=wallet.user,
            wallet=wallet,
            order=order,
            amount=amount,
            type='refund',
            status='completed',
            payment_method='wallet',
            description=description,
            metadata=metadata or {},
            balance_before=balance_before,
            balance_after=balance_after,
            held_before=held_before,
            held_after=held_after,
            completed_at=timezone.now()
        )
        
        order_payment = OrderPayment.objects.get(order=order)
        order_payment.status = 'refunded'
        order_payment.save()
        
        EmailService.send_refund_notification(wallet.user, order, amount)
        
        return transaction_obj

class PaymentProcessor:
    @staticmethod
    def create_stripe_payment_intent(amount, currency='usd', metadata=None):
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            
            intent = stripe.PaymentIntent.create(
                amount=int(amount * 100),
                currency=currency,
                metadata=metadata or {},
                idempotency_key=metadata.get('idempotency_key') if metadata else None
            )
            
            return {
                'success': True,
                'client_secret': intent.client_secret,
                'intent_id': intent.id,
                'status': intent.status
            }
        except ImportError:
            logger.error("Stripe not installed")
            return {'success': False, 'error': 'Payment provider not configured'}
        except Exception as e:
            logger.error(f"Stripe error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def confirm_stripe_payment(payment_intent_id):
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            
            return {
                'success': True,
                'status': intent.status,
                'intent': intent
            }
        except ImportError:
            logger.error("Stripe not installed")
            return {'success': False, 'error': 'Payment provider not configured'}
        except Exception as e:
            logger.error(f"Stripe error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def create_stripe_refund(payment_intent_id, amount=None):
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            
            params = {'payment_intent': payment_intent_id}
            if amount:
                params['amount'] = int(amount * 100)
            
            refund = stripe.Refund.create(**params)
            
            return {
                'success': True,
                'refund_id': refund.id,
                'status': refund.status
            }
        except ImportError:
            logger.error("Stripe not installed")
            return {'success': False, 'error': 'Payment provider not configured'}
        except Exception as e:
            logger.error(f"Stripe error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def validate_card(last_four, expiry_month, expiry_year, card_brand):
        now = timezone.now()
        if expiry_year < now.year or (expiry_year == now.year and expiry_month < now.month):
            return {'valid': False, 'error': 'Card expired'}
        
        if card_brand not in ['visa', 'mastercard', 'amex', 'discover']:
            return {'valid': False, 'error': 'Unsupported card brand'}
        
        return {'valid': True}

class FraudDetectionService:
    @staticmethod
    def check_transaction(user, amount, ip_address, user_agent):
        risk_score = 0
        flags = []
        
        recent_transactions = Transaction.objects.filter(
            user=user,
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).count()
        
        if recent_transactions > 10:
            risk_score += 20
            flags.append('high_velocity')
        
        total_daily = Transaction.objects.filter(
            user=user,
            created_at__gte=timezone.now() - timedelta(hours=24),
            type__in=['deposit', 'payment']
        ).aggregate(total=models.Sum('amount'))['total'] or 0
        
        if total_daily > 5000:
            risk_score += 30
            flags.append('high_amount')
        
        if amount > 1000:
            risk_score += 15
        
        if not ip_address or ip_address.startswith('192.168.') or ip_address.startswith('10.'):
            risk_score += 10
            flags.append('unusual_ip')
        
        if risk_score > 70:
            risk_level = 'high'
            is_blocked = True
            requires_review = True
        elif risk_score > 40:
            risk_level = 'medium'
            is_blocked = False
            requires_review = True
        else:
            risk_level = 'low'
            is_blocked = False
            requires_review = False
        
        return {
            'risk_score': risk_score,
            'risk_level': risk_level,
            'flags': flags,
            'is_blocked': is_blocked,
            'requires_review': requires_review
        }

class EmailService:
    @staticmethod
    def send_transaction_notification(user, transaction):
        subject = f'Transaction Notification - {transaction.type.title()}'
        context = {
            'user': user,
            'transaction': transaction,
            'amount': abs(transaction.amount),
            'type': transaction.type,
            'balance': transaction.balance_after
        }
        html_message = render_to_string('emails/transaction_notification.html', context)
        send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message)
    
    @staticmethod
    def send_order_payment_notification(user, order, amount):
        subject = 'Order Payment Received - Funds Held in Escrow'
        context = {'user': user, 'order': order, 'amount': amount}
        html_message = render_to_string('emails/order_payment.html', context)
        send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message)
    
    @staticmethod
    def send_order_completion_notification(user, order, amount):
        subject = 'Order Completed - Funds Released'
        context = {'user': user, 'order': order, 'amount': amount}
        html_message = render_to_string('emails/order_completed.html', context)
        send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message)
    
    @staticmethod
    def send_refund_notification(user, order, amount):
        subject = 'Refund Processed'
        context = {'user': user, 'order': order, 'amount': amount}
        html_message = render_to_string('emails/refund.html', context)
        send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message)
    
    @staticmethod
    def send_deposit_confirmation(user, amount, transaction_id):
        subject = 'Deposit Confirmation'
        context = {'user': user, 'amount': amount, 'transaction_id': transaction_id}
        html_message = render_to_string('emails/deposit.html', context)
        send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message)

class IdempotencyService:
    @staticmethod
    def check_idempotency_key(key, user):
        from django.core.cache import cache
        cache_key = f"idempotency_{user.id}_{key}"
        result = cache.get(cache_key)
        if result:
            return result
        cache.set(cache_key, 'processing', timeout=3600)
        return None
    
    @staticmethod
    def mark_completed(key, user, transaction_id):
        from django.core.cache import cache
        cache_key = f"idempotency_{user.id}_{key}"
        cache.set(cache_key, transaction_id, timeout=86400)