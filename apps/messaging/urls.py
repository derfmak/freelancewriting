from django.urls import path
from . import views

urlpatterns = [
    path('conversations/', views.get_conversations, name='conversations'),
    path('unread/', views.unread_count, name='unread-count'),
    path('order/<uuid:order_id>/', views.get_conversation, name='get-conversation'),
    path('order/<uuid:order_id>/send/', views.send_message, name='send-message'),
    path('order/<uuid:order_id>/read/', views.mark_read, name='mark-read'),
]