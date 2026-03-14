from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import Wallet, Transaction, PaymentMethod, PaymentIntent, OrderPayment, FraudCheck
from .serializers import (
    WalletSerializer, TransactionSerializer, DepositSerializer,
    WithdrawSerializer, PaymentMethodSerializer, PaymentIntentSerializer,
    OrderPaymentSerializer, FraudCheckSerializer
)
from .services import WalletService, PaymentProcessor, FraudDetectionService, IdempotencyService

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_wallet(request):
    wallet = WalletService.get_or_create_wallet(request.user)
    serializer = WalletSerializer(wallet)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_transactions(request):
    wallet = WalletService.get_or_create_wallet(request.user)
    transactions = Transaction.objects.filter(wallet=wallet).order_by('-created_at')
    
    transaction_type = request.GET.get('type')
    if transaction_type:
        transactions = transactions.filter(type=transaction_type)
    
    serializer = TransactionSerializer(transactions, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def deposit(request):
    idempotency_key = request.headers.get('Idempotency-Key')
    if idempotency_key:
        cached = IdempotencyService.check_idempotency_key(idempotency_key, request.user)
        if cached and cached != 'processing':
            return Response({'transaction_id': cached, 'status': 'already_processed'})
    
    serializer = DepositSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    wallet = WalletService.get_or_create_wallet(request.user)
    amount = serializer.validated_data['amount']
    payment_method_id = serializer.validated_data.get('payment_method_id')
    
    fraud_check = FraudDetectionService.check_transaction(
        user=request.user,
        amount=amount,
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', '')
    )
    
    if fraud_check['is_blocked']:
        FraudCheck.objects.create(
            transaction=None,
            risk_score=fraud_check['risk_score'],
            risk_level=fraud_check['risk_level'],
            flags=fraud_check['flags'],
            is_blocked=True,
            requires_review=fraud_check['requires_review']
        )
        return Response({'error': 'transaction blocked by fraud detection'}, status=status.HTTP_403_FORBIDDEN)
    
    if serializer.validated_data['payment_method'] == 'stripe':
        try:
            payment_method = PaymentMethod.objects.get(id=payment_method_id, user=request.user)
            
            if payment_method.is_expired():
                return Response({
                    'error': 'card_expired',
                    'message': 'Your card has expired. Please use a different card.'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except PaymentMethod.DoesNotExist:
            return Response({'error': 'payment method not found'}, status=status.HTTP_404_NOT_FOUND)
        
        result = PaymentProcessor.create_stripe_payment_intent(
            amount=amount,
            payment_method_id=payment_method.provider_method_id,
            metadata={
                'user_id': str(request.user.id),
                'wallet_id': str(wallet.id),
                'payment_method_id': str(payment_method.id),
                'idempotency_key': idempotency_key
            }
        )
        
        if not result['success']:
            if 'insufficient_funds' in result.get('error', '').lower():
                return Response({
                    'error': 'insufficient_funds',
                    'message': 'Insufficient funds on card',
                    'details': result['error']
                }, status=status.HTTP_400_BAD_REQUEST)
            elif 'expired' in result.get('error', '').lower():
                return Response({
                    'error': 'card_expired',
                    'message': 'Your card has expired',
                    'details': result['error']
                }, status=status.HTTP_400_BAD_REQUEST)
            elif 'declined' in result.get('error', '').lower():
                return Response({
                    'error': 'card_declined',
                    'message': 'Your card was declined',
                    'details': result['error']
                }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    'error': 'payment_failed',
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
            description=f'Stripe deposit ${amount}',
            metadata={
                'client_secret': result['client_secret'],
                'payment_method_id': str(payment_method.id)
            },
            balance_before=wallet.balance,
            balance_after=wallet.balance
        )
        
        if fraud_check['requires_review']:
            FraudCheck.objects.create(
                transaction=transaction_obj,
                risk_score=fraud_check['risk_score'],
                risk_level=fraud_check['risk_level'],
                flags=fraud_check['flags'],
                requires_review=True
            )
        
        return Response({
            'success': True,
            'client_secret': result['client_secret'],
            'transaction_id': str(transaction_obj.id),
            'amount': amount
        })
    
    return Response({'error': 'payment method not supported'}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirm_deposit(request):
    payment_intent_id = request.data.get('payment_intent_id')
    
    if not payment_intent_id:
        return Response({'error': 'payment_intent_id required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        transaction_obj = Transaction.objects.get(transaction_id=payment_intent_id, user=request.user)
    except Transaction.DoesNotExist:
        return Response({'error': 'transaction not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if transaction_obj.status == 'completed':
        return Response({
            'success': True,
            'message': 'already completed',
            'transaction_id': str(transaction_obj.id),
            'amount': float(transaction_obj.amount),
            'new_balance': float(transaction_obj.wallet.balance)
        })
    
    result = PaymentProcessor.confirm_stripe_payment(payment_intent_id)
    
    if not result['success']:
        transaction_obj.fail(result['error'])
        return Response({
            'success': False,
            'error': result['error']
        }, status=status.HTTP_400_BAD_REQUEST)
    
    from django.db import transaction as db_transaction
    with db_transaction.atomic():
        wallet = transaction_obj.wallet
        wallet.balance += transaction_obj.amount
        wallet.total_deposited += transaction_obj.amount
        wallet.save()
        
        transaction_obj.status = 'completed'
        transaction_obj.completed_at = timezone.now()
        transaction_obj.balance_after = wallet.balance
        transaction_obj.provider_response = result.get('intent', {})
        transaction_obj.save()
        
        from .services import EmailService
        EmailService.send_deposit_confirmation(
            user=request.user,
            amount=transaction_obj.amount,
            transaction_id=transaction_obj.transaction_id
        )
    
    return Response({
        'success': True,
        'message': 'deposit completed successfully',
        'transaction_id': str(transaction_obj.id),
        'amount': float(transaction_obj.amount),
        'new_balance': float(wallet.balance)
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def withdraw(request):
    idempotency_key = request.headers.get('Idempotency-Key')
    if idempotency_key:
        cached = IdempotencyService.check_idempotency_key(idempotency_key, request.user)
        if cached and cached != 'processing':
            return Response({'transaction_id': cached, 'status': 'already_processed'})
    
    serializer = WithdrawSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    wallet = WalletService.get_or_create_wallet(request.user)
    
    try:
        with transaction.atomic():
            transaction_obj = WalletService.debit(
                wallet=wallet,
                amount=serializer.validated_data['amount'],
                transaction_type='withdrawal',
                description='funds withdrawal',
                metadata={
                    'payment_method': serializer.validated_data['payment_method'],
                    'account_details': serializer.validated_data['account_details']
                }
            )
            
            if idempotency_key:
                IdempotencyService.mark_completed(idempotency_key, request.user, str(transaction_obj.id))
            
            return Response({
                'message': 'withdrawal initiated',
                'transaction': TransactionSerializer(transaction_obj).data
            })
            
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_payment_methods(request):
    methods = PaymentMethod.objects.filter(user=request.user, is_active=True)
    serializer = PaymentMethodSerializer(methods, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_payment_method(request):
    from .serializers import AddPaymentMethodSerializer
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
        return Response({'error': validation['error']}, status=status.HTTP_400_BAD_REQUEST)
    
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
    
    return Response({'message': 'payment method removed'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_default_payment_method(request, method_id):
    method = get_object_or_404(PaymentMethod, id=method_id, user=request.user, is_active=True)
    
    PaymentMethod.objects.filter(user=request.user, is_default=True).update(is_default=False)
    
    method.is_default = True
    method.save()
    
    return Response({'message': 'default payment method updated'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_order_payments(request, order_id):
    payments = OrderPayment.objects.filter(order_id=order_id, order__student=request.user)
    serializer = OrderPaymentSerializer(payments, many=True)
    return Response(serializer.data)

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
        return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)
    
    new_intent = PaymentIntent.objects.create(
        intent_id=result['intent_id'],
        user=request.user,
        amount=intent.amount,
        client_secret=result['client_secret']
    )
    
    return Response({
        'intent_id': new_intent.intent_id,
        'client_secret': new_intent.client_secret
    })