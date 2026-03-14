from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.conf import settings
from apps.messaging.models import Conversation

@login_required
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

def home(request):
    return render(request, 'public/home.html')

def login_view(request):
    return render(request, 'public/login.html')

def register_view(request):
    return render(request, 'public/register.html')

def forgot_password_view(request):
    return render(request, 'public/forgot-password.html')

def reset_password_view(request):
    return render(request, 'public/reset-password.html')

def about_view(request):
    return render(request, 'public/about.html')

def pricing_view(request):
    return render(request, 'public/pricing.html')

def how_it_works_view(request):
    return render(request, 'public/how-it-works.html')

def faq_view(request):
    return render(request, 'public/faq.html')

def contact_view(request):
    return render(request, 'public/contact.html')

def terms_view(request):
    return render(request, 'public/terms.html')

def privacy_view(request):
    return render(request, 'public/privacy.html')

def refund_policy_view(request):
    return render(request, 'public/refund-policy.html')

def guarantees_view(request):
    return render(request, 'public/guarantees.html')

def services_view(request):
    return render(request, 'public/services.html')

@login_required
def student_dashboard(request):
    if request.user.role != 'student':
        return render(request, 'access_denied.html')
    return render(request, 'student/dashboard.html')

@login_required
def student_orders(request):
    if request.user.role != 'student':
        return render(request, 'access_denied.html')
    return render(request, 'student/orders.html')

@login_required
def new_order(request):
    if request.user.role != 'student':
        return render(request, 'access_denied.html')
    return render(request, 'student/new-order.html')

@login_required
def order_detail(request, order_id):
    if request.user.role != 'student':
        return render(request, 'access_denied.html')
    return render(request, 'student/order-detail.html', {'order_id': order_id})

@login_required
def wallet(request):
    if request.user.role != 'student':
        return render(request, 'access_denied.html')
    return render(request, 'student/wallet.html')

@login_required
def messages(request):
    if request.user.role != 'student':
        return render(request, 'access_denied.html')
    return render(request, 'student/messages.html')

@login_required
def order_messages(request, order_id):
    if request.user.role != 'student':
        return render(request, 'access_denied.html')
    return render(request, 'student/order-messages.html', {'order_id': order_id})

@login_required
def student_announcements(request):
    if request.user.role != 'student':
        return render(request, 'access_denied.html')
    return render(request, 'student/announcements.html')

@login_required
def profile(request):
    if request.user.role != 'student':
        return render(request, 'access_denied.html')
    return render(request, 'student/profile.html')

@login_required
def settings(request):
    if request.user.role != 'student':
        return render(request, 'access_denied.html')
    return render(request, 'student/settings.html')

@login_required
def admin_dashboard(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/dashboard.html')

@login_required
def admin_orders(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/orders.html')

@login_required
def admin_users(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/users.html')

@login_required
def admin_finances(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/finances.html')

@login_required
def admin_refunds(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/refunds.html')

@login_required
def admin_announcements(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/announcements.html')

@login_required
def admin_create_announcement(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/create-announcement.html')

@login_required
def admin_content(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/content.html')

@login_required
def admin_logs(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/logs.html')

@login_required
def admin_settings(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/settings.html')

@login_required
def admin_profile(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/profile.html')

@login_required
def notifications(request):
    if request.user.role == 'student':
        return render(request, 'student/notifications.html')
    elif request.user.role == 'admin':
        return render(request, 'admin/notifications.html')
    return render(request, 'access_denied.html')

@login_required
def profile_edit(request):
    if request.user.role != 'student':
        return render(request, 'access_denied.html')
    return render(request, 'student/profile_edit.html')
@login_required
def admin_messages(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/messages.html')