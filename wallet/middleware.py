import base64
import binascii
import logging
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse

logger = logging.getLogger(__name__)


class ApiEnvelopeMiddleware:
    """Decrypt authenticated mobile API envelopes before DRF parses the body."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        error = self._decrypt(request)
        if error is not None:
            return error
        return self.get_response(request)

    def _decrypt(self, request):
        version = request.headers.get('X-Request-Envelope-Version')
        if not version:
            return None  # Web/bootstrap clients remain compatible.
        if version != '1':
            return JsonResponse({'error': 'Unsupported request envelope'}, status=400)
        if not request.headers.get('Authorization'):
            return JsonResponse({'error': 'Authenticated envelope required'}, status=401)

        nonce = request.headers.get('X-Request-Envelope-Nonce', '')
        timestamp = request.headers.get('X-Request-Envelope-Timestamp', '')
        request_id = request.headers.get('X-Request-ID', '')
        try:
            issued_at = int(timestamp)
            if abs(int(time.time()) - issued_at) > getattr(
                    settings, 'API_ENVELOPE_TIMESTAMP_TOLERANCE', 300):
                raise ValueError('expired')
            if not request_id or len(request_id) > 128:
                raise ValueError('request id')
            nonce_bytes = _decode_base64(nonce)
            ciphertext = _decode_base64(request.body)
            if len(nonce_bytes) != 12:
                raise ValueError('nonce')
            key = getattr(settings, 'API_ENVELOPE_KEY', '')
            if not key:
                return JsonResponse({'error': 'Request envelopes are not configured'}, status=503)
            key_bytes = _decode_key(key)
            aad = f'{request.method}\n{request.path}\n{timestamp}\n{request_id}'.encode()
            plaintext = AESGCM(key_bytes).decrypt(nonce_bytes, ciphertext, aad)
        except InvalidTag:
            logger.warning(
                'Request envelope authentication failed: method=%s path=%s request_id=%s',
                request.method,
                request.path,
                request_id or '<missing>',
            )
            return JsonResponse({'error': 'Invalid or expired request envelope'}, status=400)
        except (ValueError, binascii.Error, TypeError) as exc:
            logger.warning(
                'Request envelope rejected: method=%s path=%s request_id=%s reason=%s',
                request.method,
                request.path,
                request_id or '<missing>',
                str(exc),
            )
            return JsonResponse({'error': 'Invalid or expired request envelope'}, status=400)

        cache_key = f'api-envelope:{request_id}'
        if not cache.add(cache_key, '1', timeout=getattr(
                settings, 'API_ENVELOPE_TIMESTAMP_TOLERANCE', 300)):
            return JsonResponse({'error': 'Request envelope replayed'}, status=409)
        request._body = plaintext
        return None


def _decode_key(value):
    try:
        decoded = _decode_base64(value)
        if len(decoded) == 32:
            return decoded
    except (binascii.Error, ValueError):
        pass
    try:
        decoded = bytes.fromhex(value)
    except ValueError:
        decoded = b''
    if len(decoded) != 32:
        raise ValueError('API_ENVELOPE_KEY must decode to 32 bytes')
    return decoded


def _decode_base64(value):
    raw = value.encode() if isinstance(value, str) else value
    return base64.urlsafe_b64decode(raw + b'=' * (-len(raw) % 4))
