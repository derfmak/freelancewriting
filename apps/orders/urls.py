from django.urls import path
from . import views

urlpatterns = [
    path('', views.list_orders, name='list-orders'),
    path('create/', views.create_order, name='create-order'),
    path('<uuid:order_id>/', views.order_detail, name='order-detail'),
    path('<uuid:order_id>/action/', views.order_action, name='order-action'),
    path('<uuid:order_id>/rate/', views.rate_order, name='rate-order'),
]