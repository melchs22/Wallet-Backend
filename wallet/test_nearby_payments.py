from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.db import connections
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from wallet.models import (
    AuditLog,
    KYCTier,
    LedgerDirection,
    LedgerEntry,
    NearbyPaymentRequest,
    Transaction,
    TransactionStatus,
    TransactionType,
    User,
    UserStatus,
    Wallet,
)


@override_settings(RATELIMIT_ENABLE=False, NEARBY_PAYMENTS_ENABLED=True)
class NearbyPaymentApiTests(APITestCase):
    def setUp(self):
        self.receiver = User.objects.create_user(
            email='nearby-receiver@example.com',
            password='strong-password',
            handle='nearbyreceiver',
            display_name='Nearby Receiver',
            status=UserStatus.ACTIVE,
            kyc_tier=KYCTier.TIER_1,
        )
        self.payer = User.objects.create_user(
            email='nearby-payer@example.com',
            password='strong-password',
            handle='nearbypayer',
            display_name='Nearby Payer',
            status=UserStatus.ACTIVE,
            kyc_tier=KYCTier.TIER_1,
            transaction_pin=make_password('1234'),
        )
        self.receiver_wallet = Wallet.objects.create(user=self.receiver, currency='GNF')
        self.payer_wallet = Wallet.objects.create(user=self.payer, currency='GNF')
        opening_credit = Transaction.objects.create(
            type=TransactionType.TOPUP,
            recipient=self.payer,
            amount=Decimal('1000.00'),
            currency='GNF',
            status=TransactionStatus.COMPLETED,
        )
        LedgerEntry.objects.create(
            wallet=self.payer_wallet,
            transaction=opening_credit,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('1000.00'),
        )
        self.request_data = self.create_request()

    def create_request(self, amount='25.00'):
        self.client.force_authenticate(user=self.receiver)
        response = self.client.post(
            '/api/nearby-payments',
            {'amount': amount, 'currency': 'GNF', 'note': 'Coffee'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def pay(self, payload, key='f9df1d57-4048-49c0-a976-039d8dbce731'):
        self.client.force_authenticate(user=self.payer)
        with (
            patch('wallet.views.step_up_required', return_value=False),
            patch('wallet.views.user_has_approved_kyc', return_value=True),
        ):
            return self.client.post(
                f"/api/nearby-payments/{payload['id']}/pay",
                {'pin': '1234', 'idempotency_key': key},
                format='json',
            )

    def test_create_returns_single_use_code_without_persisting_it(self):
        code = self.request_data['discovery_code']
        self.assertRegex(code, r'^[A-HJ-NP-Z2-9]{9}$')
        nearby_request = NearbyPaymentRequest.objects.get(pk=self.request_data['id'])
        self.assertNotEqual(nearby_request.code_digest, code)
        self.assertGreater(nearby_request.expires_at - nearby_request.created_at, timedelta(seconds=119))
        self.assertLessEqual(nearby_request.expires_at - nearby_request.created_at, timedelta(minutes=2))
        self.assertNotIn(code, str(AuditLog.objects.filter(user=self.receiver).values_list('metadata', flat=True)))

    def test_disabled_feature_rejects_request_creation(self):
        self.client.force_authenticate(user=self.receiver)
        with override_settings(NEARBY_PAYMENTS_ENABLED=False):
            response = self.client.post(
                '/api/nearby-payments',
                {'amount': '10.00', 'currency': 'GNF'},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['code'], 'feature_disabled')

    def test_resolve_exposes_only_the_live_request_and_transfer_quote(self):
        self.client.force_authenticate(user=self.payer)
        response = self.client.post(
            '/api/nearby-payments/resolve',
            {'code': self.request_data['discovery_code']},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['receiver']['handle'], self.receiver.handle)
        self.assertEqual(response.data['amount'], '25.00')
        self.assertIn('fee_amount', response.data)
        self.assertNotIn('discovery_code', response.data)

    def test_payment_settles_once_and_same_idempotency_key_replays_result(self):
        before_balance = self.payer_wallet.get_balance()
        first = self.pay(self.request_data)
        replay = self.pay(self.request_data)

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(replay.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data['transaction_id'], replay.data['transaction_id'])
        self.assertEqual(
            Transaction.objects.filter(type=TransactionType.P2P_TRANSFER).count(),
            1,
        )
        self.assertLess(self.payer_wallet.get_balance(), before_balance)
        self.assertEqual(
            NearbyPaymentRequest.objects.get(pk=self.request_data['id']).status,
            NearbyPaymentRequest.Status.PAID,
        )
        self.client.force_authenticate(user=self.payer)
        status_response = self.client.get(
            f"/api/nearby-payments/{self.request_data['id']}",
        )
        self.assertEqual(status_response.status_code, status.HTTP_200_OK)
        self.assertEqual(status_response.data['status'], NearbyPaymentRequest.Status.PAID)

    def test_paid_request_rejects_a_different_idempotency_key(self):
        self.assertEqual(self.pay(self.request_data).status_code, status.HTTP_200_OK)
        response = self.pay(self.request_data, key='5bc1b340-b722-473d-98cd-e79480721199')

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(Transaction.objects.filter(type=TransactionType.P2P_TRANSFER).count(), 1)

    def test_invalid_pin_does_not_create_a_transfer(self):
        self.client.force_authenticate(user=self.payer)
        with (
            patch('wallet.views.step_up_required', return_value=False),
            patch('wallet.views.user_has_approved_kyc', return_value=True),
        ):
            response = self.client.post(
                f"/api/nearby-payments/{self.request_data['id']}/pay",
                {
                    'pin': '9999',
                    'idempotency_key': 'd663454b-ecc2-44fa-a35d-d1ef91750ff3',
                },
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Transaction.objects.filter(type=TransactionType.P2P_TRANSFER).exists())

    def test_payment_requires_step_up_and_approved_kyc(self):
        self.client.force_authenticate(user=self.payer)
        with (
            patch('wallet.views.step_up_required', return_value=True),
            patch('wallet.views.user_has_approved_kyc', return_value=True),
        ):
            step_up_response = self.client.post(
                f"/api/nearby-payments/{self.request_data['id']}/pay",
                {
                    'pin': '1234',
                    'idempotency_key': '4438185b-fb61-4b15-9c9c-7338a11fc019',
                },
                format='json',
            )
        self.assertEqual(step_up_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(step_up_response.data['code'], 'otp_required')

        with (
            patch('wallet.views.step_up_required', return_value=False),
            patch('wallet.views.user_has_approved_kyc', return_value=False),
        ):
            kyc_response = self.client.post(
                f"/api/nearby-payments/{self.request_data['id']}/pay",
                {
                    'pin': '1234',
                    'idempotency_key': '6ea75123-f77c-416a-984b-7b8892f05fb4',
                },
                format='json',
            )
        self.assertEqual(kyc_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(kyc_response.data['code'], 'kyc_required')
        self.assertFalse(Transaction.objects.filter(type=TransactionType.P2P_TRANSFER).exists())

    def test_expired_code_cannot_be_resolved_or_paid(self):
        NearbyPaymentRequest.objects.filter(pk=self.request_data['id']).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.client.force_authenticate(user=self.payer)
        response = self.client.post(
            '/api/nearby-payments/resolve',
            {'code': self.request_data['discovery_code']},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            NearbyPaymentRequest.objects.get(pk=self.request_data['id']).status,
            NearbyPaymentRequest.Status.EXPIRED,
        )
        self.assertFalse(Transaction.objects.filter(type=TransactionType.P2P_TRANSFER).exists())

    def test_status_and_cancel_are_receiver_only(self):
        self.client.force_authenticate(user=self.payer)
        response = self.client.get(f"/api/nearby-payments/{self.request_data['id']}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(user=self.receiver)
        response = self.client.post(
            f"/api/nearby-payments/{self.request_data['id']}/cancel",
            {},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], NearbyPaymentRequest.Status.CANCELLED)


@skipUnlessDBFeature('has_select_for_update')
@override_settings(NEARBY_PAYMENTS_ENABLED=True)
class NearbyPaymentConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        from django.contrib.auth.hashers import make_password

        self.receiver = User.objects.create_user(
            email='concurrent-receiver@example.com',
            password='strong-password',
            handle='concurrentreceiver',
            display_name='Concurrent Receiver',
            status=UserStatus.ACTIVE,
            kyc_tier=KYCTier.TIER_1,
        )
        self.payers = []
        for index in (1, 2):
            payer = User.objects.create_user(
                email=f'concurrent-payer-{index}@example.com',
                password='strong-password',
                handle=f'concurrentpayer{index}',
                display_name=f'Concurrent Payer {index}',
                status=UserStatus.ACTIVE,
                kyc_tier=KYCTier.TIER_1,
                transaction_pin=make_password('1234'),
            )
            wallet = Wallet.objects.create(user=payer, currency='GNF')
            credit = Transaction.objects.create(
                type=TransactionType.TOPUP,
                recipient=payer,
                amount=Decimal('100.00'),
                currency='GNF',
                status=TransactionStatus.COMPLETED,
            )
            LedgerEntry.objects.create(
                wallet=wallet,
                transaction=credit,
                direction=LedgerDirection.CREDIT,
                amount=Decimal('100.00'),
            )
            self.payers.append(payer)
        Wallet.objects.create(user=self.receiver, currency='GNF')

        receiver_client = APIClient()
        receiver_client.force_authenticate(user=self.receiver)
        response = receiver_client.post(
            '/api/nearby-payments',
            {'amount': '10.00', 'currency': 'GNF'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.request_id = response.data['id']

    def test_concurrent_distinct_payers_only_settle_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        barrier = Barrier(2)
        keys = [
            '399bb75c-d753-41be-ac6e-e50a953d0e85',
            'de5d12de-bde0-48e4-bab9-dcf5eff2600b',
        ]

        def attempt_payment(payer, idempotency_key):
            connections.close_all()
            try:
                client = APIClient()
                client.force_authenticate(user=payer)
                barrier.wait(timeout=10)
                with (
                    patch('wallet.views.step_up_required', return_value=False),
                    patch('wallet.views.user_has_approved_kyc', return_value=True),
                ):
                    response = client.post(
                        f'/api/nearby-payments/{self.request_id}/pay',
                        {'pin': '1234', 'idempotency_key': idempotency_key},
                        format='json',
                    )
                return response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(
                lambda args: attempt_payment(*args),
                zip(self.payers, keys),
            ))

        self.assertCountEqual(results, [status.HTTP_200_OK, status.HTTP_409_CONFLICT])
        self.assertEqual(
            Transaction.objects.filter(type=TransactionType.P2P_TRANSFER).count(),
            1,
        )
