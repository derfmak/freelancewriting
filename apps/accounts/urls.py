from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login, name='login'),
    path('refresh/', views.refresh_token, name='refresh-token'),
    path('register/', views.register, name='register'),
    path('logout/', views.logout, name='logout'),
    path('verify-otp/', views.verify_otp, name='verify-otp'),
    path('resend-otp/', views.resend_otp, name='resend-otp'),
    path('forgot-password/', views.forgot_password, name='forgot-password'),
    path('reset-password/', views.reset_password, name='reset-password'),
    path('change-password/', views.change_password, name='change-password'),
    path('profile/', views.profile, name='profile'),
    path('deletion/request/', views.request_deletion, name='request-deletion'),
    path('deletion/cancel/', views.cancel_deletion, name='cancel-deletion'),
    path('send-password-change-code/', views.send_password_change_code, name='send-password-change-code'),
    path('verify-password-change-code/', views.verify_password_change_code, name='verify-password-change-code'),
    path('complete-password-change/', views.complete_password_change, name='complete-password-change'),
    path('google/', views.google_login, name='google-login'),
    path('google/callback/', views.google_callback, name='google-callback'),
    path('google/signup/', views.google_signup, name='google-signup'),

    path('notifications/', views.client_notifications_list, name='client-notifications-list'),
    path('notifications/<uuid:notification_id>/read/', views.client_notification_mark_read, name='client-notification-mark-read'),
    path('notifications/mark-all-read/', views.client_notifications_mark_all_read, name='client-notifications-mark-all-read'),
    path('notifications/<uuid:notification_id>/delete/', views.client_notification_delete, name='client-notification-delete'),
    path('notifications/unread-count/', views.client_notifications_unread_count, name='client-notifications-unread-count'),
]