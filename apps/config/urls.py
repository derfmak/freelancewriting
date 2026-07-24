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
    path('forgot-password/', views.forgot_password, name='forgot-password'),
    path('reset-password/', views.reset_password, name='reset-password'),
    path('about/', views.about, name='about'),
    path('services/', views.services, name='services'),
    path('pricing/', views.pricing, name='pricing'),
    path('how-it-works/', views.how_it_works, name='how-it-works'),
    path('faq/', views.faq, name='faq'),
    path('contact/', views.contact, name='contact'),
    path('terms/', views.terms, name='terms'),
    path('privacy/', views.privacy, name='privacy'),
    path('refund-policy/', views.refund_policy, name='refund-policy'),
    path('guarantees/', views.guarantees, name='guarantees'),
    path('samples/', views.samples, name='samples'),
    path('blog/', views.blog, name='blog'),
    path('place-order/', views.place_order, name='place-order'),
    path('testimonials/', views.testimonials, name='testimonials'),

    path('dashboard/', views.dashboard_redirect, name='dashboard'),

    path('student/dashboard/', views.student_dashboard, name='student-dashboard'),
    path('student/orders/', views.student_orders, name='student-orders'),
    path('student/orders/new/', views.new_order, name='new-order'),
    path('student/orders/<uuid:order_id>/', views.order_detail, name='order-detail'),
    path('student/wallet/', views.wallet, name='wallet'),
    path('student/messages/', views.messages, name='messages'),
    path('student/announcements/', views.student_announcements, name='student-announcements'),
    path('student/profile/', views.profile, name='profile'),
    path('student/profile/edit/', views.profile_edit, name='profile-edit'),
    path('student/settings/', views.settings, name='settings'),
    path('notifications/', views.notifications, name='notifications'),

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
    path('admin/profile/', views.profile, name='admin-profile'),

    path('admin/', admin.site.urls),

    path('auth/', include('apps.accounts.urls')),
    path('api/auth/', include('apps.accounts.urls')),
    path('api/v1/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/v1/admin/', include('apps.admin_portal.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)