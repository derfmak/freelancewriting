from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import models
from django.db.models import Count, Sum, Avg, Q
from django.utils import timezone
from django.shortcuts import get_object_or_404
from datetime import timedelta
from apps.accounts.models import User
from apps.orders.models import Order, OrderHistory
from apps.payments.models import Transaction, Wallet
from apps.payments.services import WalletService
from .models import AdminActionLog, SystemSetting, SiteContent, Announcement, PlatformStats, AdminNote
from .serializers import (
    UserAdminSerializer, OrderAdminSerializer, TransactionAdminSerializer,
    DashboardStatsSerializer, SystemSettingSerializer, SiteContentSerializer,
    AnnouncementSerializer, AdminActionLogSerializer, WalletAdjustSerializer,
    PriorityQueueSerializer, AdminNoteSerializer, PlatformStatsSerializer
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
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)
    last_week = start_of_week - timedelta(days=7)
    
    users = User.objects.all()
    orders = Order.objects.all()
    
    try:
        transactions = Transaction.objects.filter(status='completed')
        total_revenue = transactions.aggregate(Sum('amount'))['amount__sum'] or 0
        revenue_today = transactions.filter(created_at__date=today).aggregate(Sum('amount'))['amount__sum'] or 0
        week_earnings = transactions.filter(created_at__date__gte=start_of_week).aggregate(Sum('amount'))['amount__sum'] or 0
        last_week_earnings = transactions.filter(
            created_at__date__gte=last_week,
            created_at__date__lt=start_of_week
        ).aggregate(Sum('amount'))['amount__sum'] or 0
    except:
        total_revenue = 0
        revenue_today = 0
        week_earnings = 0
        last_week_earnings = 0
    
    week_change = 0
    if last_week_earnings > 0:
        week_change = ((week_earnings - last_week_earnings) / last_week_earnings) * 100
    
    pending_orders = orders.filter(status='request').count()
    in_progress = orders.filter(status='in_progress').count()
    awaiting = orders.filter(status='awaiting_approval').count()
    completed = orders.filter(status='completed').count()
    completed_today = orders.filter(status='completed', updated_at__date=today).count()
    
    avg_rating = 0
    rating_agg = orders.filter(rating__isnull=False).aggregate(Avg('rating'))
    if rating_agg and rating_agg['rating__avg']:
        avg_rating = rating_agg['rating__avg']
    
    completion_rate = 0
    total_orders = orders.count()
    if total_orders > 0:
        completion_rate = (completed / total_orders) * 100
    
    stats = {
        'total_users': users.count(),
        'new_users_today': users.filter(date_joined__date=today).count(),
        'active_users': users.filter(last_login__date=today).count(),
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'in_progress_orders': in_progress,
        'completed_today': completed_today,
        'total_revenue': total_revenue,
        'revenue_today': revenue_today,
        'pending_payouts': 0,
        'average_rating': avg_rating,
        'completion_rate': completion_rate,
        'overdue_orders': orders.filter(deadline__lt=timezone.now(), status__in=['request', 'in_progress']).count(),
        'unread_messages': 0,
        'earnings': week_earnings,
        'week_earnings': week_earnings,
        'last_week_earnings': last_week_earnings,
        'week_change': week_change,
        'total_clients': users.filter(role='client').count(),
        'active_clients': users.filter(role='client', is_active=True, is_suspended=False).count(),
        'new_clients': users.filter(role='client', date_joined__date=today).count(),
        'revisions': orders.filter(status='revision').count(),
        'awaiting_approval': awaiting,
        'priority_count': orders.filter(status='request', deadline__lt=timezone.now() + timedelta(hours=6)).count(),
    }
    
    serializer = DashboardStatsSerializer(stats)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def priority_queue(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    now = timezone.now()
    six_hours = now + timedelta(hours=6)
    tomorrow = now + timedelta(days=1)
    
    urgent_orders = Order.objects.filter(
        status__in=['request', 'in_progress'],
        deadline__lte=six_hours
    ).select_related('student')
    
    medium_orders = Order.objects.filter(
        status__in=['request', 'in_progress'],
        deadline__gt=six_hours,
        deadline__lte=tomorrow
    ).select_related('student')
    
    normal_orders = Order.objects.filter(
        status__in=['request', 'in_progress'],
        deadline__gt=tomorrow
    ).select_related('student')[:5]
    
    items = []
    
    for order in urgent_orders:
        items.append({
            'id': order.id,
            'order_number': order.order_number,
            'client_name': order.student.full_name if order.student else 'N/A',
            'deadline': order.deadline.strftime('%I:%M %p') if order.deadline else 'N/A',
            'urgency': 'high',
            'status': order.status
        })
    
    for order in medium_orders[:5]:
        items.append({
            'id': order.id,
            'order_number': order.order_number,
            'client_name': order.student.full_name if order.student else 'N/A',
            'deadline': order.deadline.strftime('%I:%M %p') if order.deadline else 'N/A',
            'urgency': 'medium',
            'status': order.status
        })
    
    for order in normal_orders[:3]:
        items.append({
            'id': order.id,
            'order_number': order.order_number,
            'client_name': order.student.full_name if order.student else 'N/A',
            'deadline': order.deadline.strftime('%I:%M %p') if order.deadline else 'N/A',
            'urgency': 'low',
            'status': order.status
        })
    
    items = sorted(items, key=lambda x: ['high', 'medium', 'low'].index(x['urgency']))
    
    serializer = PriorityQueueSerializer(items, many=True)
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
    page_size = int(request.GET.get('page_size', 20))
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
def search_users(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    query = request.GET.get('q', '')
    if len(query) < 2:
        return Response({'results': []})
    
    users = User.objects.filter(
        models.Q(email__icontains=query) |
        models.Q(full_name__icontains=query)
    )[:20]
    
    serializer = UserAdminSerializer(users, many=True)
    return Response({'results': serializer.data})


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
    
    return Response({'message': f'User suspended for {days} days'})


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
    
    return Response({'message': 'User reactivated'})


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
    return Response({'message': 'User deleted'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_orders(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    status_filter = request.GET.get('status')
    search = request.GET.get('search')
    
    orders = Order.objects.all().select_related('student', 'writer').order_by('-created_at')
    
    if status_filter:
        orders = orders.filter(status=status_filter)
    
    if search:
        orders = orders.filter(
            models.Q(order_number__icontains=search) |
            models.Q(student__email__icontains=search) |
            models.Q(student__full_name__icontains=search) |
            models.Q(topic__icontains=search)
        )
    
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))
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
def pending_orders(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    orders = Order.objects.filter(status='request').select_related('student').order_by('deadline')
    serializer = OrderAdminSerializer(orders, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def active_orders(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    orders = Order.objects.filter(status='in_progress').select_related('student').order_by('deadline')
    serializer = OrderAdminSerializer(orders, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def overdue_orders(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    now = timezone.now()
    orders = Order.objects.filter(
        status__in=['request', 'in_progress'],
        deadline__lt=now
    ).select_related('student').order_by('deadline')
    
    serializer = OrderAdminSerializer(orders, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def completed_orders(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    orders = Order.objects.filter(status='completed').select_related('student').order_by('-updated_at')
    serializer = OrderAdminSerializer(orders, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_orders(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    query = request.GET.get('q', '')
    if len(query) < 2:
        return Response({'results': []})
    
    orders = Order.objects.filter(
        models.Q(order_number__icontains=query) |
        models.Q(student__email__icontains=query) |
        models.Q(student__full_name__icontains=query) |
        models.Q(topic__icontains=query)
    ).select_related('student')[:20]
    
    serializer = OrderAdminSerializer(orders, many=True)
    return Response({'results': serializer.data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_detail(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id)
    serializer = OrderAdminSerializer(order)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_workspace(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id)
    
    order_data = OrderAdminSerializer(order).data
    history = OrderHistory.objects.filter(order=order).order_by('-created_at')
    transactions = Transaction.objects.filter(order=order)
    
    return Response({
        'order': order_data,
        'history': list(history.values()),
        'transactions': list(transactions.values())
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_order(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id, status='request')
    
    order.status = 'in_progress'
    order.accepted_at = timezone.now()
    order.started_at = timezone.now()
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='accept',
        from_status='request',
        to_status='in_progress'
    )
    
    log_admin_action(
        admin=request.user,
        action_type='order_approve',
        request=request,
        target_order=order
    )
    
    return Response({'message': 'Order accepted and started'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_order(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id, status='request')
    reason = request.data.get('reason', '')
    
    order.status = 'cancelled'
    order.cancelled_at = timezone.now()
    order.cancellation_reason = reason
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='reject',
        from_status='request',
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
    
    return Response({'message': 'Order rejected'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def deliver_order(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id, status='in_progress')
    
    order.status = 'awaiting_approval'
    order.delivered_at = timezone.now()
    order.auto_approve_at = timezone.now() + timedelta(hours=48)
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='deliver',
        from_status='in_progress',
        to_status='awaiting_approval'
    )
    
    log_admin_action(
        admin=request.user,
        action_type='order_deliver',
        request=request,
        target_order=order
    )
    
    return Response({'message': 'Order delivered'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_order(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id, status='awaiting_approval')
    
    order.status = 'completed'
    order.completed_at = timezone.now()
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='complete',
        from_status='awaiting_approval',
        to_status='completed'
    )
    
    log_admin_action(
        admin=request.user,
        action_type='order_complete',
        request=request,
        target_order=order
    )
    
    return Response({'message': 'Order completed'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_order(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id)
    reason = request.data.get('reason', '')
    
    if order.status in ['completed', 'cancelled']:
        return Response({'error': 'Cannot cancel completed or cancelled order'}, status=status.HTTP_400_BAD_REQUEST)
    
    order.status = 'cancelled'
    order.cancelled_at = timezone.now()
    order.cancellation_reason = reason
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='cancel',
        from_status=order.status,
        to_status='cancelled',
        data={'reason': reason}
    )
    
    log_admin_action(
        admin=request.user,
        action_type='order_cancel',
        request=request,
        target_order=order,
        details={'reason': reason}
    )
    
    return Response({'message': 'Order cancelled'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_revision(request, order_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id, status='awaiting_approval')
    reason = request.data.get('reason', '')
    
    order.status = 'revision'
    order.last_revision_requested_at = timezone.now()
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='revise',
        from_status='awaiting_approval',
        to_status='revision',
        data={'reason': reason}
    )
    
    log_admin_action(
        admin=request.user,
        action_type='order_revision',
        request=request,
        target_order=order,
        details={'reason': reason}
    )
    
    return Response({'message': 'Revision requested'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def refund_requests(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    orders = Order.objects.filter(status='refund_pending').select_related('student').order_by('-updated_at')
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
            description=f'Refund for order {order.order_number}',
            order=order
        )
    except:
        pass
    
    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='refund_approve',
        from_status='refund_pending',
        to_status='cancelled'
    )
    
    log_admin_action(
        admin=request.user,
        action_type='refund_approve',
        request=request,
        target_order=order
    )
    
    return Response({'message': 'Refund approved'})


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
        action='refund_deny',
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
    
    return Response({'message': 'Refund denied'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_transactions(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    transactions = Transaction.objects.all().select_related(
        'user', 'wallet', 'order'
    ).order_by('-created_at')
    
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def transaction_detail(request, transaction_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    transaction = get_object_or_404(Transaction, id=transaction_id)
    serializer = TransactionAdminSerializer(transaction)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_wallet(request, user_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user = get_object_or_404(User, id=user_id)
    wallet, created = Wallet.objects.get_or_create(user=user)
    
    transactions = Transaction.objects.filter(wallet=wallet).order_by('-created_at')[:50]
    
    return Response({
        'balance': float(wallet.balance),
        'held_balance': float(wallet.held_balance) if wallet.held_balance else 0,
        'total_deposited': float(wallet.total_deposited) if wallet.total_deposited else 0,
        'total_withdrawn': float(wallet.total_withdrawn) if wallet.total_withdrawn else 0,
        'transactions': list(transactions.values(
            'id', 'amount', 'type', 'description', 'status', 'created_at'
        ))
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
    wallet, created = Wallet.objects.get_or_create(user=user)
    
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
        
        return Response({
            'message': 'Wallet adjusted successfully',
            'transaction_id': str(transaction_obj.id),
            'new_balance': float(wallet.balance)
        })
        
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_setting(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    serializer = SystemSettingSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_setting(request, setting_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    setting = get_object_or_404(SystemSetting, id=setting_id)
    setting.delete()
    return Response({'message': 'Setting deleted'})


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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_content(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    serializer = SiteContentSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_content(request, content_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    content = get_object_or_404(SiteContent, id=content_id)
    content.delete()
    return Response({'message': 'Content deleted'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_announcements(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    announcements = Announcement.objects.all().order_by('-created_at')
    serializer = AnnouncementSerializer(announcements, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def active_announcements(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    announcements = Announcement.get_active_announcements()
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
        
        log_admin_action(
            admin=request.user,
            action_type='announcement_create',
            request=request,
            details={'title': serializer.validated_data.get('title')}
        )
        
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
        
        log_admin_action(
            admin=request.user,
            action_type='announcement_update',
            request=request,
            details={'title': serializer.validated_data.get('title')}
        )
        
        return Response(serializer.data)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_announcement(request, announcement_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    announcement = get_object_or_404(Announcement, id=announcement_id)
    announcement.delete()
    return Response({'message': 'Announcement deleted'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_logs(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    action_type = request.GET.get('type')
    user_id = request.GET.get('user_id')
    search = request.GET.get('search')
    
    logs = AdminActionLog.objects.all().select_related(
        'admin', 'target_user', 'target_order'
    ).order_by('-created_at')
    
    if action_type:
        logs = logs.filter(action_type=action_type)
    
    if user_id:
        logs = logs.filter(target_user_id=user_id)
    
    if search:
        logs = logs.filter(
            models.Q(admin__email__icontains=search) |
            models.Q(target_user__email__icontains=search) |
            models.Q(target_order__order_number__icontains=search)
        )
    
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 50))
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def log_detail(request, log_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    log = get_object_or_404(AdminActionLog, id=log_id)
    serializer = AdminActionLogSerializer(log)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_logs(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    import csv
    from django.http import HttpResponse
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="admin_logs.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Date', 'Admin', 'Action', 'Target', 'Details', 'IP'])
    
    logs = AdminActionLog.objects.all().select_related('admin', 'target_user', 'target_order')
    
    for log in logs:
        writer.writerow([
            log.created_at.strftime('%Y-%m-%d %H:%M'),
            log.admin.email,
            log.get_action_type_display(),
            log.target_user.email if log.target_user else '',
            str(log.details),
            log.ip_address or ''
        ])
    
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_notes(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    notes = AdminNote.objects.filter(admin=request.user).order_by('-is_pinned', '-created_at')
    serializer = AdminNoteSerializer(notes, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_note(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    serializer = AdminNoteSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(admin=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_note(request, note_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    note = get_object_or_404(AdminNote, id=note_id, admin=request.user)
    serializer = AdminNoteSerializer(note, data=request.data, partial=True)
    
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_note(request, note_id):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    note = get_object_or_404(AdminNote, id=note_id, admin=request.user)
    note.delete()
    return Response({'message': 'Note deleted'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_overview(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    total_users = User.objects.filter(is_active=True).count()
    total_orders = Order.objects.count()
    completed_orders = Order.objects.filter(status='completed').count()
    total_revenue = Transaction.objects.filter(
        type='deposit',
        status='completed'
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    
    stats = PlatformStats.objects.filter(date__gte=thirty_days_ago.date()).order_by('date')
    
    return Response({
        'total_users': total_users,
        'total_orders': total_orders,
        'completed_orders': completed_orders,
        'completion_rate': (completed_orders / total_orders * 100) if total_orders > 0 else 0,
        'total_revenue': float(total_revenue),
        'average_order_value': float(total_revenue / total_orders) if total_orders > 0 else 0,
        'stats_over_time': list(stats.values())
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def revenue_analytics(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    period = request.GET.get('period', 'month')
    
    if period == 'week':
        days = 7
    elif period == 'month':
        days = 30
    else:
        days = 365
    
    start_date = timezone.now() - timedelta(days=days)
    
    revenue = Transaction.objects.filter(
        type='deposit',
        status='completed',
        created_at__gte=start_date
    ).extra({'date': "date(created_at)"}).values('date').annotate(
        total=Sum('amount')
    ).order_by('date')
    
    return Response({
        'period': period,
        'data': list(revenue)
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_analytics(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    status_counts = Order.objects.values('status').annotate(count=Count('id'))
    
    monthly = Order.objects.extra(
        {'month': "strftime('%%Y-%%m', created_at)"}
    ).values('month').annotate(
        count=Count('id')
    ).order_by('month')
    
    return Response({
        'status_counts': list(status_counts),
        'monthly_trend': list(monthly[:12])
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_analytics(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    top_clients = User.objects.filter(
        role='client',
        is_active=True
    ).annotate(
        order_count=Count('orders'),
        total_spent=Sum('orders__total_price')
    ).filter(order_count__gt=0).order_by('-total_spent')[:10]
    
    return Response({
        'top_clients': list(top_clients.values('id', 'full_name', 'email', 'order_count', 'total_spent'))
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_counts(request):
    if request.user.role != 'admin':
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    now = timezone.now()
    
    pending_orders = Order.objects.filter(status='request').count()
    unread_messages = 0
    overdue_orders = Order.objects.filter(
        status__in=['request', 'in_progress'],
        deadline__lt=now
    ).count()
    
    return Response({
        'pending_orders': pending_orders,
        'unread_messages': unread_messages,
        'overdue_orders': overdue_orders,
        'refund_requests': Order.objects.filter(status='refund_pending').count()
    })