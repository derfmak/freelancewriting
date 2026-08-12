from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from django.db import transaction as db_transaction
from django.db.models import Sum, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal
import logging
import json
import secrets
from django.http import JsonResponse
from django.conf import settings
import uuid

from .models import Wallet, Transaction, PaymentMethod, PaymentIntent, Payout, PayPalWebhook
from .serializers import (
    WalletSerializer, TransactionSerializer, TransactionDetailSerializer,
    PaymentMethodSerializer, PaymentIntentSerializer, PayoutSerializer
)
from .services import PayPalService, AdminPaymentService, AdminWalletManager, EmailService

logger = logging.getLogger(__name__)

VERIFICATION_CODE_TTL_MINUTES = 5
VERIFICATION_MAX_ATTEMPTS = 3
VERIFICATION_LOCKOUT_HOURS = 24


def get_or_create_wallet(user):
    wallet, created = Wallet.objects.get_or_create(user=user)
    return wallet


def generate_verification_code():
    return ''.join(secrets.choice('0123456789') for _ in range(6))


def is_locked(method):
    return bool(method.verification_locked_until and timezone.now() < method.verification_locked_until)


def lock_response(method):
    remaining_seconds = max(0, int((method.verification_locked_until - timezone.now()).total_seconds()))
    remaining_hours = max(1, remaining_seconds // 3600)
    return Response({
        'error': f'Too many failed attempts. Try again in {remaining_hours} hour(s).',
        'locked': True,
        'locked_until': method.verification_locked_until.isoformat()
    }, status=status.HTTP_400_BAD_REQUEST)


def is_code_expired(method):
    if not method.verification_code_created_at:
        return True
    return timezone.now() > method.verification_code_created_at + timezone.timedelta(minutes=VERIFICATION_CODE_TTL_MINUTES)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_wallet(request):
    wallet = get_or_create_wallet(request.user)
    serializer = WalletSerializer(wallet)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_wallet_stats(request):
    wallet = get_or_create_wallet(request.user)
    stats = {
        'balance': float(wallet.balance),
        'total_in': float(wallet.total_in),
        'total_out': float(wallet.total_out),
        'currency': wallet.currency,
        'is_active': wallet.is_active,
    }
    return Response(stats)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_transactions(request):
    wallet = get_or_create_wallet(request.user)
    transactions = Transaction.objects.filter(wallet=wallet).order_by('-created_at')

    transaction_type = request.GET.get('type')
    if transaction_type:
        transactions = transactions.filter(type=transaction_type)

    direction = request.GET.get('direction')
    if direction:
        transactions = transactions.filter(direction=direction)

    status_filter = request.GET.get('status')
    if status_filter:
        transactions = transactions.filter(status=status_filter)

    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))
    start = (page - 1) * page_size
    end = start + page_size

    total = transactions.count()
    paginated = transactions[start:end]
    serializer = TransactionSerializer(paginated, many=True)

    return Response({
        'total': total,
        'page': page,
        'page_size': page_size,
        'results': serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_transaction_detail(request, transaction_id):
    transaction = get_object_or_404(Transaction, transaction_id=transaction_id, user=request.user)
    serializer = TransactionDetailSerializer(transaction)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def check_paypal_email(request):
    paypal_email = request.data.get('paypal_email', '').strip()

    if not paypal_email:
        return Response({'error': 'PayPal email is required'}, status=status.HTTP_400_BAD_REQUEST)

    existing = PaymentMethod.objects.filter(user=request.user, paypal_email=paypal_email).first()

    if existing:
        return Response({
            'exists': True,
            'is_active': existing.is_active,
            'is_pending': not existing.is_active,
            'is_locked': is_locked(existing),
            'method_id': str(existing.id) if not existing.is_active else None
        })

    return Response({
        'exists': False,
        'is_active': False,
        'is_pending': False,
        'is_locked': False,
        'method_id': None
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_paypal_method(request):
    paypal_email = request.data.get('paypal_email', '').strip()
    if not paypal_email:
        return Response({'error': 'PayPal email is required'}, status=status.HTTP_400_BAD_REQUEST)

    existing = PaymentMethod.objects.filter(user=request.user, paypal_email=paypal_email).first()

    if existing and existing.is_active:
        return Response({'error': 'This PayPal account is already verified'}, status=status.HTTP_400_BAD_REQUEST)

    if existing and is_locked(existing):
        return lock_response(existing)

    is_new = existing is None

    if is_new:
        method = PaymentMethod(
            user=request.user,
            paypal_email=paypal_email,
            paypal_account_type=request.data.get('paypal_account_type', 'personal'),
            paypal_verified=False,
            is_active=False,
        )
    else:
        method = existing
        method.verification_attempts = 0
        method.verification_locked_until = None

    method.verification_code = generate_verification_code()
    method.verification_code_created_at = timezone.now()
    method.save()

    email_sent = EmailService.send_paypal_verification_code(
        user=request.user,
        paypal_email=paypal_email,
        verification_code=method.verification_code
    )

    if not email_sent:
        if is_new:
            method.delete()
        return Response({
            'error': 'Failed to send verification email. Please check your email address and try again.'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        'success': True,
        'message': 'Verification code sent to your PayPal email. Please verify within 5 minutes.',
        'method_id': str(method.id),
        'expires_in': VERIFICATION_CODE_TTL_MINUTES * 60
    }, status=status.HTTP_201_CREATED if is_new else status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_paypal_method(request):
    method_id = request.data.get('method_id')
    code = request.data.get('code', '').strip()

    if not method_id or not code:
        return Response({'error': 'Method ID and verification code are required'}, status=status.HTTP_400_BAD_REQUEST)

    method = get_object_or_404(PaymentMethod, id=method_id, user=request.user)

    if method.is_active:
        return Response({'error': 'This PayPal account is already verified'}, status=status.HTTP_400_BAD_REQUEST)

    if is_locked(method):
        return lock_response(method)

    if is_code_expired(method):
        return Response({
            'error': 'Verification code has expired. Please request a new one.',
            'expired': True
        }, status=status.HTTP_400_BAD_REQUEST)

    code_matches = bool(method.verification_code) and secrets.compare_digest(method.verification_code, code)

    if not code_matches:
        method.verification_attempts += 1
        if method.verification_attempts >= VERIFICATION_MAX_ATTEMPTS:
            method.verification_locked_until = timezone.now() + timezone.timedelta(hours=VERIFICATION_LOCKOUT_HOURS)
        method.save()
        remaining_attempts = VERIFICATION_MAX_ATTEMPTS - method.verification_attempts
        return Response({
            'error': 'Invalid verification code',
            'remaining_attempts': max(0, remaining_attempts),
            'locked': method.verification_attempts >= VERIFICATION_MAX_ATTEMPTS
        }, status=status.HTTP_400_BAD_REQUEST)

    method.is_active = True
    method.paypal_verified = True
    method.verification_code = None
    method.verification_code_created_at = None
    method.verification_attempts = 0
    method.verification_locked_until = None
    method.save()

    if not PaymentMethod.objects.filter(user=request.user, is_default=True).exclude(id=method.id).exists():
        method.is_default = True
        method.save()

    return Response({
        'success': True,
        'message': 'PayPal account verified and added successfully',
        'method_id': str(method.id),
        'is_default': method.is_default
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resend_verification_code(request):
    method_id = request.data.get('method_id')

    if not method_id:
        return Response({'error': 'Method ID is required'}, status=status.HTTP_400_BAD_REQUEST)

    method = get_object_or_404(PaymentMethod, id=method_id, user=request.user)

    if method.is_active:
        return Response({'error': 'This PayPal account is already verified'}, status=status.HTTP_400_BAD_REQUEST)

    if is_locked(method):
        return lock_response(method)

    new_code = generate_verification_code()
    method.verification_code = new_code
    method.verification_code_created_at = timezone.now()
    method.save()

    email_sent = EmailService.send_paypal_verification_code(
        user=request.user,
        paypal_email=method.paypal_email,
        verification_code=new_code
    )

    if not email_sent:
        return Response({'error': 'Failed to send email. Please try again.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        'success': True,
        'message': 'New verification code sent to your PayPal email',
        'expires_in': VERIFICATION_CODE_TTL_MINUTES * 60
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_paypal_methods(request):
    methods = PaymentMethod.objects.filter(
        user=request.user,
        is_active=True
    ).order_by('-is_default', '-created_at')

    results = []
    for m in methods:
        results.append({
            'id': str(m.id),
            'is_default': m.is_default,
            'is_active': m.is_active,
            'paypal_email': m.paypal_email,
            'paypal_account_type': m.paypal_account_type,
            'paypal_verified': m.paypal_verified,
            'created_at': m.created_at.isoformat(),
            'last_used_at': m.last_used_at.isoformat() if m.last_used_at else None,
        })

    return Response(results)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_payment_method(request, method_id):
    method = get_object_or_404(PaymentMethod, id=method_id, user=request.user, is_active=True)

    active_count = PaymentMethod.objects.filter(user=request.user, is_active=True).count()

    if active_count == 1:
        return Response({
            'error': 'Cannot remove the only payment method. You need at least one active PayPal account.'
        }, status=status.HTTP_400_BAD_REQUEST)

    if method.is_default and active_count > 1:
        return Response({
            'error': 'Cannot remove your default payment method. Please set another account as default first.'
        }, status=status.HTTP_400_BAD_REQUEST)

    method.is_active = False
    method.save()

    if method.is_default:
        new_default = PaymentMethod.objects.filter(user=request.user, is_active=True).first()
        if new_default:
            new_default.is_default = True
            new_default.save()

    return Response({
        'success': True,
        'message': 'Payment method removed successfully.'
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_default_payment_method(request, method_id):
    method = get_object_or_404(PaymentMethod, id=method_id, user=request.user, is_active=True)

    PaymentMethod.objects.filter(user=request.user, is_default=True).update(is_default=False)

    method.is_default = True
    method.save()

    return Response({
        'success': True,
        'message': 'Default payment method updated'
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_paypal_deposit(request):
    try:
        amount = Decimal(str(request.data.get('amount', 0)))

        if amount < 5:
            return Response({'error': 'Minimum deposit is $5'}, status=status.HTTP_400_BAD_REQUEST)

        wallet = get_or_create_wallet(request.user)

        method = PaymentMethod.objects.filter(
            user=request.user,
            is_active=True
        ).first()

        if not method:
            return Response({
                'error': 'no_paypal_account',
                'message': 'Please add and verify a PayPal account first'
            }, status=status.HTTP_400_BAD_REQUEST)

        with db_transaction.atomic():
            transaction_obj = Transaction.objects.create(
                user=request.user,
                wallet=wallet,
                amount=amount,
                type='deposit',
                direction='credit',
                status='pending',
                payment_method='paypal',
                description=f'PayPal deposit of ${amount}',
            )

            local_payment_intent_id = uuid.uuid4()

            payment_intent = PaymentIntent.objects.create(
                id=local_payment_intent_id,
                user=request.user,
                intent_id=None,
                amount=amount,
                transaction=transaction_obj,
                status='pending',
                return_url=request.build_absolute_uri('/api/v1/wallet/paypal/deposit/execute/'),
                cancel_url=request.build_absolute_uri('/client/wallet/'),
                metadata={'local_id': str(local_payment_intent_id)}
            )

            transaction_obj.metadata['payment_intent_id'] = str(local_payment_intent_id)
            transaction_obj.save()

        paypal_service = PayPalService()
        paypal_result = paypal_service.create_payment(
            amount=amount,
            return_url=payment_intent.return_url,
            cancel_url=payment_intent.cancel_url,
            idempotency_key=str(local_payment_intent_id)
        )

        with db_transaction.atomic():
            transaction_obj.refresh_from_db()
            payment_intent.refresh_from_db()

            if paypal_result.get('success'):
                transaction_obj.status = 'completed'
                transaction_obj.paypal_transaction_id = paypal_result['payment_id']
                transaction_obj.completed_at = timezone.now()
                transaction_obj.save()

                payment_intent.intent_id = paypal_result['payment_id']
                payment_intent.status = 'succeeded'
                payment_intent.save()

                approval_url = paypal_result['approval_url']

                return Response({
                    'approval_url': approval_url,
                    'payment_id': paypal_result['payment_id'],
                    'transaction_id': transaction_obj.transaction_id,
                    'amount': float(amount)
                })

            elif paypal_result.get('error'):
                transaction_obj.status = 'failed'
                transaction_obj.metadata['failure_reason'] = paypal_result['error']
                transaction_obj.save()

                payment_intent.status = 'failed'
                payment_intent.save()

                return Response({
                    'error': 'paypal_error',
                    'message': paypal_result['error']
                }, status=status.HTTP_400_BAD_REQUEST)

            else:
                transaction_obj.status = 'unknown'
                transaction_obj.metadata['failure_reason'] = 'PayPal request timed out or network error'
                transaction_obj.save()

                payment_intent.status = 'unknown'
                payment_intent.save()

                return Response({
                    'status': 'processing',
                    'message': 'Payment is being processed. We will confirm shortly.',
                    'transaction_id': transaction_obj.transaction_id
                }, status=status.HTTP_202_ACCEPTED)

    except Exception as e:
        logger.error(f"PayPal deposit creation failed: {str(e)}")
        return Response({
            'error': 'paypal_error',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def execute_paypal_payment(request):
    try:
        payment_id = request.GET.get('paymentId')
        payer_id = request.GET.get('PayerID')

        if not payment_id or not payer_id:
            return Response({'error': 'Missing payment parameters'}, status=status.HTTP_400_BAD_REQUEST)

        payment_intent = get_object_or_404(PaymentIntent, intent_id=payment_id, user=request.user)
        transaction_obj = payment_intent.transaction
        wallet = request.user.wallet

        if payment_id.startswith('PAYPAL_TEST_'):
            with db_transaction.atomic():
                amount = payment_intent.amount
                transaction_obj.status = 'completed'
                transaction_obj.completed_at = timezone.now()
                transaction_obj.save()

                payment_intent.status = 'succeeded'
                payment_intent.save()

            return Response({
                'success': True,
                'message': f'${amount} deposited successfully',
                'balance': float(wallet.balance)
            })

        paypal_service = PayPalService()
        paypal_result = paypal_service.execute_payment(payment_id, payer_id)

        with db_transaction.atomic():
            transaction_obj.refresh_from_db()
            payment_intent.refresh_from_db()

            if paypal_result.get('success') and paypal_result.get('state') == 'approved':
                amount = paypal_result['amount']

                transaction_obj.status = 'completed'
                transaction_obj.completed_at = timezone.now()
                transaction_obj.paypal_transaction_id = payment_id
                transaction_obj.save()

                payment_intent.status = 'succeeded'
                payment_intent.save()

                return Response({
                    'success': True,
                    'message': f'${amount} deposited successfully',
                    'balance': float(wallet.balance),
                    'transaction_id': str(transaction_obj.id)
                })

            elif paypal_result.get('error'):
                transaction_obj.status = 'failed'
                transaction_obj.metadata['failure_reason'] = paypal_result['error']
                transaction_obj.save()

                payment_intent.status = 'failed'
                payment_intent.save()

                return Response({'error': paypal_result['error']}, status=status.HTTP_400_BAD_REQUEST)

            else:
                transaction_obj.status = 'unknown'
                transaction_obj.metadata['failure_reason'] = 'PayPal execution returned unknown state'
                transaction_obj.save()

                payment_intent.status = 'unknown'
                payment_intent.save()

                return Response({
                    'status': 'processing',
                    'message': 'Payment execution is being confirmed.'
                }, status=status.HTTP_202_ACCEPTED)

    except PaymentIntent.DoesNotExist:
        return Response({'error': 'Payment intent not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"PayPal payment execution failed: {str(e)}")
        try:
            payment_intent = PaymentIntent.objects.get(intent_id=payment_id, user=request.user)
            transaction_obj = payment_intent.transaction
            with db_transaction.atomic():
                transaction_obj.status = 'unknown'
                transaction_obj.metadata['failure_reason'] = f'Exception: {str(e)}'
                transaction_obj.save()
                payment_intent.status = 'unknown'
                payment_intent.save()
            return Response({
                'status': 'processing',
                'message': 'Payment is being confirmed. Please check back later.'
            }, status=status.HTTP_202_ACCEPTED)
        except:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_paypal_payment(request):
    payment_id = request.data.get('payment_id')

    if not payment_id:
        return Response({'error': 'Payment ID is required'}, status=status.HTTP_400_BAD_REQUEST)

    payment_intent = get_object_or_404(PaymentIntent, intent_id=payment_id, user=request.user)

    if payment_intent.status in ['succeeded', 'failed']:
        return Response({
            'error': 'cannot_cancel',
            'message': f'Cannot cancel payment with status: {payment_intent.status}'
        }, status=status.HTTP_400_BAD_REQUEST)

    payment_intent.status = 'cancelled'
    payment_intent.save()

    if payment_intent.transaction:
        payment_intent.transaction.status = 'cancelled'
        payment_intent.transaction.save()

    return Response({
        'success': True,
        'message': 'Payment cancelled successfully'
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_withdrawal(request):
    wallet = get_or_create_wallet(request.user)

    amount = Decimal(str(request.data.get('amount', 0)))
    paypal_email = request.data.get('paypal_email', '').strip()

    if amount < Decimal('10.00'):
        return Response({
            'error': 'minimum_withdrawal',
            'message': 'Minimum withdrawal amount is $10.00'
        }, status=status.HTTP_400_BAD_REQUEST)

    if not paypal_email:
        return Response({
            'error': 'paypal_email_required',
            'message': 'PayPal email is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    if wallet.balance < amount:
        return Response({
            'error': 'insufficient_balance',
            'message': f'Insufficient balance. Available: ${wallet.balance}'
        }, status=status.HTTP_400_BAD_REQUEST)

    method = PaymentMethod.objects.filter(
        user=request.user,
        paypal_email=paypal_email,
        is_active=True
    ).first()

    if not method:
        return Response({
            'error': 'paypal_method_not_found',
            'message': 'PayPal account not found'
        }, status=status.HTTP_404_NOT_FOUND)

    try:
        with db_transaction.atomic():
            transaction_obj = Transaction.objects.create(
                user=request.user,
                wallet=wallet,
                amount=amount,
                type='withdrawal',
                direction='debit',
                status='pending',
                payment_method='paypal',
                description=f'Withdrawal to {paypal_email}',
            )

            payout = Payout.objects.create(
                user=request.user,
                transaction=transaction_obj,
                amount=amount,
                paypal_email=paypal_email,
                status='pending'
            )

            paypal_service = PayPalService()
            payout_result = paypal_service.create_payout(
                email=paypal_email,
                amount=amount,
                note=f'Withdrawal from wallet'
            )

            if payout_result['success']:
                payout.status = 'processing'
                payout.paypal_payout_id = payout_result['payout_id']
                payout.paypal_response = payout_result
                payout.save()

                transaction_obj.status = 'processing'
                transaction_obj.paypal_transaction_id = payout_result['payout_id']
                transaction_obj.save()
            else:
                payout.fail(str(payout_result.get('error', 'PayPal payout failed')))
                transaction_obj.fail(str(payout_result.get('error', 'PayPal payout failed')))
                raise Exception(payout_result.get('error', 'PayPal payout failed'))

        return Response({
            'success': True,
            'message': 'Withdrawal request submitted',
            'transaction_id': str(transaction_obj.id),
            'payout_id': payout.payout_id,
            'amount': float(amount),
            'status': payout.status,
            'new_balance': float(wallet.balance)
        })

    except Exception as e:
        logger.error(f"Withdrawal error: {e}")
        return Response({
            'error': 'withdrawal_failed',
            'message': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_withdrawal_status(request, payout_id):
    payout = get_object_or_404(Payout, payout_id=payout_id, user=request.user)
    serializer = PayoutSerializer(payout)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_payouts(request):
    payouts = Payout.objects.filter(user=request.user).order_by('-created_at')

    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))
    start = (page - 1) * page_size
    end = start + page_size

    total = payouts.count()
    paginated = payouts[start:end]
    serializer = PayoutSerializer(paginated, many=True)

    return Response({
        'total': total,
        'page': page,
        'page_size': page_size,
        'results': serializer.data
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_payout_detail(request, payout_id):
    payout = get_object_or_404(Payout, payout_id=payout_id, user=request.user)
    serializer = PayoutSerializer(payout)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_payment_methods(request):
    return get_paypal_methods(request)


@csrf_exempt
def paypal_webhook(request):
    try:
        payload = json.loads(request.body)
        event_type = payload.get('event_type')
        resource = payload.get('resource', {})

        webhook = PayPalWebhook.objects.create(
            webhook_id=payload.get('id', ''),
            event_type=event_type,
            resource_id=resource.get('id', ''),
            payload=payload,
        )

        if event_type == 'PAYMENT.CAPTURE.COMPLETED':
            payment_id = resource.get('id')
            payment_intent = PaymentIntent.objects.filter(intent_id=payment_id).first()

            if payment_intent and payment_intent.status not in ['succeeded', 'failed']:
                with db_transaction.atomic():
                    payment_intent.refresh_from_db()
                    if payment_intent.status not in ['succeeded', 'failed']:
                        if payment_intent.transaction:
                            payment_intent.transaction.status = 'completed'
                            payment_intent.transaction.completed_at = timezone.now()
                            payment_intent.transaction.paypal_transaction_id = payment_id
                            payment_intent.transaction.save()

                        payment_intent.status = 'succeeded'
                        payment_intent.save()

        elif event_type == 'PAYMENT.CAPTURE.DENIED':
            payment_id = resource.get('id')
            payment_intent = PaymentIntent.objects.filter(intent_id=payment_id).first()

            if payment_intent and payment_intent.status not in ['succeeded', 'failed']:
                with db_transaction.atomic():
                    payment_intent.refresh_from_db()
                    if payment_intent.status not in ['succeeded', 'failed']:
                        payment_intent.status = 'failed'
                        payment_intent.save()
                        if payment_intent.transaction:
                            payment_intent.transaction.status = 'failed'
                            payment_intent.transaction.save()

        elif event_type == 'PAYMENT.PAYOUTSBATCH.SUCCESS':
            payout_batch_id = resource.get('payout_batch_id')
            payout = Payout.objects.filter(paypal_payout_id=payout_batch_id).first()

            if payout and payout.status not in ['completed', 'failed']:
                with db_transaction.atomic():
                    payout.refresh_from_db()
                    if payout.status not in ['completed', 'failed']:
                        payout.status = 'completed'
                        payout.completed_at = timezone.now()
                        payout.save()
                        if payout.transaction:
                            payout.transaction.status = 'completed'
                            payout.transaction.completed_at = timezone.now()
                            payout.transaction.save()

        elif event_type == 'PAYMENT.PAYOUTSBATCH.FAILED':
            payout_batch_id = resource.get('payout_batch_id')
            payout = Payout.objects.filter(paypal_payout_id=payout_batch_id).first()

            if payout and payout.status not in ['completed', 'failed']:
                with db_transaction.atomic():
                    payout.refresh_from_db()
                    if payout.status not in ['completed', 'failed']:
                        payout.status = 'failed'
                        payout.metadata['failure_reason'] = resource.get('errors', {}).get('message', 'Unknown error')
                        payout.save()
                        if payout.transaction:
                            payout.transaction.status = 'failed'
                            payout.transaction.save()

        webhook.mark_processed()
        return JsonResponse({'success': True})

    except Exception as e:
        logger.error(f"PayPal webhook error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_payment_stats(request):
    total_deposits = Transaction.objects.filter(
        type='deposit',
        direction='credit',
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_withdrawals = Transaction.objects.filter(
        type='withdrawal',
        direction='debit',
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_payouts = Transaction.objects.filter(
        type='payout',
        direction='debit',
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_refunds = Transaction.objects.filter(
        type='refund',
        direction='debit',
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_users = Wallet.objects.filter(is_active=True).count()

    total_balance = Wallet.objects.aggregate(
        total=Sum('balance')
    )['total'] or Decimal('0.00')

    stats = {
        'total_deposits': float(total_deposits),
        'total_withdrawals': float(total_withdrawals),
        'total_payouts': float(total_payouts),
        'total_refunds': float(total_refunds),
        'total_balance': float(total_balance),
        'total_users': total_users,
        'currency': 'USD'
    }

    return Response(stats)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_financial_summary(request):
    summary = AdminPaymentService.get_admin_financial_summary()
    return Response(summary)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_set_paypal_email(request):
    email = request.data.get('paypal_email', '').strip()

    if not email:
        return Response({'error': 'PayPal email is required'}, status=status.HTTP_400_BAD_REQUEST)

    AdminWalletManager.set_admin_paypal_email(email)

    return Response({
        'success': True,
        'message': f'Admin PayPal email set to {email}',
        'email': email
    })


@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_process_client_payment(request):
    order_id = request.data.get('order_id')
    amount = Decimal(str(request.data.get('amount', 0)))
    client_id = request.data.get('client_id')

    if not order_id or not client_id:
        return Response({'error': 'order_id and client_id are required'}, status=status.HTTP_400_BAD_REQUEST)

    from apps.orders.models import Order
    from apps.accounts.models import User

    try:
        order = get_object_or_404(Order, id=order_id)
        client = get_object_or_404(User, id=client_id)

        result = AdminPaymentService.process_client_payment(order, client, amount)
        return Response(result)
    except Exception as e:
        logger.error(f"Admin payment processing error: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_process_writer_payout(request):
    order_id = request.data.get('order_id')
    amount = Decimal(str(request.data.get('amount', 0)))
    writer_id = request.data.get('writer_id')

    if not order_id or not writer_id:
        return Response({'error': 'order_id and writer_id are required'}, status=status.HTTP_400_BAD_REQUEST)

    from apps.orders.models import Order
    from apps.accounts.models import User

    try:
        order = get_object_or_404(Order, id=order_id)
        writer = get_object_or_404(User, id=writer_id)

        result = AdminPaymentService.process_writer_payout(order, writer, amount)
        return Response(result)
    except Exception as e:
        logger.error(f"Admin payout processing error: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_process_refund(request):
    order_id = request.data.get('order_id')
    amount = Decimal(str(request.data.get('amount', 0)))

    if not order_id:
        return Response({'error': 'order_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    from apps.orders.models import Order

    try:
        order = get_object_or_404(Order, id=order_id)

        result = AdminPaymentService.process_refund(order, amount)
        return Response(result)
    except Exception as e:
        logger.error(f"Admin refund processing error: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_transactions(request):
    admin_wallet = AdminWalletManager.get_admin_wallet()
    transactions = Transaction.objects.filter(wallet=admin_wallet).order_by('-created_at')

    transaction_type = request.GET.get('type')
    if transaction_type:
        transactions = transactions.filter(type=transaction_type)

    direction = request.GET.get('direction')
    if direction:
        transactions = transactions.filter(direction=direction)

    status_filter = request.GET.get('status')
    if status_filter:
        transactions = transactions.filter(status=status_filter)

    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))
    start = (page - 1) * page_size
    end = start + page_size

    total = transactions.count()
    paginated = transactions[start:end]
    serializer = TransactionSerializer(paginated, many=True)

    return Response({
        'total': total,
        'page': page,
        'page_size': page_size,
        'results': serializer.data
    })