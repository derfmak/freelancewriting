import logging
import secrets
import requests
import hashlib
from django.shortcuts import redirect, get_object_or_404
from django.core.cache import cache
from django.db import transaction, IntegrityError
from django.contrib.auth import login as django_login, authenticate, logout as auth_logout
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import User, PendingUser, LoginLog, SecurityEvent, ClientNotification, PasswordChangeVerification
from .serializers import (
    RegisterSerializer, OTPVerificationSerializer, ResendOTPSerializer,
    LoginSerializer, ForgotPasswordSerializer, ResetPasswordSerializer,
    ChangePasswordSerializer, UserProfileSerializer, UserSerializer,
    SendPasswordChangeCodeSerializer, VerifyPasswordChangeCodeSerializer,
    CompletePasswordChangeSerializer, ResendPasswordChangeCodeSerializer,
    GoogleLoginSerializer, UserListSerializer,
)
from .utils import (
    generate_otp, generate_reset_token, generate_password_change_code,
    send_otp_email, send_password_reset_email, send_password_change_code_email,
    get_client_ip, get_client_user_agent, generate_apple_client_secret,
    log_security_event,
)

logger = logging.getLogger(__name__)


def verify_google_token(access_token, id_token, client_id):
    if id_token:
        try:
            response = requests.get(
                f'https://oauth2.googleapis.com/tokeninfo?id_token={id_token}',
                timeout=10
            )
            response.raise_for_status()
            token_info = response.json()
            if token_info.get('aud') != client_id:
                logger.warning(f"Google token audience mismatch: expected {client_id}, got {token_info.get('aud')}")
                return None
            if token_info.get('iss') not in ['accounts.google.com', 'https://accounts.google.com']:
                logger.warning(f"Google token issuer mismatch: {token_info.get('iss')}")
                return None
            if int(token_info.get('exp', 0)) < timezone.now().timestamp():
                logger.warning("Google token expired")
                return None
            return token_info
        except Exception as e:
            logger.error(f"Google ID token verification failed: {str(e)}")
            return None
    if access_token:
        try:
            response = requests.get(
                'https://www.googleapis.com/oauth2/v3/userinfo',
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Google access token verification failed: {str(e)}")
            return None
    return None


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def register(request):
    ip = get_client_ip(request)
    rate_key = f'register_rate:{ip}'
    limit = 5
    window = 3600
    count = cache.get(rate_key, 0)
    if count >= limit:
        log_security_event(
            'rate_limit_hit',
            ip,
            get_client_user_agent(request),
            metadata={'endpoint': 'register'}
        )
        return Response(
            {'error': 'Too many registration attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    cache.set(rate_key, count + 1, window)

    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data['email']

    existing_user = User.objects.filter(email=email).first()
    if existing_user and existing_user.email_verified:
        log_security_event(
            'register_duplicate',
            ip,
            get_client_user_agent(request),
            metadata={'email': email}
        )
        return Response(
            {
                'error': 'An account with this email already exists. Please sign in.',
                'redirect': f'/login/?email={email}'
            },
            status=status.HTTP_409_CONFLICT
        )

    pending = PendingUser.objects.filter(email=email).first()
    if pending and pending.is_expired():
        pending.delete()
        pending = None

    if not pending:
        if existing_user:
            pending = PendingUser.objects.create(
                email=email,
                full_name=existing_user.full_name,
                password=existing_user.password,
                phone=existing_user.phone,
                institution=existing_user.institution,
                otp_code_hash='',
                otp_expires=timezone.now() + timezone.timedelta(minutes=10),
                ip_address=ip
            )
        else:
            pending = PendingUser.objects.create(
                email=email,
                full_name=serializer.validated_data['full_name'],
                password=make_password(serializer.validated_data['password']),
                phone=serializer.validated_data.get('phone', ''),
                institution=serializer.validated_data.get('institution', ''),
                otp_code_hash='',
                otp_expires=timezone.now() + timezone.timedelta(minutes=10),
                ip_address=ip
            )

    otp = generate_otp()
    pending.set_otp(otp)
    email_sent = send_otp_email(email, otp, pending.full_name)

    if not email_sent:
        pending.delete()
        log_security_event(
            'email_send_failed',
            ip,
            get_client_user_agent(request),
            metadata={'email': email}
        )
        return Response(
            {'error': 'Failed to send verification email. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    log_security_event(
        'register_attempt',
        ip,
        get_client_user_agent(request),
        metadata={'email': email}
    )

    return Response({
        'require_verification': True,
        'email': email,
        'redirect': f'/login/?require_verification=true&email={email}'
    }, status=status.HTTP_201_CREATED if not existing_user else status.HTTP_409_CONFLICT)


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def verify_otp(request):
    ip = get_client_ip(request)
    rate_key = f'verify_otp_rate:{ip}'
    limit = 10
    window = 3600
    count = cache.get(rate_key, 0)
    if count >= limit:
        return Response(
            {'error': 'Too many verification attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    cache.set(rate_key, count + 1, window)

    serializer = OTPVerificationSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data['email']
    otp = serializer.validated_data['otp_code']

    lock_key = f'otp_lock_{email}'
    attempts_key = f'otp_attempts_{email}'

    if cache.get(lock_key):
        log_security_event('otp_verification_locked', ip, get_client_user_agent(request), metadata={'email': email})
        return Response(
            {'error': 'Too many failed attempts. Please wait 30 minutes before trying again.'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        pending_user = PendingUser.objects.get(email=email)
    except PendingUser.DoesNotExist:
        log_security_event('otp_verification_failed', ip, get_client_user_agent(request), metadata={'email': email})
        return Response(
            {'error': 'No pending registration found. Please register again.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not pending_user.verify_otp(otp):
        attempts = cache.get(attempts_key, 0) + 1
        cache.set(attempts_key, attempts, timeout=1800)
        remaining = 3 - attempts

        if attempts >= 3:
            cache.set(lock_key, True, timeout=1800)
            log_security_event('otp_verification_locked', ip, get_client_user_agent(request), metadata={'email': email, 'attempts': attempts})
            return Response(
                {'error': 'Too many failed attempts. Your account is locked for 30 minutes.'},
                status=status.HTTP_403_FORBIDDEN
            )

        log_security_event('otp_verification_failed', ip, get_client_user_agent(request), metadata={'email': email, 'remaining_attempts': remaining})
        return Response(
            {'error': f'Invalid or expired verification code. {remaining} attempt(s) remaining.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    cache.delete(attempts_key)
    cache.delete(lock_key)

    user = User.objects.filter(email=email).first()
    if user:
        if not user.email_verified:
            user.email_verified = True
            user.save(update_fields=['email_verified'])
        pending_user.delete()
        log_security_event('verification_success_existing_user', ip, get_client_user_agent(request), user=user, metadata={'email': email})
        return Response({
            'message': 'Email verified successfully. You can now login.',
            'verified': True
        }, status=status.HTTP_200_OK)

    try:
        with transaction.atomic():
            user = User(
                email=pending_user.email,
                full_name=pending_user.full_name,
                phone=pending_user.phone,
                institution=pending_user.institution,
                email_verified=True,
                is_active=True,
                role='client'
            )
            user.password = pending_user.password
            user.save()
            pending_user.delete()
    except IntegrityError:
        user = User.objects.get(email=email)
        if not user.email_verified:
            user.email_verified = True
            user.save(update_fields=['email_verified'])
        pending_user.delete()
        log_security_event('verification_success_existing_user', ip, get_client_user_agent(request), user=user, metadata={'email': email})
        return Response({
            'message': 'Email verified successfully. You can now login.',
            'verified': True
        }, status=status.HTTP_200_OK)
    except Exception as e:
        log_security_event('user_creation_failed', ip, get_client_user_agent(request), metadata={'email': email, 'error': str(e)})
        return Response(
            {'error': f'Failed to create account: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    log_security_event('register_success', ip, get_client_user_agent(request), user=user, metadata={'email': email})
    return Response({
        'message': 'Email verified successfully. You can now login.',
        'verified': True
    }, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def resend_otp(request):
    ip = get_client_ip(request)
    rate_key = f'resend_otp_rate:{ip}'
    limit = 5
    window = 3600
    count = cache.get(rate_key, 0)
    if count >= limit:
        return Response(
            {'error': 'Too many resend attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    cache.set(rate_key, count + 1, window)

    serializer = ResendOTPSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data['email']

    lock_key = f'otp_lock_{email}'
    resend_key = f'otp_resend_{email}'

    if cache.get(lock_key):
        log_security_event(
            'otp_resend_blocked_locked',
            ip,
            get_client_user_agent(request),
            metadata={'email': email}
        )
        return Response(
            {'error': 'This email is temporarily locked. Please wait 30 minutes.'},
            status=status.HTTP_403_FORBIDDEN
        )

    resend_count = cache.get(resend_key, 0)
    if resend_count >= 3:
        log_security_event(
            'otp_resend_limit_reached',
            ip,
            get_client_user_agent(request),
            metadata={'email': email, 'attempts': resend_count}
        )
        return Response(
            {'error': 'Maximum resend limit reached. Please register again.'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        pending_user = PendingUser.objects.get(email=email)
    except PendingUser.DoesNotExist:
        log_security_event(
            'otp_resend_no_pending',
            ip,
            get_client_user_agent(request),
            metadata={'email': email}
        )
        return Response(
            {'error': 'No pending registration found. Please register first.'},
            status=status.HTTP_404_NOT_FOUND
        )

    if pending_user.is_expired():
        pending_user.delete()
        cache.delete(resend_key)
        cache.delete(lock_key)
        return Response(
            {'error': 'Your registration has expired. Please register again.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    new_otp = generate_otp()
    pending_user.set_otp(new_otp)

    email_sent = send_otp_email(email, new_otp, pending_user.full_name)
    if not email_sent:
        pending_user.delete()
        log_security_event(
            'otp_resend_email_failed',
            ip,
            get_client_user_agent(request),
            metadata={'email': email}
        )
        return Response(
            {'error': 'Failed to send verification email. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    cache.set(resend_key, resend_count + 1, timeout=3600)
    log_security_event(
        'otp_resend_success',
        ip,
        get_client_user_agent(request),
        metadata={'email': email, 'remaining': 2 - resend_count}
    )

    return Response({
        'message': 'New verification code sent to your email.',
        'remaining_attempts': 2 - resend_count,
        'email': email
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def login(request):
    ip = get_client_ip(request)
    rate_key = f'login_rate:{ip}'
    limit = 10
    window = 3600
    count = cache.get(rate_key, 0)
    if count >= limit:
        log_security_event('rate_limit_hit', ip, get_client_user_agent(request), metadata={'endpoint': 'login'})
        return Response(
            {'error': 'Too many login attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    cache.set(rate_key, count + 1, window)

    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data['email']
    password = serializer.validated_data['password']
    remember = request.data.get('remember', False)

    user = User.objects.filter(email=email).first()

    if user:
        if not user.email_verified:
            pending = PendingUser.objects.filter(email=email).first()
            if not pending:
                pending = PendingUser.objects.create(
                    email=email,
                    full_name=user.full_name,
                    password=user.password,
                    phone=user.phone,
                    institution=user.institution,
                    otp_code_hash='',
                    otp_expires=timezone.now() + timezone.timedelta(minutes=10),
                    ip_address=ip
                )
            elif pending.is_expired():
                pending.delete()
                pending = PendingUser.objects.create(
                    email=email,
                    full_name=user.full_name,
                    password=user.password,
                    phone=user.phone,
                    institution=user.institution,
                    otp_code_hash='',
                    otp_expires=timezone.now() + timezone.timedelta(minutes=10),
                    ip_address=ip
                )
            otp = generate_otp()
            pending.set_otp(otp)
            email_sent = send_otp_email(email, otp, pending.full_name)
            if not email_sent:
                pending.delete()
                log_security_event('email_send_failed', ip, get_client_user_agent(request), metadata={'email': email})
                return Response(
                    {'error': 'Failed to send verification email. Please try again.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            log_security_event('login_unverified', ip, get_client_user_agent(request), user=user, metadata={'email': email})
            return Response(
                {
                    'error': 'Email not verified. A new verification code has been sent.',
                    'require_verification': True,
                    'email': email,
                    'redirect': f'/login/?require_verification=true&email={email}'
                },
                status=status.HTTP_403_FORBIDDEN
            )

        if user.account_locked_until and user.account_locked_until > timezone.now():
            log_security_event('account_locked', ip, get_client_user_agent(request), user=user)
            return Response(
                {'error': 'Account locked due to multiple failed attempts. Try again later.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if user.is_suspended:
            if user.suspended_until and user.suspended_until > timezone.now():
                return Response(
                    {'error': f'Account suspended until {user.suspended_until.strftime("%Y-%m-%d %H:%M")}'},
                    status=status.HTTP_403_FORBIDDEN
                )
            else:
                user.is_suspended = False
                user.suspension_reason = ''
                user.suspended_until = None
                user.save(update_fields=['is_suspended', 'suspension_reason', 'suspended_until'])

        authenticated_user = authenticate(request=request, username=email, password=password)
        if not authenticated_user:
            user.increment_failed_login()
            LoginLog.objects.create(
                user=user,
                email=email,
                ip_address=ip,
                user_agent=get_client_user_agent(request),
                success=False
            )
            log_security_event('login_failed', ip, get_client_user_agent(request), user=user)
            return Response(
                {'error': 'Invalid password. Please try again.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        with transaction.atomic():
            user.reset_failed_login()
            user.last_login = timezone.now()
            user.last_login_ip = ip
            user.last_login_user_agent = get_client_user_agent(request)
            user.save(update_fields=['last_login', 'last_login_ip', 'last_login_user_agent'])

        django_login(request, authenticated_user)

        LoginLog.objects.create(
            user=user,
            email=email,
            ip_address=ip,
            user_agent=get_client_user_agent(request),
            success=True
        )

        refresh = RefreshToken.for_user(user)
        refresh['email'] = user.email
        refresh['role'] = user.role
        refresh['full_name'] = user.full_name

        if not remember:
            request.session.set_expiry(0)

        profile_serializer = UserProfileSerializer(user)

        response = Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': profile_serializer.data,
            'access_expires_in': 3600,
            'refresh_expires_in': 604800
        }, status=status.HTTP_200_OK)

        response.set_cookie(
            'access_token',
            str(refresh.access_token),
            max_age=3600,
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax',
            path='/'
        )
        response.set_cookie(
            'refresh_token',
            str(refresh),
            max_age=604800,
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax',
            path='/'
        )

        log_security_event('login_success', ip, get_client_user_agent(request), user=user)
        return response

    pending = PendingUser.objects.filter(email=email).first()

    if pending:
        if pending.is_expired():
            pending.delete()
            log_security_event('login_pending_expired', ip, get_client_user_agent(request), metadata={'email': email})
            return Response(
                {
                    'error': 'Your registration has expired. Please register again.',
                    'redirect': f'/register/?email={email}'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        otp = generate_otp()
        pending.set_otp(otp)
        email_sent = send_otp_email(email, otp, pending.full_name)

        if not email_sent:
            pending.delete()
            log_security_event('email_send_failed', ip, get_client_user_agent(request), metadata={'email': email})
            return Response(
                {'error': 'Failed to send verification email. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        log_security_event('login_pending_verification_sent', ip, get_client_user_agent(request), metadata={'email': email})
        return Response(
            {
                'error': 'Please verify your email before logging in.',
                'require_verification': True,
                'email': email,
                'redirect': f'/login/?require_verification=true&email={email}'
            },
            status=status.HTTP_403_FORBIDDEN
        )

    LoginLog.objects.create(
        email=email,
        ip_address=ip,
        user_agent=get_client_user_agent(request),
        success=False
    )
    log_security_event('login_user_not_found', ip, get_client_user_agent(request), metadata={'email': email})
    return Response(
        {
            'error': 'No account found with this email address.',
            'redirect': f'/register/?email={email}'
        },
        status=status.HTTP_404_NOT_FOUND
    )


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def refresh_token(request):
    try:
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            refresh_token = request.COOKIES.get('refresh_token')

        if not refresh_token:
            return Response(
                {'error': 'Refresh token is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        refresh = RefreshToken(refresh_token)
        access_token = str(refresh.access_token)

        response = Response({
            'access': access_token,
            'access_expires_in': 3600
        }, status=status.HTTP_200_OK)

        response.set_cookie(
            'access_token',
            access_token,
            max_age=3600,
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax',
            path='/'
        )

        return response
    except Exception:
        log_security_event(
            'token_refresh_failed',
            get_client_ip(request),
            get_client_user_agent(request)
        )
        return Response(
            {'error': 'Invalid refresh token'},
            status=status.HTTP_401_UNAUTHORIZED
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    try:
        refresh_token = request.data.get('refresh') or request.COOKIES.get('refresh_token')
        if refresh_token:
            RefreshToken(refresh_token).blacklist()
    except Exception:
        pass
    auth_logout(request)
    response = Response({'message': 'Successfully logged out'}, status=status.HTTP_200_OK)
    response.delete_cookie('access_token', path='/')
    response.delete_cookie('refresh_token', path='/')
    return response


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def forgot_password(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def reset_password(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def profile(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_deletion(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_deletion(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_password_change_code(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resend_password_change_code(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_password_change_code(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_password_change(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def google_login(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['GET'])
@permission_classes([AllowAny])
def google_callback(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def google_signup(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def apple_login(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['GET'])
@permission_classes([AllowAny])
def apple_callback(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def apple_signup(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_notifications_list(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_notification_mark_read(request, notification_id):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_notifications_mark_all_read(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def client_notification_delete(request, notification_id):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_notifications_unread_count(request):
    return Response({'error': 'Not implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@authentication_classes([JWTAuthentication])
def logout(request):
    try:
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            refresh_token = request.COOKIES.get('refresh_token')

        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
    except Exception:
        pass

    auth_logout(request)

    response = Response({
        'message': 'Logged out successfully'
    }, status=status.HTTP_200_OK)

    response.delete_cookie('access_token')
    response.delete_cookie('refresh_token')

    return response


@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    throttle = PasswordResetThrottle()
    if not throttle.allow_request(request, None):
        return Response(
            {'error': 'Too many attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )

    serializer = ForgotPasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data['email']

    try:
        user = User.objects.get(email=email)
        token = user.generate_reset_token()
        email_sent = send_password_reset_email(email, token, user.full_name)
        if not email_sent:
            logger.error(f"Failed to send password reset email to {email}")
    except User.DoesNotExist:
        pass

    return Response({
        'message': 'If an account exists with this email, a reset link has been sent.'
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    serializer = ResetPasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    token = serializer.validated_data['token']
    email = request.data.get('email')
    ip = get_client_ip(request)

    if not email:
        return Response({'error': 'email is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({'error': 'Invalid or expired reset token.'}, status=status.HTTP_400_BAD_REQUEST)

    if not user.verify_reset_token(token):
        return Response({'error': 'Invalid or expired reset token.'}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(serializer.validated_data['password'])
    user.clear_reset_token()
    user.save(update_fields=['password', 'password_reset_token_hash', 'password_reset_expires'])

    log_security_event(
        'password_reset',
        ip,
        get_client_user_agent(request),
        user=user
    )

    return Response({
        'message': 'Password reset successful. You can now login.'
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    serializer = ChangePasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    current_password = serializer.validated_data['current_password']
    new_password = serializer.validated_data['new_password']

    if not user.check_password(current_password):
        return Response(
            {'current_password': 'Current password is incorrect.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if user.check_password(new_password):
        return Response(
            {'new_password': 'New password must be different from current password.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user.set_password(new_password)
    user.save(update_fields=['password'])

    log_security_event(
        'password_changed',
        get_client_ip(request),
        get_client_user_agent(request),
        user=user
    )

    return Response(
        {'message': 'Password changed successfully.'},
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_password_change_code(request):
    ip = get_client_ip(request)
    rate_key = f'password_change_code_rate:{ip}'
    limit = 3
    window = 3600
    count = cache.get(rate_key, 0)
    if count >= limit:
        return Response(
            {'error': 'Too many attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    cache.set(rate_key, count + 1, window)

    serializer = SendPasswordChangeCodeSerializer(data=request.data)
    if not serializer.is_valid():
        errors = []
        for field, msgs in serializer.errors.items():
            errors.extend(msgs)
        return Response(
            {'error': ' '.join(errors) or 'Invalid input.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = request.user
    current_password = serializer.validated_data['current_password']
    new_password = serializer.validated_data['new_password']

    if not user.check_password(current_password):
        return Response(
            {'error': 'Current password is incorrect.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if user.check_password(new_password):
        return Response(
            {'error': 'New password must be different from current password.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    code = generate_password_change_code()
    verification = PasswordChangeVerification.objects.create(
        user=user,
        code_hash='',
        expires_at=timezone.now() + timezone.timedelta(minutes=5),
        temp_password_hash=make_password(new_password)
    )
    verification.set_code(code)

    email_sent = send_password_change_code_email(user.email, code, user.full_name)

    if not email_sent:
        if settings.DEBUG:
            logger.info(f"Password change code for {user.email}: {code}")
            return Response({
                'message': 'Verification code generated (email not sent in DEBUG mode).',
                'verification_id': str(verification.id),
                'expires_in': 300,
                'debug_code': code
            }, status=status.HTTP_200_OK)
        else:
            verification.delete()
            return Response(
                {'error': 'Failed to send verification code. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    return Response({
        'message': 'Verification code sent to your email.',
        'verification_id': str(verification.id),
        'expires_in': 300
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_password_change_code(request):
    ip = get_client_ip(request)
    rate_key = f'password_change_verify_rate:{ip}'
    limit = 10
    window = 3600
    count = cache.get(rate_key, 0)
    if count >= limit:
        return Response(
            {'error': 'Too many verification attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    cache.set(rate_key, count + 1, window)

    serializer = VerifyPasswordChangeCodeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    code = serializer.validated_data['code']
    verification_id = serializer.validated_data['verification_id']

    try:
        verification = PasswordChangeVerification.objects.get(
            id=verification_id,
            user=user,
            used=False,
            expires_at__gt=timezone.now()
        )
    except PasswordChangeVerification.DoesNotExist:
        return Response(
            {'error': 'Invalid or expired verification session.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not verification.verify_code(code):
        return Response(
            {'error': 'Invalid verification code.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user.password = verification.temp_password_hash
    user.save(update_fields=['password'])

    verification.used = True
    verification.save(update_fields=['used'])

    auth_logout(request)

    try:
        refresh_token = request.COOKIES.get('refresh_token')
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
    except Exception:
        pass

    response = Response({
        'message': 'Password changed successfully. Please log in with your new password.',
        'redirect': '/login/'
    }, status=status.HTTP_200_OK)

    response.delete_cookie('access_token')
    response.delete_cookie('refresh_token')

    log_security_event(
        'password_changed_via_code',
        get_client_ip(request),
        get_client_user_agent(request),
        user=user
    )

    return response


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resend_password_change_code(request):
    ip = get_client_ip(request)
    rate_key = f'resend_password_change_code_rate:{ip}'
    limit = 3
    window = 3600
    count = cache.get(rate_key, 0)
    if count >= limit:
        return Response(
            {'error': 'Too many resend attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    cache.set(rate_key, count + 1, window)

    serializer = ResendPasswordChangeCodeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    verification_id = serializer.validated_data.get('verification_id')

    if verification_id:
        try:
            verification = PasswordChangeVerification.objects.get(
                id=verification_id,
                user=user,
                used=False,
                expires_at__gt=timezone.now()
            )
        except PasswordChangeVerification.DoesNotExist:
            return Response(
                {'error': 'Invalid or expired verification session.'},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        verification = PasswordChangeVerification.objects.filter(
            user=user,
            used=False,
            expires_at__gt=timezone.now()
        ).order_by('-created_at').first()
        if not verification:
            return Response(
                {'error': 'No pending verification found. Please request a new code.'},
                status=status.HTTP_400_BAD_REQUEST
            )

    verification.delete()

    new_code = generate_password_change_code()
    new_verification = PasswordChangeVerification.objects.create(
        user=user,
        code_hash='',
        expires_at=timezone.now() + timezone.timedelta(minutes=5),
        temp_password_hash=verification.temp_password_hash
    )
    new_verification.set_code(new_code)

    email_sent = send_password_change_code_email(user.email, new_code, user.full_name)

    if not email_sent:
        if settings.DEBUG:
            logger.info(f"Resent password change code for {user.email}: {new_code}")
            return Response({
                'message': 'Verification code regenerated (email not sent in DEBUG mode).',
                'verification_id': str(new_verification.id),
                'expires_in': 300,
                'debug_code': new_code
            }, status=status.HTTP_200_OK)
        else:
            new_verification.delete()
            return Response(
                {'error': 'Failed to send verification code. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    return Response({
        'message': 'New verification code sent to your email.',
        'verification_id': str(new_verification.id),
        'expires_in': 300
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_password_change(request):
    serializer = CompletePasswordChangeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    current_password = serializer.validated_data['current_password']
    new_password = serializer.validated_data['new_password']

    if not user.check_password(current_password):
        return Response(
            {'current_password': 'Current password is incorrect.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if user.check_password(new_password):
        return Response(
            {'new_password': 'New password must be different from current password.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user.set_password(new_password)
    user.save(update_fields=['password'])

    return Response(
        {'message': 'Password changed successfully.'},
        status=status.HTTP_200_OK
    )


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def profile(request):
    user = request.user

    if request.method == 'GET':
        serializer = UserProfileSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'PUT':
        serializer = UserProfileSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_deletion(request):
    user = request.user

    user.deletion_requested_at = timezone.now()
    user.deletion_scheduled_for = timezone.now() + timezone.timedelta(days=30)
    user.save(update_fields=['deletion_requested_at', 'deletion_scheduled_for'])

    return Response({
        'message': 'Account deletion scheduled in 30 days. Login to cancel.'
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_deletion(request):
    user = request.user

    user.deletion_requested_at = None
    user.deletion_scheduled_for = None
    user.save(update_fields=['deletion_requested_at', 'deletion_scheduled_for'])

    return Response({
        'message': 'Account deletion cancelled.'
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def google_login(request):
    redirect_uri = request.build_absolute_uri('/auth/google/callback/')
    client_id = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']['client_id']

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    cache.set(f'google_oauth_state_{state}', nonce, timeout=600)

    auth_url = (
        'https://accounts.google.com/o/oauth2/v2/auth'
        f'?client_id={client_id}'
        f'&redirect_uri={redirect_uri}'
        '&response_type=code'
        '&scope=openid%20email%20profile'
        '&access_type=online'
        '&prompt=select_account'
        f'&state={state}'
        f'&nonce={nonce}'
    )

    return redirect(auth_url)


@api_view(['GET'])
@permission_classes([AllowAny])
def google_callback(request):
    code = request.GET.get('code')
    state = request.GET.get('state', '')
    ip = get_client_ip(request)
    user_agent = get_client_user_agent(request)

    if not code:
        log_security_event('google_callback_no_code', ip, user_agent)
        return redirect(f'{settings.FRONTEND_URL}/login/?error=google_auth_failed')

    client_id = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']['client_id']
    client_secret = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']['secret']
    redirect_uri = request.build_absolute_uri('/auth/google/callback/')

    try:
        token_response = requests.post(
            'https://oauth2.googleapis.com/token',
            data={
                'code': code,
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code'
            },
            timeout=10
        )
        token_response.raise_for_status()
        tokens = token_response.json()
        google_access_token = tokens.get('access_token')
        google_id_token = tokens.get('id_token')
    except Exception as e:
        logger.error(f"Google token exchange failed: {str(e)}")
        log_security_event(
            'google_token_exchange_failed',
            ip,
            user_agent,
            metadata={'error': str(e)}
        )
        return redirect(f'{settings.FRONTEND_URL}/login/?error=google_auth_failed')

    idempotency_key = hashlib.sha256(f"google_callback:{code}".encode()).hexdigest()
    cached_result = cache.get(f'google_result_{idempotency_key}')
    if cached_result:
        return cached_result

    user_info = verify_google_token(google_access_token, google_id_token, client_id)
    if not user_info:
        log_security_event('google_token_verification_failed', ip, user_agent)
        return redirect(f'{settings.FRONTEND_URL}/login/?error=google_auth_failed')

    email = user_info.get('email')
    full_name = user_info.get('name', '')
    google_id = user_info.get('sub')
    picture = user_info.get('picture', '')

    if not email:
        return redirect(f'{settings.FRONTEND_URL}/login/?error=google_no_email')

    user = User.objects.filter(email=email).first()

    if user:
        if user.is_suspended:
            return redirect(f'{settings.FRONTEND_URL}/login/?error=account_suspended')

        if not user.google_id:
            user.google_id = google_id
            user.picture = picture
            user.save(update_fields=['google_id', 'picture'])

        django_login(request, user, backend='django.contrib.auth.backends.ModelBackend')

        refresh = RefreshToken.for_user(user)
        refresh['email'] = user.email
        refresh['role'] = user.role
        refresh['full_name'] = user.full_name

        response = redirect(f'{settings.FRONTEND_URL}/dashboard/')
        response.set_cookie(
            'access_token',
            str(refresh.access_token),
            max_age=3600,
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax',
            path='/'
        )
        response.set_cookie(
            'refresh_token',
            str(refresh),
            max_age=604800,
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax',
            path='/'
        )

        log_security_event('google_login_success', ip, user_agent, user=user)
        cache.set(f'google_result_{idempotency_key}', response, timeout=60)
        return response

    cache_key = f'google_signup_{google_id}'
    existing_signup = cache.get(cache_key)
    if existing_signup:
        return redirect(f'{settings.FRONTEND_URL}/register/?token={existing_signup}')

    temp_token = secrets.token_urlsafe(32)
    cache.set(cache_key, temp_token, timeout=600)
    cache.set(
        f'google_signup_{temp_token}',
        {
            'email': email,
            'full_name': full_name,
            'google_id': google_id,
            'picture': picture
        },
        timeout=600
    )

    log_security_event(
        'google_signup_redirect',
        ip,
        user_agent,
        metadata={'email': email}
    )

    return redirect(f'{settings.FRONTEND_URL}/register/?token={temp_token}')


@api_view(['POST'])
@permission_classes([AllowAny])
def google_signup(request):
    temp_token = request.data.get('token')
    ip = get_client_ip(request)
    user_agent = get_client_user_agent(request)

    if not temp_token:
        return Response(
            {'error': 'Invalid signup session', 'redirect': 'login'},
            status=status.HTTP_400_BAD_REQUEST
        )

    google_data = cache.get(f'google_signup_{temp_token}')

    if not google_data:
        return Response(
            {'error': 'Signup session expired. Please try again.', 'redirect': 'login'},
            status=status.HTTP_400_BAD_REQUEST
        )

    email = google_data['email']
    full_name = request.data.get('full_name', google_data['full_name'])
    google_id = google_data['google_id']
    picture = google_data['picture']

    if User.objects.filter(email=email).exists():
        cache.delete(f'google_signup_{temp_token}')
        cache.delete(f'google_signup_{google_id}')
        return Response(
            {'error': 'An account with this email already exists. Please sign in.', 'redirect': 'login'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                full_name=full_name,
                password=None,
                google_id=google_id,
                picture=picture,
                email_verified=True,
                is_active=True,
                role='client'
            )

            cache.delete(f'google_signup_{temp_token}')
            cache.delete(f'google_signup_{google_id}')

            django_login(request, user, backend='django.contrib.auth.backends.ModelBackend')

    except Exception as e:
        logger.error(f"Google signup transaction failed: {str(e)}")
        log_security_event(
            'google_signup_rollback',
            ip,
            user_agent,
            metadata={'email': email, 'error': str(e)}
        )
        return Response(
            {'error': 'Registration failed. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    refresh = RefreshToken.for_user(user)
    refresh['email'] = user.email
    refresh['role'] = user.role
    refresh['full_name'] = user.full_name

    profile_serializer = UserProfileSerializer(user)

    response = Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': profile_serializer.data,
        'access_expires_in': 3600,
        'refresh_expires_in': 604800
    }, status=status.HTTP_200_OK)

    response.set_cookie(
        'access_token',
        str(refresh.access_token),
        max_age=3600,
        httponly=True,
        secure=not settings.DEBUG,
        samesite='Lax',
        path='/'
    )
    response.set_cookie(
        'refresh_token',
        str(refresh),
        max_age=604800,
        httponly=True,
        secure=not settings.DEBUG,
        samesite='Lax',
        path='/'
    )

    log_security_event('google_signup_success', ip, user_agent, user=user)

    return response


@api_view(['GET'])
@permission_classes([AllowAny])
def apple_login(request):
    redirect_uri = request.build_absolute_uri('/auth/apple/callback/')
    client_id = settings.APPLE_CLIENT_ID

    state = secrets.token_urlsafe(32)
    cache.set(f'apple_oauth_state_{state}', 'nonce', timeout=600)

    auth_url = (
        'https://appleid.apple.com/auth/authorize'
        f'?client_id={client_id}'
        f'&redirect_uri={redirect_uri}'
        '&response_type=code'
        '&response_mode=form_post'
        '&scope=email%20name'
        f'&state={state}'
    )

    return redirect(auth_url)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def apple_callback(request):
    code = request.POST.get('code')
    state = request.POST.get('state', '')
    user_data = request.POST.get('user')
    ip = get_client_ip(request)
    user_agent = get_client_user_agent(request)

    if not code:
        log_security_event('apple_callback_no_code', ip, user_agent)
        return redirect(f'{settings.FRONTEND_URL}/login/?error=apple_auth_failed')

    client_secret = generate_apple_client_secret()
    token_url = 'https://appleid.apple.com/auth/token'
    data = {
        'client_id': settings.APPLE_CLIENT_ID,
        'client_secret': client_secret,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': request.build_absolute_uri('/auth/apple/callback/'),
    }

    try:
        token_response = requests.post(token_url, data=data, timeout=10)
        token_response.raise_for_status()
        tokens = token_response.json()
        id_token = tokens.get('id_token')
        access_token = tokens.get('access_token')
    except Exception as e:
        logger.error(f"Apple token exchange failed: {str(e)}")
        log_security_event('apple_token_exchange_failed', ip, user_agent, metadata={'error': str(e)})
        return redirect(f'{settings.FRONTEND_URL}/login/?error=apple_auth_failed')

    try:
        decoded = jwt.decode(
            id_token,
            options={'verify_signature': False},
            audience=settings.APPLE_CLIENT_ID,
            algorithms=['RS256']
        )
        apple_user_id = decoded.get('sub')
        email = decoded.get('email')
        email_verified = decoded.get('email_verified', False)
    except Exception as e:
        logger.error(f"Apple token verification failed: {str(e)}")
        log_security_event('apple_token_verification_failed', ip, user_agent)
        return redirect(f'{settings.FRONTEND_URL}/login/?error=apple_auth_failed')

    if not apple_user_id:
        return redirect(f'{settings.FRONTEND_URL}/login/?error=apple_no_user_id')

    full_name = ''
    picture = ''
    if user_data:
        try:
            user_info = json.loads(user_data)
            full_name = user_info.get('name', {}).get('fullName', '')
            if full_name:
                full_name = f"{full_name.get('givenName', '')} {full_name.get('familyName', '')}".strip()
        except json.JSONDecodeError:
            pass

    user = User.objects.filter(apple_id=apple_user_id).first()

    if user:
        if user.is_suspended:
            return redirect(f'{settings.FRONTEND_URL}/login/?error=account_suspended')

        if full_name and not user.full_name:
            user.full_name = full_name
            user.save(update_fields=['full_name'])

        django_login(request, user, backend='django.contrib.auth.backends.ModelBackend')

        refresh = RefreshToken.for_user(user)
        response = redirect(f'{settings.FRONTEND_URL}/dashboard/')
        response.set_cookie('access_token', str(refresh.access_token), max_age=3600, httponly=True, secure=not settings.DEBUG, samesite='Lax', path='/')
        response.set_cookie('refresh_token', str(refresh), max_age=604800, httponly=True, secure=not settings.DEBUG, samesite='Lax', path='/')

        log_security_event('apple_login_success', ip, user_agent, user=user)
        return response

    if email:
        existing_user = User.objects.filter(email=email).first()
        if existing_user and not existing_user.apple_id:
            existing_user.apple_id = apple_user_id
            if full_name and not existing_user.full_name:
                existing_user.full_name = full_name
            existing_user.save(update_fields=['apple_id', 'full_name'])
            django_login(request, existing_user, backend='django.contrib.auth.backends.ModelBackend')
            refresh = RefreshToken.for_user(existing_user)
            response = redirect(f'{settings.FRONTEND_URL}/dashboard/')
            response.set_cookie('access_token', str(refresh.access_token), max_age=3600, httponly=True, secure=not settings.DEBUG, samesite='Lax', path='/')
            response.set_cookie('refresh_token', str(refresh), max_age=604800, httponly=True, secure=not settings.DEBUG, samesite='Lax', path='/')
            log_security_event('apple_login_success', ip, user_agent, user=existing_user)
            return response

    cache_key = f'apple_signup_{apple_user_id}'
    existing_signup = cache.get(cache_key)
    if existing_signup:
        return redirect(f'{settings.FRONTEND_URL}/register/?token={existing_signup}')

    temp_token = secrets.token_urlsafe(32)
    cache.set(cache_key, temp_token, timeout=600)
    cache.set(
        f'apple_signup_{temp_token}',
        {
            'email': email,
            'full_name': full_name,
            'apple_id': apple_user_id,
            'email_verified': email_verified,
        },
        timeout=600
    )

    log_security_event('apple_signup_redirect', ip, user_agent, metadata={'email': email})
    return redirect(f'{settings.FRONTEND_URL}/register/?token={temp_token}')


@api_view(['POST'])
@permission_classes([AllowAny])
def apple_signup(request):
    temp_token = request.data.get('token')
    ip = get_client_ip(request)
    user_agent = get_client_user_agent(request)

    if not temp_token:
        return Response({'error': 'Invalid signup session', 'redirect': 'login'}, status=status.HTTP_400_BAD_REQUEST)

    apple_data = cache.get(f'apple_signup_{temp_token}')

    if not apple_data:
        return Response({'error': 'Signup session expired. Please try again.', 'redirect': 'login'}, status=status.HTTP_400_BAD_REQUEST)

    email = apple_data['email']
    full_name = request.data.get('full_name', apple_data.get('full_name', ''))
    apple_id = apple_data['apple_id']
    email_verified = apple_data.get('email_verified', False)

    if User.objects.filter(email=email).exists():
        cache.delete(f'apple_signup_{temp_token}')
        cache.delete(f'apple_signup_{apple_id}')
        return Response({'error': 'An account with this email already exists. Please sign in.', 'redirect': 'login'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                full_name=full_name,
                password=None,
                apple_id=apple_id,
                email_verified=email_verified,
                is_active=True,
                role='client'
            )

            cache.delete(f'apple_signup_{temp_token}')
            cache.delete(f'apple_signup_{apple_id}')

            django_login(request, user, backend='django.contrib.auth.backends.ModelBackend')

    except Exception as e:
        logger.error(f"Apple signup transaction failed: {str(e)}")
        log_security_event('apple_signup_rollback', ip, user_agent, metadata={'email': email, 'error': str(e)})
        return Response({'error': 'Registration failed. Please try again.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    refresh = RefreshToken.for_user(user)
    profile_serializer = UserProfileSerializer(user)

    response = Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': profile_serializer.data,
        'access_expires_in': 3600,
        'refresh_expires_in': 604800
    }, status=status.HTTP_200_OK)

    response.set_cookie('access_token', str(refresh.access_token), max_age=3600, httponly=True, secure=not settings.DEBUG, samesite='Lax', path='/')
    response.set_cookie('refresh_token', str(refresh), max_age=604800, httponly=True, secure=not settings.DEBUG, samesite='Lax', path='/')

    log_security_event('apple_signup_success', ip, user_agent, user=user)

    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_notifications_list(request):
    page = int(request.GET.get('page', 1))
    page_size = int(request.GET.get('page_size', 20))
    filter_type = request.GET.get('filter')

    notifications = ClientNotification.objects.filter(user=request.user)

    if filter_type == 'unread':
        notifications = notifications.filter(is_read=False)
    elif filter_type == 'read':
        notifications = notifications.filter(is_read=True)

    paginator = Paginator(notifications, page_size)
    page_obj = paginator.get_page(page)

    return Response({
        'count': paginator.count,
        'page': page,
        'page_size': page_size,
        'results': [{
            'id': str(n.id),
            'title': n.title,
            'message': n.message,
            'type': n.type,
            'is_read': n.is_read,
            'link': n.link,
            'created_at': n.created_at.isoformat()
        } for n in page_obj]
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_notification_mark_read(request, notification_id):
    notification = get_object_or_404(ClientNotification, id=notification_id, user=request.user)
    notification.is_read = True
    notification.save()
    return Response({'success': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_notifications_mark_all_read(request):
    updated = ClientNotification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({'success': True, 'marked': updated})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def client_notification_delete(request, notification_id):
    notification = get_object_or_404(ClientNotification, id=notification_id, user=request.user)
    notification.delete()
    return Response({'success': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_notifications_unread_count(request):
    count = ClientNotification.objects.filter(user=request.user, is_read=False).count()
    return Response({'unread_count': count})