from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from .models import User, PendingUser, LoginLog


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=100)
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=17, required=False, allow_blank=True)
    institution = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_email(self, value):
        return value.lower().strip()

    def validate_full_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError('Full name must be at least 2 characters')
        return value

    def validate(self, data):
        password = data.get('password')
        password_confirm = data.get('password_confirm')
        if password_confirm and password != password_confirm:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match'})
        return data


class OTPVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(min_length=6, max_length=6)

    def validate_email(self, value):
        return value.lower().strip()

    def validate_otp_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('OTP must contain only numbers')
        return value


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower().strip()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        return value.lower().strip()


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower().strip()


class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(validators=[validate_password], write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match'})
        return data


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(validators=[validate_password], write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match'})
        if data['current_password'] == data['new_password']:
            raise serializers.ValidationError('New password must be different from current password')
        return data


class SendPasswordChangeCodeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(validators=[validate_password], write_only=True)


class VerifyPasswordChangeCodeSerializer(serializers.Serializer):
    verification_id = serializers.UUIDField(required=True)
    code = serializers.CharField(min_length=6, max_length=6)

    def validate_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('Code must contain only numbers')
        return value


class CompletePasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(validators=[validate_password], write_only=True)


class UserProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=17, required=False, allow_blank=True)
    institution = serializers.CharField(max_length=100, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            'id', 'email', 'full_name', 'phone', 'institution',
            'email_verified', 'phone_verified', 'role', 'is_suspended',
            'created_at', 'picture'
        ]
        read_only_fields = [
            'id', 'email', 'email_verified', 'phone_verified',
            'role', 'is_suspended', 'created_at', 'picture'
        ]

    def validate_full_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError('Full name must be at least 2 characters')
        return value

    def validate_phone(self, value):
        if value and not value.strip():
            return ''
        return value


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'email', 'full_name', 'role', 'is_active',
            'email_verified', 'phone_verified', 'institution',
            'phone', 'last_login', 'date_joined', 'created_at', 'picture'
        ]
        read_only_fields = ['id', 'email', 'last_login', 'date_joined', 'created_at']


class LoginLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoginLog
        fields = ['id', 'email', 'ip_address', 'success', 'created_at']
        read_only_fields = ['id', 'created_at']


class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'email', 'full_name', 'role', 'email_verified',
            'is_suspended', 'is_active', 'last_login', 'created_at'
        ]
        read_only_fields = fields


class PendingUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = PendingUser
        fields = ['id', 'email', 'full_name', 'phone', 'institution', 'created_at', 'otp_expires']
        read_only_fields = ['id', 'created_at', 'otp_expires']


class GoogleLoginSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    id_token = serializers.CharField(required=False, allow_blank=True)


class ResendPasswordChangeCodeSerializer(serializers.Serializer):
    verification_id = serializers.UUIDField(required=False)