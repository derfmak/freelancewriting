from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages

def home(request):
    return render(request, 'public/home.html')

def about(request):
    return render(request, 'public/about.html')

def how_it_works(request):
    return render(request, 'public/how-it-works.html')

def services(request):
    return render(request, 'public/services.html')

def pricing(request):
    return render(request, 'public/pricing.html')

def contact(request):
    return render(request, 'public/contact.html')

def terms(request):
    return render(request, 'public/terms.html')

def privacy(request):
    return render(request, 'public/privacy.html')

def refund_policy(request):
    return render(request, 'public/refund-policy.html')

def faq(request):
    return render(request, 'public/faq.html')

def place_order(request):
    return render(request, 'public/place-order.html')

def samples(request):
    return render(request, 'public/samples.html')

def guarantees(request):
    return render(request, 'public/guarantees.html')

def testimonials(request):
    return render(request, 'public/testimonials.html')

def blog(request):
    return render(request, 'public/blog.html')

def forgot_password(request):
    return render(request, 'public/forgot-password.html')

def reset_password(request, token=None):
    return render(request, 'public/reset-password.html', {'token': token})

def login_view(request):
    return render(request, 'public/login.html')

def register_view(request):
    return render(request, 'public/register.html')

@login_required
def dashboard_redirect(request):
    if request.user.role == 'admin':
        return redirect('admin-dashboard')
    elif request.user.role == 'client':
        return redirect('student-dashboard')
    return redirect('home')

@login_required
def student_dashboard(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'student/dashboard.html')

@login_required
def student_orders(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'student/orders.html')

@login_required
def new_order(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'student/new-order.html')

@login_required
def order_detail(request, order_id):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'student/order-detail.html', {'order_id': order_id})

@login_required
def wallet(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'student/wallet.html')

@login_required
def messages(request):
    if request.user.role == 'client':
        return render(request, 'student/messages.html')
    elif request.user.role == 'admin':
        return render(request, 'admin/messages.html')
    return render(request, 'access_denied.html')

@login_required
def order_messages(request, order_id):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'student/order-messages.html', {'order_id': order_id})

@login_required
def student_announcements(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'student/announcements.html')

@login_required
def profile(request):
    if request.user.role == 'client':
        return render(request, 'student/profile.html')
    elif request.user.role == 'admin':
        return render(request, 'admin/profile.html')
    return render(request, 'access_denied.html')

@login_required
def profile_edit(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'student/profile-edit.html')

@login_required
def settings(request):
    if request.user.role == 'client':
        return render(request, 'student/settings.html')
    elif request.user.role == 'admin':
        return render(request, 'admin/settings.html')
    return render(request, 'access_denied.html')

@login_required
def admin_settings(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/settings.html')

@login_required
def notifications(request):
    if request.user.role == 'client':
        return render(request, 'student/notifications.html')
    elif request.user.role == 'admin':
        return render(request, 'admin/notifications.html')
    return render(request, 'access_denied.html')

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
def admin_messages(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/messages.html')