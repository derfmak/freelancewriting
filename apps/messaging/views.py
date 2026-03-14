from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import models
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import Conversation, Message, MessageStatus, TypingStatus
from .serializers import (
    ConversationSerializer, MessageSerializer, MessageCreateSerializer,
    MessageEditSerializer, MessageRecallSerializer, TypingStatusSerializer
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_or_create_conversation(request, order_id):
    try:
        order = Order.objects.get(id=order_id, student=request.user)
        
        admin = User.objects.filter(role='admin').first()
        
        if not admin:
            return Response({'error': 'No admin available'}, status=status.HTTP_404_NOT_FOUND)
        
        conversation, created = Conversation.objects.get_or_create(
            order=order,
            defaults={
                'student': request.user,
                'admin': admin
            }
        )
        
        serializer = ConversationSerializer(conversation, context={'request': request})
        
        return Response({
            'conversation': serializer.data,
            'created': created
        })
        
    except Order.DoesNotExist:
        return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_conversations(request):
    user = request.user
    
    if user.role == 'admin':
        conversations = Conversation.objects.filter(admin=user)
    else:
        conversations = Conversation.objects.filter(student=user)
    
    conversations = conversations.select_related('order').prefetch_related(
        'messages'
    ).order_by('-last_message_at')
    
    serializer = ConversationSerializer(conversations, many=True, context={'request': request})
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_conversation(request, order_id):
    conversation = get_object_or_404(Conversation, order_id=order_id)
    
    if request.user.role != 'admin' and conversation.student != request.user:
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    messages = conversation.messages.all().order_by('created_at')
    
    unread_messages = messages.filter(
        ~Q(sender=request.user),
        is_read=False
    )
    for message in unread_messages:
        message.mark_as_read()
    
    if request.user == conversation.student:
        conversation.student_last_seen = timezone.now()
    elif request.user == conversation.admin:
        conversation.admin_last_seen = timezone.now()
    conversation.save(update_fields=['student_last_seen', 'admin_last_seen'])
    
    message_serializer = MessageSerializer(messages, many=True)
    conversation_serializer = ConversationSerializer(conversation, context={'request': request})
    
    return Response({
        'conversation': conversation_serializer.data,
        'messages': message_serializer.data
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_message(request, order_id):
    conversation = get_object_or_404(Conversation, order_id=order_id)
    
    if request.user.role != 'admin' and conversation.student != request.user:
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    serializer = MessageCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    message = Message.objects.create(
        conversation=conversation,
        sender=request.user,
        content=serializer.validated_data['content'],
        message_type=serializer.validated_data.get('message_type', 'text'),
        file_url=serializer.validated_data.get('file_url', ''),
        file_name=serializer.validated_data.get('file_name', ''),
        file_size=serializer.validated_data.get('file_size')
    )
    
    conversation.last_message_at = message.created_at
    conversation.save(update_fields=['last_message_at'])
    
    recipient = conversation.admin if request.user == conversation.student else conversation.student
    
    MessageStatus.objects.create(
        message=message,
        user=recipient,
        is_delivered=True,
        delivered_at=timezone.now()
    )
    
    return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_read(request, order_id):
    conversation = get_object_or_404(Conversation, order_id=order_id)
    
    if request.user.role != 'admin' and conversation.student != request.user:
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    message_ids = request.data.get('message_ids', [])
    
    messages = Message.objects.filter(
        Q(id__in=message_ids) if message_ids else Q(conversation=conversation),
        ~Q(sender=request.user),
        is_read=False
    )
    
    for message in messages:
        message.mark_as_read()
        
        MessageStatus.objects.filter(
            message=message,
            user=request.user
        ).update(
            is_read=True,
            read_at=timezone.now()
        )
    
    if request.user == conversation.student:
        conversation.student_last_seen = timezone.now()
    elif request.user == conversation.admin:
        conversation.admin_last_seen = timezone.now()
    conversation.save(update_fields=['student_last_seen', 'admin_last_seen'])
    
    return Response({'message': 'messages marked as read'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_delivered(request, order_id):
    conversation = get_object_or_404(Conversation, order_id=order_id)
    
    if request.user.role != 'admin' and conversation.student != request.user:
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    message_ids = request.data.get('message_ids', [])
    
    messages = Message.objects.filter(
        Q(id__in=message_ids) if message_ids else Q(conversation=conversation),
        ~Q(sender=request.user)
    )
    
    for message in messages:
        MessageStatus.objects.get_or_create(
            message=message,
            user=request.user,
            defaults={
                'is_delivered': True,
                'delivered_at': timezone.now()
            }
        )
    
    return Response({'message': 'messages marked as delivered'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def edit_message(request, message_id):
    message = get_object_or_404(Message, id=message_id, sender=request.user)
    
    if message.created_at < timezone.now() - timezone.timedelta(minutes=5):
        return Response({'error': 'messages can only be edited within 5 minutes'}, status=status.HTTP_400_BAD_REQUEST)
    
    if message.is_recalled:
        return Response({'error': 'cannot edit recalled message'}, status=status.HTTP_400_BAD_REQUEST)
    
    serializer = MessageEditSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    message.edit(serializer.validated_data['content'])
    
    return Response(MessageSerializer(message).data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def recall_message(request, message_id):
    message = get_object_or_404(Message, id=message_id, sender=request.user)
    
    if message.created_at < timezone.now() - timezone.timedelta(minutes=1):
        return Response({'error': 'messages can only be recalled within 1 minute'}, status=status.HTTP_400_BAD_REQUEST)
    
    if message.is_recalled:
        return Response({'error': 'message already recalled'}, status=status.HTTP_400_BAD_REQUEST)
    
    message.recall()
    
    return Response(MessageSerializer(message).data)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_message(request, message_id):
    message = get_object_or_404(Message, id=message_id, sender=request.user)
    
    if message.created_at < timezone.now() - timezone.timedelta(minutes=5):
        return Response({'error': 'messages can only be deleted within 5 minutes'}, status=status.HTTP_400_BAD_REQUEST)
    
    message.delete()
    
    return Response({'message': 'message deleted'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unread_count(request):
    user = request.user
    
    if user.role == 'admin':
        conversations = Conversation.objects.filter(admin=user)
    else:
        conversations = Conversation.objects.filter(student=user)
    
    total_unread = 0
    for conv in conversations:
        total_unread += conv.get_unread_count(user)
    
    return Response({'unread_count': total_unread})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def typing_status(request, order_id):
    conversation = get_object_or_404(Conversation, order_id=order_id)
    
    if request.user.role != 'admin' and conversation.student != request.user:
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    is_typing = request.data.get('is_typing', False)
    
    typing_status, created = TypingStatus.objects.update_or_create(
        conversation=conversation,
        user=request.user,
        defaults={'is_typing': is_typing}
    )
    
    if not is_typing:
        typing_status.delete()
    
    return Response({'is_typing': is_typing})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_typing_status(request, order_id):
    conversation = get_object_or_404(Conversation, order_id=order_id)
    
    if request.user.role != 'admin' and conversation.student != request.user:
        return Response({'error': 'unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    other_user = conversation.admin if request.user == conversation.student else conversation.student
    
    typing_status = TypingStatus.objects.filter(
        conversation=conversation,
        user=other_user,
        is_typing=True
    ).first()
    
    return Response({
        'is_typing': typing_status.is_typing if typing_status else False
    })