import hashlib
import hmac
import json
import os
import secrets
import base64
import logging
import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.db import transaction
from django.utils import timezone

from wallet.models import AuditLog, OtpChallenge, TrustedDevice


OTP_TTL = timedelta(minutes=5)
STEP_UP_TTL = timedelta(minutes=10)
logger = logging.getLogger(__name__)


def device_id_from_request(request):
    return (request.META.get('HTTP_X_DEVICE_ID') or request.META.get('HTTP_DEVICE_ID') or '').strip()


def get_or_create_device(user, device_id, *, platform='', device_name='', public_key_pem=''):
    if not device_id:
        return None
    existing = TrustedDevice.objects.filter(device_id=device_id).first()
    if existing and existing.user_id != user.id:
        raise ValueError('This device is already registered to another account.')
    device, _ = TrustedDevice.objects.update_or_create(
        device_id=device_id,
        defaults={
            'user': user,
            'platform': platform,
            'device_name': device_name,
            'public_key_pem': public_key_pem or (existing.public_key_pem if existing else ''),
            'is_trusted': True,
            'revoked_at': None,
        },
    )
    return device


def verify_device_signature(request, user, body=None):
    """Verify a short-lived RSA signature from the authenticated trusted device."""
    device_id = device_id_from_request(request)
    timestamp = (request.META.get('HTTP_X_TIMESTAMP') or '').strip()
    signature = (request.META.get('HTTP_X_SIGNATURE') or '').strip()
    if not all((device_id, timestamp, signature)):
        return None, 'Missing device signature headers.'
    try:
        timestamp_value = int(timestamp)
    except ValueError:
        return None, 'Invalid request timestamp.'
    if abs(int(timezone.now().timestamp()) - timestamp_value) > 60:
        return None, 'Stale request timestamp.'
    device = user.trusted_devices.filter(device_id=device_id, is_trusted=True, revoked_at__isnull=True).first()
    if not device or not device.public_key_pem:
        return None, 'This device has no registered signing key.'
    raw_body = request.body if body is None else body
    body_hash = hashlib.sha256(raw_body).hexdigest()
    payload = f'{request.method}|{request.path}|{timestamp}|{body_hash}'.encode()
    try:
        try:
            public_key = serialization.load_pem_public_key(device.public_key_pem.encode())
            public_key.verify(base64.b64decode(signature, validate=True), payload, padding.PKCS1v15(), hashes.SHA256())
        except ValueError:
            public_key = ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(device.public_key_pem, validate=True))
            public_key.verify(base64.b64decode(signature, validate=True), payload)
    except (ValueError, TypeError, InvalidSignature):
        return None, 'Invalid device signature.'
    device.last_seen_at = timezone.now()
    device.save(update_fields=['last_seen_at'])
    return device, None


def _request_metadata(request):
    return {
        'ip_address': request.META.get('REMOTE_ADDR'),
        'user_agent': request.META.get('HTTP_USER_AGENT', '')[:2000],
    }


def create_otp_challenge(user, purpose, request, *, device_id=None, platform='', device_name=''):
    device_id = device_id or device_id_from_request(request) or user.current_device_id
    device = get_or_create_device(user, device_id, platform=platform, device_name=device_name)
    OtpChallenge.objects.filter(
        user=user,
        purpose=purpose,
        consumed_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).update(consumed_at=timezone.now())
    code = f'{secrets.randbelow(1_000_000):06d}'
    challenge = OtpChallenge.objects.create(
        user=user,
        device=device,
        purpose=purpose,
        code_hash=make_password(code),
        dev_code=code if settings.DEBUG else '',
        expires_at=timezone.now() + OTP_TTL,
        **_request_metadata(request),
    )
    AuditLog.objects.create(
        user=user,
        action='otp_challenge_created',
        metadata={'challenge_id': str(challenge.request_id), 'purpose': purpose, 'device_id': device_id or ''},
    )
    return challenge, code


def verify_otp_challenge(challenge, code):
    now = timezone.now()
    if challenge.consumed_at or challenge.expires_at <= now:
        return False, 'This verification code has expired.'
    if challenge.locked_until and challenge.locked_until > now:
        return False, 'Too many attempts. Request a new verification code.'
    if challenge.attempts >= challenge.max_attempts:
        challenge.locked_until = now + timedelta(minutes=15)
        challenge.save(update_fields=['locked_until'])
        return False, 'Too many attempts. Request a new verification code.'
    challenge.attempts += 1
    if not check_password(code, challenge.code_hash):
        if challenge.attempts >= challenge.max_attempts:
            challenge.locked_until = now + timedelta(minutes=15)
        challenge.save(update_fields=['attempts', 'locked_until'])
        return False, 'Invalid verification code.'
    challenge.consumed_at = now
    challenge.save(update_fields=['attempts', 'consumed_at'])
    if challenge.device_id:
        TrustedDevice.objects.filter(pk=challenge.device_id).update(last_seen_at=now, is_trusted=True, revoked_at=None)
    AuditLog.objects.create(
        user=challenge.user,
        action='otp_challenge_verified',
        metadata={'challenge_id': str(challenge.request_id), 'purpose': challenge.purpose},
    )
    return True, None


def token_is_step_up_verified(token, user, request, purpose=None):
    try:
        payload = signing.loads(token, salt='wallet.api-access-token', max_age=settings.API_ACCESS_TOKEN_MAX_AGE)
    except signing.BadSignature:
        return False
    if payload.get('user_id') != str(user.pk):
        return False
    if purpose and payload.get('step_up_purpose') != purpose:
        return False
    device_id = device_id_from_request(request)
    if not device_id:
        return False
    if not payload.get('device_id'):
        return user.current_device_id == device_id
    if payload.get('device_id') != device_id:
        return False
    if payload.get('step_up_purpose'):
        if int(payload.get('step_up_until', 0)) <= int(timezone.now().timestamp()):
            return False
        return True
    if payload.get('device_id') == device_id:
        return True
    if user.current_device_id == device_id:
        return True
    return TrustedDevice.objects.filter(
        user=user,
        device_id=device_id,
        is_trusted=True,
        revoked_at__isnull=True,
    ).exists()


def webhook_signature(payload, timestamp):
    secret = getattr(settings, 'MOBILE_MONEY_WEBHOOK_SECRET', '')
    return hmac.new(secret.encode(), f'{timestamp}.'.encode() + payload, hashlib.sha256).hexdigest()


def valid_webhook_signature(payload, timestamp, signature):
    if not getattr(settings, 'MOBILE_MONEY_WEBHOOK_SECRET', '') or not timestamp or not signature:
        return False
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(timezone.now().timestamp()) - timestamp_value) > 300:
        return False
    return hmac.compare_digest(webhook_signature(payload, timestamp), signature)


def send_otp_push(challenge, code):
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging
    except ImportError:
        return {'status': 'firebase_admin_unavailable'}

    try:
        firebase_admin.get_app()
    except ValueError:
        from wallet.services.notifications import _service_account_info
        credential_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', '')
        if credential_json:
            try:
                credential = credentials.Certificate(_service_account_info(credential_json))
            except (TypeError, ValueError, json.JSONDecodeError):
                return {'status': 'firebase_credentials_invalid'}
        else:
            credential_path = Path(__file__).resolve().parents[2] / 'dsd-wallet-firebase-adminsdk-fbsvc-457d21a5b0.json'
            if not credential_path.exists():
                return {'status': 'firebase_not_configured'}
            try:
                credential = credentials.Certificate(_service_account_info(credential_path.read_text()))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                return {'status': 'firebase_credentials_invalid'}
        try:
            firebase_admin.initialize_app(credential)
        except ValueError:
            return {'status': 'firebase_initialization_failed'}

    if not challenge.device_id:
        return {'status': 'device_not_registered'}
    from wallet.models import PushDevice
    tokens = list(PushDevice.objects.filter(
        user=challenge.user,
        device_id=challenge.device.device_id,
        active=True,
    ).values_list('token', flat=True))
    if not tokens:
        return {'status': 'push_token_not_registered'}
    message = messaging.MulticastMessage(
        tokens=tokens,
        data={
            'type': 'otp_challenge',
            'challenge_id': str(challenge.request_id),
            'otp': code,
            'purpose': challenge.purpose,
        },
        apns=messaging.APNSConfig(
            headers={'apns-push-type': 'background', 'apns-priority': '5'},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(content_available=True),
            ),
        ),
    )
    response = messaging.send_each_for_multicast(message)
    return {'status': 'sent', 'success_count': response.success_count, 'failure_count': response.failure_count}


def send_multiwa_text(phone, text, *, log_context=None):
    """Deliver a text message through the configured Multiwa gateway."""
    api_key = os.getenv('MULTIWA_API_KEY', '').strip()
    profile_id = os.getenv(
        'MULTIWA_PROFILE_ID',
        '24a50869-40c9-4498-ac97-df123e899619',
    ).strip()
    if not api_key or not profile_id:
        logger.error('multiwa_sms_not_configured')
        return {'status': 'not_configured'}

    phone = (phone or '').strip()
    if not phone:
        logger.error('multiwa_phone_missing', extra=log_context or {})
        return {'status': 'phone_missing'}

    base_url = os.getenv(
        'MULTIWA_BASE_URL',
        'https://duuka.transportunion.ug/multiwa-api/api/v1',
    ).rstrip('/')
    try:
        response = requests.post(
            f'{base_url}/messages/text',
            json={
                'profileId': profile_id,
                'to': phone,
                'text': text,
            },
            headers={'Content-Type': 'application/json', 'X-API-Key': api_key},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception('multiwa_sms_delivery_failed', extra=log_context or {})
        return {'status': 'delivery_failed'}
    return {'status': 'sent'}


def send_otp_sms(challenge, code):
    """Deliver a merchant login code through the configured Multiwa gateway."""
    phone = challenge.user.primary_phone_number or challenge.user.phone_number
    app_hash = os.getenv('MULTIWA_ANDROID_APP_HASH', '').strip()
    message = f'DSD PAY login code: {code}. It expires in 5 minutes. Do not share this code.'
    if app_hash:
        message = f'<#> {message} {app_hash}'
    return send_multiwa_text(
        phone,
        message,
        log_context={'user_id': challenge.user_id},
    )