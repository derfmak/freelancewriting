from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

app_name = 'config'

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('forgot-password/', views.forgot_password, name='forgot-password'),
    path('reset-password/<str:token>/', views.reset_password, name='reset-password'),
    
    path('about/', views.about, name='about'),
    path('about/stats/', views.about_stats, name='about-stats'),
    path('services/', views.services, name='services'),
    path('samples/', views.samples, name='samples'),
    path('samples/<uuid:sample_id>/download/', views.download_sample, name='download-sample'),
    path('pricing/', views.pricing, name='pricing'),
    path('how-it-works/', views.how_it_works, name='how-it-works'),
    path('faq/', views.faq, name='faq'),
    path('contact/', views.contact, name='contact'),
    path('contact/send/', views.contact_message, name='contact-send'),
    path('terms/', views.terms, name='terms'),
    path('privacy/', views.privacy, name='privacy'),
    path('refund-policy/', views.refund_policy, name='refund-policy'),
    path('guarantees/', views.guarantees, name='guarantees'),
    path('testimonials/', views.testimonials, name='testimonials'),
    path('place-order/', views.place_order, name='place-order'),
    
    path('blog/', views.blog, name='blog'),
    path('blog/<slug:slug>/', views.blog_detail, name='blog-detail'),
    path('blog/<slug:slug>/share/', views.blog_share, name='blog-share'),
    path('api/blog/search/', views.blog_search_suggestions, name='blog-search-suggestions'),
    
    path('dashboard/', views.dashboard_redirect, name='dashboard'),
    
    path('client/dashboard/', views.client_dashboard, name='client-dashboard'),
    path('client/orders/', views.client_orders, name='client-orders'),
    path('client/orders/new/', views.client_new_order, name='client-new-order'),
    path('client/orders/<uuid:order_id>/', views.client_order_detail, name='client-order-detail'),
    path('client/wallet/', views.client_wallet, name='client-wallet'),
    path('client/messages/', views.client_messages, name='client-messages'),
    path('client/messages/<uuid:order_id>/', views.client_order_messages, name='client-order-messages'),
    path('client/announcements/', views.client_announcements, name='client-announcements'),
    path('client/profile/', views.client_profile, name='client-profile'),
    path('client/profile/edit/', views.client_profile_edit, name='client-profile-edit'),
    path('client/settings/', views.client_settings, name='client-settings'),
    path('client/notifications/', views.client_notifications, name='client-notifications'),
    
    path('admin/dashboard/', views.admin_dashboard, name='admin-dashboard'),
    path('admin/orders/', views.admin_orders, name='admin-orders'),
    path('admin/users/', views.admin_users, name='admin-users'),
    path('admin/finances/', views.admin_finances, name='admin-finances'),
    path('admin/refunds/', views.admin_refunds, name='admin-refunds'),
    path('admin/messages/', views.admin_messages, name='admin-messages'),
    
    path('admin/blog/', views.admin_blog, name='admin-blog'),
    path('admin/blog/create/', views.admin_create_blog, name='admin-create-blog'),
    path('admin/blog/<uuid:blog_id>/edit/', views.admin_edit_blog, name='admin-edit-blog'),
    path('admin/blog/<uuid:blog_id>/delete/', views.admin_delete_blog_ajax, name='admin-delete-blog'),
    path('admin/blog/<uuid:blog_id>/toggle/', views.admin_toggle_blog_status, name='admin-toggle-blog'),
    path('api/admin/blog/<uuid:blog_id>/detail/', views.admin_blog_detail, name='admin-blog-detail'),
    path('api/admin/blog/search/', views.admin_blog_search_suggestions, name='admin-blog-search-suggestions'),
    
    path('admin/samples/', views.admin_samples, name='admin-samples'),
    path('admin/samples/<uuid:sample_id>/toggle/', views.admin_toggle_sample, name='admin-toggle-sample'),
    path('admin/samples/<uuid:sample_id>/delete/', views.admin_delete_sample, name='admin-delete-sample'),
    
    path('admin/content/', views.admin_content, name='admin-content'),
    path('admin/logs/', views.admin_logs, name='admin-logs'),
    path('admin/settings/', views.admin_settings, name='admin-settings'),
    path('admin/profile/', views.admin_profile, name='admin-profile'),
    path('admin/notifications/', views.admin_notifications, name='admin-notifications'),
    
    path('admin/', admin.site.urls),
    
    path('auth/', include('apps.accounts.urls')),
    path('api/auth/', include('apps.accounts.urls')),
    path('api/v1/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    path('api/v1/admin/', include('apps.admin_portal.urls')),
    path('api/v1/messaging/', include('apps.messaging.urls')),
    
    path('api/v1/orders/', include('apps.orders.urls')),
    path('api/v1/wallet/', include('apps.payments.urls')),
    
    path('api/v1/client/counts/', views.client_counts, name='client-counts'),
    path('api/v1/client/wallet/', views.client_wallet_data, name='client-wallet-data'),
    path('api/v1/client/orders/', views.client_orders_data, name='client-orders-data'),
    
    path('api/v1/admin/counts/', views.admin_counts, name='admin-counts'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)