from decimal import Decimal
from unittest.mock import MagicMock, patch

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

    @patch('wallet.services.exchange_rates.fetch_latest_rates')
    def test_refresh_creates_new_rows_without_updating_old(self, mock_fetch):
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
        # Historical row preserved — two EUR rates now exist
        self.assertEqual(ExchangeRate.objects.filter(from_currency='USD', to_currency='EUR').count(), 2)

        active = get_active_exchange_rate('USD', 'EUR')
        self.assertEqual(active.rate, Decimal('0.87'))
        expired = ExchangeRate.objects.filter(
            from_currency='USD', to_currency='EUR', valid_until__isnull=False
        ).first()
        self.assertIsNotNone(expired)

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
