from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from django.db import transaction as db_transaction
from django.db.models import Q, Sum, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal
import logging
import hashlib
import hmac
import secrets
import json

from .models import Wallet, Transaction, PaymentMethod, PaymentIntent, OrderPayment, FraudCheck, Payout, PayPalWebhook
from .serializers import (
    WalletSerializer, TransactionSerializer, TransactionDetailSerializer,
    DepositSerializer, DepositConfirmSerializer, WithdrawSerializer,
    PaymentMethodSerializer, AddPaymentMethodSerializer,
    PaymentIntentSerializer, OrderPaymentSerializer, PayoutSerializer,
    WalletStatsSerializer, PaymentStatsSerializer, FraudCheckSerializer
)
from .services import (
    WalletService, PaymentProcessor, FraudDetectionService,
    IdempotencyService, PayoutService, EscrowService, WebhookService,
    EmailService
)

logger = logging.getLogger(__name__)


def wallet_locked_response(wallet):
    if not wallet.is_active:
        return Response({
            'error': 'wallet_inactive',
            'message': 'This wallet is not active'
        }, status=status.HTTP_403_FORBIDDEN)
    
    if wallet.is_locked():
        return Response({
            'error': 'wallet_locked',
            'message': 'This wallet is temporarily locked',
            'locked_until': wallet.locked_until.isoformat() if wallet.locked_until else None
        }, status=status.HTTP_403_FORBIDDEN)
    
    return None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_wallet(request):
    wallet = WalletService.get_or_create_wallet(request.user)
    serializer = WalletSerializer(wallet)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_wallet_stats(request):
    wallet = WalletService.get_or_create_wallet(request.user)
    
    stats = {
        'total_balance': float(wallet.balance),
        'held_balance': float(wallet.held_balance),
        'available_balance': float(wallet.available_balance),
        'total_deposited': float(wallet.total_deposited),
        'total_spent': float(wallet.total_spent),
        'total_refunded': float(wallet.total_refunded),
        'total_withdrawn': float(wallet.total_withdrawn),
        'is_locked': wallet.is_locked(),
        'currency': wallet.currency
    }
    
    return Response(stats)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_transactions(request):
    wallet = WalletService.get_or_create_wallet(request.user)
    transactions = Transaction.objects.filter(wallet=wallet).order_by('-created_at')

    transaction_type = request.GET.get('type')
    if transaction_type:
        transactions = transactions.filter(type=transaction_type)
    
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
def deposit(request):
    wallet = WalletService.get_or_create_wallet(request.user)

    locked_response = wallet_locked_response(wallet)
    if locked_response:
        return locked_response

    idempotency_key = request.headers.get('Idempotency-Key')
    if idempotency_key:
        cached = IdempotencyService.check_idempotency_key(idempotency_key, request.user)
        if cached and cached != 'processing':
            return Response({
                'message': 'already_processed',
                'transaction_id': cached
            })

    serializer = DepositSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    amount = serializer.validated_data['amount']
    payment_method_id = serializer.validated_data.get('payment_method_id')

    fraud_check = FraudDetectionService.check_transaction(
        user=request.user,
        amount=amount,
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', '')
    )

    if fraud_check['is_blocked']:
        wallet.register_failed_attempt()
        FraudCheck.objects.create(
            user=request.user,
            risk_score=fraud_check['risk_score'],
            risk_level=fraud_check['risk_level'],
            flags=fraud_check['flags'],
            is_blocked=True,
            requires_review=fraud_check['requires_review']
        )
        return Response({
            'error': 'transaction_blocked',
            'message': 'Transaction blocked by fraud detection system'
        }, status=status.HTTP_403_FORBIDDEN)

    try:
        payment_method = PaymentMethod.objects.get(id=payment_method_id, user=request.user, is_active=True)
    except PaymentMethod.DoesNotExist:
        return Response({
            'error': 'payment_method_not_found',
            'message': 'Payment method not found'
        }, status=status.HTTP_404_NOT_FOUND)

    if payment_method.is_expired():
        return Response({
            'error': 'card_expired',
            'message': 'Your card has expired. Please use a different card.'
        }, status=status.HTTP_400_BAD_REQUEST)

    result = PaymentProcessor.create_stripe_payment_intent(
        amount=amount,
        payment_method_id=payment_method.provider_method_id,
        metadata={
            'user_id': str(request.user.id),
            'wallet_id': str(wallet.id),
            'payment_method_id': str(payment_method.id)
        }
    )

    if not result['success']:
        wallet.register_failed_attempt()
        error_text = result.get('error', '').lower()
        
        if 'insufficient_funds' in error_text:
            error_code = 'insufficient_funds'
        elif 'expired' in error_text:
            error_code = 'card_expired'
        elif 'declined' in error_text:
            error_code = 'card_declined'
        else:
            error_code = 'payment_failed'
        
        return Response({
            'error': error_code,
            'message': result['error']
        }, status=status.HTTP_400_BAD_REQUEST)

    transaction_obj = Transaction.objects.create(
        transaction_id=result['intent_id'],
        user=request.user,
        wallet=wallet,
        amount=amount,
        type='deposit',
        status='pending',
        payment_method='stripe',
        description=f'Deposit of ${amount} via Stripe',
        metadata={
            'client_secret': result['client_secret'],
            'payment_method_id': str(payment_method.id)
        },
        balance_before=wallet.balance,
        balance_after=wallet.balance,
        held_before=wallet.held_balance,
        held_after=wallet.held_balance
    )

    if fraud_check['requires_review']:
        FraudCheck.objects.create(
            transaction=transaction_obj,
            user=request.user,
            risk_score=fraud_check['risk_score'],
            risk_level=fraud_check['risk_level'],
            flags=fraud_check['flags'],
            requires_review=True
        )

    if idempotency_key:
        IdempotencyService.mark_completed(idempotency_key, request.user, str(transaction_obj.id))

    return Response({
        'success': True,
        'client_secret': result['client_secret'],
        'transaction_id': str(transaction_obj.id),
        'amount': float(amount)
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirm_deposit(request):
    serializer = DepositConfirmSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    payment_intent_id = serializer.validated_data['payment_intent_id']

    transaction_obj = get_object_or_404(Transaction, transaction_id=payment_intent_id, user=request.user)

    if transaction_obj.status == 'completed':
        return Response({
            'success': True,
            'message': 'already_completed',
            'transaction_id': str(transaction_obj.id),
            'amount': float(transaction_obj.amount),
            'new_balance': float(transaction_obj.wallet.balance)
        })

    result = PaymentProcessor.confirm_stripe_payment(payment_intent_id)

    if not result['success']:
        transaction_obj.fail(result['error'])
        return Response({
            'success': False,
            'error': 'payment_confirmation_failed',
            'message': result['error']
        }, status=status.HTTP_400_BAD_REQUEST)

    with db_transaction.atomic():
        wallet = transaction_obj.wallet
        wallet.balance += transaction_obj.amount
        wallet.total_deposited += transaction_obj.amount
        wallet.unlock()

        transaction_obj.status = 'completed'
        transaction_obj.completed_at = timezone.now()
        transaction_obj.balance_after = wallet.balance
        transaction_obj.provider_response = result.get('intent', {})
        transaction_obj.save()

    try:
        EmailService.send_deposit_confirmation(
            user=request.user,
            amount=transaction_obj.amount,
            transaction_id=transaction_obj.transaction_id
        )
    except Exception as e:
        logger.error(f"Failed to send deposit confirmation email: {e}")

    return Response({
        'success': True,
        'message': 'deposit_completed',
        'transaction_id': str(transaction_obj.id),
        'amount': float(transaction_obj.amount),
        'new_balance': float(wallet.balance)
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_withdrawal(request):
    wallet = WalletService.get_or_create_wallet(request.user)

    locked_response = wallet_locked_response(wallet)
    if locked_response:
        return locked_response

    idempotency_key = request.headers.get('Idempotency-Key')
    if idempotency_key:
        cached = IdempotencyService.check_idempotency_key(idempotency_key, request.user)
        if cached and cached != 'processing':
            return Response({
                'message': 'already_processed',
                'transaction_id': cached
            })

    serializer = WithdrawSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    amount = serializer.validated_data['amount']
    payment_method = serializer.validated_data['payment_method']
    account_details = serializer.validated_data['account_details']

    if payment_method not in ['paypal', 'bank']:
        return Response({
            'error': 'unsupported_payment_method',
            'message': 'Only PayPal and bank transfers are supported for withdrawals'
        }, status=status.HTTP_400_BAD_REQUEST)

    if amount < Decimal('10.00'):
        return Response({
            'error': 'minimum_withdrawal',
            'message': 'Minimum withdrawal amount is $10.00'
        }, status=status.HTTP_400_BAD_REQUEST)

    if not wallet.has_sufficient_available_balance(amount):
        return Response({
            'error': 'insufficient_balance',
            'message': f'Insufficient available balance. Available: ${wallet.available_balance}'
        }, status=status.HTTP_400_BAD_REQUEST)

    if payment_method == 'paypal':
        paypal_email = account_details.get('email')
        if not paypal_email:
            return Response({
                'error': 'paypal_email_required',
                'message': 'PayPal email is required'
            }, status=status.HTTP_400_BAD_REQUEST)

    if wallet.is_locked():
        return Response({
            'error': 'wallet_locked',
            'message': 'Your wallet is locked. Please try again later.'
        }, status=status.HTTP_403_FORBIDDEN)

    try:
        with db_transaction.atomic():
            transaction_obj = WalletService.debit(
                wallet=wallet,
                amount=amount,
                transaction_type='withdrawal',
                description=f'Withdrawal via {payment_method}',
                payment_method=payment_method,
                metadata={'account_details': account_details}
            )

            payout = Payout.objects.create(
                user=request.user,
                transaction=transaction_obj,
                amount=amount,
                payment_method=payment_method,
                account_details=account_details,
                status='pending'
            )

            if payment_method == 'paypal':
                try:
                    payout_result = PaymentProcessor.create_paypal_payout(
                        email=account_details.get('email'),
                        amount=amount,
                        note=f'Withdrawal for order payments',
                        payout_id=payout.payout_id
                    )
                    
                    if payout_result['success']:
                        payout.status = 'processing'
                        payout.provider_payout_id = payout_result.get('payout_id')
                        payout.provider_response = payout_result
                        payout.save()
                    else:
                        payout.fail(payout_result.get('error', 'Unknown PayPal error'))
                        transaction_obj.status = 'failed'
                        transaction_obj.metadata['failure_reason'] = payout_result.get('error')
                        transaction_obj.save()
                        raise Exception(payout_result.get('error', 'PayPal withdrawal failed'))
                        
                except Exception as e:
                    logger.error(f"PayPal payout failed: {e}")
                    payout.fail(str(e))
                    transaction_obj.status = 'failed'
                    transaction_obj.metadata['failure_reason'] = str(e)
                    transaction_obj.save()
                    raise

            if idempotency_key:
                IdempotencyService.mark_completed(idempotency_key, request.user, str(transaction_obj.id))

            try:
                EmailService.send_withdrawal_request(
                    user=request.user,
                    amount=amount,
                    payout_id=payout.payout_id,
                    payment_method=payment_method
                )
            except Exception as e:
                logger.error(f"Failed to send withdrawal email: {e}")

        return Response({
            'success': True,
            'message': 'withdrawal_requested',
            'transaction_id': str(transaction_obj.id),
            'payout_id': payout.payout_id,
            'amount': float(amount),
            'status': payout.status,
            'new_balance': float(wallet.balance)
        })

    except ValueError as e:
        return Response({
            'error': 'withdrawal_failed',
            'message': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Withdrawal error: {e}")
        return Response({
            'error': 'withdrawal_failed',
            'message': 'An unexpected error occurred. Please try again.'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_withdrawal_status(request, payout_id):
    payout = get_object_or_404(Payout, payout_id=payout_id, user=request.user)
    serializer = PayoutSerializer(payout)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def hold_funds(request):
    order_id = request.data.get('order_id')
    amount = Decimal(str(request.data.get('amount', 0)))

    if not order_id:
        return Response({
            'error': 'order_id_required',
            'message': 'Order ID is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    if amount <= 0:
        return Response({
            'error': 'invalid_amount',
            'message': 'Amount must be greater than 0'
        }, status=status.HTTP_400_BAD_REQUEST)

    wallet = request.user.wallet

    if not wallet.has_sufficient_available_balance(amount):
        return Response({
            'error': 'insufficient_balance',
            'message': f'Insufficient available balance. Available: ${wallet.available_balance}'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        with db_transaction.atomic():
            transaction_obj = WalletService.debit(
                wallet=wallet,
                amount=amount,
                transaction_type='hold',
                description=f'Escrow hold for order',
                payment_method='wallet',
                order_id=order_id
            )

            order_payment = OrderPayment.objects.create(
                order_id=order_id,
                hold_transaction=transaction_obj,
                amount=amount,
                status='held',
                held_at=timezone.now()
            )

        return Response({
            'success': True,
            'message': 'funds_held',
            'transaction_id': str(transaction_obj.id),
            'amount': float(amount),
            'held_balance': float(wallet.held_balance),
            'available_balance': float(wallet.available_balance)
        })

    except ValueError as e:
        return Response({
            'error': 'hold_failed',
            'message': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def release_funds(request):
    order_id = request.data.get('order_id')
    amount = Decimal(str(request.data.get('amount', 0)))

    if not order_id:
        return Response({
            'error': 'order_id_required',
            'message': 'Order ID is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    order_payment = get_object_or_404(OrderPayment, order_id=order_id, status='held')

    if amount <= 0:
        return Response({
            'error': 'invalid_amount',
            'message': 'Amount must be greater than 0'
        }, status=status.HTTP_400_BAD_REQUEST)

    if amount > order_payment.amount:
        return Response({
            'error': 'invalid_amount',
            'message': f'Amount exceeds held balance. Held: ${order_payment.amount}'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        with db_transaction.atomic():
            wallet = request.user.wallet
            
            if not wallet.held_balance >= amount:
                return Response({
                    'error': 'insufficient_held_balance',
                    'message': f'Insufficient held balance. Held: ${wallet.held_balance}'
                }, status=status.HTTP_400_BAD_REQUEST)

            wallet.settle_held_funds(amount)

            release_transaction = Transaction.objects.create(
                user=request.user,
                wallet=wallet,
                amount=amount,
                type='release',
                status='completed',
                payment_method='wallet',
                description=f'Escrow release for order',
                balance_before=wallet.balance,
                balance_after=wallet.balance,
                held_before=wallet.held_balance + amount,
                held_after=wallet.held_balance
            )

            order_payment.mark_released(release_transaction)

        return Response({
            'success': True,
            'message': 'funds_released',
            'transaction_id': str(release_transaction.id),
            'amount': float(amount),
            'held_balance': float(wallet.held_balance),
            'available_balance': float(wallet.available_balance)
        })

    except ValueError as e:
        return Response({
            'error': 'release_failed',
            'message': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def refund_funds(request):
    order_id = request.data.get('order_id')
    amount = Decimal(str(request.data.get('amount', 0)))

    if not order_id:
        return Response({
            'error': 'order_id_required',
            'message': 'Order ID is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    order_payment = get_object_or_404(OrderPayment, order_id=order_id)

    if order_payment.status != 'held':
        return Response({
            'error': 'invalid_status',
            'message': f'Payment is not held. Current status: {order_payment.status}'
        }, status=status.HTTP_400_BAD_REQUEST)

    if amount <= 0:
        return Response({
            'error': 'invalid_amount',
            'message': 'Amount must be greater than 0'
        }, status=status.HTTP_400_BAD_REQUEST)

    if amount > order_payment.amount:
        return Response({
            'error': 'invalid_amount',
            'message': f'Amount exceeds held balance. Held: ${order_payment.amount}'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        with db_transaction.atomic():
            wallet = request.user.wallet
            
            if not wallet.held_balance >= amount:
                return Response({
                    'error': 'insufficient_held_balance',
                    'message': f'Insufficient held balance. Held: ${wallet.held_balance}'
                }, status=status.HTTP_400_BAD_REQUEST)

            wallet.release_held_funds(amount)
            wallet.balance += amount
            wallet.total_refunded += amount
            wallet.save()

            refund_transaction = Transaction.objects.create(
                user=request.user,
                wallet=wallet,
                amount=amount,
                type='refund',
                status='completed',
                payment_method='wallet',
                description=f'Refund for order',
                balance_before=wallet.balance - amount,
                balance_after=wallet.balance,
                held_before=wallet.held_balance + amount,
                held_after=wallet.held_balance
            )

            order_payment.mark_refunded(refund_transaction)

        return Response({
            'success': True,
            'message': 'funds_refunded',
            'transaction_id': str(refund_transaction.id),
            'amount': float(amount),
            'new_balance': float(wallet.balance),
            'held_balance': float(wallet.held_balance)
        })

    except ValueError as e:
        return Response({
            'error': 'refund_failed',
            'message': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_payment_methods(request):
    methods = PaymentMethod.objects.filter(user=request.user, is_active=True)
    serializer = PaymentMethodSerializer(methods, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_payment_method(request):
    serializer = AddPaymentMethodSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    validation = PaymentProcessor.validate_card(
        last_four=serializer.validated_data['last_four'],
        expiry_month=serializer.validated_data['expiry_month'],
        expiry_year=serializer.validated_data['expiry_year'],
        card_brand=serializer.validated_data['card_brand']
    )

    if not validation['valid']:
        return Response({
            'error': 'card_validation_failed',
            'message': validation['error']
        }, status=status.HTTP_400_BAD_REQUEST)

    method = PaymentMethod.objects.create(
        user=request.user,
        provider='stripe',
        provider_method_id=serializer.validated_data['provider_method_id'],
        last_four=serializer.validated_data['last_four'],
        card_brand=serializer.validated_data['card_brand'],
        cardholder_name=serializer.validated_data['cardholder_name'],
        expiry_month=serializer.validated_data['expiry_month'],
        expiry_year=serializer.validated_data['expiry_year']
    )

    if not PaymentMethod.objects.filter(user=request.user, is_default=True).exists():
        method.is_default = True
        method.save()

    return Response(PaymentMethodSerializer(method).data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_payment_method(request, method_id):
    method = get_object_or_404(PaymentMethod, id=method_id, user=request.user)
    method.is_active = False
    method.save()

    if method.is_default:
        next_method = PaymentMethod.objects.filter(user=request.user, is_active=True).first()
        if next_method:
            next_method.is_default = True
            next_method.save()

    return Response({
        'success': True,
        'message': 'payment_method_removed'
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
        'message': 'default_payment_method_updated'
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_order_payment(request, order_id):
    payment = get_object_or_404(
        OrderPayment.objects.filter(
            Q(order__student=request.user) | Q(order__writer=request.user)
        ),
        order_id=order_id
    )
    serializer = OrderPaymentSerializer(payment)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_order_payment_status(request, order_id):
    payment = get_object_or_404(
        OrderPayment.objects.filter(
            Q(order__student=request.user) | Q(order__writer=request.user)
        ),
        order_id=order_id
    )
    
    return Response({
        'status': payment.status,
        'amount': float(payment.amount),
        'held_at': payment.held_at.isoformat() if payment.held_at else None,
        'released_at': payment.released_at.isoformat() if payment.released_at else None,
        'auto_release_at': payment.auto_release_at.isoformat() if payment.auto_release_at else None
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_payment_intent(request, intent_id):
    intent = get_object_or_404(PaymentIntent, intent_id=intent_id, user=request.user)
    serializer = PaymentIntentSerializer(intent)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def retry_payment(request, intent_id):
    intent = get_object_or_404(PaymentIntent, intent_id=intent_id, user=request.user, status='failed')

    result = PaymentProcessor.create_stripe_payment_intent(
        amount=intent.amount,
        metadata={
            'user_id': str(request.user.id),
            'original_intent_id': intent_id
        }
    )

    if not result['success']:
        return Response({
            'error': 'payment_retry_failed',
            'message': result['error']
        }, status=status.HTTP_400_BAD_REQUEST)

    new_intent = PaymentIntent.objects.create(
        intent_id=result['intent_id'],
        user=request.user,
        amount=intent.amount,
        client_secret=result['client_secret']
    )

    return Response({
        'success': True,
        'intent_id': new_intent.intent_id,
        'client_secret': new_intent.client_secret
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_payment_intent(request, intent_id):
    intent = get_object_or_404(PaymentIntent, intent_id=intent_id, user=request.user)
    
    if intent.status in ['succeeded', 'failed']:
        return Response({
            'error': 'cannot_cancel',
            'message': f'Cannot cancel payment intent with status: {intent.status}'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    intent.status = 'cancelled'
    intent.save()
    
    return Response({
        'success': True,
        'message': 'payment_intent_cancelled'
    })


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


@api_view(['POST'])
@permission_classes([IsAdminUser])
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    result = WebhookService.process_stripe_webhook(payload, sig_header)
    
    if result['success']:
        return Response({'status': 'success'})
    else:
        return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def paypal_webhook(request):
    payload = request.body
    
    result = WebhookService.process_paypal_webhook(payload)
    
    if result['success']:
        return Response({'status': 'success'})
    else:
        return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def fraud_check(request):
    amount = Decimal(str(request.data.get('amount', 0)))
    
    result = FraudDetectionService.check_transaction(
        user=request.user,
        amount=amount,
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', '')
    )
    
    return Response(result)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def review_fraud(request, fraud_id):
    fraud_check = get_object_or_404(FraudCheck, id=fraud_id, requires_review=True)
    
    action = request.data.get('action')
    notes = request.data.get('notes', '')
    
    if action not in ['approve', 'block']:
        return Response({
            'error': 'invalid_action',
            'message': 'Action must be "approve" or "block"'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    fraud_check.reviewed_by = request.user
    fraud_check.reviewed_at = timezone.now()
    fraud_check.review_notes = notes
    fraud_check.requires_review = False
    
    if action == 'block':
        fraud_check.is_blocked = True
    
    fraud_check.save()
    
    return Response({
        'success': True,
        'message': f'fraud_check_{action}ed'
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_payment_stats(request):
    from django.db.models import Sum, Count, Avg
    
    total_deposits = Transaction.objects.filter(type='deposit', status='completed').aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    
    total_withdrawals = Transaction.objects.filter(type='withdrawal', status='completed').aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    
    total_payouts = Transaction.objects.filter(type='payout', status='completed').aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    
    total_refunds = Transaction.objects.filter(type='refund', status='completed').aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    
    total_users = Wallet.objects.filter(is_active=True).count()
    
    total_balance = Wallet.objects.aggregate(
        total=Sum('balance')
    )['total'] or Decimal('0.00')
    
    total_held = Wallet.objects.aggregate(
        total=Sum('held_balance')
    )['total'] or Decimal('0.00')
    
    stats = {
        'total_deposits': float(total_deposits),
        'total_withdrawals': float(total_withdrawals),
        'total_payouts': float(total_payouts),
        'total_refunds': float(total_refunds),
        'total_balance': float(total_balance),
        'total_held': float(total_held),
        'total_users': total_users,
        'currency': 'USD'
    }
    
    return Response(stats)