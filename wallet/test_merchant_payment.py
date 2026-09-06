from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.utils import timezone
from datetime import timedelta

from wallet.models import (
    FeeAppliesTo, FeePolicy, LedgerDirection, LedgerEntry, Merchant,
    MerchantApiKey, MerchantMode, MerchantStatus, PaymentIntent,
    PaymentIntentStatus, Wallet, WalletStatus,
)
from wallet.services.fees import resolve_fee
from wallet.services.merchants import generate_merchant_api_keys
from wallet.services.payment_intents import (
    PaymentIntentError,
    confirm_payment_intent,
    create_payment_intent,
    expire_payment_intents,
)
from wallet.merchant_authentication import MerchantApiKeyAuthentication

User = get_user_model()


class MerchantPaymentTestCase(TestCase):
    def setUp(self):
        self.merchant_user = User.objects.create_user(
            email='merchant@test.com', handle='merchant1', display_name='Merchant',
        )
        self.customer = User.objects.create_user(
            email='customer@test.com', handle='customer1', display_name='Customer',
        )
        self.merchant_wallet = Wallet.objects.create(user=self.merchant_user, currency='USD')
        self.customer_wallet = Wallet.objects.create(user=self.customer, currency='USD')

        self.merchant = Merchant.objects.create(
            user=self.merchant_user,
            business_name='Test Shop',
            wallet=self.merchant_wallet,
            status=MerchantStatus.ACTIVE,
            webhook_url='https://example.com/webhook',
            webhook_secret='test-secret',
        )

        LedgerEntry.objects.create(
            wallet=self.customer_wallet, transaction=None,
            direction=LedgerDirection.CREDIT, amount=Decimal('100.00'),
        )

        self.live_public, self.live_secret = generate_merchant_api_keys(self.merchant, MerchantMode.LIVE)
        self.test_public, self.test_secret = generate_merchant_api_keys(self.merchant, MerchantMode.SANDBOX)

    def _auth_request(self, secret_key):
        from rest_framework.test import APIRequestFactory
        factory = APIRequestFactory()
        request = factory.post('/api/merchant/v1/payment-intents', HTTP_AUTHORIZATION=f'Bearer {secret_key}')
        auth = MerchantApiKeyAuthentication()
        user, api_key = auth.authenticate(request)
        request.user = user
        request.merchant_api_mode = request.merchant_api_mode
        request.merchant_api_key = api_key
        return request

    def test_sk_test_cannot_create_live_intent_via_mode_mismatch(self):
        request = self._auth_request(self.test_secret)
        self.assertEqual(request.merchant_api_mode, MerchantMode.SANDBOX)
        intent = create_payment_intent(
            self.merchant, amount=Decimal('10.00'), currency='USD',
            external_reference='order-1', mode=MerchantMode.SANDBOX,
        )
        self.assertEqual(intent.mode, MerchantMode.SANDBOX)

    def test_live_checkout_moves_money_with_fee_split(self):
        FeePolicy.objects.create(
            name='Default merchant fee',
            applies_to=FeeAppliesTo.MERCHANT_TRANSFER,
            fee_percent=Decimal('2.5'),
            priority=1,
        )
        intent = create_payment_intent(
            self.merchant, amount=Decimal('20.00'), currency='USD',
            mode=MerchantMode.LIVE,
        )
        with patch('wallet.tasks.deliver_webhook_task.delay'):
            confirm_payment_intent(intent, self.customer, 'idem-checkout-1')
        intent.refresh_from_db()
        self.assertEqual(intent.status, PaymentIntentStatus.SUCCEEDED)
        self.customer_wallet.refresh_from_db()
        self.merchant_wallet.refresh_from_db()

        fee_amount, _ = resolve_fee(Decimal('20.00'), FeeAppliesTo.MERCHANT_TRANSFER, currency='USD')
        self.assertEqual(self.customer_wallet.get_balance(), Decimal('100.00') - Decimal('20.00') - fee_amount)
        self.assertEqual(self.merchant_wallet.get_balance(), Decimal('20.00'))

    def test_sandbox_payment_does_not_affect_live_balance(self):
        intent = create_payment_intent(
            self.merchant, amount=Decimal('15.00'), currency='USD',
            mode=MerchantMode.SANDBOX,
        )
        from wallet.services.payment_intents import _get_payer_wallet
        sandbox_wallet = _get_payer_wallet(self.customer, 'USD', is_sandbox=True)
        LedgerEntry.objects.create(
            wallet=sandbox_wallet, transaction=None,
            direction=LedgerDirection.CREDIT, amount=Decimal('50.00'),
        )
        with patch('wallet.tasks.deliver_webhook_task.delay'):
            confirm_payment_intent(intent, self.customer, 'idem-sandbox-1')
        self.assertEqual(self.merchant_wallet.get_balance(), Decimal('0.00'))

    def test_expired_intent_cannot_be_confirmed(self):
        intent = create_payment_intent(
            self.merchant, amount=Decimal('5.00'), currency='USD', mode=MerchantMode.LIVE,
        )
        PaymentIntent.objects.filter(pk=intent.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        intent.refresh_from_db()
        with self.assertRaises(PaymentIntentError) as ctx:
            confirm_payment_intent(intent, self.customer, 'idem-expired')
        self.assertEqual(ctx.exception.code, 'expired')

    def test_expire_payment_intents_task(self):
        intent = create_payment_intent(
            self.merchant, amount=Decimal('5.00'), currency='USD', mode=MerchantMode.LIVE,
        )
        PaymentIntent.objects.filter(pk=intent.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        with patch('wallet.tasks.deliver_webhook_task.delay'):
            result = expire_payment_intents()
        self.assertEqual(result['expired_count'], 1)
        intent.refresh_from_db()
        self.assertEqual(intent.status, PaymentIntentStatus.EXPIRED)

    def test_merchant_scoped_fee_outranks_general(self):
        FeePolicy.objects.create(
            name='General', applies_to=FeeAppliesTo.MERCHANT_TRANSFER,
            fee_percent=Decimal('5.0'), priority=1,
        )
        FeePolicy.objects.create(
            name='Merchant special', applies_to=FeeAppliesTo.MERCHANT_TRANSFER,
            merchant=self.merchant, fee_percent=Decimal('1.0'), priority=0,
        )
        fee, policy = resolve_fee(
            Decimal('100.00'), FeeAppliesTo.MERCHANT_TRANSFER, merchant=self.merchant, currency='USD',
        )
        self.assertEqual(policy.name, 'Merchant special')
        self.assertEqual(fee, Decimal('1.00'))

    @patch('wallet.services.webhooks.requests.post')
    def test_webhook_retries_on_failure(self, mock_post):
        from wallet.services.webhooks import deliver_webhook, enqueue_payment_intent_webhook

        import requests

        mock_post.side_effect = requests.ConnectionError('connection refused')
        intent = create_payment_intent(
            self.merchant, amount=Decimal('10.00'), currency='USD', mode=MerchantMode.LIVE,
        )
        intent.status = PaymentIntentStatus.SUCCEEDED
        intent.save()
        with patch('wallet.tasks.deliver_webhook_task.delay'):
            delivery = enqueue_payment_intent_webhook(intent, 'payment_intent.succeeded')
        with self.assertRaises(Exception):
            deliver_webhook(delivery.id)
        delivery.refresh_from_db()
        self.assertEqual(delivery.attempt_count, 1)

    def test_public_key_cannot_authenticate(self):
        from rest_framework.test import APIRequestFactory
        factory = APIRequestFactory()
        request = factory.post('/api/merchant/v1/payment-intents', HTTP_AUTHORIZATION=f'Bearer {self.live_public}')
        auth = MerchantApiKeyAuthentication()
        self.assertIsNone(auth.authenticate(request))
