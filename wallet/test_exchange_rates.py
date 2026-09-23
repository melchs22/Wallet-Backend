from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase, override_settings

from wallet.models import ExchangeRate, SupportedCountry, Wallet
from wallet.services.exchange_rates import (
    fetch_latest_rates,
    get_active_exchange_rate,
    get_active_currencies,
    refresh_exchange_rates,
)


MOCK_API_RESPONSE = {
    'timestamp': 1786996800,
    'base': 'USD',
    'rates': {
        'USD': 1,
        'EUR': 0.86,
        'GBP': 0.74,
        'KES': 129.39,
    },
}


@override_settings(EXCHANGE_RATE_EXTRA_CURRENCIES=['USD', 'EUR', 'GBP', 'KES'])
class ExchangeRateServiceTestCase(TestCase):
    @patch('wallet.services.exchange_rates.requests.get')
    def test_fetch_latest_rates(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = MOCK_API_RESPONSE
        mock_get.return_value = mock_response

        result = fetch_latest_rates('USD')
        self.assertEqual(result['base'], 'USD')
        self.assertEqual(result['rates']['EUR'], 0.86)

    @patch('wallet.services.exchange_rates.requests.get')
    def test_fetch_falls_back_when_primary_is_unavailable(self, mock_get):
        primary = MagicMock()
        primary.raise_for_status.side_effect = requests.HTTPError('403')
        fallback = MagicMock()
        fallback.raise_for_status = MagicMock()
        fallback.json.return_value = {
            'base': 'USD',
            'rates': {'EUR': 0.86},
        }
        mock_get.side_effect = [primary, fallback]

        result = fetch_latest_rates('USD')

        self.assertEqual(result['source'], 'frankfurter.app')
        self.assertEqual(result['rates']['EUR'], 0.86)
        self.assertEqual(mock_get.call_count, 2)

    @patch('wallet.services.exchange_rates.fetch_latest_rates')
    def test_refresh_replaces_old_rows(self, mock_fetch):
        mock_fetch.return_value = {
            'base': 'USD',
            'timestamp': 1786996800,
            'rates': {'USD': 1, 'EUR': 0.86, 'GBP': 0.74, 'KES': 129.39},
        }

        first = refresh_exchange_rates(base_currencies=['USD'], target_currencies=['USD', 'EUR', 'GBP'])
        self.assertEqual(first['created_count'], 2)
        self.assertEqual(ExchangeRate.objects.filter(from_currency='USD', to_currency='EUR').count(), 1)

        mock_fetch.return_value = {
            'base': 'USD',
            'timestamp': 1786996801,
            'rates': {'USD': 1, 'EUR': 0.87, 'GBP': 0.74, 'KES': 129.39},
        }
        second = refresh_exchange_rates(base_currencies=['USD'], target_currencies=['USD', 'EUR', 'GBP'])
        self.assertEqual(second['created_count'], 2)
        # A replacement refresh must not retain stale rows.
        self.assertEqual(ExchangeRate.objects.filter(from_currency='USD', to_currency='EUR').count(), 1)

        active = get_active_exchange_rate('USD', 'EUR')
        self.assertEqual(active.rate, Decimal('0.87'))
        self.assertFalse(ExchangeRate.objects.filter(valid_until__isnull=False).exists())

    @patch('wallet.services.exchange_rates.fetch_latest_rates')
    def test_refresh_failure_preserves_existing_rows(self, mock_fetch):
        ExchangeRate.objects.create(
            from_currency='USD',
            to_currency='EUR',
            rate=Decimal('0.86'),
            source='test',
            valid_from='2026-01-01T00:00:00Z',
        )
        mock_fetch.side_effect = ValueError('provider unavailable')

        with self.assertRaises(RuntimeError):
            refresh_exchange_rates(
                base_currencies=['USD'],
                target_currencies=['USD', 'EUR'],
            )

        self.assertEqual(ExchangeRate.objects.count(), 1)

    @patch('wallet.services.exchange_rates.fetch_latest_rates')
    def test_refresh_uses_wallet_currencies(self, mock_fetch):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create_user(email='u@test.com', handle='u1', display_name='U')
        Wallet.objects.create(user=user, currency='EUR')

        mock_fetch.return_value = {
            'base': 'EUR',
            'rates': {'USD': 1.16, 'EUR': 1, 'GBP': 0.86},
        }

        refresh_exchange_rates(base_currencies=['EUR'], target_currencies=['USD', 'EUR', 'GBP'])
        self.assertTrue(ExchangeRate.objects.filter(from_currency='EUR', to_currency='USD').exists())
        mock_fetch.assert_called()

    def test_active_country_currencies_are_included(self):
        SupportedCountry.objects.create(
            code='UG',
            name='Uganda',
            dial_code='+256',
            currency='UGX',
            active=True,
        )
        SupportedCountry.objects.create(
            code='XX',
            name='Inactive',
            dial_code='+000',
            currency='XXX',
            active=False,
        )

        currencies = get_active_currencies()

        self.assertIn('UGX', currencies)
        self.assertNotIn('XXX', currencies)

    @patch('wallet.services.exchange_rates.fetch_latest_rates')
    def test_refresh_uses_reverse_pair_when_direct_rate_is_missing(self, mock_fetch):
        mock_fetch.side_effect = [
            {'base': 'GNF', 'rates': {'GNF': 1}},
            {'base': 'USD', 'rates': {'USD': 1, 'GNF': 10000}},
        ]

        result = refresh_exchange_rates(
            base_currencies=['GNF', 'USD'],
            target_currencies=['GNF', 'USD'],
        )

        self.assertEqual(result['created_count'], 2)
        self.assertEqual(
            ExchangeRate.objects.get(from_currency='GNF', to_currency='USD').rate,
            Decimal('0.0001'),
        )
