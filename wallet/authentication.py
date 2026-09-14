"""Authentication for API clients that cannot rely on third-party cookies."""

from django.conf import settings
from django.core import signing
from rest_framework import authentication, exceptions

from .models import User, UserStatus


TOKEN_SALT = 'wallet.api-access-token'


def issue_access_token(user, *, device_id=None, step_up_purpose=None, step_up_until=None):
    """Return a signed, expiring token containing only the user's primary key."""
    payload = {'user_id': str(user.pk)}
    if device_id:
        payload['device_id'] = device_id
    if step_up_purpose and step_up_until:
        payload['step_up_purpose'] = step_up_purpose
        payload['step_up_until'] = int(step_up_until)
    return signing.dumps(payload, salt=TOKEN_SALT, compress=True)


class SignedTokenAuthentication(authentication.BaseAuthentication):
    """Authenticate ``Authorization: Bearer <signed token>`` requests."""

    keyword = 'Bearer'

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header:
            return None
        if header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed('Invalid authorization header.')

        try:
            payload = signing.loads(
                header[1].decode('utf-8'),
                salt=TOKEN_SALT,
                max_age=settings.API_ACCESS_TOKEN_MAX_AGE,
            )
            user = User.objects.get(pk=payload['user_id'], status=UserStatus.ACTIVE)
        except (UnicodeDecodeError, KeyError, User.DoesNotExist, signing.BadSignature):
            raise exceptions.AuthenticationFailed('Invalid or expired access token.')

        device_id = (request.META.get('HTTP_X_DEVICE_ID') or request.META.get('HTTP_DEVICE_ID') or '').strip()
        bound_device_id = payload.get('device_id', '')
        if bound_device_id and device_id != bound_device_id:
            raise exceptions.AuthenticationFailed('This session is bound to another device.')
        return (user, header[1].decode('utf-8'))

    def authenticate_header(self, request):
        return self.keyword
