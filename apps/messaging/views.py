import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import Order
from apps.accounts.models import User
from .models import Conversation, Message, MessageStatus, TypingStatus
from .serializers import (
    ConversationSerializer,
    MessageCreateSerializer,
    MessageEditSerializer,
    MessageSerializer,
)

logger = logging.getLogger(__name__)

MESSAGES_PAGE_SIZE = 20
UNREAD_CACHE_TTL = 30
LIST_CACHE_TTL = 30


def broadcast(conversation_id, event_type, payload):
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(
            f'chat_{conversation_id}',
            {'type': event_type, 'payload': payload},
        )
    except Exception as e:
        logger.error(f"Broadcast error: {e}")


def invalidate_user_caches(*user_ids):
    for user_id in user_ids:
        if user_id:
            cache.delete(f'messaging_unread_{user_id}')
            cache.delete(f'messaging_list_{user_id}')


class ConversationAccessMixin:
    def get_conversation(self, order_id):
        try:
            order = get_object_or_404(Order, id=order_id)

            if self.request.user.role == 'client' and order.client_id != self.request.user.id:
                return None

            try:
                conversation = Conversation.objects.get(order=order)
                return conversation
            except Conversation.DoesNotExist:
                admin_user = User.objects.filter(role='admin').first()

                if not admin_user and self.request.user.role == 'admin':
                    admin_user = self.request.user

                if not admin_user:
                    logger.error(f"No admin user available to create conversation for order {order_id}")
                    return None

                conversation = Conversation.objects.create(
                    order=order,
                    client=order.client,
                    admin=admin_user,
                    last_message_at=timezone.now()
                )

                return conversation

        except Order.DoesNotExist:
            logger.warning(f"Order {order_id} not found")
            return None
        except Exception as e:
            logger.error(f"Error in get_conversation: {e}")
            return None


class MessageAccessMixin:
    def get_owned_message(self, message_id):
        return get_object_or_404(
            Message.objects.select_related('conversation'),
            id=message_id, sender=self.request.user,
        )


class ConversationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            cache_key = f'messaging_list_{request.user.id}'
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)

            if request.user.role == 'admin':
                conversations = Conversation.objects.filter(admin=request.user)
            else:
                conversations = Conversation.objects.filter(client=request.user)

            conversations = conversations.select_related(
                'order', 'client', 'admin',
            ).prefetch_related('messages').order_by('-last_message_at')

            data = ConversationSerializer(
                conversations, many=True, context={'request': request},
            ).data
            cache.set(cache_key, data, LIST_CACHE_TTL)
            return Response(data)
        except Exception as e:
            logger.error(f"ConversationListView error: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            cache_key = f'messaging_unread_{request.user.id}'
            cached = cache.get(cache_key)
            if cached is not None:
                return Response({'unread_count': cached})

            if request.user.role == 'admin':
                conversations = Conversation.objects.filter(admin=request.user)
            else:
                conversations = Conversation.objects.filter(client=request.user)

            total = sum(conversation.get_unread_count(request.user) for conversation in conversations)
            cache.set(cache_key, total, UNREAD_CACHE_TTL)
            return Response({'unread_count': total})
        except Exception as e:
            logger.error(f"UnreadCountView error: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ConversationDetailView(ConversationAccessMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        try:
            conversation = self.get_conversation(order_id)
            if conversation is None:
                return Response({'error': 'unauthorized or conversation not found'}, status=status.HTTP_403_FORBIDDEN)

            page = max(int(request.query_params.get('page', 1)), 1)
            start = (page - 1) * MESSAGES_PAGE_SIZE
            end = start + MESSAGES_PAGE_SIZE

            total_messages = conversation.messages.count()
            messages = list(
                conversation.messages.select_related('sender').order_by('-created_at')[start:end],
            )
            messages.reverse()

            updated = conversation.messages.filter(~Q(sender=request.user), is_read=False).update(
                is_read=True, read_at=timezone.now(),
            )
            MessageStatus.objects.filter(
                message__conversation=conversation, user=request.user, is_read=False,
            ).update(is_read=True, read_at=timezone.now())

            conversation.mark_seen(request.user)
            invalidate_user_caches(request.user.id)

            if updated:
                broadcast(conversation.id, 'message.read', {
                    'reader': str(request.user.id),
                    'read_at': timezone.now().isoformat(),
                })

            return Response({
                'conversation': ConversationSerializer(conversation, context={'request': request}).data,
                'messages': MessageSerializer(messages, many=True).data,
                'page': page,
                'has_more': total_messages > end,
            })
        except Exception as e:
            logger.error(f"ConversationDetailView error for order {order_id}: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SendMessageView(ConversationAccessMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        try:
            conversation = self.get_conversation(order_id)
            if conversation is None:
                return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

            serializer = MessageCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            message = Message.objects.create(
                conversation=conversation,
                sender=request.user,
                content=serializer.validated_data.get('content', ''),
                message_type=serializer.validated_data.get('message_type', Message.TEXT),
                file_url=serializer.validated_data.get('file_url', ''),
                file_name=serializer.validated_data.get('file_name', ''),
                file_size=serializer.validated_data.get('file_size'),
                is_delivered=True,
                delivered_at=timezone.now(),
            )

            conversation.last_message_at = message.created_at
            conversation.save(update_fields=['last_message_at'])

            recipient = conversation.admin if request.user == conversation.client else conversation.client
            if recipient:
                MessageStatus.objects.create(
                    message=message, user=recipient, is_delivered=True, delivered_at=timezone.now(),
                )

            invalidate_user_caches(request.user.id, recipient.id if recipient else None)

            output = MessageSerializer(message).data
            broadcast(conversation.id, 'message.sent', output)

            return Response(output, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"SendMessageView error: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MarkReadView(ConversationAccessMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        try:
            conversation = self.get_conversation(order_id)
            if conversation is None:
                return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

            message_ids = request.data.get('message_ids', [])
            now = timezone.now()

            messages = Message.objects.filter(
                Q(id__in=message_ids) if message_ids else Q(conversation=conversation),
                ~Q(sender=request.user),
                is_read=False,
            )
            updated = messages.update(is_read=True, read_at=now)
            MessageStatus.objects.filter(
                message__in=messages, user=request.user,
            ).update(is_read=True, read_at=now)

            conversation.mark_seen(request.user)
            invalidate_user_caches(request.user.id)

            if updated:
                broadcast(conversation.id, 'message.read', {
                    'reader': str(request.user.id),
                    'read_at': now.isoformat(),
                })

            return Response({'marked_read': updated})
        except Exception as e:
            logger.error(f"MarkReadView error: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TypingStatusView(ConversationAccessMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        try:
            conversation = self.get_conversation(order_id)
            if conversation is None:
                return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

            is_typing = bool(request.data.get('is_typing', False))
            TypingStatus.objects.update_or_create(
                conversation=conversation, user=request.user,
                defaults={'is_typing': is_typing},
            )

            broadcast(conversation.id, 'typing.start' if is_typing else 'typing.stop', {
                'user': str(request.user.id),
            })
            return Response({'is_typing': is_typing})
        except Exception as e:
            logger.error(f"TypingStatusView POST error: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get(self, request, order_id):
        try:
            conversation = self.get_conversation(order_id)
            if conversation is None:
                return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)

            other_user = conversation.admin if request.user == conversation.client else conversation.client
            typing = TypingStatus.objects.filter(
                conversation=conversation, user=other_user, is_typing=True,
            ).first()

            return Response({'is_typing': bool(typing)})
        except Exception as e:
            logger.error(f"TypingStatusView GET error: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MessageEditView(MessageAccessMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, message_id):
        try:
            message = self.get_owned_message(message_id)

            if not message.can_edit(request.user):
                return Response({'error': 'message cannot be edited'}, status=status.HTTP_400_BAD_REQUEST)

            serializer = MessageEditSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            message.edit(serializer.validated_data['content'])
            output = MessageSerializer(message).data
            broadcast(message.conversation_id, 'message.edited', output)
            return Response(output)
        except Exception as e:
            logger.error(f"MessageEditView error: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MessageRecallView(MessageAccessMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, message_id):
        try:
            message = self.get_owned_message(message_id)

            if not message.can_recall(request.user):
                return Response({'error': 'message cannot be recalled'}, status=status.HTTP_400_BAD_REQUEST)

            message.recall()
            output = MessageSerializer(message).data
            broadcast(message.conversation_id, 'message.recalled', output)
            return Response(output)
        except Exception as e:
            logger.error(f"MessageRecallView error: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MessageDeleteView(MessageAccessMixin, APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, message_id):
        try:
            message = self.get_owned_message(message_id)

            if not message.can_delete(request.user):
                return Response({'error': 'message cannot be deleted'}, status=status.HTTP_400_BAD_REQUEST)

            conversation_id = message.conversation_id
            deleted_id = str(message.id)
            message.delete()

            broadcast(conversation_id, 'message.deleted', {'message_id': deleted_id})
            return Response({'message': 'message deleted'})
        except Exception as e:
            logger.error(f"MessageDeleteView error: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)