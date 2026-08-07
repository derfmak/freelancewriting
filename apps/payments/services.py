import secrets
import string
import logging
import json
import requests
from decimal import Decimal
from datetime import timedelta
from django.db import transaction as db_transaction
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.core.cache import cache
from .models import Wallet, Transaction, PaymentMethod, PaymentIntent, Payout, PayPalWebhook, AdminWalletManager

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
    def _base_url():
        return 'https://api-m.sandbox.paypal.com' if settings.PAYPAL_MODE == 'sandbox' else 'https://api-m.paypal.com'

    @staticmethod
    def _access_token():
        resp = requests.post(
            f"{PayPalService._base_url()}/v1/oauth2/token",
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            data={'grant_type': 'client_credentials'},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()['access_token']

    @staticmethod
    def create_payment(amount, return_url, cancel_url, description=None):
        token = PayPalService._access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        body = {
            'intent': 'CAPTURE',
            'purchase_units': [{
                'amount': {
                    'currency_code': 'USD',
                    'value': str(amount),
                },
                'payee': {
                    'email_address': settings.ADMIN_PAYPAL_EMAIL,
                },
                'description': description or f'Payment of ${amount}',
            }],
            'application_context': {
                'return_url': return_url,
                'cancel_url': cancel_url,
                'shipping_preference': 'NO_SHIPPING',
            },
        }

        resp = requests.post(
            f"{PayPalService._base_url()}/v2/checkout/orders",
            json=body,
            headers=headers,
            timeout=15,
        )

        if resp.status_code != 201:
            logger.error(f"PayPal order creation failed: {resp.text}")
            return {
                'success': False,
                'error': resp.json().get('message', 'PayPal error'),
            }

        order = resp.json()
        approval_url = next(
            link['href'] for link in order['links'] if link['rel'] == 'approve'
        )
        return {
            'success': True,
            'payment_id': order['id'],
            'approval_url': approval_url,
            'state': order['status'],
        }

    @staticmethod
    def execute_payment(paypal_order_id, payer_id=None):
        token = PayPalService._access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        url = f"{PayPalService._base_url()}/v2/checkout/orders/{paypal_order_id}/capture"
        resp = requests.post(url, headers=headers, timeout=15)

        if resp.status_code != 201:
            logger.error(f"PayPal capture failed: {resp.text}")
            return {'success': False, 'error': 'Payment capture failed'}

        capture = resp.json()
        if capture['status'] == 'COMPLETED':
            amount = Decimal(
                capture['purchase_units'][0]['payments']['captures'][0]['amount']['value']
            )
            return {
                'success': True,
                'state': 'approved',
                'amount': amount,
            }
        return {'success': False, 'error': 'Payment not completed'}

    @staticmethod
    def create_payout(email, amount, note=''):
        token = PayPalService._access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        body = {
            'sender_batch_header': {
                'sender_batch_id': f"Payout-{timezone.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}",
                'email_subject': 'You have a payout!',
            },
            'items': [{
                'recipient_type': 'EMAIL',
                'amount': {
                    'value': str(amount),
                    'currency': 'USD',
                },
                'receiver': email,
                'note': note or 'Payout from AcademicWrite',
                'sender_item_id': f"item-{secrets.token_hex(6)}",
            }]
        }

        resp = requests.post(
            f"{PayPalService._base_url()}/v1/payments/payouts",
            json=body,
            headers=headers,
            timeout=15,
        )

        if resp.status_code != 201:
            logger.error(f"PayPal payout creation failed: {resp.text}")
            return {
                'success': False,
                'error': resp.json().get('message', 'PayPal error'),
            }

        payout = resp.json()
        return {
            'success': True,
            'payout_id': payout['batch_header']['payout_batch_id'],
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

    @staticmethod
    def send_paypal_verification_code(user, paypal_email, verification_code):
        subject = 'PayPal Account Verification Code'
        try:
            html_message = f"""
            <html>
            <body>
                <p>Hello {user.full_name},</p>
                <p>You are adding <strong>{paypal_email}</strong> as a PayPal payment method.</p>
                <p>Your verification code is:</p>
                <h2 style="background:#f4f4f4; padding:15px; display:inline-block; letter-spacing:2px;">{verification_code}</h2>
                <p>This code expires in <strong>5</strong> minutes.</p>
                <p>If you did not request this, please ignore this email.</p>
                <p>— AcademicWrite Team</p>
            </body>
            </html>
            """
            plain_message = f"Your PayPal verification code is: {verification_code}. It expires in 5 minutes."

            send_mail(
                subject,
                plain_message,
                settings.DEFAULT_FROM_EMAIL,
                [paypal_email],
                html_message=html_message,
                fail_silently=False,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send PayPal verification email to {paypal_email}: {e}")
            return False


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


class AdminPaymentService:

    @staticmethod
    def process_client_payment(order, client, amount, payment_method='paypal'):
        with db_transaction.atomic():
            AdminWalletManager.record_client_debit(
                client=client,
                amount=amount,
                order=order,
                description=f'Payment for order {order.order_number}'
            )

            AdminWalletManager.record_admin_credit(
                user=client,
                amount=amount,
                order=order,
                description=f'Payment for order {order.order_number}'
            )

            order.payment_status = 'paid'
            order.paid_at = timezone.now()
            order.save(update_fields=['payment_status', 'paid_at'])

            return {
                'success': True,
                'message': f'Payment of ${amount} processed'
            }

    @staticmethod
    def process_writer_payout(order, writer, amount, payment_method='paypal'):
        with db_transaction.atomic():
            AdminWalletManager.record_admin_debit(
                user=writer,
                amount=amount,
                order=order,
                description=f'Payment to writer for order {order.order_number}'
            )

            AdminWalletManager.record_writer_credit(
                writer=writer,
                amount=amount,
                order=order,
                description=f'Payment for order {order.order_number}'
            )

            payout = Payout.objects.create(
                user=writer,
                amount=amount,
                paypal_email=writer.paypal_email,
                status='pending',
                metadata={'order_id': str(order.id)}
            )

            return {
                'success': True,
                'payout_id': payout.payout_id,
                'message': f'Payout of ${amount} initiated'
            }

    @staticmethod
    def process_refund(order, amount, payment_method='paypal'):
        client = order.client

        with db_transaction.atomic():
            AdminWalletManager.record_admin_debit(
                user=client,
                amount=amount,
                order=order,
                description=f'Refund for order {order.order_number}'
            )

            AdminWalletManager.record_client_credit(
                client=client,
                amount=amount,
                order=order,
                description=f'Refund for order {order.order_number}'
            )

            order.payment_status = 'refunded'
            order.refunded_at = timezone.now()
            order.save(update_fields=['payment_status', 'refunded_at'])

            return {
                'success': True,
                'message': f'Refund of ${amount} processed'
            }

    @staticmethod
    def get_admin_financial_summary():
        admin_wallet = AdminWalletManager.get_admin_wallet()

        return {
            'balance': float(admin_wallet.balance),
            'total_received': float(admin_wallet.total_in),
            'total_paid_out': float(admin_wallet.total_out),
            'net_position': float(admin_wallet.balance),
            'admin_paypal_email': AdminWalletManager.get_admin_paypal_email(),
            'wallet_id': str(admin_wallet.id),
            'currency': admin_wallet.currency
        }

    @staticmethod
    def create_paypal_payment_for_order(order, return_url, cancel_url):
        amount = order.total_price
        return PayPalService.create_payment(
            amount=amount,
            return_url=return_url,
            cancel_url=cancel_url,
            description=f'Payment for order {order.order_number}'
        )

    @staticmethod
    def send_paypal_payout_to_writer(writer, amount, order):
        return PayPalService.create_payout(
            email=writer.paypal_email,
            amount=amount,
            note=f'Payment for order {order.order_number}'
        )

    @staticmethod
    def send_paypal_refund_to_client(client, amount, order):
        return PayPalService.create_payout(
            email=client.paypal_email,
            amount=amount,
            note=f'Refund for order {order.order_number}'
        )