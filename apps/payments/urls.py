from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('wallet/', views.get_wallet, name='wallet'),
    path('wallet/stats/', views.get_wallet_stats, name='wallet-stats'),
    
    path('transactions/', views.get_transactions, name='transactions'),
    path('transactions/<uuid:transaction_id>/', views.get_transaction_detail, name='transaction-detail'),
    
    path('deposit/', views.deposit, name='deposit'),
    path('deposit/confirm/', views.confirm_deposit, name='confirm-deposit'),
    
    path('withdraw/', views.request_withdrawal, name='withdraw'),
    path('withdraw/<uuid:payout_id>/status/', views.get_withdrawal_status, name='withdrawal-status'),
    
    path('hold/', views.hold_funds, name='hold-funds'),
    path('release/', views.release_funds, name='release-funds'),
    path('refund/', views.refund_funds, name='refund-funds'),
    
    path('payment-methods/', views.get_payment_methods, name='payment-methods'),
    path('payment-methods/add/', views.add_payment_method, name='add-payment-method'),
    path('payment-methods/<uuid:method_id>/remove/', views.remove_payment_method, name='remove-payment-method'),
    path('payment-methods/<uuid:method_id>/default/', views.set_default_payment_method, name='set-default-payment-method'),
    
    path('order/<uuid:order_id>/payment/', views.get_order_payment, name='order-payment'),
    path('order/<uuid:order_id>/payment/status/', views.get_order_payment_status, name='order-payment-status'),
    
    path('intent/<str:intent_id>/', views.get_payment_intent, name='payment-intent'),
    path('intent/<str:intent_id>/retry/', views.retry_payment, name='retry-payment'),
    path('intent/<str:intent_id>/cancel/', views.cancel_payment_intent, name='cancel-payment-intent'),
    
    path('payouts/', views.get_payouts, name='payouts'),
    path('payouts/<uuid:payout_id>/', views.get_payout_detail, name='payout-detail'),
    
    path('webhook/stripe/', views.stripe_webhook, name='stripe-webhook'),
    path('webhook/paypal/', views.paypal_webhook, name='paypal-webhook'),
    
    path('fraud/check/', views.fraud_check, name='fraud-check'),
    path('fraud/review/<uuid:fraud_id>/', views.review_fraud, name='review-fraud'),
    
    path('stats/', views.get_payment_stats, name='payment-stats'),
]