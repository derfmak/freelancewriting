import secrets
import string
import hashlib
import hmac
import logging
from decimal import Decimal
from datetime import timedelta
from django.db import transaction as db_transaction
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.core.cache import cache
from .models import Wallet, Transaction, PaymentMethod, PaymentIntent, OrderPayment, FraudCheck, Payout, PayPalWebhook

logger = logging.getLogger(__name__)


class TransactionIdGenerator:
    
    @staticmethod
    def generate():
        prefix = 'TXN'
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        return f"{prefix}{timestamp}{random_part}"


class PayoutIdGenerator:
    
    @staticmethod
    def generate():
        prefix = 'PO'
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
        return f"{prefix}{timestamp}{random_part}"


class WalletService:
    
    @staticmethod
    def get_or_create_wallet(user):
        wallet, created = Wallet.objects.get_or_create(
            user=user,
            defaults={
                'balance': 0,
                'held_balance': 0,
                'total_deposited': 0,
                'total_spent': 0,
                'total_refunded': 0,
                'total_withdrawn': 0
            }
        )
        return wallet
    
    @staticmethod
    @db_transaction.atomic
    def credit(wallet, amount, transaction_type, description, order=None, metadata=None):
        if wallet.is_locked():
            raise ValueError('Wallet is locked')
        
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')
        
        balance_before = wallet.balance
        balance_after = wallet.balance + amount
        
        wallet.balance = balance_after
        
        if transaction_type == 'deposit':
            wallet.total_deposited += amount
        elif transaction_type == 'refund':
            wallet.total_refunded += amount
        elif transaction_type == 'payout':
            wallet.total_withdrawn += amount
        
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
        
        try:
            EmailService.send_transaction_notification(wallet.user, transaction_obj)
        except Exception as e:
            logger.error(f"Failed to send transaction notification: {e}")
        
        return transaction_obj
    
    @staticmethod
    @db_transaction.atomic
    def debit(wallet, amount, transaction_type, description, order=None, payment_method='wallet', metadata=None):
        if wallet.is_locked():
            raise ValueError('Wallet is locked')
        
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')
        
        if not wallet.has_sufficient_balance(amount):
            raise ValueError('Insufficient balance')
        
        balance_before = wallet.balance
        balance_after = wallet.balance - amount
        
        wallet.balance = balance_after
        
        if transaction_type == 'payment' or transaction_type == 'settle':
            wallet.total_spent += amount
        elif transaction_type == 'withdrawal':
            wallet.total_withdrawn += amount
        
        wallet.save()
        
        transaction_obj = Transaction.objects.create(
            transaction_id=TransactionIdGenerator.generate(),
            user=wallet.user,
            wallet=wallet,
            order=order,
            amount=-amount,
            type=transaction_type,
            status='completed',
            payment_method=payment_method,
            description=description,
            metadata=metadata or {},
            balance_before=balance_before,
            balance_after=balance_after,
            held_before=wallet.held_balance,
            held_after=wallet.held_balance,
            completed_at=timezone.now()
        )
        
        try:
            EmailService.send_transaction_notification(wallet.user, transaction_obj)
        except Exception as e:
            logger.error(f"Failed to send transaction notification: {e}")
        
        return transaction_obj
    
    @staticmethod
    @db_transaction.atomic
    def hold_funds(wallet, amount, order, description, metadata=None):
        if wallet.is_locked():
            raise ValueError('Wallet is locked')
        
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')
        
        if not wallet.has_sufficient_available_balance(amount):
            raise ValueError(f'Insufficient available balance. Available: ${wallet.available_balance}')
        
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
        
        order_payment = OrderPayment.objects.create(
            order=order,
            hold_transaction=transaction_obj,
            amount=amount,
            status='held'
        )
        
        try:
            EmailService.send_order_payment_notification(wallet.user, order, amount)
        except Exception as e:
            logger.error(f"Failed to send order payment notification: {e}")
        
        return transaction_obj
    
    @staticmethod
    @db_transaction.atomic
    def release_held_funds(wallet, amount, order, description, admin_user=None, metadata=None):
        if wallet.is_locked():
            raise ValueError('Wallet is locked')
        
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')
        
        if not wallet.held_balance >= amount:
            raise ValueError(f'Insufficient held balance. Held: ${wallet.held_balance}')
        
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
        order_payment.mark_released(transaction_obj, admin_user)
        
        try:
            EmailService.send_order_completion_notification(wallet.user, order, amount)
        except Exception as e:
            logger.error(f"Failed to send order completion notification: {e}")
        
        return transaction_obj
    
    @staticmethod
    @db_transaction.atomic
    def refund_held_funds(wallet, amount, order, description, admin_user=None, metadata=None):
        if wallet.is_locked():
            raise ValueError('Wallet is locked')
        
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')
        
        if not wallet.held_balance >= amount:
            raise ValueError(f'Insufficient held balance. Held: ${wallet.held_balance}')
        
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
        order_payment.mark_refunded(transaction_obj, admin_user)
        
        try:
            EmailService.send_refund_notification(wallet.user, order, amount)
        except Exception as e:
            logger.error(f"Failed to send refund notification: {e}")
        
        return transaction_obj


class PaymentProcessor:
    
    @staticmethod
    def create_stripe_payment_intent(amount, payment_method_id=None, currency='usd', metadata=None):
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            
            params = {
                'amount': int(amount * 100),
                'currency': currency,
                'metadata': metadata or {},
            }
            
            if payment_method_id:
                params['payment_method'] = payment_method_id
                params['confirm'] = True
                params['return_url'] = settings.FRONTEND_URL + '/payment/return/'
            
            intent = stripe.PaymentIntent.create(**params)
            
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
    def create_paypal_payout(email, amount, note=None, payout_id=None):
        try:
            import paypalrestsdk
            paypalrestsdk.configure({
                'mode': settings.PAYPAL_MODE,
                'client_id': settings.PAYPAL_CLIENT_ID,
                'client_secret': settings.PAYPAL_CLIENT_SECRET
            })
            
            payout = paypalrestsdk.Payout({
                'sender_batch_header': {
                    'sender_batch_id': payout_id or PayoutIdGenerator.generate(),
                    'email_subject': 'You have received a payment from AcademicWrite',
                    'recipient_type': 'EMAIL'
                },
                'items': [{
                    'recipient_type': 'EMAIL',
                    'amount': {
                        'value': str(amount),
                        'currency': 'USD'
                    },
                    'receiver': email,
                    'note': note or 'Payment for academic writing services'
                }]
            })
            
            if payout.create():
                return {
                    'success': True,
                    'payout_id': payout.batch_header.payout_batch_id,
                    'status': payout.batch_header.batch_status
                }
            else:
                return {
                    'success': False,
                    'error': payout.error
                }
        except ImportError:
            logger.error("PayPal SDK not installed")
            return {'success': False, 'error': 'PayPal provider not configured'}
        except Exception as e:
            logger.error(f"PayPal error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def create_paypal_order(amount, email, return_url=None, cancel_url=None, metadata=None):
        try:
            import paypalrestsdk
            paypalrestsdk.configure({
                'mode': settings.PAYPAL_MODE,
                'client_id': settings.PAYPAL_CLIENT_ID,
                'client_secret': settings.PAYPAL_CLIENT_SECRET
            })
            
            order = paypalrestsdk.Order({
                'intent': 'CAPTURE',
                'purchase_units': [{
                    'amount': {
                        'currency_code': 'USD',
                        'value': str(amount)
                    },
                    'custom_id': metadata.get('order_id') if metadata else None,
                    'description': metadata.get('description', 'AcademicWrite Order Payment')
                }],
                'application_context': {
                    'return_url': return_url or settings.FRONTEND_URL + '/payment/return/',
                    'cancel_url': cancel_url or settings.FRONTEND_URL + '/payment/cancel/'
                }
            })
            
            if order.create():
                return {
                    'success': True,
                    'order_id': order.id,
                    'approval_url': next(link.href for link in order.links if link.rel == 'approval_url'),
                    'status': order.status
                }
            else:
                return {
                    'success': False,
                    'error': order.error
                }
        except ImportError:
            logger.error("PayPal SDK not installed")
            return {'success': False, 'error': 'PayPal provider not configured'}
        except Exception as e:
            logger.error(f"PayPal error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def capture_paypal_order(order_id):
        try:
            import paypalrestsdk
            paypalrestsdk.configure({
                'mode': settings.PAYPAL_MODE,
                'client_id': settings.PAYPAL_CLIENT_ID,
                'client_secret': settings.PAYPAL_CLIENT_SECRET
            })
            
            order = paypalrestsdk.Order.find(order_id)
            
            if order.capture():
                return {
                    'success': True,
                    'capture_id': order.id,
                    'status': order.status
                }
            else:
                return {
                    'success': False,
                    'error': order.error
                }
        except ImportError:
            logger.error("PayPal SDK not installed")
            return {'success': False, 'error': 'PayPal provider not configured'}
        except Exception as e:
            logger.error(f"PayPal error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def validate_card(last_four, expiry_month, expiry_year, card_brand):
        now = timezone.now()
        
        if expiry_year < now.year or (expiry_year == now.year and expiry_month < now.month):
            return {'valid': False, 'error': 'Card expired'}
        
        if card_brand not in ['visa', 'mastercard', 'amex', 'discover', 'jcb', 'diners']:
            return {'valid': False, 'error': 'Unsupported card brand'}
        
        if len(last_four) != 4 or not last_four.isdigit():
            return {'valid': False, 'error': 'Invalid last four digits'}
        
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
            flags.append('large_transaction')
        
        if not ip_address or ip_address.startswith('192.168.') or ip_address.startswith('10.'):
            risk_score += 10
            flags.append('unusual_ip')
        
        if user_agent and ('python' in user_agent.lower() or 'curl' in user_agent.lower()):
            risk_score += 15
            flags.append('unusual_user_agent')
        
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
    
    @staticmethod
    def create_fraud_check(user, transaction, risk_score, risk_level, flags, is_blocked, requires_review):
        return FraudCheck.objects.create(
            user=user,
            transaction=transaction,
            risk_score=risk_score,
            risk_level=risk_level,
            flags=flags,
            is_blocked=is_blocked,
            requires_review=requires_review
        )


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
        context = {
            'user': user,
            'order': order,
            'amount': amount
        }
        html_message = render_to_string('emails/order_payment.html', context)
        send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message)
    
    @staticmethod
    def send_order_completion_notification(user, order, amount):
        subject = 'Order Completed - Funds Released'
        context = {
            'user': user,
            'order': order,
            'amount': amount
        }
        html_message = render_to_string('emails/order_completed.html', context)
        send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message)
    
    @staticmethod
    def send_refund_notification(user, order, amount):
        subject = 'Refund Processed'
        context = {
            'user': user,
            'order': order,
            'amount': amount
        }
        html_message = render_to_string('emails/refund.html', context)
        send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message)
    
    @staticmethod
    def send_deposit_confirmation(user, amount, transaction_id):
        subject = 'Deposit Confirmation'
        context = {
            'user': user,
            'amount': amount,
            'transaction_id': transaction_id
        }
        html_message = render_to_string('emails/deposit.html', context)
        send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message)
    
    @staticmethod
    def send_withdrawal_request(user, amount, payout_id, payment_method):
        subject = 'Withdrawal Request Submitted'
        context = {
            'user': user,
            'amount': amount,
            'payout_id': payout_id,
            'payment_method': payment_method
        }
        html_message = render_to_string('emails/withdrawal_request.html', context)
        send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message)
    
    @staticmethod
    def send_withdrawal_completed(user, amount, payout_id, payment_method):
        subject = 'Withdrawal Completed'
        context = {
            'user': user,
            'amount': amount,
            'payout_id': payout_id,
            'payment_method': payment_method
        }
        html_message = render_to_string('emails/withdrawal_completed.html', context)
        send_mail(subject, '', settings.DEFAULT_FROM_EMAIL, [user.email], html_message=html_message)


class IdempotencyService:
    
    @staticmethod
    def check_idempotency_key(key, user):
        if not key:
            return None
        
        cache_key = f"idempotency_{user.id}_{key}"
        result = cache.get(cache_key)
        
        if result:
            return result
        
        cache.set(cache_key, 'processing', timeout=3600)
        return None
    
    @staticmethod
    def mark_completed(key, user, transaction_id):
        if not key:
            return
        
        cache_key = f"idempotency_{user.id}_{key}"
        cache.set(cache_key, transaction_id, timeout=86400)
    
    @staticmethod
    def mark_failed(key, user):
        if not key:
            return
        
        cache_key = f"idempotency_{user.id}_{key}"
        cache.delete(cache_key)


class PayoutService:
    
    @staticmethod
    @db_transaction.atomic
    def create_payout(user, amount, payment_method, account_details, description=None, metadata=None):
        wallet = user.wallet
        
        if wallet.is_locked():
            raise ValueError('Wallet is locked')
        
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')
        
        if amount < 10:
            raise ValueError('Minimum payout amount is $10.00')
        
        if not wallet.has_sufficient_available_balance(amount):
            raise ValueError(f'Insufficient available balance. Available: ${wallet.available_balance}')
        
        fee_percentage = Decimal('2.00')
        fee_amount = (amount * fee_percentage) / Decimal('100')
        net_amount = amount - fee_amount
        
        payout = Payout.objects.create(
            user=user,
            amount=amount,
            fee_amount=fee_amount,
            fee_percentage=fee_percentage,
            net_amount=net_amount,
            payment_method=payment_method,
            account_details=account_details,
            status='pending',
            metadata=metadata or {}
        )
        
        try:
            EmailService.send_withdrawal_request(user, amount, payout.payout_id, payment_method)
        except Exception as e:
            logger.error(f"Failed to send withdrawal request email: {e}")
        
        return payout
    
    @staticmethod
    @db_transaction.atomic
    def process_payout(payout_id):
        payout = Payout.objects.get(payout_id=payout_id, status='pending')
        
        if payout.payment_method == 'paypal':
            result = PaymentProcessor.create_paypal_payout(
                email=payout.account_details.get('email'),
                amount=payout.net_amount,
                note=f'Payment for academic writing services',
                payout_id=payout.payout_id
            )
            
            if result['success']:
                payout.status = 'processing'
                payout.provider_payout_id = result['payout_id']
                payout.provider_response = result
                payout.save()
                
                with db_transaction.atomic():
                    transaction_obj = WalletService.debit(
                        wallet=payout.user.wallet,
                        amount=payout.amount,
                        transaction_type='withdrawal',
                        description=f'Withdrawal via PayPal to {payout.account_details.get("email")}',
                        payment_method='paypal',
                        metadata={'payout_id': payout.payout_id}
                    )
                    
                    payout.transaction = transaction_obj
                    payout.save()
                
                return {
                    'success': True,
                    'payout_id': payout.payout_id,
                    'status': payout.status
                }
            else:
                payout.fail(result.get('error', 'Unknown PayPal error'))
                return {
                    'success': False,
                    'error': result.get('error', 'PayPal processing failed')
                }
        
        return {'success': False, 'error': 'Unsupported payment method'}
    
    @staticmethod
    @db_transaction.atomic
    def complete_payout(payout_id):
        payout = Payout.objects.get(payout_id=payout_id, status='processing')
        payout.complete()
        
        try:
            EmailService.send_withdrawal_completed(
                user=payout.user,
                amount=payout.amount,
                payout_id=payout.payout_id,
                payment_method=payout.payment_method
            )
        except Exception as e:
            logger.error(f"Failed to send withdrawal completed email: {e}")
        
        return payout


class EscrowService:
    
    @staticmethod
    @db_transaction.atomic
    def create_escrow(order, amount, description=None):
        wallet = order.student.wallet
        
        if wallet.is_locked():
            raise ValueError('Wallet is locked')
        
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')
        
        if not wallet.has_sufficient_available_balance(amount):
            raise ValueError(f'Insufficient available balance. Available: ${wallet.available_balance}')
        
        transaction_obj = WalletService.hold_funds(
            wallet=wallet,
            amount=amount,
            order=order,
            description=description or f'Escrow hold for order {order.order_number}'
        )
        
        return transaction_obj
    
    @staticmethod
    @db_transaction.atomic
    def release_escrow(order, amount=None, admin_user=None):
        order_payment = OrderPayment.objects.get(order=order, status='held')
        
        if not amount:
            amount = order_payment.amount
        
        wallet = order.student.wallet
        
        transaction_obj = WalletService.release_held_funds(
            wallet=wallet,
            amount=amount,
            order=order,
            description=f'Release of escrow funds for order {order.order_number}',
            admin_user=admin_user
        )
        
        if order.writer:
            payout = PayoutService.create_payout(
                user=order.writer,
                amount=amount,
                payment_method='wallet',
                account_details={'wallet': 'internal'},
                description=f'Payment for order {order.order_number}'
            )
            
            try:
                PayoutService.process_payout(payout.payout_id)
            except Exception as e:
                logger.error(f"Failed to process writer payout: {e}")
        
        return transaction_obj
    
    @staticmethod
    @db_transaction.atomic
    def refund_escrow(order, amount=None, admin_user=None, reason=None):
        order_payment = OrderPayment.objects.get(order=order)
        
        if not amount:
            amount = order_payment.amount
        
        wallet = order.student.wallet
        
        transaction_obj = WalletService.refund_held_funds(
            wallet=wallet,
            amount=amount,
            order=order,
            description=f'Refund of escrow funds for order {order.order_number}: {reason or "No reason provided"}',
            admin_user=admin_user
        )
        
        return transaction_obj


class WebhookService:
    
    @staticmethod
    def process_stripe_webhook(payload, signature):
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            
            event = stripe.Webhook.construct_event(
                payload, signature, settings.STRIPE_WEBHOOK_SECRET
            )
            
            event_type = event['type']
            data = event['data']['object']
            
            if event_type == 'payment_intent.succeeded':
                return WebhookService.handle_payment_intent_succeeded(data)
            elif event_type == 'payment_intent.payment_failed':
                return WebhookService.handle_payment_intent_failed(data)
            elif event_type == 'charge.refunded':
                return WebhookService.handle_charge_refunded(data)
            
            return {'success': True, 'message': 'Webhook received but not processed'}
            
        except Exception as e:
            logger.error(f"Stripe webhook error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def handle_payment_intent_succeeded(data):
        payment_intent_id = data['id']
        metadata = data.get('metadata', {})
        order_id = metadata.get('order_id')
        
        if not order_id:
            return {'success': True, 'message': 'No order associated'}
        
        from apps.orders.models import Order
        order = Order.objects.get(id=order_id)
        
        if order.status == 'pending_payment':
            with db_transaction.atomic():
                EscrowService.create_escrow(order, order.total_price)
                order.status = 'request'
                order.save()
        
        return {'success': True, 'message': 'Order updated'}
    
    @staticmethod
    def handle_payment_intent_failed(data):
        payment_intent_id = data['id']
        metadata = data.get('metadata', {})
        order_id = metadata.get('order_id')
        
        if not order_id:
            return {'success': True, 'message': 'No order associated'}
        
        from apps.orders.models import Order
        order = Order.objects.get(id=order_id)
        
        if order.status == 'pending_payment':
            order.status = 'cancelled'
            order.cancellation_reason = 'payment_failed'
            order.save()
        
        return {'success': True, 'message': 'Order cancelled'}
    
    @staticmethod
    def handle_charge_refunded(data):
        payment_intent_id = data['payment_intent']
        amount = data['amount_refunded'] / 100
        
        from apps.orders.models import Order
        order = Order.objects.filter(
            metadata__payment_intent_id=payment_intent_id
        ).first()
        
        if order:
            with db_transaction.atomic():
                EscrowService.refund_escrow(
                    order=order,
                    amount=Decimal(str(amount)),
                    admin_user=None,
                    reason='Stripe refund processed'
                )
        
        return {'success': True, 'message': 'Refund processed'}
    
    @staticmethod
    def process_paypal_webhook(payload):
        try:
            import paypalrestsdk
            paypalrestsdk.configure({
                'mode': settings.PAYPAL_MODE,
                'client_id': settings.PAYPAL_CLIENT_ID,
                'client_secret': settings.PAYPAL_CLIENT_SECRET
            })
            
            event = paypalrestsdk.WebhookEvent.verify(payload)
            
            if not event:
                return {'success': False, 'error': 'Invalid webhook signature'}
            
            event_type = event['event_type']
            resource = event['resource']
            
            if event_type == 'PAYMENT.PAYOUTS-ITEM.SUCCEEDED':
                return WebhookService.handle_paypal_payout_succeeded(resource)
            elif event_type == 'PAYMENT.PAYOUTS-ITEM.FAILED':
                return WebhookService.handle_paypal_payout_failed(resource)
            
            return {'success': True, 'message': 'Webhook received but not processed'}
            
        except Exception as e:
            logger.error(f"PayPal webhook error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def handle_paypal_payout_succeeded(data):
        payout_id = data.get('payout_item_id')
        
        if payout_id:
            try:
                payout = Payout.objects.get(provider_payout_id=payout_id)
                payout.complete()
                
                return {'success': True, 'message': 'Payout completed'}
            except Payout.DoesNotExist:
                logger.warning(f"Payout not found for ID: {payout_id}")
        
        return {'success': True, 'message': 'Payout processed'}
    
    @staticmethod
    def handle_paypal_payout_failed(data):
        payout_id = data.get('payout_item_id')
        error_message = data.get('errors', {}).get('message', 'Unknown error')
        
        if payout_id:
            try:
                payout = Payout.objects.get(provider_payout_id=payout_id)
                payout.fail(error_message)
                
                return {'success': True, 'message': 'Payout failed recorded'}
            except Payout.DoesNotExist:
                logger.warning(f"Payout not found for ID: {payout_id}")
        
        return {'success': True, 'message': 'Payout failure recorded'}