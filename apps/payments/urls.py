from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('', views.get_wallet, name='wallet'),
    path('stats/', views.get_wallet_stats, name='wallet-stats'),
    path('transactions/', views.get_transactions, name='transactions'),
    path('transactions/<uuid:transaction_id>/', views.get_transaction_detail, name='transaction-detail'),
    path('withdraw/', views.request_withdrawal, name='withdraw'),
    path('withdraw/<uuid:payout_id>/status/', views.get_withdrawal_status, name='withdrawal-status'),
    path('payment-methods/', views.get_payment_methods, name='payment-methods'),
    path('payment-methods/<uuid:method_id>/remove/', views.remove_payment_method, name='remove-payment-method'),
    path('payment-methods/<uuid:method_id>/default/', views.set_default_payment_method, name='set-default-payment-method'),
    path('payouts/', views.get_payouts, name='payouts'),
    path('payouts/<uuid:payout_id>/', views.get_payout_detail, name='payout-detail'),
    path('webhook/paypal/', views.paypal_webhook, name='paypal-webhook'),
    path('stats/', views.get_payment_stats, name='payment-stats'),
    path('paypal/methods/', views.get_paypal_methods, name='paypal-methods'),
    path('paypal/methods/add/', views.add_paypal_method, name='add-paypal-method'),
    path('paypal/methods/verify/', views.verify_paypal_method, name='verify-paypal-method'),
    path('paypal/methods/resend-code/', views.resend_verification_code, name='resend-verification-code'),
    path('paypal/methods/check/', views.check_paypal_email, name='check-paypal-email'),
    path('paypal/deposit/', views.create_paypal_deposit, name='paypal-deposit'),
    path('paypal/deposit/execute/', views.execute_paypal_payment, name='paypal-execute'),
    path('paypal/deposit/cancel/', views.cancel_paypal_payment, name='paypal-cancel'),
]