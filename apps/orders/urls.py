from django.urls import path
from . import views

app_name = 'orders-api'

urlpatterns = [
    path('', views.my_orders, name='my-orders'),
    path('create/', views.create_order, name='create-order'),
    path('search/', views.search_orders, name='search-orders'),
    path('price-quote/', views.price_quote, name='price-quote'),
    
    path('<uuid:order_id>/', views.order_detail, name='order-detail'),
    path('<uuid:order_id>/timeline/', views.order_timeline, name='order-timeline'),
    path('<uuid:order_id>/history/', views.order_history, name='order-history'),
    
    path('<uuid:order_id>/cancel/', views.cancel_order, name='cancel-order'),
    path('<uuid:order_id>/decline/', views.decline_order, name='decline-order'),
    path('<uuid:order_id>/resubmit/', views.resubmit_order, name='resubmit-order'),
    path('<uuid:order_id>/reorder/', views.reorder_order, name='reorder-order'),
    path('<uuid:order_id>/split/', views.split_order, name='split-order'),
    
    path('<uuid:order_id>/accept/', views.accept_order, name='accept-order'),
    path('<uuid:order_id>/deliver/', views.deliver_order, name='deliver-order'),
    path('<uuid:order_id>/approve/', views.approve_order, name='approve-order'),
    
    path('<uuid:order_id>/revision/', views.request_revision, name='request-revision'),
    path('<uuid:order_id>/refund/', views.request_refund, name='request-refund'),
    path('<uuid:order_id>/rate/', views.rate_order, name='rate-order'),
    
    path('<uuid:order_id>/attachments/', views.list_attachments, name='list-attachments'),
    path('<uuid:order_id>/attachments/upload/', views.upload_attachment, name='upload-attachment'),
    
    path('<uuid:order_id>/capture-payment/', views.capture_order_payment, name='capture-order-payment'),
    
    path('writer/assigned/', views.assigned_orders, name='assigned-orders'),
    path('writer/available/', views.available_orders, name='available-orders'),
    
    path('presence/update/', views.update_presence, name='update-presence'),
    path('presence/<uuid:user_id>/', views.get_presence, name='get-presence'),
    path('<uuid:order_id>/presence/', views.get_online_status, name='get-online-status'),
]