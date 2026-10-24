import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def verify_recaptcha(token, remote_ip=None):
    secret = getattr(settings, 'RECAPTCHA_SECRET_KEY', '')
    if not secret:
        logger.error('reCAPTCHA verification requested but RECAPTCHA_SECRET_KEY is not configured')
        return False
    if not token:
        return False
    try:
        response = requests.post(
            'https://www.google.com/recaptcha/api/siteverify',
            data={'secret': secret, 'response': token, 'remoteip': remote_ip or ''},
            timeout=5,
        )
        response.raise_for_status()
        return bool(response.json().get('success'))
    except (requests.RequestException, ValueError):
        logger.exception('reCAPTCHA verification failed')
        return False


def should_require_recaptcha(request):
    origin = (request.META.get('HTTP_ORIGIN') or '').lower()
    configured_origin = str(getattr(settings, 'FRONTEND_ORIGIN', '')).lower().rstrip('/')
    return bool(origin and (origin == configured_origin or origin.startswith('https://dsdwallet.com')))
