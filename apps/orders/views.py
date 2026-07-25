from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
from apps.payments.services import WalletService
from .models import Order, OrderHistory, Attachment
from .serializers import (
    OrderSerializer, OrderListSerializer, OrderCreateSerializer,
    OrderHistorySerializer, AttachmentSerializer, PriceQuoteSerializer,
    RevisionRequestSerializer, RefundRequestSerializer, RatingSerializer
)


def log_history(order, user, action, from_status, to_status, data=None):
    OrderHistory.objects.create(
        order=order,
        user=user,
        action=action,
        from_status=from_status,
        to_status=to_status,
        data=data or {}
    )


def is_owner(order, user):
    return order.student_id == user.id


def is_assigned_writer(order, user):
    return order.writer_id == user.id


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def price_quote(request):
    academic_level = request.data.get('academic_level')
    words = request.data.get('words')
    pages = request.data.get('pages')
    spacing = request.data.get('spacing', 'double')
    deadline = request.data.get('deadline')

    if not academic_level or not deadline:
        return Response(
            {'error': 'academic_level and deadline are required'}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    if not words and not pages:
        return Response(
            {'error': 'Either words or pages must be provided'}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    if pages and not words:
        words = Order.pages_to_words(pages, spacing)
    elif words and not pages:
        pages = Order.words_to_pages(words, spacing)

    price_data = Order.calculate_price(
        academic_level,
        words,
        spacing,
        deadline
    )

    return Response({
        'pages': float(price_data['pages']),
        'words': words,
        'words_per_page': price_data['words_per_page'],
        'cost_per_page': float(price_data['cost_per_page']),
        'base_price': float(price_data['base_price']),
        'level_multiplier': float(price_data['level_multiplier']),
        'level_adjusted': float(price_data['level_adjusted']),
        'urgency_multiplier': float(price_data['urgency_multiplier']),
        'total_price': float(price_data['total_price'])
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    serializer = OrderCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    
    words = data.get('words')
    pages = data.get('pages')
    spacing = data.get('spacing', 'double')
    
    if not words and not pages:
        return Response(
            {'error': 'Either words or pages must be provided'}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    if pages and not words:
        words = Order.pages_to_words(pages, spacing)
    elif words and not pages:
        pages = Order.words_to_pages(words, spacing)

    price_data = Order.calculate_price(
        data['academic_level'],
        words,
        spacing,
        data['deadline']
    )

    wallet = request.user.wallet

    try:
        WalletService.debit(
            wallet=wallet,
            amount=price_data['total_price'],
            transaction_type='escrow_hold',
            description='Order payment held in escrow'
        )
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    order = Order.objects.create(
        student=request.user,
        academic_level=data['academic_level'],
        paper_type=data['paper_type'],
        subject=data['subject'],
        topic=data['topic'],
        instructions=data['instructions'],
        pages=price_data['pages'],
        words=words,
        spacing=spacing,
        slides=data.get('slides'),
        sources_count=data.get('sources_count', 0),
        deadline=data['deadline'],
        format=data['format'],
        links=data.get('links', []),
        base_price=price_data['base_price'],
        level_multiplier=price_data['level_multiplier'],
        level_adjusted=price_data['level_adjusted'],
        urgency_multiplier=price_data['urgency_multiplier'],
        total_price=price_data['total_price'],
        status='request'
    )

    log_history(order, request.user, 'create', None, 'request', {
        'total_price': str(price_data['total_price']),
        'pages': float(price_data['pages']),
        'words': words,
        'spacing': spacing
    })

    return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_orders(request):
    status_filter = request.GET.get('status')
    orders = Order.objects.filter(student=request.user).order_by('-created_at')

    if status_filter and status_filter in dict(Order.STATUS_CHOICES):
        orders = orders.filter(status=status_filter)

    serializer = OrderListSerializer(orders, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def assigned_orders(request):
    status_filter = request.GET.get('status')
    orders = Order.objects.filter(writer=request.user).order_by('deadline')

    if status_filter and status_filter in dict(Order.STATUS_CHOICES):
        orders = orders.filter(status=status_filter)

    serializer = OrderListSerializer(orders, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def available_orders(request):
    orders = Order.objects.filter(status='request', writer__isnull=True).order_by('deadline')
    serializer = OrderListSerializer(orders, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    if not (is_owner(order, request.user) or is_assigned_writer(order, request.user)):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    serializer = OrderSerializer(order)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_history(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    if not (is_owner(order, request.user) or is_assigned_writer(order, request.user)):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    history = OrderHistory.objects.filter(order=order).order_by('-created_at')
    serializer = OrderHistorySerializer(history, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def accept_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, status='request', writer__isnull=True)

    order.writer = request.user
    order.status = 'in_progress'
    order.accepted_at = timezone.now()
    order.started_at = timezone.now()
    order.save()

    log_history(order, request.user, 'accept', 'request', 'in_progress')

    return Response(OrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, status='request')
    reason = request.data.get('reason', '')

    order.status = 'cancelled'
    order.cancelled_at = timezone.now()
    order.cancelled_by = request.user
    order.cancellation_reason = reason
    order.save()

    WalletService.credit(
        wallet=order.student.wallet,
        amount=order.total_price,
        transaction_type='refund',
        description=f'Refund for rejected order {order.order_number}',
        order=order
    )

    log_history(order, request.user, 'reject', 'request', 'cancelled', {'reason': reason})

    return Response({'message': 'Order rejected and refunded'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user, status='request')
    reason = request.data.get('reason', '')

    order.status = 'cancelled'
    order.cancelled_at = timezone.now()
    order.cancelled_by = request.user
    order.cancellation_reason = reason
    order.save()

    WalletService.credit(
        wallet=order.student.wallet,
        amount=order.total_price,
        transaction_type='refund',
        description=f'Refund for cancelled order {order.order_number}',
        order=order
    )

    log_history(order, request.user, 'cancel', 'request', 'cancelled', {'reason': reason})

    return Response({'message': 'Order cancelled and refunded'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_attachment(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    if not (is_owner(order, request.user) or is_assigned_writer(order, request.user)):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    serializer = AttachmentSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    attachment = serializer.save(uploaded_by=request.user)
    order.attachments.add(attachment)

    return Response(AttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_attachments(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    if not (is_owner(order, request.user) or is_assigned_writer(order, request.user)):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    serializer = AttachmentSerializer(order.attachments.all().order_by('-uploaded_at'), many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def deliver_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, status='in_progress')

    if not is_assigned_writer(order, request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    attachment_id = request.data.get('attachment_id')
    attachment = get_object_or_404(Attachment, id=attachment_id) if attachment_id else None

    order.status = 'awaiting_approval'
    order.delivered_at = timezone.now()
    order.delivered_file = attachment
    order.auto_approve_at = timezone.now() + timedelta(hours=Order.REVISION_WINDOW_HOURS)
    order.save()

    log_history(order, request.user, 'deliver', 'in_progress', 'awaiting_approval')

    return Response(OrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user, status='awaiting_approval')

    order.status = 'completed'
    order.completed_at = timezone.now()
    order.escrow_released_at = timezone.now()
    order.save()

    if order.writer:
        WalletService.credit(
            wallet=order.writer.wallet,
            amount=order.total_price,
            transaction_type='payout',
            description=f'Payment for order {order.order_number}',
            order=order
        )

    log_history(order, request.user, 'complete', 'awaiting_approval', 'completed')

    return Response(OrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_revision(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user, status='awaiting_approval')

    serializer = RevisionRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    order.status = 'in_progress'
    order.revision_count += 1
    order.last_revision_requested_at = timezone.now()
    order.auto_approve_at = None
    order.save()

    log_history(
        order, request.user, 'revise', 'awaiting_approval', 'in_progress',
        {'notes': serializer.validated_data.get('notes', '')}
    )

    return Response(OrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_refund(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)

    if order.status not in ['awaiting_approval', 'completed']:
        return Response({'error': 'Order is not eligible for a refund'}, status=status.HTTP_400_BAD_REQUEST)

    serializer = RefundRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    from_status = order.status
    order.status = 'refund_pending'
    order.refund_reason = serializer.validated_data['reason']
    order.save()

    log_history(
        order, request.user, 'refund_request', from_status, 'refund_pending',
        {'reason': order.refund_reason}
    )

    return Response(OrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def rate_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user, status='completed')

    serializer = RatingSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    order.rating = serializer.validated_data['rating']
    order.feedback = serializer.validated_data.get('feedback', '')
    order.save()

    return Response(OrderSerializer(order).data)


def process_auto_approvals():
    now = timezone.now()
    due_orders = Order.objects.filter(status='awaiting_approval', auto_approve_at__lte=now)

    for order in due_orders:
        order.status = 'completed'
        order.completed_at = now
        order.escrow_released_at = now
        order.save()

        if order.writer:
            WalletService.credit(
                wallet=order.writer.wallet,
                amount=order.total_price,
                transaction_type='payout',
                description=f'Payment for order {order.order_number}',
                order=order
            )

        log_history(order, None, 'auto_approve', 'awaiting_approval', 'completed')