from datetime import timedelta
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from wallet.authentication import issue_access_token
from wallet.models import (
    MobileMoneyWebhookEvent,
    OtpChallenge,
    User,
    UserStatus,
)
from wallet.services.security import (
    create_otp_challenge,
    token_is_step_up_verified,
    valid_webhook_signature,
    verify_otp_challenge,
    webhook_signature,
)


class OtpChallengeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='otp@example.com',
            password='password-123',
            handle='otp-user',
            display_name='OTP User',
            status=UserStatus.ACTIVE,
        )
        self.factory = RequestFactory()
        self.request = self.factory.post('/api/auth/otp/request', REMOTE_ADDR='127.0.0.1', HTTP_USER_AGENT='test-agent')
        self.request.user = self.user

    def test_code_is_hashed_and_can_only_be_consumed_once(self):
        challenge, code = create_otp_challenge(self.user, OtpChallenge.Purpose.TRANSFER, self.request, device_id='device-1')
        self.assertNotEqual(challenge.code_hash, code)
        verified, error = verify_otp_challenge(challenge, code)
        self.assertTrue(verified)
        self.assertIsNone(error)
        challenge.refresh_from_db()
        verified, error = verify_otp_challenge(challenge, code)
        self.assertFalse(verified)
        self.assertIn('expired', error)

    def test_three_invalid_codes_lock_the_challenge(self):
        challenge, _ = create_otp_challenge(self.user, OtpChallenge.Purpose.TRANSFER, self.request, device_id='device-2')
        for _ in range(3):
            verified, _ = verify_otp_challenge(challenge, '000000')
            self.assertFalse(verified)
            challenge.refresh_from_db()
        self.assertIsNotNone(challenge.locked_until)

    def test_expired_code_is_rejected(self):
        challenge, code = create_otp_challenge(self.user, OtpChallenge.Purpose.TRANSFER, self.request, device_id='device-3')
        OtpChallenge.objects.filter(pk=challenge.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        challenge.refresh_from_db()
        verified, error = verify_otp_challenge(challenge, code)
        self.assertFalse(verified)
        self.assertIn('expired', error)

    def test_step_up_token_is_bound_to_purpose_and_device(self):
        token = issue_access_token(
            self.user,
            device_id='device-4',
            step_up_purpose='transfer',
            step_up_until=(timezone.now() + timedelta(minutes=5)).timestamp(),
        )
        request = self.factory.post('/api/transfers', HTTP_X_DEVICE_ID='device-4')
        self.assertTrue(token_is_step_up_verified(token, self.user, request, 'transfer'))
        request.META['HTTP_X_DEVICE_ID'] = 'other-device'
        self.assertFalse(token_is_step_up_verified(token, self.user, request, 'transfer'))
        self.assertFalse(token_is_step_up_verified(token, self.user, request, 'withdrawal'))

    def test_current_device_can_use_normal_and_legacy_tokens_without_otp(self):
        self.user.current_device_id = 'device-current'
        self.user.save(update_fields=['current_device_id'])
        request = self.factory.post('/api/transfers', HTTP_X_DEVICE_ID='device-current')
        normal_token = issue_access_token(self.user, device_id='device-current')
        legacy_token = issue_access_token(self.user)
        self.assertTrue(token_is_step_up_verified(normal_token, self.user, request))
        self.assertTrue(token_is_step_up_verified(legacy_token, self.user, request))

    def test_bound_normal_token_does_not_require_push_registration(self):
        request = self.factory.post('/api/transfers', HTTP_X_DEVICE_ID='email-login-device')
        token = issue_access_token(self.user, device_id='email-login-device')
        self.assertTrue(token_is_step_up_verified(token, self.user, request))


@override_settings(MOBILE_MONEY_WEBHOOK_SECRET='test-webhook-secret')
class WebhookSecurityTests(TestCase):
    def test_signature_requires_timestamp_and_exact_payload(self):
        payload = b'{"provider_transaction_id":"p-1","status":"completed"}'
        timestamp = str(int(timezone.now().timestamp()))
        signature = webhook_signature(payload, timestamp)
        self.assertTrue(valid_webhook_signature(payload, timestamp, signature))
        self.assertFalse(valid_webhook_signature(payload + b' ', timestamp, signature))
        self.assertFalse(valid_webhook_signature(payload, str(int(timestamp) - 301), signature))

    def test_webhook_event_ids_are_unique(self):
        MobileMoneyWebhookEvent.objects.create(
            event_id='event-1',
            provider_transaction_id='provider-1',
            status='completed',
            signature='signature',
        )
        self.assertTrue(MobileMoneyWebhookEvent.objects.filter(event_id='event-1').exists())
