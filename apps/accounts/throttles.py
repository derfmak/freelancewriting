from rest_framework.throttling import SimpleRateThrottle

class RegisterThrottle(SimpleRateThrottle):
    scope = 'register'
    
    def get_cache_key(self, request, view):
        return self.get_ident(request)

class LoginThrottle(SimpleRateThrottle):
    scope = 'login'
    
    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = request.data.get('email', '')
        return f'{ident}_{email}'

class PasswordResetThrottle(SimpleRateThrottle):
    scope = 'password_reset'
    
    def get_cache_key(self, request, view):
        return self.get_ident(request)