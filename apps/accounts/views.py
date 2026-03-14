from rest_framework import status
from django.contrib.auth import login as django_login
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from django.db import transaction
from django.db.models import F
from .models import User, PendingUser
from .serializers import (
    RegisterSerializer, VerifyEmailSerializer, LoginSerializer,
    ForgotPasswordSerializer, ResetPasswordSerializer, 
    ChangePasswordSerializer, UserProfileSerializer
)
from .utils import (
    generate_verification_code, generate_reset_token,
    send_verification_email, send_password_reset_email,
    get_client_ip, get_client_user_agent
)
from .throttles import RegisterThrottle, LoginThrottle, PasswordResetThrottle

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    throttle = RegisterThrottle()
    if not throttle.allow_request(request, None):
        return Response({'error': 'too many registration attempts'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    # Check if user already exists
    if User.objects.filter(email=serializer.validated_data['email']).exists():
        return Response({'email': 'user already exists'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Delete any existing pending registration for this email
    PendingUser.objects.filter(email=serializer.validated_data['email']).delete()
    
    # Generate verification code
    verification_code = generate_verification_code()
    
    # Create pending user
    pending_user = PendingUser.objects.create(
        email=serializer.validated_data['email'],
        full_name=serializer.validated_data['full_name'],
        password=make_password(serializer.validated_data['password']),
        phone=serializer.validated_data.get('phone', ''),
        institution=serializer.validated_data.get('institution', ''),
        verification_code=verification_code,
        expires_at=timezone.now() + timezone.timedelta(hours=24)
    )
    
    # Send verification email
    send_verification_email(pending_user.email, verification_code)
    
    return Response({
        'message': 'Verification code sent. Please check your email.',
        'email': pending_user.email
    }, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_email(request):
    serializer = VerifyEmailSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    email = serializer.validated_data['email']
    code = serializer.validated_data['code']
    
    # Find pending user
    try:
        pending_user = PendingUser.objects.get(
            email=email,
            verification_code=code,
            expires_at__gt=timezone.now()
        )
    except PendingUser.DoesNotExist:
        return Response({'error': 'invalid or expired code'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Check if user already exists (prevent double creation)
    if User.objects.filter(email=email).exists():
        pending_user.delete()
        return Response({'error': 'user already exists'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Create actual user
    user = User.objects.create_user(
        email=pending_user.email,
        full_name=pending_user.full_name,
        password=pending_user.password,  # Password already hashed
        phone=pending_user.phone,
        institution=pending_user.institution,
        email_verified=True,
        is_active=True
    )
    
    # Delete pending user
    pending_user.delete()
    
    return Response({'message': 'email verified successfully. You can now login.'})

@api_view(['POST'])
@permission_classes([AllowAny])
def resend_verification(request):
    email = request.data.get('email')
    if not email:
        return Response({'error': 'email required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        pending_user = PendingUser.objects.get(email=email, expires_at__gt=timezone.now())
    except PendingUser.DoesNotExist:
        return Response({'error': 'no pending registration found or expired'}, status=status.HTTP_404_NOT_FOUND)
    
    # Generate new code
    new_code = generate_verification_code()
    pending_user.verification_code = new_code
    pending_user.expires_at = timezone.now() + timezone.timedelta(hours=24)
    pending_user.save(update_fields=['verification_code', 'expires_at'])
    
    send_verification_email(pending_user.email, new_code)
    return Response({'message': 'verification code resent'})

from django.conf import settings

@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    if not settings.DEBUG:
        throttle = LoginThrottle()
        if not throttle.allow_request(request, None):
            return Response({'error': 'too many login attempts'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = User.objects.get(email=serializer.validated_data['email'])
        
        if user.account_locked_until and user.account_locked_until > timezone.now():
            return Response({'error': 'account locked, try again later'}, status=status.HTTP_403_FORBIDDEN)
        
        if not user.email_verified:
            return Response({'error': 'email not verified'}, status=status.HTTP_403_FORBIDDEN)
        
        if user.is_suspended:
            return Response({'error': 'account suspended'}, status=status.HTTP_403_FORBIDDEN)
        
    except User.DoesNotExist:
        return Response({'error': 'invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
    
    authenticated_user = authenticate(
        request=request,  
        username=serializer.validated_data['email'],
        password=serializer.validated_data['password']
    )
    
    if not authenticated_user:
        user.increment_failed_login()
        return Response({'error': 'invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
    
    with transaction.atomic():
        user.reset_failed_login()
        user.last_login = timezone.now()
        user.last_login_ip = get_client_ip(request)
        user.last_login_user_agent = get_client_user_agent(request)
        user.save(update_fields=['last_login', 'last_login_ip', 'last_login_user_agent'])
    
    django_login(request, authenticated_user)
    
    refresh = RefreshToken.for_user(user)
    profile_serializer = UserProfileSerializer(user)
    
    return Response({
        'refresh': str(refresh),
        'access': str(refresh.access_token),
        'user': profile_serializer.data
    })

@api_view(['POST'])
def logout(request):
    try:
        refresh_token = request.data.get('refresh')
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
    except:
        pass
    return Response({'message': 'logged out successfully'})

@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    throttle = PasswordResetThrottle()
    if not throttle.allow_request(request, None):
        return Response({'error': 'too many attempts'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    
    serializer = ForgotPasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = User.objects.get(email=serializer.validated_data['email'])
    except User.DoesNotExist:
        return Response({'message': 'if email exists, reset link will be sent'})
    
    user.password_reset_token = generate_reset_token()
    user.password_reset_expires = timezone.now() + timezone.timedelta(hours=1)
    user.save(update_fields=['password_reset_token', 'password_reset_expires'])
    
    send_password_reset_email(user.email, user.password_reset_token)
    return Response({'message': 'if email exists, reset link will be sent'})

@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    serializer = ResetPasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = User.objects.get(
            password_reset_token=serializer.validated_data['token'],
            password_reset_expires__gt=timezone.now()
        )
    except User.DoesNotExist:
        return Response({'error': 'invalid or expired token'}, status=status.HTTP_400_BAD_REQUEST)
    
    user.set_password(serializer.validated_data['password'])
    user.password_reset_token = ''
    user.password_reset_expires = None
    user.save(update_fields=['password', 'password_reset_token', 'password_reset_expires'])
    
    return Response({'message': 'password reset successful'})

@api_view(['POST'])
def change_password(request):
    serializer = ChangePasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    user = request.user
    
    if not user.check_password(serializer.validated_data['old_password']):
        return Response({'old_password': 'incorrect password'}, status=status.HTTP_400_BAD_REQUEST)
    
    user.set_password(serializer.validated_data['new_password'])
    user.save(update_fields=['password'])
    
    return Response({'message': 'password changed successfully'})

@api_view(['GET', 'PUT'])
def profile(request):
    user = request.user
    
    if request.method == 'GET':
        serializer = UserProfileSerializer(user)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        serializer = UserProfileSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
def request_account_deletion(request):
    user = request.user
    
    user.deletion_requested_at = timezone.now()
    user.deletion_scheduled_for = timezone.now() + timezone.timedelta(days=30)
    user.save(update_fields=['deletion_requested_at', 'deletion_scheduled_for'])
    
    return Response({'message': 'deletion scheduled in 30 days, login to cancel'})

@api_view(['POST'])
def cancel_deletion(request):
    user = request.user
    
    user.deletion_requested_at = None
    user.deletion_scheduled_for = None
    user.save(update_fields=['deletion_requested_at', 'deletion_scheduled_for'])
    
    return Response({'message': 'deletion cancelled'})