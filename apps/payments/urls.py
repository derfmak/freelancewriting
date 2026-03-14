from django.urls import path
from . import views

urlpatterns = [
    path('', views.get_wallet, name='wallet'),
    path('transactions/', views.get_transactions, name='transactions'),
    path('deposit/', views.deposit, name='deposit'),
    path('deposit/confirm/', views.confirm_deposit, name='confirm-deposit'),
    path('withdraw/', views.withdraw, name='withdraw'),
    path('payment-methods/', views.get_payment_methods, name='payment-methods'),
    path('payment-methods/add/', views.add_payment_method, name='add-payment-method'),
    path('payment-methods/<uuid:method_id>/', views.remove_payment_method, name='remove-payment-method'),
    path('payment-methods/<uuid:method_id>/default/', views.set_default_payment_method, name='set-default-payment-method'),
    path('order/<uuid:order_id>/payments/', views.get_order_payments, name='order-payments'),
    path('intent/<str:intent_id>/', views.get_payment_intent, name='payment-intent'),
    path('intent/<str:intent_id>/retry/', views.retry_payment, name='retry-payment'),
]