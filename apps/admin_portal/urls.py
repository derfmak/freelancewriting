from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard_stats, name='dashboard'),
    
    path('users/', views.list_users, name='list-users'),
    path('users/<uuid:user_id>/', views.user_detail, name='user-detail'),
    path('users/<uuid:user_id>/suspend/', views.suspend_user, name='suspend-user'),
    path('users/<uuid:user_id>/reactivate/', views.reactivate_user, name='reactivate-user'),
    path('users/<uuid:user_id>/delete/', views.delete_user, name='delete-user'),
    
    path('orders/', views.list_orders, name='list-orders'),
    path('orders/<uuid:order_id>/', views.order_detail, name='order-detail'),
    path('orders/<uuid:order_id>/approve/', views.approve_order, name='approve-order'),
    path('orders/<uuid:order_id>/reject/', views.reject_order, name='reject-order'),
    path('orders/<uuid:order_id>/deliver/', views.deliver_order, name='deliver-order'),
    
    path('refunds/', views.refund_requests, name='refund-requests'),
    path('refunds/<uuid:order_id>/approve/', views.approve_refund, name='approve-refund'),
    path('refunds/<uuid:order_id>/deny/', views.deny_refund, name='deny-refund'),
    
    path('transactions/', views.list_transactions, name='list-transactions'),
    path('wallet/adjust/', views.adjust_wallet, name='adjust-wallet'),
    
    path('settings/', views.list_settings, name='list-settings'),
    path('settings/<uuid:setting_id>/', views.update_setting, name='update-setting'),
    
    path('content/', views.list_content, name='list-content'),
    path('content/<uuid:content_id>/', views.update_content, name='update-content'),
    
    path('announcements/', views.list_announcements, name='list-announcements'),
    path('announcements/create/', views.create_announcement, name='create-announcement'),
    path('announcements/<uuid:announcement_id>/', views.update_announcement, name='update-announcement'),
    path('announcements/<uuid:announcement_id>/delete/', views.delete_announcement, name='delete-announcement'),
    
    path('logs/', views.list_logs, name='list-logs'),
]