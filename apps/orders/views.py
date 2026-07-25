from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from apps.payments.services import WalletService
from .models import Order, OrderHistory, Attachment, OrderTimeline, UserPresence
from .serializers import (
    OrderSerializer, OrderListSerializer, OrderCreateSerializer,
    OrderHistorySerializer, AttachmentSerializer,
    RevisionRequestSerializer, RefundRequestSerializer, RatingSerializer,
    CancelOrderSerializer, DeclineOrderSerializer, ResubmitOrderSerializer
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


def create_timeline(order, status, title, description='', icon='', color='gray'):
    OrderTimeline.objects.create(
        order=order,
        status=status,
        title=title,
        description=description,
        icon=icon,
        color=color
    )


def is_owner(order, user):
    return order.student_id == user.id


def is_assigned_writer(order, user):
    return order.writer_id == user.id


def sanitize_links(links):
    if not links:
        return []
    
    sanitized = []
    dangerous_protocols = ['javascript:', 'data:', 'vbscript:', 'file:']
    
    for link in links:
        if isinstance(link, dict):
            url = link.get('url', '')
            for protocol in dangerous_protocols:
                if url.lower().startswith(protocol):
                    url = ''
                    break
            url = url.replace('<', '&lt;').replace('>', '&gt;')
            link['url'] = url
            sanitized.append(link)
        elif isinstance(link, str):
            for protocol in dangerous_protocols:
                if link.lower().startswith(protocol):
                    link = ''
                    break
            link = link.replace('<', '&lt;').replace('>', '&gt;')
            sanitized.append({'url': link, 'title': ''})
    
    return sanitized


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def price_quote(request):
    academic_level = request.data.get('academic_level')
    words = request.data.get('words')
    pages = request.data.get('pages')
    spacing = request.data.get('spacing', 'double')
    deadline = request.data.get('deadline')
    slides = request.data.get('slides')
    paper_type = request.data.get('paper_type')

    if not academic_level or not deadline:
        return Response(
            {'error': 'academic_level and deadline are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        if paper_type == 'presentation':
            if not slides or int(slides) < 1:
                return Response(
                    {'error': 'Number of slides is required for presentations'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            words = int(slides) * 50
        else:
            if not words and not pages:
                return Response(
                    {'error': 'Either words or pages must be provided'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if pages:
                pages = Decimal(str(pages))
                if not words:
                    words = Order.pages_to_words(pages, spacing)
                else:
                    words = int(words)
            elif words:
                words = int(words)
                pages = Order.words_to_pages(words, spacing)
    except (ValueError, TypeError, Decimal.InvalidOperation) as e:
        return Response(
            {'error': f'Invalid input: {str(e)}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        if isinstance(deadline, str):
            if 'T' in deadline:
                deadline_str = deadline.replace('T', ' ')
                if '.' in deadline_str:
                    deadline_str = deadline_str.split('.')[0]
                deadline_dt = timezone.datetime.strptime(deadline_str, '%Y-%m-%d %H:%M')
                if timezone.is_naive(deadline_dt):
                    deadline_dt = timezone.make_aware(deadline_dt)
            else:
                deadline_dt = timezone.datetime.fromisoformat(deadline.replace('Z', '+00:00'))
        else:
            deadline_dt = deadline
            
        if timezone.is_naive(deadline_dt):
            deadline_dt = timezone.make_aware(deadline_dt)
            
        deadline_utc = deadline_dt.astimezone(dt_timezone.utc)
        now_utc = timezone.now()
        
        if deadline_utc < now_utc + timedelta(hours=12):
            return Response(
                {'error': 'Deadline must be at least 12 hours from now'},
                status=status.HTTP_400_BAD_REQUEST
            )
    except (ValueError, AttributeError) as e:
        return Response(
            {'error': f'Invalid deadline format: {str(e)}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    price_data = Order.calculate_price(
        academic_level,
        words,
        spacing,
        deadline_utc,
        int(slides) if slides else None,
        paper_type
    )

    response_data = {
        'pages': float(price_data.get('pages', 0)),
        'words': int(words),
        'words_per_page': price_data.get('words_per_page', 0),
        'cost_per_page': float(price_data.get('cost_per_page', 0)),
        'base_price': float(price_data['base_price']),
        'level_multiplier': float(price_data['level_multiplier']),
        'level_adjusted': float(price_data['level_adjusted']),
        'urgency_multiplier': float(price_data['urgency_multiplier']),
        'total_price': float(price_data['total_price'])
    }

    if price_data.get('slides'):
        response_data['slides'] = price_data['slides']

    return Response(response_data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    serializer = OrderCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data

    if data['paper_type'] == 'presentation':
        if not data.get('slides'):
            return Response(
                {'slides': 'Number of slides is required for presentations'},
                status=status.HTTP_400_BAD_REQUEST
            )
        words = data['slides'] * 50
        pages = None
        spacing = 'double'
    else:
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

    if data['deadline'] < timezone.now() + timedelta(hours=12):
        return Response(
            {'deadline': 'Deadline must be at least 12 hours from now'},
            status=status.HTTP_400_BAD_REQUEST
        )

    price_data = Order.calculate_price(
        data['academic_level'],
        words,
        spacing if data['paper_type'] != 'presentation' else 'double',
        data['deadline'],
        data.get('slides') if data['paper_type'] == 'presentation' else None,
        data['paper_type']
    )

    wallet = request.user.wallet
    try:
        WalletService.debit(
            wallet=wallet,
            amount=price_data['total_price'],
            transaction_type='escrow_hold',
            description=f'Order payment held in escrow for {data["topic"][:50]}'
        )
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    links = data.get('links', [])
    sanitized_links = sanitize_links(links)

    order = Order.objects.create(
        student=request.user,
        academic_level=data['academic_level'],
        paper_type=data['paper_type'],
        subject=data['subject'],
        topic=data['topic'],
        instructions=data['instructions'],
        pages=pages,
        words=words,
        spacing=spacing,
        slides=data.get('slides') if data['paper_type'] == 'presentation' else None,
        sources_count=data.get('sources_count', 0),
        deadline=data['deadline'],
        format=data['format'],
        links=sanitized_links,
        base_price=price_data['base_price'],
        level_multiplier=price_data['level_multiplier'],
        level_adjusted=price_data['level_adjusted'],
        urgency_multiplier=price_data['urgency_multiplier'],
        total_price=price_data['total_price'],
        status='request'
    )

    log_history(order, request.user, 'create', None, 'request', {
        'total_price': str(price_data['total_price']),
        'pages': float(price_data.get('pages', 0)),
        'words': words,
        'spacing': spacing
    })

    create_timeline(order, 'request', 'Order Created', 
                   'Your order has been submitted and is waiting for a writer',
                   'fa-file-alt', 'green')

    return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_orders(request):
    status_filter = request.GET.get('status')
    search = request.GET.get('search')
    
    orders = Order.objects.filter(student=request.user).order_by('-created_at')

    if status_filter and status_filter in dict(Order.STATUS_CHOICES):
        orders = orders.filter(status=status_filter)
    
    if search:
        orders = orders.filter(
            Q(order_number__icontains=search) |
            Q(topic__icontains=search) |
            Q(subject__icontains=search)
        )

    serializer = OrderListSerializer(orders, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_orders(request):
    search = request.GET.get('q', '')
    if not search or len(search) < 2:
        return Response([])
    
    orders = Order.objects.filter(
        student=request.user
    ).filter(
        Q(order_number__icontains=search) |
        Q(topic__icontains=search)
    ).order_by('-created_at')[:10]
    
    results = []
    for order in orders:
        results.append({
            'id': str(order.id),
            'order_number': order.order_number,
            'topic': order.topic,
            'status': order.status,
            'created_at': order.created_at.isoformat()
        })
    
    return Response(results)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def assigned_orders(request):
    status_filter = request.GET.get('status')
    search = request.GET.get('search')
    
    orders = Order.objects.filter(writer=request.user).order_by('deadline')

    if status_filter and status_filter in dict(Order.STATUS_CHOICES):
        orders = orders.filter(status=status_filter)
    
    if search:
        orders = orders.filter(
            Q(order_number__icontains=search) |
            Q(topic__icontains=search)
        )

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
def order_timeline(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    if not (is_owner(order, request.user) or is_assigned_writer(order, request.user)):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    timeline = OrderTimeline.objects.filter(order=order).order_by('created_at')
    data = []
    for item in timeline:
        data.append({
            'status': item.status,
            'title': item.title,
            'description': item.description,
            'icon': item.icon,
            'color': item.color,
            'created_at': item.created_at.isoformat()
        })
    
    return Response(data)


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
    create_timeline(order, 'in_progress', 'Order Accepted', 
                   'A writer has been assigned to your order',
                   'fa-check-circle', 'blue')

    return Response(OrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, status='request')
    reason = request.data.get('reason', '')

    order.status = 'declined'
    order.declined_at = timezone.now()
    order.declined_by = request.user
    order.declined_reason = reason
    order.save()

    WalletService.credit(
        wallet=order.student.wallet,
        amount=order.total_price,
        transaction_type='refund',
        description=f'Refund for rejected order {order.order_number}',
        order=order
    )

    log_history(order, request.user, 'decline', 'request', 'declined', {'reason': reason})
    create_timeline(order, 'declined', 'Order Declined', 
                   'Your order was declined. Please review the feedback and resubmit.',
                   'fa-times-circle', 'red')

    return Response({'message': 'Order declined and refunded'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)
    
    serializer = CancelOrderSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    if not order.can_cancel(request.user):
        return Response(
            {'error': 'This order cannot be cancelled'},
            status=status.HTTP_400_BAD_REQUEST
        )

    from_status = order.status
    order.status = 'cancelled'
    order.cancelled_at = timezone.now()
    order.cancelled_by = request.user
    order.cancellation_reason = serializer.validated_data['reason']
    order.cancellation_feedback = serializer.validated_data.get('feedback', '')
    order.save()

    if order.status in ['awaiting_approval', 'in_progress']:
        WalletService.credit(
            wallet=order.student.wallet,
            amount=order.total_price,
            transaction_type='refund',
            description=f'Refund for cancelled order {order.order_number}',
            order=order
        )

    log_history(order, request.user, 'cancel', from_status, 'cancelled', {
        'reason': order.cancellation_reason,
        'feedback': order.cancellation_feedback
    })
    
    create_timeline(order, 'cancelled', 'Order Cancelled', 
                   'Order was cancelled by client',
                   'fa-ban', 'red')

    return Response({'message': 'Order cancelled and refunded'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def decline_order(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    
    if not is_assigned_writer(order, request.user) and not request.user.is_staff:
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    if order.status != 'request':
        return Response(
            {'error': 'Only orders in request status can be declined'},
            status=status.HTTP_400_BAD_REQUEST
        )

    serializer = DeclineOrderSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    from_status = order.status
    order.status = 'declined'
    order.declined_at = timezone.now()
    order.declined_by = request.user
    order.declined_reason = serializer.validated_data['reason']
    order.declined_feedback = serializer.validated_data.get('feedback', '')
    order.save()

    WalletService.credit(
        wallet=order.student.wallet,
        amount=order.total_price,
        transaction_type='refund',
        description=f'Refund for declined order {order.order_number}',
        order=order
    )

    log_history(order, request.user, 'decline', from_status, 'declined', {
        'reason': order.declined_reason,
        'feedback': order.declined_feedback
    })
    
    create_timeline(order, 'declined', 'Order Declined', 
                   f'Order declined: {order.declined_reason}',
                   'fa-times-circle', 'red')

    return Response({'message': 'Order declined and refunded'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resubmit_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)
    
    if not order.can_resubmit(request.user):
        return Response(
            {'error': 'This order cannot be resubmitted'},
            status=status.HTTP_400_BAD_REQUEST
        )

    serializer = ResubmitOrderSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    order.status = 'request'
    order.declined_at = None
    order.declined_by = None
    order.declined_reason = ''
    order.declined_feedback = ''
    order.save()

    log_history(order, request.user, 'resubmit', 'declined', 'request', {
        'notes': serializer.validated_data.get('notes', '')
    })
    
    create_timeline(order, 'request', 'Order Resubmitted', 
                   'Order has been resubmitted for review',
                   'fa-redo', 'green')

    return Response(OrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reorder_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)
    
    if not order.can_reorder(request.user):
        return Response(
            {'error': 'This order cannot be reordered'},
            status=status.HTTP_400_BAD_REQUEST
        )

    price_data = Order.calculate_price(
        order.academic_level,
        order.words,
        order.spacing,
        timezone.now() + timedelta(days=7),
        order.slides,
        order.paper_type
    )

    new_order = Order.objects.create(
        student=request.user,
        academic_level=order.academic_level,
        paper_type=order.paper_type,
        subject=order.subject,
        topic=order.topic,
        instructions=order.instructions,
        pages=price_data.get('pages'),
        words=order.words,
        spacing=order.spacing,
        slides=order.slides,
        sources_count=order.sources_count,
        deadline=timezone.now() + timedelta(days=7),
        format=order.format,
        links=order.links,
        base_price=price_data['base_price'],
        level_multiplier=price_data['level_multiplier'],
        level_adjusted=price_data['level_adjusted'],
        urgency_multiplier=price_data['urgency_multiplier'],
        total_price=price_data['total_price'],
        status='request',
        parent_order=order,
        version=order.version + 1
    )

    wallet = request.user.wallet
    try:
        WalletService.debit(
            wallet=wallet,
            amount=price_data['total_price'],
            transaction_type='escrow_hold',
            description=f'Order payment held in escrow for {order.topic[:50]}'
        )
    except ValueError as e:
        new_order.delete()
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    log_history(new_order, request.user, 'reorder', None, 'request', {
        'original_order': str(order.id),
        'version': new_order.version
    })
    
    create_timeline(new_order, 'request', 'Order Reordered', 
                   f'Reordered from Order #{order.order_number}',
                   'fa-copy', 'green')

    return Response(OrderSerializer(new_order).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def split_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)
    
    if not order.can_split(request.user):
        return Response(
            {'error': 'This order cannot be split'},
            status=status.HTTP_400_BAD_REQUEST
        )

    parts = request.data.get('parts', 2)
    if parts < 2:
        return Response(
            {'error': 'Must split into at least 2 parts'},
            status=status.HTTP_400_BAD_REQUEST
        )

    total_pages = order.pages or 0
    total_words = order.words or 0
    total_price = order.total_price
    
    pages_per_part = total_pages / parts if total_pages else 0
    words_per_part = total_words / parts if total_words else 0
    price_per_part = total_price / parts

    order_group = order.order_group or order.id

    split_orders = []
    for i in range(parts):
        part_price_data = Order.calculate_price(
            order.academic_level,
            int(words_per_part) if words_per_part > 0 else 275,
            order.spacing,
            order.deadline,
            order.slides,
            order.paper_type
        )

        new_order = Order.objects.create(
            student=request.user,
            academic_level=order.academic_level,
            paper_type=order.paper_type,
            subject=order.subject,
            topic=f"{order.topic} - Part {i+1}",
            instructions=order.instructions,
            pages=pages_per_part if pages_per_part else None,
            words=int(words_per_part) if words_per_part > 0 else 275,
            spacing=order.spacing,
            slides=order.slides,
            sources_count=order.sources_count,
            deadline=order.deadline,
            format=order.format,
            links=order.links,
            base_price=part_price_data['base_price'],
            level_multiplier=part_price_data['level_multiplier'],
            level_adjusted=part_price_data['level_adjusted'],
            urgency_multiplier=part_price_data['urgency_multiplier'],
            total_price=part_price_data['total_price'],
            status='request',
            parent_order=order,
            order_group=order_group,
            split_part=i+1,
            split_total=parts
        )

        wallet = request.user.wallet
        try:
            WalletService.debit(
                wallet=wallet,
                amount=part_price_data['total_price'],
                transaction_type='escrow_hold',
                description=f'Order payment held in escrow for {new_order.topic[:50]}'
            )
        except ValueError as e:
            for split_order in split_orders:
                split_order.delete()
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        log_history(new_order, request.user, 'split', None, 'request', {
            'parent_order': str(order.id),
            'split_part': i+1,
            'split_total': parts
        })
        
        create_timeline(new_order, 'request', f'Order Part {i+1} of {parts}', 
                       f'Split from Order #{order.order_number}',
                       'fa-cut', 'blue')
        
        split_orders.append(new_order)

    order.status = 'cancelled'
    order.cancelled_at = timezone.now()
    order.cancelled_by = request.user
    order.cancellation_reason = 'split'
    order.cancellation_feedback = f'Split into {parts} parts'
    order.save()

    log_history(order, request.user, 'split', 'in_progress', 'cancelled', {
        'split_into': parts
    })

    return Response({
        'message': f'Order split into {parts} parts',
        'orders': OrderSerializer(split_orders, many=True).data
    })


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
    create_timeline(order, 'awaiting_approval', 'Order Delivered', 
                   'Your order has been delivered and is awaiting approval',
                   'fa-file-check', 'green')

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
    create_timeline(order, 'completed', 'Order Completed', 
                   'Order has been completed and approved',
                   'fa-check-circle', 'green')

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
    
    create_timeline(order, 'in_progress', 'Revision Requested', 
                   f'Revision #{order.revision_count} requested',
                   'fa-edit', 'orange')

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
    
    create_timeline(order, 'refund_pending', 'Refund Requested', 
                   'Refund has been requested',
                   'fa-hand-holding-usd', 'orange')

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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_presence(request):
    is_online = request.data.get('is_online', True)
    current_room = request.data.get('current_room', '')
    
    presence, created = UserPresence.objects.get_or_create(user=request.user)
    presence.is_online = is_online
    presence.current_room = current_room
    if is_online:
        presence.last_seen_at = timezone.now()
    presence.save()
    
    return Response({
        'is_online': presence.is_online,
        'last_seen_at': presence.last_seen_at.isoformat()
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_presence(request, user_id):
    try:
        presence = UserPresence.objects.get(user_id=user_id)
        return Response({
            'is_online': presence.is_online,
            'last_seen_at': presence.last_seen_at.isoformat()
        })
    except UserPresence.DoesNotExist:
        return Response({
            'is_online': False,
            'last_seen_at': None
        })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_online_status(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    
    if not (is_owner(order, request.user) or is_assigned_writer(order, request.user)):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    other_user = order.writer if is_owner(order, request.user) else order.student
    
    if other_user:
        try:
            presence = UserPresence.objects.get(user=other_user)
            return Response({
                'is_online': presence.is_online,
                'last_seen_at': presence.last_seen_at.isoformat()
            })
        except UserPresence.DoesNotExist:
            return Response({
                'is_online': False,
                'last_seen_at': None
            })
    
    return Response({
        'is_online': False,
        'last_seen_at': None
    })


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
        create_timeline(order, 'completed', 'Auto-Approved', 
                       'Order was automatically approved after review period',
                       'fa-clock', 'gray')