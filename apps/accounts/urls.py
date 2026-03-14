from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('verify-email/', views.verify_email, name='verify-email'),
    path('resend-code/', views.resend_verification, name='resend-code'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    path('forgot-password/', views.forgot_password, name='forgot-password'),
    path('reset-password/', views.reset_password, name='reset-password'),
    path('change-password/', views.change_password, name='change-password'),
    path('profile/', views.profile, name='profile'),
    path('deletion/request/', views.request_account_deletion, name='request-deletion'),
    path('deletion/cancel/', views.cancel_deletion, name='cancel-deletion'),
]