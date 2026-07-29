from rest_framework import status
from django.contrib.auth import login as django_login, logout as auth_logout
from django.shortcuts import redirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from django.core.cache import cache
import logging
import requests
import secrets
from .models import User, PendingUser, LoginLog, PasswordChangeVerification
from .serializers import (
    RegisterSerializer, OTPVerificationSerializer, ResendOTPSerializer,
    LoginSerializer, ForgotPasswordSerializer, ResetPasswordSerializer,
    ChangePasswordSerializer, UserProfileSerializer, UserSerializer,
    SendPasswordChangeCodeSerializer, VerifyPasswordChangeCodeSerializer,
    CompletePasswordChangeSerializer
)
from .utils import (
    generate_otp, generate_reset_token, generate_password_change_code,
    send_otp_email, send_password_reset_email, send_password_change_code_email,
    get_client_ip, get_client_user_agent
)
from .throttles import (
    RegisterThrottle, LoginThrottle, PasswordResetThrottle,
    ResendOTPThrottle, VerifyOTPThrottle, SendPasswordChangeCodeThrottle,
    VerifyPasswordChangeCodeThrottle, GoogleLoginThrottle
)

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    throttle = RegisterThrottle()
    if not throttle.allow_request(request, None):
        return Response(
            {'error': 'Too many registration attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )

    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data['email']

    if User.objects.filter(email=email).exists():
        return Response(
            {'email': 'An account with this email already exists'},
            status=status.HTTP_400_BAD_REQUEST
        )

    PendingUser.objects.filter(email=email).delete()

    otp = generate_otp()
    ip = get_client_ip(request)

    pending_user = PendingUser.objects.create(
        email=email,
        full_name=serializer.validated_data['full_name'],
        password=make_password(serializer.validated_data['password']),
        phone=serializer.validated_data.get('phone', ''),
        institution=serializer.validated_data.get('institution', ''),
        otp_code=otp,
        otp_expires=timezone.now() + timezone.timedelta(minutes=10),
        ip_address=ip
    )

    email_sent = send_otp_email(pending_user.email, otp, pending_user.full_name)

    if not email_sent:
        pending_user.delete()
        return Response(
            {'error': 'Failed to send verification email. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return Response({
        'message': 'Verification code sent to your email.',
        'email': pending_user.email
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp(request):
    throttle = VerifyOTPThrottle()
    if not throttle.allow_request(request, None):
        return Response(
            {'error': 'Too many verification attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )

    serializer = OTPVerificationSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data['email']
    otp = serializer.validated_data['otp_code']

    try:
        pending_user = PendingUser.objects.get(
            email=email,
            otp_code=otp,
            otp_expires__gt=timezone.now()
        )
    except PendingUser.DoesNotExist:
        return Response(
            {'error': 'Invalid or expired verification code'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if User.objects.filter(email=email).exists():
        pending_user.delete()
        return Response(
            {'error': 'An account with this email already exists'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = User.objects.create_user(
        email=pending_user.email,
        full_name=pending_user.full_name,
        password=pending_user.password,
        phone=pending_user.phone,
        institution=pending_user.institution,
        email_verified=True,
        is_active=True,
        role='client'
    )

    pending_user.delete()

    return Response({
        'message': 'Email verified successfully. You can now login.'
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def resend_otp(request):
    throttle = ResendOTPThrottle()
    if not throttle.allow_request(request, None):
        return Response(
            {'error': 'Too many resend attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )

    serializer = ResendOTPSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data['email']

    try:
        pending_user = PendingUser.objects.get(email=email)
    except PendingUser.DoesNotExist:
        return Response(
            {'error': 'No pending registration found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if pending_user.is_expired():
        pending_user.delete()
        return Response(
            {'error': 'Your registration has expired. Please register again.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    new_otp = generate_otp()
    pending_user.otp_code = new_otp
    pending_user.otp_expires = timezone.now() + timezone.timedelta(minutes=10)
    pending_user.save(update_fields=['otp_code', 'otp_expires'])

    email_sent = send_otp_email(email, new_otp, pending_user.full_name)

    if not email_sent:
        return Response(
            {'error': 'Failed to send verification email. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return Response({
        'message': 'New verification code sent to your email.'
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    if not settings.DEBUG:
        throttle = LoginThrottle()
        if not throttle.allow_request(request, None):
            return Response(
                {'error': 'Too many login attempts. Please try again later.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data['email']
    password = serializer.validated_data['password']
    remember = request.data.get('remember', False)
    ip = get_client_ip(request)

    try:
        user = User.objects.get(email=email)

        if user.account_locked_until and user.account_locked_until > timezone.now():
            return Response(
                {'error': 'Account locked due to multiple failed attempts. Try again later.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if not user.email_verified:
            return Response(
                {'error': 'Please verify your email before logging in.'},
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

    except User.DoesNotExist:
        LoginLog.objects.create(
            email=email,
            ip_address=ip,
            user_agent=get_client_user_agent(request),
            success=False
        )
        return Response(
            {'error': 'No account found with this email address.'},
            status=status.HTTP_401_UNAUTHORIZED
        )

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

    return response


@api_view(['POST'])
@permission_classes([AllowAny])
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
        return Response(
            {'error': 'Invalid refresh token'},
            status=status.HTTP_401_UNAUTHORIZED
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
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
        token = generate_reset_token()
        user.password_reset_token = token
        user.password_reset_expires = timezone.now() + timezone.timedelta(hours=1)
        user.save(update_fields=['password_reset_token', 'password_reset_expires'])

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

    try:
        user = User.objects.get(
            password_reset_token=token,
            password_reset_expires__gt=timezone.now()
        )
    except User.DoesNotExist:
        return Response(
            {'error': 'Invalid or expired reset token.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user.set_password(serializer.validated_data['password'])
    user.password_reset_token = ''
    user.password_reset_expires = None
    user.save(update_fields=['password', 'password_reset_token', 'password_reset_expires'])

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

    if not user.check_password(serializer.validated_data['current_password']):
        return Response(
            {'current_password': 'Current password is incorrect.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user.set_password(serializer.validated_data['new_password'])
    user.save(update_fields=['password'])

    return Response({
        'message': 'Password changed successfully.'
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_password_change_code(request):
    throttle = SendPasswordChangeCodeThrottle()
    if not throttle.allow_request(request, None):
        return Response(
            {'error': 'Too many attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )

    serializer = SendPasswordChangeCodeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user

    if not user.check_password(serializer.validated_data['current_password']):
        return Response(
            {'current_password': 'Current password is incorrect.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if user.check_password(serializer.validated_data['new_password']):
        return Response(
            {'new_password': 'New password must be different from current password.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user.set_temp_password(serializer.validated_data['new_password'])
    code = user.generate_password_change_code()

    PasswordChangeVerification.objects.create(
        user=user,
        code=code,
        expires_at=timezone.now() + timezone.timedelta(minutes=5)
    )

    email_sent = send_password_change_code_email(user.email, code, user.full_name)

    if not email_sent:
        user.clear_password_change_code()
        return Response(
            {'error': 'Failed to send verification code. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return Response({
        'message': 'Verification code sent to your email.',
        'expires_in': 300
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_password_change_code(request):
    throttle = VerifyPasswordChangeCodeThrottle()
    if not throttle.allow_request(request, None):
        return Response(
            {'error': 'Too many verification attempts. Please try again later.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )

    serializer = VerifyPasswordChangeCodeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    code = serializer.validated_data['code']

    try:
        verification = PasswordChangeVerification.objects.get(
            user=user,
            code=code,
            used=False,
            expires_at__gt=timezone.now()
        )
    except PasswordChangeVerification.DoesNotExist:
        return Response(
            {'error': 'Invalid or expired verification code.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if user.apply_temp_password():
        verification.used = True
        verification.save()
        user.clear_password_change_code()
        return Response({
            'message': 'Password changed successfully. Please login again.'
        }, status=status.HTTP_200_OK)
    else:
        return Response(
            {'error': 'Failed to apply password change.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_password_change(request):
    serializer = CompletePasswordChangeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user

    if not user.check_password(serializer.validated_data['current_password']):
        return Response(
            {'current_password': 'Current password is incorrect.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user.set_password(serializer.validated_data['new_password'])
    user.save(update_fields=['password'])
    user.clear_password_change_code()

    return Response({
        'message': 'Password changed successfully.'
    }, status=status.HTTP_200_OK)


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

    auth_url = (
        'https://accounts.google.com/o/oauth2/v2/auth'
        f'?client_id={client_id}'
        f'&redirect_uri={redirect_uri}'
        '&response_type=code'
        '&scope=openid%20email%20profile'
        '&access_type=online'
        '&prompt=select_account'
    )

    return redirect(auth_url)


@api_view(['GET'])
@permission_classes([AllowAny])
def google_callback(request):
    code = request.GET.get('code')

    if not code:
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
    except Exception as e:
        logger.error(f"Google token exchange failed: {str(e)}")
        return redirect(f'{settings.FRONTEND_URL}/login/?error=google_auth_failed')

    try:
        user_response = requests.get(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            headers={'Authorization': f'Bearer {google_access_token}'},
            timeout=10
        )
        user_response.raise_for_status()
        user_data = user_response.json()
    except Exception as e:
        logger.error(f"Google userinfo failed: {str(e)}")
        return redirect(f'{settings.FRONTEND_URL}/login/?error=google_auth_failed')

    email = user_data.get('email')
    full_name = user_data.get('name', '')
    google_id = user_data.get('sub')
    picture = user_data.get('picture', '')

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
        return response

    temp_token = secrets.token_urlsafe(32)
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

    return redirect(f'{settings.FRONTEND_URL}/register/?token={temp_token}')


@api_view(['POST'])
@permission_classes([AllowAny])
def google_signup(request):
    temp_token = request.data.get('token')

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
        return Response(
            {'error': 'An account with this email already exists. Please sign in.', 'redirect': 'login'},
            status=status.HTTP_400_BAD_REQUEST
        )

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

    django_login(request, user, backend='django.contrib.auth.backends.ModelBackend')

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

    return response