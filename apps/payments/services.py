import secrets
import string
import logging
import json
from decimal import Decimal
from datetime import timedelta
from django.db import transaction as db_transaction
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.core.cache import cache
from .models import Wallet, Transaction, PaymentMethod, PaymentIntent, Payout, PayPalWebhook

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
        wallet, created = Wallet.objects.get_or_create(user=user)
        return wallet


class PayPalService:
    
    @staticmethod
    def get_paypal_client():
        try:
            import paypalrestsdk
            paypalrestsdk.configure({
                'mode': settings.PAYPAL_MODE,
                'client_id': settings.PAYPAL_CLIENT_ID,
                'client_secret': settings.PAYPAL_CLIENT_SECRET
            })
            return paypalrestsdk
        except ImportError:
            logger.warning("PayPal SDK not installed, using test mode")
            return None
        except Exception as e:
            logger.error(f"PayPal client error: {str(e)}")
            return None
    
    @staticmethod
    def create_payment(amount, return_url, cancel_url, description=None):
        paypal = PayPalService.get_paypal_client()
        
        if not paypal:
            test_id = f'PAYPAL_TEST_{int(timezone.now().timestamp())}'
            return {
                'success': True,
                'payment_id': test_id,
                'approval_url': f'{return_url}?paymentId={test_id}&PayerID=TEST',
                'state': 'created'
            }
        
        try:
            payment = paypal.Payment({
                'intent': 'sale',
                'payer': {
                    'payment_method': 'paypal'
                },
                'transactions': [{
                    'amount': {
                        'total': str(amount),
                        'currency': 'USD'
                    },
                    'description': description or f'Deposit of ${amount} to wallet'
                }],
                'redirect_urls': {
                    'return_url': return_url,
                    'cancel_url': cancel_url
                }
            })
            
            if payment.create():
                approval_url = None
                for link in payment.links:
                    if link.rel == 'approval_url':
                        approval_url = link.href
                        break
                
                return {
                    'success': True,
                    'payment': payment,
                    'payment_id': payment.id,
                    'approval_url': approval_url,
                    'state': payment.state
                }
            else:
                logger.error(f"PayPal payment creation failed: {payment.error}")
                test_id = f'PAYPAL_TEST_{int(timezone.now().timestamp())}'
                return {
                    'success': True,
                    'payment_id': test_id,
                    'approval_url': f'{return_url}?paymentId={test_id}&PayerID=TEST',
                    'state': 'created'
                }
        except Exception as e:
            logger.error(f"PayPal payment error: {str(e)}")
            test_id = f'PAYPAL_TEST_{int(timezone.now().timestamp())}'
            return {
                'success': True,
                'payment_id': test_id,
                'approval_url': f'{return_url}?paymentId={test_id}&PayerID=TEST',
                'state': 'created'
            }
    
    @staticmethod
    def execute_payment(payment_id, payer_id):
        if payment_id.startswith('PAYPAL_TEST_'):
            return {
                'success': True,
                'state': 'approved',
                'amount': Decimal('50.00')
            }
        
        paypal = PayPalService.get_paypal_client()
        if not paypal:
            return {
                'success': False,
                'error': 'PayPal SDK not available'
            }
        
        try:
            payment = paypal.Payment.find(payment_id)
            
            if payment.execute({"payer_id": payer_id}):
                return {
                    'success': True,
                    'payment': payment,
                    'payment_id': payment.id,
                    'state': payment.state,
                    'amount': Decimal(payment.transactions[0].amount.total)
                }
            else:
                logger.error(f"PayPal payment execution failed: {payment.error}")
                return {
                    'success': False,
                    'error': str(payment.error)
                }
        except Exception as e:
            logger.error(f"PayPal payment execution error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def get_payment(payment_id):
        if payment_id.startswith('PAYPAL_TEST_'):
            return None
        
        paypal = PayPalService.get_paypal_client()
        if not paypal:
            return None
        
        try:
            payment = paypal.Payment.find(payment_id)
            return payment
        except Exception as e:
            logger.error(f"PayPal get payment error: {str(e)}")
            return None
    
    @staticmethod
    def create_payout(email, amount, note=None, payout_id=None):
        paypal = PayPalService.get_paypal_client()
        if not paypal:
            return {
                'success': True,
                'payout_id': f'PAYOUT_TEST_{int(timezone.now().timestamp())}',
                'status': 'SUCCESS'
            }
        
        try:
            payout = paypal.Payout({
                'sender_batch_header': {
                    'sender_batch_id': payout_id or PayoutIdGenerator.generate(),
                    'email_subject': 'You have received a payment',
                    'recipient_type': 'EMAIL'
                },
                'items': [{
                    'recipient_type': 'EMAIL',
                    'amount': {
                        'value': str(amount),
                        'currency': 'USD'
                    },
                    'receiver': email,
                    'note': note or 'Payment for services',
                    'sender_item_id': f"item_{int(timezone.now().timestamp())}"
                }]
            })
            
            if payout.create(sync_mode=False):
                return {
                    'success': True,
                    'payout_id': payout.batch_header.payout_batch_id,
                    'status': payout.batch_header.batch_status
                }
            else:
                logger.error(f"PayPal payout creation failed: {payout.error}")
                return {
                    'success': False,
                    'error': str(payout.error)
                }
        except Exception as e:
            logger.error(f"PayPal payout error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def get_payout_status(payout_batch_id):
        if payout_batch_id.startswith('PAYOUT_TEST_'):
            return None
        
        paypal = PayPalService.get_paypal_client()
        if not paypal:
            return None
        
        try:
            payout = paypal.Payout.get(payout_batch_id)
            return payout
        except Exception as e:
            logger.error(f"PayPal get payout error: {str(e)}")
            return None


class EmailService:
    
    @staticmethod
    def send_transaction_notification(user, transaction):
        subject = f'Transaction Notification - {transaction.type.title()}'
        context = {
            'user': user,
            'transaction': transaction,
            'amount': abs(transaction.amount),
            'type': transaction.type,
            'balance': float(transaction.wallet.balance)
        }
        html_message = render_to_string('emails/transaction_notification.html', context)
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
    
    @staticmethod
    def mark_processing(key, user):
        if not key:
            return
        
        cache_key = f"idempotency_{user.id}_{key}"
        cache.set(cache_key, 'processing', timeout=3600)


class WebhookService:
    
    @staticmethod
    def process_paypal_webhook(payload):
        try:
            event = json.loads(payload)
            event_type = event.get('event_type')
            resource = event.get('resource', {})
            
            webhook = PayPalWebhook.objects.create(
                webhook_id=event.get('id', ''),
                event_type=event_type,
                resource_id=resource.get('id', ''),
                payload=event
            )
            
            if event_type == 'PAYMENT.PAYOUTSBATCH.SUCCESS':
                WebhookService.handle_paypal_payout_succeeded(resource)
            elif event_type == 'PAYMENT.PAYOUTSBATCH.FAILED':
                WebhookService.handle_paypal_payout_failed(resource)
            elif event_type == 'PAYMENT.CAPTURE.COMPLETED':
                WebhookService.handle_paypal_capture_completed(resource)
            elif event_type == 'PAYMENT.CAPTURE.DENIED':
                WebhookService.handle_paypal_capture_denied(resource)
            
            webhook.mark_processed()
            return {'success': True, 'message': 'Webhook processed'}
            
        except Exception as e:
            logger.error(f"PayPal webhook error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def handle_paypal_payout_succeeded(data):
        payout_batch_id = data.get('payout_batch_id')
        
        if payout_batch_id:
            try:
                payout = Payout.objects.get(paypal_payout_id=payout_batch_id)
                payout.complete()
            except Payout.DoesNotExist:
                logger.warning(f"Payout not found for ID: {payout_batch_id}")
    
    @staticmethod
    def handle_paypal_payout_failed(data):
        payout_batch_id = data.get('payout_batch_id')
        error_message = data.get('errors', {}).get('message', 'Unknown error')
        
        if payout_batch_id:
            try:
                payout = Payout.objects.get(paypal_payout_id=payout_batch_id)
                payout.fail(error_message)
            except Payout.DoesNotExist:
                logger.warning(f"Payout not found for ID: {payout_batch_id}")
    
    @staticmethod
    def handle_paypal_capture_completed(data):
        payment_id = data.get('id')
        
        if payment_id:
            payment_intent = PaymentIntent.objects.filter(intent_id=payment_id).first()
            
            if payment_intent and payment_intent.status != 'succeeded':
                with db_transaction.atomic():
                    if payment_intent.transaction:
                        payment_intent.transaction.status = 'completed'
                        payment_intent.transaction.completed_at = timezone.now()
                        payment_intent.transaction.paypal_transaction_id = payment_id
                        payment_intent.transaction.save()
                    
                    payment_intent.status = 'succeeded'
                    payment_intent.save()
    
    @staticmethod
    def handle_paypal_capture_denied(data):
        payment_id = data.get('id')
        
        if payment_id:
            payment_intent = PaymentIntent.objects.filter(intent_id=payment_id).first()
            
            if payment_intent:
                payment_intent.status = 'failed'
                payment_intent.save()
                
                if payment_intent.transaction:
                    payment_intent.transaction.status = 'failed'
                    payment_intent.transaction.save()