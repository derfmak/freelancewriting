from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import Order, OrderHistory, Attachment
from .serializers import (
    OrderCreateSerializer, OrderDetailSerializer,
    OrderListSerializer, OrderActionSerializer, OrderRatingSerializer,
    FileUploadSerializer, OrderHistorySerializer
)
from .services import OrderWorkflow
from .utils import generate_order_number, check_file_integrity, calculate_file_hash, scan_file_for_viruses

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    serializer = OrderCreateSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        try:
            with transaction.atomic():
                order = serializer.save()
                OrderHistory.objects.create(
                    order=order,
                    user=request.user,
                    action='create',
                    from_status='',
                    to_status='pending',
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                return Response({
                    'message': 'Order created successfully',
                    'id': order.id,
                    'order_number': order.order_number
                }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_orders(request):
    status_filter = request.GET.get('status')
    orders = Order.objects.filter(student=request.user)
    
    if status_filter:
        orders = orders.filter(status=status_filter)
    
    orders = orders.order_by('-created_at')
    serializer = OrderListSerializer(orders, many=True)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)
    serializer = OrderDetailSerializer(order)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def order_action(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)
    serializer = OrderActionSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    action = serializer.validated_data['action']
    from_status = order.status
    
    with transaction.atomic():
        if action == 'cancel':
            if not OrderWorkflow.can_transition(order, 'cancelled'):
                return Response({'error': 'Cannot cancel order'}, status=status.HTTP_400_BAD_REQUEST)
            
            order.status = 'cancelled'
            order.cancelled_at = timezone.now()
            order.cancelled_by = request.user
            order.cancellation_reason = serializer.validated_data.get('reason', '')
            order.save()
            
        elif action == 'request_revision':
            if order.status not in ['awaiting_review', 'completed']:
                return Response({'error': 'Cannot request revision'}, status=status.HTTP_400_BAD_REQUEST)
            
            order.status = 'ongoing'
            order.revision_count += 1
            order.last_revision_requested_at = timezone.now()
            order.save()
            
        elif action == 'approve':
            if order.status != 'awaiting_review':
                return Response({'error': 'Cannot approve order'}, status=status.HTTP_400_BAD_REQUEST)
            
            order.status = 'completed'
            order.completed_at = timezone.now()
            order.save()
            
        elif action == 'request_refund':
            if order.status != 'completed':
                return Response({'error': 'Cannot request refund'}, status=status.HTTP_400_BAD_REQUEST)
            
            order.status = 'refund_pending'
            order.refund_reason = serializer.validated_data.get('reason', '')
            order.grade_received = serializer.validated_data.get('grade', '')
            order.save()
        
        OrderHistory.objects.create(
            order=order,
            user=request.user,
            action=action,
            from_status=from_status,
            to_status=order.status,
            data=serializer.validated_data,
            ip_address=request.META.get('REMOTE_ADDR')
        )
    
    return Response({'message': f'Action {action} completed successfully'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def rate_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user, status='completed')
    
    serializer = OrderRatingSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    order.rating = serializer.validated_data['rating']
    order.feedback = serializer.validated_data.get('feedback', '')
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='rate',
        from_status=order.status,
        to_status=order.status,
        data=serializer.validated_data,
        ip_address=request.META.get('REMOTE_ADDR')
    )
    
    return Response({'message': 'Rating submitted successfully'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_files(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)
    files = order.attachments.all()
    data = [{
        'id': f.id,
        'filename': f.filename,
        'file_size': f.file_size,
        'mime_type': f.mime_type,
        'uploaded_at': f.uploaded_at,
        'url': f.file.url if f.file else None
    } for f in files]
    return Response(data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_order_file(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)
    
    if 'file' not in request.FILES:
        return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
    
    file = request.FILES['file']
    
    attachment = Attachment.objects.create(
        file=file,
        filename=file.name,
        file_size=file.size,
        mime_type=file.content_type,
        uploaded_by=request.user,
        scan_status='pending'
    )
    
    order.attachments.add(attachment)
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='upload',
        from_status=order.status,
        to_status=order.status,
        data={'filename': file.name},
        ip_address=request.META.get('REMOTE_ADDR')
    )
    
    return Response({
        'id': attachment.id,
        'filename': attachment.filename,
        'message': 'File uploaded successfully'
    }, status=status.HTTP_201_CREATED)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_order_file(request, order_id, file_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)
    attachment = get_object_or_404(Attachment, id=file_id, uploaded_by=request.user)
    
    order.attachments.remove(attachment)
    attachment.delete()
    
    return Response({'message': 'File deleted successfully'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_history(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)
    history = order.history.all().order_by('-created_at')
    serializer = OrderHistorySerializer(history, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_file(request):
    serializer = FileUploadSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    file = serializer.validated_data['file']
    
    file_data = file.read()
    file.seek(0)
    
    file_hash = calculate_file_hash(file)
    
    is_corrupt, error = check_file_integrity(file, file.content_type)
    if is_corrupt:
        return Response({
            'verified': False,
            'scan_status': 'corrupt',
            'error': error
        }, status=status.HTTP_400_BAD_REQUEST)
    
    is_infected, virus_name = scan_file_for_viruses(file_data)
    if is_infected:
        return Response({
            'verified': False,
            'scan_status': 'infected',
            'virus_name': virus_name
        }, status=status.HTTP_400_BAD_REQUEST)
    
    return Response({
        'verified': True,
        'scan_status': 'clean',
        'file_hash': file_hash
    })
    
    
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def create_or_get_conversation(request, order_id):
    order = get_object_or_404(Order, id=order_id, student=request.user)
    
    admin = User.objects.filter(role='admin').first()
    
    conversation, created = Conversation.objects.get_or_create(
        order=order,
        defaults={
            'student': request.user,
            'admin': admin
        }
    )
    
    return redirect(f'/student/messages/?order={order.id}')