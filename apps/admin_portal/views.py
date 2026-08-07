from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg, F, Sum
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from decimal import Decimal
from datetime import timedelta
import hashlib
import json

from apps.accounts.models import User
from apps.orders.models import Order, OrderHistory, OrderTimeline, Attachment
from apps.payments.models import Transaction, Wallet
from apps.payments.services import WalletService
from apps.messaging.models import Conversation, Message
from apps.admin_portal.models import (
    AdminActionLog, SystemSetting, SiteContent, Blog, 
    PlatformStats, AdminNote, Sample, AdminNotification, ContactMessage
)


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def is_admin(user):
    return user.is_authenticated and user.role == 'admin'


def admin_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            return render(request, 'access_denied.html')
        return view_func(request, *args, **kwargs)
    return wrapper


def log_admin_action(admin, action_type, request, **kwargs):
    AdminActionLog.objects.create(
        admin=admin,
        action_type=action_type,
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        **kwargs
    )


@login_required
@admin_required
def admin_order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    
    try:
        conversation = Conversation.objects.get(order=order)
        messages = conversation.messages.all().order_by('created_at')[:50]
    except Conversation.DoesNotExist:
        conversation = None
        messages = []
    
    client_online = False
    try:
        from apps.orders.models import UserPresence
        presence = UserPresence.objects.get(user=order.client)
        client_online = presence.is_online
    except:
        pass
    
    for msg in messages:
        if not msg.content or msg.content.strip() == '':
            msg.content = "Message content unavailable"
    
    delivered_files = []
    for attachment in order.attachments.filter(delivered_at__isnull=False):
        time_elapsed = timezone.now() - attachment.delivered_at
        can_pull_back = time_elapsed <= timedelta(minutes=30)
        time_remaining = max(0, int((timedelta(minutes=30) - time_elapsed).total_seconds() / 60))
        delivered_files.append({
            'id': str(attachment.id),
            'filename': attachment.filename,
            'file_size': attachment.file_size,
            'file_url': attachment.file.url,
            'delivered_at': attachment.delivered_at,
            'can_pull_back': can_pull_back,
            'time_remaining': f'{time_remaining}m left' if can_pull_back else 'Expired'
        })
    
    context = {
        'order': order,
        'messages': messages,
        'conversation': conversation,
        'client_online': client_online,
        'now': timezone.now(),
        'delivered_files': delivered_files,
    }
    return render(request, 'admin/order-detail.html', context)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def admin_dashboard(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    today = timezone.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    last_week = start_of_week - timedelta(days=7)
    
    users = User.objects.all()
    orders = Order.objects.all()
    
    transactions = Transaction.objects.filter(status='completed')
    total_revenue = transactions.aggregate(Sum('amount'))['amount__sum'] or 0
    revenue_today = transactions.filter(created_at__date=today).aggregate(Sum('amount'))['amount__sum'] or 0
    week_earnings = transactions.filter(created_at__date__gte=start_of_week).aggregate(Sum('amount'))['amount__sum'] or 0
    last_week_earnings = transactions.filter(
        created_at__date__gte=last_week,
        created_at__date__lt=start_of_week
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    
    week_change = 0
    if last_week_earnings > 0:
        week_change = ((week_earnings - last_week_earnings) / last_week_earnings) * 100
    
    pending_orders = orders.filter(status='request').count()
    in_progress = orders.filter(status='in_progress').count()
    awaiting = orders.filter(status='awaiting_approval').count()
    completed = orders.filter(status='completed').count()
    cancelled = orders.filter(status='cancelled').count()
    declined = orders.filter(status='declined').count()
    completed_today = orders.filter(status='completed', updated_at__date=today).count()
    
    avg_rating = 0
    rating_agg = orders.filter(rating__isnull=False).aggregate(Avg('rating'))
    if rating_agg and rating_agg['rating__avg']:
        avg_rating = rating_agg['rating__avg']
    
    completion_rate = 0
    total_orders = orders.count()
    if total_orders > 0:
        completion_rate = (completed / total_orders) * 100
    
    admin_wallet = Wallet.objects.filter(user=request.user).first()
    admin_balance = float(admin_wallet.balance) if admin_wallet else 0
    
    unread_messages = 0
    try:
        conversations = Conversation.objects.filter(admin=request.user)
        for conv in conversations:
            unread_messages += conv.get_unread_count(request.user)
    except:
        pass
    
    return Response({
        'users': {
            'total': users.count(),
            'clients': users.filter(role='client').count(),
            'admins': users.filter(role='admin').count(),
            'new_today': users.filter(date_joined__date=today).count(),
            'active': users.filter(last_login__date=today).count()
        },
        'orders': {
            'total': total_orders,
            'pending': pending_orders,
            'in_progress': in_progress,
            'awaiting_approval': awaiting,
            'completed': completed,
            'cancelled': cancelled,
            'declined': declined,
            'completed_today': completed_today,
            'overdue': orders.filter(
                deadline__lt=timezone.now(),
                status__in=['request', 'in_progress']
            ).count(),
            'revisions': orders.filter(status='revision').count(),
            'priority': orders.filter(
                status='request',
                deadline__lt=timezone.now() + timedelta(hours=6)
            ).count()
        },
        'finance': {
            'total_revenue': float(total_revenue),
            'revenue_today': float(revenue_today),
            'week_earnings': float(week_earnings),
            'last_week_earnings': float(last_week_earnings),
            'week_change': float(week_change),
            'admin_balance': admin_balance,
            'pending_payouts': 0
        },
        'ratings': {
            'average': float(avg_rating),
            'completion_rate': float(completion_rate)
        },
        'unread_messages': unread_messages
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def dashboard_stats(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    today = timezone.now().date()
    start_of_week = today - timedelta(days=today.weekday())
    last_week = start_of_week - timedelta(days=7)
    
    users = User.objects.all()
    orders = Order.objects.all()
    
    transactions = Transaction.objects.filter(status='completed')
    total_revenue = transactions.aggregate(Sum('amount'))['amount__sum'] or 0
    revenue_today = transactions.filter(created_at__date=today).aggregate(Sum('amount'))['amount__sum'] or 0
    week_earnings = transactions.filter(created_at__date__gte=start_of_week).aggregate(Sum('amount'))['amount__sum'] or 0
    last_week_earnings = transactions.filter(
        created_at__date__gte=last_week,
        created_at__date__lt=start_of_week
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    
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
        'total_revenue': float(total_revenue),
        'revenue_today': float(revenue_today),
        'pending_payouts': 0,
        'average_rating': float(avg_rating),
        'completion_rate': float(completion_rate),
        'overdue_orders': orders.filter(
            deadline__lt=timezone.now(),
            status__in=['request', 'in_progress']
        ).count(),
        'unread_messages': 0,
        'earnings': float(week_earnings),
        'week_earnings': float(week_earnings),
        'last_week_earnings': float(last_week_earnings),
        'week_change': float(week_change),
        'total_clients': users.filter(role='client').count(),
        'active_clients': users.filter(role='client', is_active=True, is_suspended=False).count(),
        'new_clients': users.filter(role='client', date_joined__date=today).count(),
        'revisions': orders.filter(status='revision').count(),
        'awaiting_approval': awaiting,
        'priority_count': orders.filter(
            status='request',
            deadline__lt=timezone.now() + timedelta(hours=6)
        ).count(),
    }
    
    return Response(stats)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def priority_queue(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    now = timezone.now()
    six_hours = now + timedelta(hours=6)
    tomorrow = now + timedelta(days=1)
    
    urgent_orders = Order.objects.filter(
        status__in=['request', 'in_progress'],
        deadline__lte=six_hours
    ).select_related('client')
    
    medium_orders = Order.objects.filter(
        status__in=['request', 'in_progress'],
        deadline__gt=six_hours,
        deadline__lte=tomorrow
    ).select_related('client')
    
    normal_orders = Order.objects.filter(
        status__in=['request', 'in_progress'],
        deadline__gt=tomorrow
    ).select_related('client')[:5]
    
    items = []
    
    for order in urgent_orders:
        items.append({
            'id': order.id,
            'order_number': order.order_number,
            'client_name': order.client.full_name if order.client else 'N/A',
            'deadline': order.deadline.strftime('%I:%M %p') if order.deadline else 'N/A',
            'urgency': 'high',
            'status': order.status
        })
    
    for order in medium_orders[:5]:
        items.append({
            'id': order.id,
            'order_number': order.order_number,
            'client_name': order.client.full_name if order.client else 'N/A',
            'deadline': order.deadline.strftime('%I:%M %p') if order.deadline else 'N/A',
            'urgency': 'medium',
            'status': order.status
        })
    
    for order in normal_orders[:3]:
        items.append({
            'id': order.id,
            'order_number': order.order_number,
            'client_name': order.client.full_name if order.client else 'N/A',
            'deadline': order.deadline.strftime('%I:%M %p') if order.deadline else 'N/A',
            'urgency': 'low',
            'status': order.status
        })
    
    items = sorted(items, key=lambda x: ['high', 'medium', 'low'].index(x['urgency']))
    
    return Response(items)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def list_users(request):
    if not is_admin(request.user):
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
            Q(email__icontains=search) |
            Q(full_name__icontains=search)
        )
    
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))
    start = (page - 1) * page_size
    end = start + page_size
    
    paginated_users = users[start:end]
    
    return Response({
        'total': users.count(),
        'page': page,
        'page_size': page_size,
        'results': [{
            'id': str(user.id),
            'email': user.email,
            'full_name': user.full_name,
            'role': user.role,
            'is_active': user.is_active,
            'is_suspended': user.is_suspended,
            'suspension_reason': user.suspension_reason,
            'suspended_until': user.suspended_until.isoformat() if user.suspended_until else None,
            'email_verified': user.email_verified,
            'date_joined': user.date_joined.isoformat(),
            'last_login': user.last_login.isoformat() if user.last_login else None
        } for user in paginated_users]
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def search_users(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    query = request.GET.get('q', '')
    if len(query) < 2:
        return Response({'results': []})
    
    users = User.objects.filter(
        Q(email__icontains=query) |
        Q(full_name__icontains=query)
    )[:20]
    
    return Response({
        'results': [{
            'id': str(user.id),
            'email': user.email,
            'full_name': user.full_name,
            'role': user.role
        } for user in users]
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def user_detail(request, user_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user = get_object_or_404(User, id=user_id)
    return Response({
        'id': str(user.id),
        'email': user.email,
        'full_name': user.full_name,
        'role': user.role,
        'is_active': user.is_active,
        'is_suspended': user.is_suspended,
        'suspension_reason': user.suspension_reason,
        'suspended_until': user.suspended_until.isoformat() if user.suspended_until else None,
        'email_verified': user.email_verified,
        'date_joined': user.date_joined.isoformat(),
        'last_login': user.last_login.isoformat() if user.last_login else None
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def suspend_user(request, user_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user = get_object_or_404(User, id=user_id)
    reason = request.data.get('reason', '').strip()
    days = int(request.data.get('days', 7))
    
    if not reason:
        return Response({'error': 'Suspension reason is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    if days < 1 or days > 365:
        return Response({'error': 'Suspension days must be between 1 and 365'}, status=status.HTTP_400_BAD_REQUEST)
    
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
@permission_classes([IsAuthenticated, IsAdminUser])
def reactivate_user(request, user_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user = get_object_or_404(User, id=user_id)
    
    if not user.is_suspended:
        return Response({'error': 'User is not suspended'}, status=status.HTTP_400_BAD_REQUEST)
    
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
@permission_classes([IsAuthenticated, IsAdminUser])
def delete_user(request, user_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user = get_object_or_404(User, id=user_id)
    
    if user.role == 'admin':
        return Response({'error': 'Cannot delete another admin user'}, status=status.HTTP_403_FORBIDDEN)
    
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
@permission_classes([IsAuthenticated, IsAdminUser])
def list_orders(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    status_filter = request.GET.get('status')
    search = request.GET.get('search')

    orders = Order.objects.all().select_related('client', 'writer').order_by('-created_at')

    if status_filter:
        orders = orders.filter(status=status_filter)

    if search:
        orders = orders.filter(
            Q(order_number__icontains=search) |
            Q(client__email__icontains=search) |
            Q(client__full_name__icontains=search) |
            Q(topic__icontains=search)
        )

    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))
    start = (page - 1) * page_size
    end = start + page_size

    paginated_orders = orders[start:end]

    return Response({
        'total': orders.count(),
        'page': page,
        'page_size': page_size,
        'results': [{
            'id': str(order.id),
            'order_number': order.order_number,
            'client': order.client.full_name if order.client else None,
            'client_email': order.client.email if order.client else None,
            'writer': order.writer.full_name if order.writer else None,
            'topic': order.topic,
            'subject': order.subject,
            'total_price': float(order.total_price),
            'status': order.status,
            'deadline': order.deadline.isoformat() if order.deadline else None,
            'created_at': order.created_at.isoformat(),
            'updated_at': order.updated_at.isoformat(),
            'words': order.words or 0,
            'academic_level': order.academic_level,
            'rating': order.rating,
            'feedback': order.feedback,
            'cancellation_feedback': order.cancellation_feedback,
            'declined_reason': order.declined_reason,
            'completed_at': order.completed_at.isoformat() if order.completed_at else None,
            'cancelled_at': order.cancelled_at.isoformat() if order.cancelled_at else None,
            'declined_at': order.declined_at.isoformat() if order.declined_at else None,
        } for order in paginated_orders]
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def pending_orders(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    orders = Order.objects.filter(status='request').select_related('client').order_by('deadline')
    return Response([{
        'id': str(order.id),
        'order_number': order.order_number,
        'client': order.client.full_name if order.client else None,
        'client_email': order.client.email if order.client else None,
        'topic': order.topic,
        'total_price': float(order.total_price),
        'deadline': order.deadline.isoformat() if order.deadline else None,
        'created_at': order.created_at.isoformat(),
        'words': order.words or 0,
        'academic_level': order.academic_level,
    } for order in orders])


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def active_orders(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    orders = Order.objects.filter(status='in_progress').select_related('client').order_by('deadline')
    return Response([{
        'id': str(order.id),
        'order_number': order.order_number,
        'client': order.client.full_name if order.client else None,
        'topic': order.topic,
        'total_price': float(order.total_price),
        'deadline': order.deadline.isoformat() if order.deadline else None,
        'created_at': order.created_at.isoformat(),
        'words': order.words or 0,
        'academic_level': order.academic_level,
    } for order in orders])


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def overdue_orders(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    now = timezone.now()
    orders = Order.objects.filter(
        status__in=['request', 'in_progress'],
        deadline__lt=now
    ).select_related('client').order_by('deadline')

    return Response([{
        'id': str(order.id),
        'order_number': order.order_number,
        'client': order.client.full_name if order.client else None,
        'topic': order.topic,
        'total_price': float(order.total_price),
        'deadline': order.deadline.isoformat() if order.deadline else None,
        'created_at': order.created_at.isoformat(),
        'words': order.words or 0,
        'academic_level': order.academic_level,
    } for order in orders])


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def completed_orders(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    orders = Order.objects.filter(status='completed').select_related('client').order_by('-updated_at')
    return Response([{
        'id': str(order.id),
        'order_number': order.order_number,
        'client': order.client.full_name if order.client else None,
        'topic': order.topic,
        'total_price': float(order.total_price),
        'completed_at': order.completed_at.isoformat() if order.completed_at else None,
        'rating': order.rating,
        'feedback': order.feedback,
        'words': order.words or 0,
        'academic_level': order.academic_level,
    } for order in orders])


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def search_orders(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    query = request.GET.get('q', '')
    if len(query) < 2:
        return Response({'results': []})

    orders = Order.objects.filter(
        Q(order_number__icontains=query) |
        Q(client__email__icontains=query) |
        Q(client__full_name__icontains=query) |
        Q(topic__icontains=query)
    ).select_related('client')[:20]

    return Response({
        'results': [{
            'id': str(order.id),
            'order_number': order.order_number,
            'client': order.client.full_name if order.client else None,
            'topic': order.topic,
            'status': order.status,
            'total_price': float(order.total_price),
            'words': order.words or 0,
            'academic_level': order.academic_level,
            'rating': order.rating,
            'feedback': order.feedback,
            'cancellation_feedback': order.cancellation_feedback,
            'declined_reason': order.declined_reason,
        } for order in orders]
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def order_workspace(request, order_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    order = get_object_or_404(Order, id=order_id)
    history = OrderHistory.objects.filter(order=order).order_by('-created_at')
    transactions = Transaction.objects.filter(order=order)

    return Response({
        'order': {
            'id': str(order.id),
            'order_number': order.order_number,
            'client': order.client.full_name if order.client else None,
            'topic': order.topic,
            'subject': order.subject,
            'total_price': float(order.total_price),
            'status': order.status,
            'deadline': order.deadline.isoformat() if order.deadline else None,
            'created_at': order.created_at.isoformat(),
            'words': order.words or 0,
            'academic_level': order.academic_level,
            'rating': order.rating,
            'feedback': order.feedback,
        },
        'history': list(history.values()),
        'transactions': list(transactions.values())
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def admin_accept_order(request, order_id):
    if not is_admin(request.user):
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

    OrderTimeline.objects.create(
        order=order,
        status='in_progress',
        title='Order Accepted',
        description='The order has been accepted and is now in progress',
        icon='fa-check-circle',
        color='green'
    )

    log_admin_action(
        admin=request.user,
        action_type='order_approve',
        request=request,
        target_order=order
    )

    return Response({'success': True, 'message': 'Order accepted successfully'})


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def admin_reject_order(request, order_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    order = get_object_or_404(Order, id=order_id, status='request')
    reason = request.data.get('reason', '').strip()

    if not reason:
        return Response({'error': 'Reason is required'}, status=status.HTTP_400_BAD_REQUEST)

    payment_completed = Transaction.objects.filter(
        order=order,
        type='payment',
        direction='debit',
        status='completed'
    ).exists()

    order.status = 'declined'
    order.declined_at = timezone.now()
    order.declined_by = request.user
    order.declined_reason = reason
    order.save()

    if payment_completed:
        try:
            AdminPaymentService.process_refund(order, order.total_price)
        except Exception:
            pass

    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='decline',
        from_status='request',
        to_status='declined',
        data={'reason': reason}
    )

    OrderTimeline.objects.create(
        order=order,
        status='declined',
        title='Order Declined',
        description=f'Order declined: {reason}',
        icon='fa-times-circle',
        color='red'
    )

    log_admin_action(
        admin=request.user,
        action_type='order_reject',
        request=request,
        target_order=order,
        details={'reason': reason}
    )

    return Response({'success': True, 'message': 'Order rejected successfully'})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def get_order_status(request, order_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    order = get_object_or_404(Order, id=order_id)
    return Response({
        'id': str(order.id),
        'status': order.status,
        'order_number': order.order_number,
        'can_deliver': order.status == 'in_progress'
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def admin_deliver_order(request, order_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    order = get_object_or_404(Order, id=order_id)

    if order.status != 'in_progress':
        return Response({
            'error': f'Order must be in progress to deliver. Current status: {order.status}'
        }, status=status.HTTP_400_BAD_REQUEST)

    files = request.FILES.getlist('files')
    if not files:
        return Response({'error': 'No files provided'}, status=status.HTTP_400_BAD_REQUEST)

    allowed_extensions = ['pdf', 'doc', 'docx', 'zip']
    max_size = 100 * 1024 * 1024

    for file in files:
        ext = file.name.split('.')[-1].lower() if '.' in file.name else ''
        if ext not in allowed_extensions:
            return Response({
                'error': f'File "{file.name}" is not supported. Please upload PDF, DOC, DOCX, or ZIP.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if file.size > max_size:
            return Response({
                'error': f'File "{file.name}" exceeds 100MB limit'
            }, status=status.HTTP_400_BAD_REQUEST)

    delivered_files = []

    try:
        from django.db import transaction
        with transaction.atomic():
            for file in files:
                attachment = Attachment.objects.create(
                    file=file,
                    filename=file.name,
                    file_size=file.size,
                    mime_type=file.content_type,
                    uploaded_by=request.user,
                    delivered_at=timezone.now()
                )
                order.attachments.add(attachment)
                delivered_files.append({
                    'id': str(attachment.id),
                    'filename': attachment.filename,
                    'file_size': attachment.file_size,
                    'delivered_at': attachment.delivered_at.isoformat()
                })

            order.status = 'awaiting_approval'
            order.delivered_at = timezone.now()
            order.auto_approve_at = timezone.now() + timedelta(hours=Order.REVISION_WINDOW_HOURS)
            order.save()

            OrderHistory.objects.create(
                order=order,
                user=request.user,
                action='deliver',
                from_status='in_progress',
                to_status='awaiting_approval'
            )

            OrderTimeline.objects.create(
                order=order,
                status='awaiting_approval',
                title='Files Delivered',
                description=f'{len(files)} file(s) delivered and awaiting client approval',
                icon='fa-file-check',
                color='purple'
            )

        log_admin_action(
            admin=request.user,
            action_type='order_deliver',
            request=request,
            target_order=order
        )

        return Response({
            'success': True,
            'message': f'{len(files)} file(s) delivered successfully',
            'files': delivered_files
        })

    except Exception as e:
        return Response({
            'error': f'Failed to deliver files: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def admin_pullback_file(request, order_id, file_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    order = get_object_or_404(Order, id=order_id)
    attachment = get_object_or_404(Attachment, id=file_id)

    if attachment not in order.attachments.all():
        return Response({'error': 'File not found in this order'}, status=status.HTTP_404_NOT_FOUND)

    delivered_at = getattr(attachment, 'delivered_at', None)
    if not delivered_at:
        return Response({'error': 'File was not delivered'}, status=status.HTTP_400_BAD_REQUEST)

    time_elapsed = timezone.now() - delivered_at
    if time_elapsed > timedelta(minutes=10):
        return Response({'error': 'Pull-back window expired (10 minutes)'}, status=status.HTTP_400_BAD_REQUEST)

    order.attachments.remove(attachment)
    attachment.delete()

    remaining_files = order.attachments.filter(delivered_at__isnull=False).count()
    if remaining_files == 0:
        order.status = 'in_progress'
        order.auto_approve_at = None
        order.save()

    log_admin_action(
        admin=request.user,
        action_type='file_pullback',
        request=request,
        target_order=order,
        details={'file_id': str(file_id), 'filename': attachment.filename}
    )

    return Response({
        'success': True,
        'message': 'File pulled back successfully',
        'remaining_files': remaining_files
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def admin_cancel_order(request, order_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    order = get_object_or_404(Order, id=order_id)
    reason = request.data.get('reason', '').strip()

    if order.status in ['completed', 'cancelled']:
        return Response({'error': 'Cannot cancel completed or cancelled order'}, status=status.HTTP_400_BAD_REQUEST)

    if not reason:
        return Response({'error': 'Cancellation reason is required'}, status=status.HTTP_400_BAD_REQUEST)

    payment_completed = Transaction.objects.filter(
        order=order,
        type='payment',
        direction='debit',
        status='completed'
    ).exists()

    from_status = order.status
    order.status = 'cancelled'
    order.cancelled_at = timezone.now()
    order.cancellation_reason = reason
    order.save()

    OrderHistory.objects.create(
        order=order,
        user=request.user,
        action='cancel',
        from_status=from_status,
        to_status='cancelled',
        data={'reason': reason}
    )

    OrderTimeline.objects.create(
        order=order,
        status='cancelled',
        title='Order Cancelled',
        description=f'Order cancelled: {reason}',
        icon='fa-ban',
        color='red'
    )

    if payment_completed:
        try:
            AdminPaymentService.process_refund(order, order.total_price)
        except Exception:
            pass

    log_admin_action(
        admin=request.user,
        action_type='order_cancel',
        request=request,
        target_order=order,
        details={'reason': reason}
    )

    return Response({'success': True, 'message': 'Order cancelled successfully'})

@login_required
@admin_required
def admin_contact_messages(request):
    messages_list = ContactMessage.objects.all().order_by('-created_at')
    context = {'messages': messages_list}
    return render(request, 'admin/contact-messages.html', context)

@login_required
@admin_required
def admin_contact_message_read(request, message_id):
    message = get_object_or_404(ContactMessage, id=message_id)
    message.is_read = True
    message.save()
    return JsonResponse({'success': True})

@login_required
@admin_required
def admin_contact_message_delete(request, message_id):
    message = get_object_or_404(ContactMessage, id=message_id)
    message.delete()
    return JsonResponse({'success': True})
@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def refund_requests(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    orders = Order.objects.filter(status='refund_pending').select_related('client').order_by('-updated_at')
    return Response([{
        'id': str(order.id),
        'order_number': order.order_number,
        'client': order.client.full_name if order.client else None,
        'client_email': order.client.email if order.client else None,
        'total_price': float(order.total_price),
        'created_at': order.created_at.isoformat(),
        'words': order.words or 0,
        'academic_level': order.academic_level,
    } for order in orders])


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def approve_refund(request, order_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    order = get_object_or_404(Order, id=order_id, status='refund_pending')

    order.status = 'cancelled'
    order.refund_approved_at = timezone.now()
    order.save()

    try:
        WalletService.credit(
            wallet=order.client.wallet,
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
@permission_classes([IsAuthenticated, IsAdminUser])
def deny_refund(request, order_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id, status='refund_pending')
    reason = request.data.get('reason', '').strip()
    
    if not reason:
        return Response({'error': 'Reason for denial is required'}, status=status.HTTP_400_BAD_REQUEST)
    
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


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def send_message(request, order_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id)
    content = request.data.get('content', '').strip()
    
    if not content:
        return Response({'error': 'Message content is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    conversation, created = Conversation.objects.get_or_create(
        order=order,
        defaults={
            'client': order.client,
            'admin': request.user
        }
    )
    
    message = Message.objects.create(
        conversation=conversation,
        sender=request.user,
        content=content,
        message_type='text'
    )
    
    conversation.last_message_at = timezone.now()
    conversation.admin_last_seen = timezone.now()
    conversation.save()
    
    return Response({
        'success': True,
        'message': {
            'id': str(message.id),
            'content': message.content,
            'sender': str(request.user.id),
            'sender_name': request.user.full_name or request.user.email,
            'created_at': message.created_at.isoformat()
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def get_messages(request, order_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    order = get_object_or_404(Order, id=order_id)
    
    try:
        conversation = Conversation.objects.get(order=order)
        messages = conversation.messages.all().order_by('created_at')[:100]
        
        conversation.admin_last_seen = timezone.now()
        conversation.save()
        
        return Response({
            'messages': [{
                'id': str(msg.id),
                'content': msg.content,
                'sender': str(msg.sender_id),
                'sender_name': msg.sender.full_name or msg.sender.email,
                'created_at': msg.created_at.isoformat(),
                'is_admin': msg.sender_id == request.user.id,
                'is_read': msg.is_read,
                'is_delivered': msg.is_delivered,
            } for msg in messages]
        })
    except Conversation.DoesNotExist:
        return Response({'messages': []})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def get_unread_count(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    conversations = Conversation.objects.filter(admin=request.user)
    unread_count = 0
    
    for conv in conversations:
        unread_count += conv.get_unread_count(request.user)
    
    return Response({'unread_count': unread_count})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def list_transactions(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    transactions = Transaction.objects.all().select_related(
        'user', 'wallet', 'order'
    ).order_by('-created_at')
    
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))
    start = (page - 1) * page_size
    end = start + page_size
    
    paginated = transactions[start:end]
    
    return Response({
        'total': transactions.count(),
        'page': page,
        'page_size': page_size,
        'results': [{
            'id': str(t.id),
            'transaction_id': t.transaction_id,
            'user': t.user.email if t.user else None,
            'amount': float(t.amount),
            'type': t.type,
            'direction': t.direction,
            'status': t.status,
            'payment_method': t.payment_method,
            'description': t.description,
            'order_id': str(t.order.id) if t.order else None,
            'created_at': t.created_at.isoformat(),
            'completed_at': t.completed_at.isoformat() if t.completed_at else None
        } for t in paginated]
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def transaction_detail(request, transaction_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    transaction_obj = get_object_or_404(Transaction, id=transaction_id)
    return Response({
        'id': str(transaction_obj.id),
        'transaction_id': transaction_obj.transaction_id,
        'user': transaction_obj.user.email if transaction_obj.user else None,
        'amount': float(transaction_obj.amount),
        'fee_amount': float(transaction_obj.fee_amount),
        'net_amount': float(transaction_obj.net_amount) if transaction_obj.net_amount else None,
        'type': transaction_obj.type,
        'direction': transaction_obj.direction,
        'status': transaction_obj.status,
        'payment_method': transaction_obj.payment_method,
        'description': transaction_obj.description,
        'metadata': transaction_obj.metadata,
        'order_id': str(transaction_obj.order.id) if transaction_obj.order else None,
        'created_at': transaction_obj.created_at.isoformat(),
        'completed_at': transaction_obj.completed_at.isoformat() if transaction_obj.completed_at else None
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def client_wallet(request, user_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user = get_object_or_404(User, id=user_id)
    wallet, created = Wallet.objects.get_or_create(user=user)
    
    transactions = Transaction.objects.filter(wallet=wallet).order_by('-created_at')[:50]
    
    return Response({
        'balance': float(wallet.balance),
        'held_balance': float(getattr(wallet, 'held_balance', 0)),
        'total_deposited': float(getattr(wallet, 'total_deposited', 0)),
        'total_withdrawn': float(getattr(wallet, 'total_withdrawn', 0)),
        'transactions': [{
            'id': str(t.id),
            'amount': float(t.amount),
            'type': t.type,
            'description': t.description,
            'status': t.status,
            'created_at': t.created_at.isoformat()
        } for t in transactions]
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def adjust_wallet(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    user_id = request.data.get('user_id')
    amount = Decimal(str(request.data.get('amount', 0)))
    action_type = request.data.get('type', 'credit')
    reason = request.data.get('reason', '').strip()
    
    if not user_id:
        return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    if amount <= 0:
        return Response({'error': 'Amount must be greater than 0'}, status=status.HTTP_400_BAD_REQUEST)
    
    if not reason:
        return Response({'error': 'Reason is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    user = get_object_or_404(User, id=user_id)
    wallet, created = Wallet.objects.get_or_create(user=user)
    
    try:
        if action_type == 'credit':
            transaction_obj = WalletService.credit(
                wallet=wallet,
                amount=amount,
                transaction_type='adjustment',
                description=reason,
                metadata={'admin': str(request.user.id)}
            )
        else:
            transaction_obj = WalletService.debit(
                wallet=wallet,
                amount=amount,
                transaction_type='adjustment',
                description=reason,
                metadata={'admin': str(request.user.id)}
            )
        
        log_admin_action(
            admin=request.user,
            action_type='wallet_adjust',
            request=request,
            target_user=user,
            details={'type': action_type, 'amount': str(amount), 'reason': reason}
        )
        
        return Response({
            'message': 'Wallet adjusted successfully',
            'transaction_id': str(transaction_obj.id),
            'new_balance': float(wallet.balance)
        })
        
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def list_settings(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    settings = SystemSetting.objects.all().order_by('key')
    return Response([{
        'id': str(s.id),
        'key': s.key,
        'value': s.value,
        'type': s.type,
        'description': s.description,
        'is_public': s.is_public,
        'updated_at': s.updated_at.isoformat()
    } for s in settings])


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def create_setting(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    key = request.data.get('key')
    value = request.data.get('value')
    type = request.data.get('type', 'text')
    description = request.data.get('description', '')
    is_public = request.data.get('is_public', False)
    
    if not key or value is None:
        return Response({'error': 'key and value are required'}, status=status.HTTP_400_BAD_REQUEST)
    
    setting = SystemSetting.objects.create(
        key=key,
        value=str(value),
        type=type,
        description=description,
        is_public=is_public,
        updated_by=request.user
    )
    
    return Response({
        'id': str(setting.id),
        'key': setting.key,
        'value': setting.value,
        'type': setting.type,
        'description': setting.description,
        'is_public': setting.is_public
    }, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsAuthenticated, IsAdminUser])
def update_setting(request, setting_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    setting = get_object_or_404(SystemSetting, id=setting_id)
    
    setting.value = str(request.data.get('value', setting.value))
    setting.type = request.data.get('type', setting.type)
    setting.description = request.data.get('description', setting.description)
    setting.is_public = request.data.get('is_public', setting.is_public)
    setting.updated_by = request.user
    setting.save()
    
    log_admin_action(
        admin=request.user,
        action_type='settings_change',
        request=request,
        details={'key': setting.key, 'value': setting.value}
    )
    
    return Response({
        'id': str(setting.id),
        'key': setting.key,
        'value': setting.value,
        'type': setting.type,
        'description': setting.description,
        'is_public': setting.is_public
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated, IsAdminUser])
def delete_setting(request, setting_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    setting = get_object_or_404(SystemSetting, id=setting_id)
    setting.delete()
    return Response({'message': 'Setting deleted'})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def list_content(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    page = request.GET.get('page')
    content = SiteContent.objects.all()
    
    if page:
        content = content.filter(page=page)
    
    return Response([{
        'id': str(c.id),
        'page': c.page,
        'section': c.section,
        'title': c.title,
        'content': c.content,
        'meta_data': c.meta_data,
        'is_active': c.is_active,
        'updated_at': c.updated_at.isoformat()
    } for c in content])


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def create_content(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    page = request.data.get('page')
    section = request.data.get('section')
    title = request.data.get('title')
    content = request.data.get('content')
    meta_data = request.data.get('meta_data', {})
    is_active = request.data.get('is_active', True)
    
    if not all([page, section, title, content]):
        return Response({'error': 'page, section, title, and content are required'}, status=status.HTTP_400_BAD_REQUEST)
    
    content_obj = SiteContent.objects.create(
        page=page,
        section=section,
        title=title,
        content=content,
        meta_data=meta_data,
        is_active=is_active,
        updated_by=request.user
    )
    
    return Response({
        'id': str(content_obj.id),
        'page': content_obj.page,
        'section': content_obj.section,
        'title': content_obj.title,
        'content': content_obj.content,
        'is_active': content_obj.is_active
    }, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsAuthenticated, IsAdminUser])
def update_content(request, content_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    content_obj = get_object_or_404(SiteContent, id=content_id)
    
    content_obj.title = request.data.get('title', content_obj.title)
    content_obj.content = request.data.get('content', content_obj.content)
    content_obj.meta_data = request.data.get('meta_data', content_obj.meta_data)
    content_obj.is_active = request.data.get('is_active', content_obj.is_active)
    content_obj.updated_by = request.user
    content_obj.save()
    
    log_admin_action(
        admin=request.user,
        action_type='content_edit',
        request=request,
        details={'page': content_obj.page, 'section': content_obj.section}
    )
    
    return Response({
        'id': str(content_obj.id),
        'page': content_obj.page,
        'section': content_obj.section,
        'title': content_obj.title,
        'content': content_obj.content,
        'is_active': content_obj.is_active
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated, IsAdminUser])
def delete_content(request, content_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    content_obj = get_object_or_404(SiteContent, id=content_id)
    content_obj.delete()
    return Response({'message': 'Content deleted'})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def list_logs(request):
    if not is_admin(request.user):
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
            Q(admin__email__icontains=search) |
            Q(target_user__email__icontains=search) |
            Q(target_order__order_number__icontains=search)
        )
    
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 50))
    start = (page - 1) * page_size
    end = start + page_size
    
    paginated = logs[start:end]
    
    return Response({
        'total': logs.count(),
        'page': page,
        'page_size': page_size,
        'results': [{
            'id': str(log.id),
            'admin': log.admin.email if log.admin else None,
            'action_type': log.action_type,
            'target_user': log.target_user.email if log.target_user else None,
            'target_order': log.target_order.order_number if log.target_order else None,
            'details': log.details,
            'ip_address': log.ip_address,
            'created_at': log.created_at.isoformat()
        } for log in paginated]
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def log_detail(request, log_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    log = get_object_or_404(AdminActionLog, id=log_id)
    return Response({
        'id': str(log.id),
        'admin': log.admin.email if log.admin else None,
        'action_type': log.action_type,
        'target_user': log.target_user.email if log.target_user else None,
        'target_order': log.target_order.order_number if log.target_order else None,
        'details': log.details,
        'ip_address': log.ip_address,
        'user_agent': log.user_agent,
        'created_at': log.created_at.isoformat()
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def export_logs(request):
    if not is_admin(request.user):
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
            log.admin.email if log.admin else '',
            log.get_action_type_display(),
            log.target_user.email if log.target_user else '',
            str(log.details),
            log.ip_address or ''
        ])
    
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def list_notes(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    notes = AdminNote.objects.filter(admin=request.user).order_by('-is_pinned', '-created_at')
    return Response([{
        'id': str(note.id),
        'title': note.title,
        'content': note.content,
        'is_pinned': note.is_pinned,
        'is_archived': note.is_archived,
        'created_at': note.created_at.isoformat(),
        'updated_at': note.updated_at.isoformat()
    } for note in notes])


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def create_note(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    title = request.data.get('title', '').strip()
    content = request.data.get('content', '').strip()
    is_pinned = request.data.get('is_pinned', False)
    
    if not title or not content:
        return Response({'error': 'title and content are required'}, status=status.HTTP_400_BAD_REQUEST)
    
    note = AdminNote.objects.create(
        admin=request.user,
        title=title,
        content=content,
        is_pinned=is_pinned
    )
    
    return Response({
        'id': str(note.id),
        'title': note.title,
        'content': note.content,
        'is_pinned': note.is_pinned,
        'created_at': note.created_at.isoformat()
    }, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsAuthenticated, IsAdminUser])
def update_note(request, note_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    note = get_object_or_404(AdminNote, id=note_id, admin=request.user)
    
    note.title = request.data.get('title', note.title)
    note.content = request.data.get('content', note.content)
    note.is_pinned = request.data.get('is_pinned', note.is_pinned)
    note.is_archived = request.data.get('is_archived', note.is_archived)
    note.save()
    
    return Response({
        'id': str(note.id),
        'title': note.title,
        'content': note.content,
        'is_pinned': note.is_pinned,
        'is_archived': note.is_archived,
        'updated_at': note.updated_at.isoformat()
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated, IsAdminUser])
def delete_note(request, note_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    note = get_object_or_404(AdminNote, id=note_id, admin=request.user)
    note.delete()
    return Response({'message': 'Note deleted'})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def analytics_overview(request):
    if not is_admin(request.user):
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
@permission_classes([IsAuthenticated, IsAdminUser])
def revenue_analytics(request):
    if not is_admin(request.user):
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
@permission_classes([IsAuthenticated, IsAdminUser])
def order_analytics(request):
    if not is_admin(request.user):
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
@permission_classes([IsAuthenticated, IsAdminUser])
def client_analytics(request):
    if not is_admin(request.user):
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
@permission_classes([IsAuthenticated, IsAdminUser])
def get_counts(request):
    if not is_admin(request.user):
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


@login_required
@admin_required
def admin_samples(request):
    samples = Sample.objects.all().order_by('-created_at')
    
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        file = request.FILES.get('file')
        is_active = request.POST.get('is_active') == 'true'
        
        if not file:
            messages.error(request, 'Please select a file to upload.')
            context = {'samples': samples}
            return render(request, 'admin/samples.html', context)
        
        if not title:
            messages.error(request, 'Please provide a title for the sample.')
            context = {'samples': samples}
            return render(request, 'admin/samples.html', context)
        
        sample = Sample.objects.create(
            title=title,
            description=description,
            file=file,
            file_name=file.name,
            file_size=file.size,
            file_type=file.content_type,
            uploaded_by=request.user,
            is_active=is_active
        )
        
        messages.success(request, f'Sample "{title}" uploaded successfully.')
        return redirect('admin-samples')
    
    context = {'samples': samples}
    return render(request, 'admin/samples.html', context)


@login_required
@admin_required
def admin_toggle_sample(request, sample_id):
    try:
        sample = get_object_or_404(Sample, id=sample_id)
        sample.is_active = not sample.is_active
        sample.save()
        
        status = 'activated' if sample.is_active else 'deactivated'
        return JsonResponse({'success': True, 'message': f'Sample "{sample.title}" {status}.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
@admin_required
def admin_delete_sample(request, sample_id):
    try:
        sample = get_object_or_404(Sample, id=sample_id)
        title = sample.title
        sample.delete()
        return JsonResponse({'success': True, 'message': f'Sample "{title}" deleted.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def list_notifications(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    filter_type = request.GET.get('filter')
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))

    notifications = AdminNotification.objects.filter(recipient=request.user)

    if filter_type == 'unread':
        notifications = notifications.filter(is_read=False)
    elif filter_type == 'read':
        notifications = notifications.filter(is_read=True)

    paginator = Paginator(notifications, page_size)
    page_obj = paginator.get_page(page)

    return Response({
        'count': paginator.count,
        'page': page,
        'page_size': page_size,
        'results': [{
            'id': str(n.id),
            'title': n.title,
            'message': n.message,
            'type': n.type,
            'is_read': n.is_read,
            'link': n.link,
            'created_at': n.created_at.isoformat()
        } for n in page_obj]
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def mark_notification_read(request, notification_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    notification = get_object_or_404(AdminNotification, id=notification_id, recipient=request.user)
    notification.is_read = True
    notification.save()
    return Response({'success': True, 'message': 'Marked as read'})


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def mark_all_notifications_read(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    updated = AdminNotification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return Response({'success': True, 'message': f'Marked {updated} notifications as read'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated, IsAdminUser])
def delete_notification(request, notification_id):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    notification = get_object_or_404(AdminNotification, id=notification_id, recipient=request.user)
    notification.delete()
    return Response({'success': True, 'message': 'Notification deleted'})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def unread_notification_count(request):
    if not is_admin(request.user):
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

    count = AdminNotification.objects.filter(recipient=request.user, is_read=False).count()
    return Response({'unread_count': count})