from rest_framework.throttling import SimpleRateThrottle

class RegisterThrottle(SimpleRateThrottle):
    scope = 'register'
    
    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = request.data.get('email', '')
        return f'register_{ident}_{email}'
    
    def allow_request(self, request, view):
        if not self.get_ident(request):
            return True
        return super().allow_request(request, view)


class LoginThrottle(SimpleRateThrottle):
    scope = 'login'
    
    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = request.data.get('email', '').lower().strip()
        return f'login_{ident}_{email}' if email else f'login_{ident}'


class PasswordResetThrottle(SimpleRateThrottle):
    scope = 'password_reset'
    
    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = request.data.get('email', '').lower().strip()
        return f'reset_{ident}_{email}' if email else f'reset_{ident}'


class ResendOTPThrottle(SimpleRateThrottle):
    scope = 'resend_otp'
    
    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = request.data.get('email', '').lower().strip()
        return f'resend_otp_{ident}_{email}' if email else f'resend_otp_{ident}'


class VerifyOTPThrottle(SimpleRateThrottle):
    scope = 'verify_otp'
    
    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = request.data.get('email', '').lower().strip()
        return f'verify_otp_{ident}_{email}' if email else f'verify_otp_{ident}'


class ProfileUpdateThrottle(SimpleRateThrottle):
    scope = 'profile_update'
    
    def get_cache_key(self, request, view):
        if not request.user.is_authenticated:
            return None
        return f'profile_{request.user.id}_{self.get_ident(request)}'


class ChangePasswordThrottle(SimpleRateThrottle):
    scope = 'change_password'
    
    def get_cache_key(self, request, view):
        if not request.user.is_authenticated:
            return None
        return f'change_pw_{request.user.id}_{self.get_ident(request)}'


class DeletionRequestThrottle(SimpleRateThrottle):
    scope = 'deletion_request'
    
    def get_cache_key(self, request, view):
        if not request.user.is_authenticated:
            return None
        return f'deletion_{request.user.id}_{self.get_ident(request)}'