from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import models
from django.db.models import Count, Sum, Avg
from django.utils import timezone
from django.shortcuts import get_object_or_404
from datetime import timedelta
from apps.accounts.models import User
from apps.orders.models import Order, OrderHistory
from apps.payments.models import Transaction, Wallet
from apps.payments.services import WalletService
from .models import AdminActionLog, SystemSetting, SiteContent, Announcement, PlatformStats
from .serializers import (
    UserAdminSerializer, OrderAdminSerializer, TransactionAdminSerializer,
    DashboardStatsSerializer, SystemSettingSerializer, SiteContentSerializer,
    AnnouncementSerializer, AdminActionLogSerializer, WalletAdjustSerializer
)

def log_admin_action(admin, action_type, request, **kwargs):
    AdminActionLog.objects.create(
        admin=admin,
        action_type=action_type,
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        **kwargs
    )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    today = timezone.now().date()
    tomorrow = today + timedelta(days=1)
    
    users = User.objects.all()
    orders = Order.objects.all()
    transactions = Transaction.objects.filter(status='completed')
    
    stats = {
        'total_users': users.count(),
        'new_users_today': users.filter(date_joined__date=today).count(),
        'active_users': users.filter(last_login__date=today).count(),
        
        'total_orders': orders.count(),
        'pending_orders': orders.filter(status='pending').count(),
        'ongoing_orders': orders.filter(status='ongoing').count(),
        'completed_today': orders.filter(
            status='completed',
            completed_at__date=today
        ).count(),
        
        'total_revenue': transactions.aggregate(Sum('amount'))['amount__sum'] or 0,
        'revenue_today': transactions.filter(
            completed_at__date=today
        ).aggregate(Sum('amount'))['amount__sum'] or 0,
        'pending_payouts': 0,
        
        'average_rating': orders.filter(rating__isnull=False).aggregate(Avg('rating'))['rating__avg'] or 0,
        'completion_rate': 0,
    }
    
    if stats['total_orders'] > 0:
        completed = orders.filter(status='completed').count()
        stats['completion_rate'] = (completed / stats['total_orders']) * 100
    
    serializer = DashboardStatsSerializer(stats)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_users(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    role = request.GET.get('role')
    status_filter = request.GET.get('status')
    search = request.GET.get('search')
    
    users = User.objects.all().order_by('-date_joined')
    
    if role:
        users = users.filter(role=role)
    
    if status_filter == 'suspended':
        users = users.filter(is_suspended=True)
    elif status_filter == 'active':
        users = users.filter(is_suspended=False, is_active=True)
    elif status_filter == 'pending':
        users = users.filter(email_verified=False)
    
    if search:
        users = users.filter(
            models.Q(email__icontains=search) |
            models.Q(full_name__icontains=search)
        )
    
    page = int(request.GET.get('page', 1))
    page_size = 20
    start = (page - 1) * page_size
    end = start + page_size
    
    paginated_users = users[start:end]
    serializer = UserAdminSerializer(paginated_users, many=True)
    
    return Response({
        'total': users.count(),
        'page': page,
        'page_size': page_size,
        'results': serializer.data
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_detail(request, user_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user = get_object_or_404(User, id=user_id)
    serializer = UserAdminSerializer(user)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def suspend_user(request, user_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user = get_object_or_404(User, id=user_id)
    reason = request.data.get('reason', '')
    days = int(request.data.get('days', 7))
    
    user.is_suspended = True
    user.suspension_reason = reason
    user.suspended_until = timezone.now() + timedelta(days=days)
    user.save()
    
    log_admin_action(
        admin=request.user,
        action_type='user_suspend',
        request=request,
        target_user=user,
        details={'reason': reason, 'days': days}
    )
    
    return Response({'message': f'user suspended for {days} days'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reactivate_user(request, user_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user = get_object_or_404(User, id=user_id)
    
    user.is_suspended = False
    user.suspension_reason = ''
    user.suspended_until = None
    user.save()
    
    log_admin_action(
        admin=request.user,
        action_type='user_reactivate',
        request=request,
        target_user=user
    )
    
    return Response({'message': 'user reactivated'})

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_user(request, user_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user = get_object_or_404(User, id=user_id)
    
    log_admin_action(
        admin=request.user,
        action_type='user_delete',
        request=request,
        target_user=user,
        details={'email': user.email, 'full_name': user.full_name}
    )
    
    user.delete()
    return Response({'message': 'user deleted'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_orders(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    status_filter = request.GET.get('status')
    search = request.GET.get('search')
    
    orders = Order.objects.all().select_related('student').order_by('-created_at')
    
    if status_filter:
        orders = orders.filter(status=status_filter)
    
    if search:
        orders = orders.filter(
            models.Q(order_number__icontains=search) |
            models.Q(student__email__icontains=search) |
            models.Q(topic__icontains=search)
        )
    
    page = int(request.GET.get('page', 1))
    page_size = 20
    start = (page - 1) * page_size
    end = start + page_size
    
    paginated_orders = orders[start:end]
    serializer = OrderAdminSerializer(paginated_orders, many=True)
    
    return Response({
        'total': orders.count(),
        'page': page,
        'page_size': page_size,
        'results': serializer.data
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_detail(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id)
    serializer = OrderAdminSerializer(order)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_order(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id, status='pending')
    
    order.status = 'ongoing'
    order.approved_at = timezone.now()
    order.started_at = timezone.now()
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='approve',
        from_status='pending',
        to_status='ongoing'
    )
    
    log_admin_action(
        admin=request.user,
        action_type='order_approve',
        request=request,
        target_order=order
    )
    
    return Response({'message': 'order approved'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_order(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id, status='pending')
    reason = request.data.get('reason', '')
    
    order.status = 'cancelled'
    order.cancelled_at = timezone.now()
    order.cancelled_by = request.user
    order.cancellation_reason = reason
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='reject',
        from_status='pending',
        to_status='cancelled',
        data={'reason': reason}
    )
    
    log_admin_action(
        admin=request.user,
        action_type='order_reject',
        request=request,
        target_order=order,
        details={'reason': reason}
    )
    
    return Response({'message': 'order rejected'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def deliver_order(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id, status='ongoing')
    
    order.status = 'awaiting_review'
    order.delivered_at = timezone.now()
    order.auto_approve_at = timezone.now() + timedelta(hours=48)
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='deliver',
        from_status='ongoing',
        to_status='awaiting_review'
    )
    
    log_admin_action(
        admin=request.user,
        action_type='order_deliver',
        request=request,
        target_order=order
    )
    
    return Response({'message': 'order delivered'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def refund_requests(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    orders = Order.objects.filter(status='refund_pending').order_by('-updated_at')
    serializer = OrderAdminSerializer(orders, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_refund(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id, status='refund_pending')
    
    order.status = 'cancelled'
    order.refund_approved_at = timezone.now()
    order.save()
    
    try:
        WalletService.credit(
            wallet=order.student.wallet,
            amount=order.total_price,
            transaction_type='refund',
            description=f'refund for order {order.order_number}',
            order=order
        )
    except:
        pass
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='approve_refund',
        from_status='refund_pending',
        to_status='cancelled'
    )
    
    log_admin_action(
        admin=request.user,
        action_type='refund_approve',
        request=request,
        target_order=order
    )
    
    return Response({'message': 'refund approved'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def deny_refund(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id, status='refund_pending')
    reason = request.data.get('reason', '')
    
    order.status = 'completed'
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='deny_refund',
        from_status='refund_pending',
        to_status='completed',
        data={'reason': reason}
    )
    
    log_admin_action(
        admin=request.user,
        action_type='refund_deny',
        request=request,
        target_order=order,
        details={'reason': reason}
    )
    
    return Response({'message': 'refund denied'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_transactions(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    transactions = Transaction.objects.all().select_related(
        'user', 'wallet', 'order'
    ).order_by('-created_at')
    
    page = int(request.GET.get('page', 1))
    page_size = 20
    start = (page - 1) * page_size
    end = start + page_size
    
    paginated = transactions[start:end]
    serializer = TransactionAdminSerializer(paginated, many=True)
    
    return Response({
        'total': transactions.count(),
        'page': page,
        'page_size': page_size,
        'results': serializer.data
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def adjust_wallet(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    serializer = WalletAdjustSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    user = get_object_or_404(User, id=serializer.validated_data['user_id'])
    wallet = WalletService.get_or_create_wallet(user)
    
    try:
        if serializer.validated_data['type'] == 'credit':
            transaction_obj = WalletService.credit(
                wallet=wallet,
                amount=serializer.validated_data['amount'],
                transaction_type='adjustment',
                description=serializer.validated_data['reason'],
                metadata={'admin': str(request.user.id)}
            )
        else:
            transaction_obj = WalletService.debit(
                wallet=wallet,
                amount=serializer.validated_data['amount'],
                transaction_type='adjustment',
                description=serializer.validated_data['reason'],
                metadata={'admin': str(request.user.id)}
            )
        
        log_admin_action(
            admin=request.user,
            action_type='wallet_adjust',
            request=request,
            target_user=user,
            details=serializer.validated_data
        )
        
        return Response({'message': 'wallet adjusted', 'transaction_id': str(transaction_obj.id)})
        
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_settings(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    settings = SystemSetting.objects.all().order_by('key')
    serializer = SystemSettingSerializer(settings, many=True)
    return Response(serializer.data)

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_setting(request, setting_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    setting = get_object_or_404(SystemSetting, id=setting_id)
    serializer = SystemSettingSerializer(setting, data=request.data, partial=True)
    
    if serializer.is_valid():
        serializer.save(updated_by=request.user)
        
        log_admin_action(
            admin=request.user,
            action_type='settings_change',
            request=request,
            details={'key': setting.key, 'value': serializer.validated_data.get('value')}
        )
        
        return Response(serializer.data)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_content(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    page = request.GET.get('page')
    content = SiteContent.objects.all()
    
    if page:
        content = content.filter(page=page)
    
    serializer = SiteContentSerializer(content, many=True)
    return Response(serializer.data)

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_content(request, content_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    content = get_object_or_404(SiteContent, id=content_id)
    serializer = SiteContentSerializer(content, data=request.data, partial=True)
    
    if serializer.is_valid():
        serializer.save(updated_by=request.user)
        
        log_admin_action(
            admin=request.user,
            action_type='content_edit',
            request=request,
            details={'page': content.page, 'section': content.section}
        )
        
        return Response(serializer.data)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_announcements(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    announcements = Announcement.objects.all().order_by('-created_at')
    serializer = AnnouncementSerializer(announcements, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_announcement(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    serializer = AnnouncementSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_announcement(request, announcement_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    announcement = get_object_or_404(Announcement, id=announcement_id)
    serializer = AnnouncementSerializer(announcement, data=request.data, partial=True)
    
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_announcement(request, announcement_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    announcement = get_object_or_404(Announcement, id=announcement_id)
    announcement.delete()
    return Response({'message': 'announcement deleted'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_logs(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    action_type = request.GET.get('type')
    user_id = request.GET.get('user_id')
    
    logs = AdminActionLog.objects.all().select_related(
        'admin', 'target_user', 'target_order'
    ).order_by('-created_at')
    
    if action_type:
        logs = logs.filter(action_type=action_type)
    
    if user_id:
        logs = logs.filter(target_user_id=user_id)
    
    page = int(request.GET.get('page', 1))
    page_size = 50
    start = (page - 1) * page_size
    end = start + page_size
    
    paginated = logs[start:end]
    serializer = AdminActionLogSerializer(paginated, many=True)
    
    return Response({
        'total': logs.count(),
        'page': page,
        'page_size': page_size,
        'results': serializer.data
    })