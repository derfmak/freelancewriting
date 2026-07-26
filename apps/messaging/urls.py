from django.urls import path
from . import views

app_name = 'messaging'

urlpatterns = [
    path('conversations/', views.ConversationListView.as_view(), name='conversation-list'),
    path('unread/', views.UnreadCountView.as_view(), name='unread-count'),
    path('order/<uuid:order_id>/', views.ConversationDetailView.as_view(), name='conversation-detail'),
    path('order/<uuid:order_id>/send/', views.SendMessageView.as_view(), name='send-message'),
    path('order/<uuid:order_id>/read/', views.MarkReadView.as_view(), name='mark-read'),
    path('order/<uuid:order_id>/typing/', views.TypingStatusView.as_view(), name='typing-status'),
    path('message/<uuid:message_id>/edit/', views.MessageEditView.as_view(), name='message-edit'),
    path('message/<uuid:message_id>/recall/', views.MessageRecallView.as_view(), name='message-recall'),
    path('message/<uuid:message_id>/delete/', views.MessageDeleteView.as_view(), name='message-delete'),
]