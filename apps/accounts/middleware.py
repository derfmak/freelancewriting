from django.utils.deprecation import MiddlewareMixin
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
import logging

logger = logging.getLogger(__name__)


class JWTAuthMiddleware(MiddlewareMixin):
    def process_request(self, request):
        access_token = None

        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if auth_header and auth_header.startswith('Bearer '):
            access_token = auth_header.split(' ')[1]
        else:
            access_token = request.COOKIES.get('access_token')

        if access_token:
            try:
                token = AccessToken(access_token)
                request.META['HTTP_AUTHORIZATION'] = f'Bearer {access_token}'
            except TokenError as e:
                logger.debug(f"Invalid JWT token: {e}")
                pass