from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('forgot-password/', views.forgot_password_view, name='forgot-password'),
    path('reset-password/', views.reset_password_view, name='reset-password'),
    path('about/', views.about_view, name='about'),
    path('services/', views.services_view, name='services'),
    path('pricing/', views.pricing_view, name='pricing'),
    path('how-it-works/', views.how_it_works_view, name='how-it-works'),
    path('faq/', views.faq_view, name='faq'),
    path('contact/', views.contact_view, name='contact'),
    path('terms/', views.terms_view, name='terms'),
    path('privacy/', views.privacy_view, name='privacy'),
    path('refund-policy/', views.refund_policy_view, name='refund-policy'),
    path('guarantees/', views.guarantees_view, name='guarantees'),
    

    path('student/dashboard/', views.student_dashboard, name='student-dashboard'),
    path('student/orders/', views.student_orders, name='student-orders'),
    path('student/orders/new/', views.new_order, name='new-order'),
    path('student/orders/<uuid:order_id>/', views.order_detail, name='order-detail'),
    path('student/wallet/', views.wallet, name='wallet'),
    path('student/messages/', views.messages, name='messages'),
    path('student/orders/<uuid:order_id>/chat/', views.create_or_get_conversation, name='order-chat'),
    path('student/announcements/', views.student_announcements, name='student-announcements'),
    path('student/profile/', views.profile, name='profile'),
    path('student/settings/', views.settings, name='settings'),
    
 
    path('admin/dashboard/', views.admin_dashboard, name='admin-dashboard'),
    path('admin/orders/', views.admin_orders, name='admin-orders'),
    path('admin/users/', views.admin_users, name='admin-users'),
    path('admin/finances/', views.admin_finances, name='admin-finances'),
    path('admin/refunds/', views.admin_refunds, name='admin-refunds'),
    path('admin/messages/', views.admin_messages, name='admin-messages'),
    path('admin/announcements/', views.admin_announcements, name='admin-announcements'),
    path('admin/announcements/create/', views.admin_create_announcement, name='admin-create-announcement'),
    path('admin/content/', views.admin_content, name='admin-content'),
    path('admin/logs/', views.admin_logs, name='admin-logs'),
    path('admin/settings/', views.admin_settings, name='admin-settings'),
    path('admin/profile/', views.admin_profile, name='admin-profile'),
    path('notifications/', views.notifications, name='notifications'),
    
    path('admin/', admin.site.urls),
    
   
    path('api/v1/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/orders/', include('apps.orders.urls')),
    path('api/v1/messages/', include('apps.messaging.urls')),
    path('api/v1/wallet/', include('apps.payments.urls')),
    path('api/v1/admin/', include('apps.admin_portal.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)