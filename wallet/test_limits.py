from decimal import Decimal

from django.test import TestCase

from wallet.models import (
    KYCTier,
    LedgerDirection,
    LedgerEntry,
    SystemSetting,
    Transaction,
    TransactionStatus,
    TransactionType,
    User,
    UserStatus,
    Wallet,
)
from wallet.services.limits import apply_usage_based_limits, compute_limit_snapshot


class UsageBasedLimitsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='limits@example.com',
            handle='limitsuser',
            display_name='Limits User',
            kyc_tier=KYCTier.TIER_0,
            status=UserStatus.ACTIVE,
        )
        self.wallet = Wallet.objects.create(user=self.user, currency='GNF')
        LedgerEntry.objects.create(
            wallet=self.wallet,
            transaction=None,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('0.00'),
        )

    def test_new_user_uses_system_base_limits(self):
        snapshot = apply_usage_based_limits(self.user)
        self.user.refresh_from_db()
        self.assertEqual(self.user.send_limit_per_tx, Decimal('1000.00'))
        self.assertEqual(self.user.send_limit_daily, Decimal('5000.00'))
        self.assertEqual(snapshot['current_step'], 0)
        self.assertEqual(snapshot['transfers_until_next_increase'], 5)

    def test_completed_transfers_raise_limits(self):
        recipient = User.objects.create_user(
            email='recv@example.com',
            handle='recvuser',
            display_name='Recv',
            kyc_tier=KYCTier.TIER_0,
            status=UserStatus.ACTIVE,
        )
        for _ in range(5):
            Transaction.objects.create(
                type=TransactionType.P2P_TRANSFER,
                sender=self.user,
                recipient=recipient,
                amount=Decimal('10.00'),
                currency='GNF',
                status=TransactionStatus.COMPLETED,
            )
        snapshot = apply_usage_based_limits(self.user)
        self.user.refresh_from_db()
        self.assertEqual(snapshot['current_step'], 1)
        self.assertEqual(self.user.send_limit_per_tx, Decimal('1500.00'))
        self.assertEqual(self.user.send_limit_daily, Decimal('7500.00'))
        self.assertEqual(snapshot['next_send_limit_per_tx'], Decimal('2000.00'))
        self.assertEqual(snapshot['next_send_limit_daily'], Decimal('10000.00'))
        self.assertEqual(snapshot['transfers_per_step'], 5)

    def test_kyc_tier_adds_bonus(self):
        self.user.kyc_tier = KYCTier.TIER_1
        self.user.save(update_fields=['kyc_tier'])
        apply_usage_based_limits(self.user)
        self.user.refresh_from_db()
        self.assertEqual(self.user.send_limit_per_tx, Decimal('3000.00'))
        self.assertEqual(self.user.send_limit_daily, Decimal('15000.00'))

    def test_manual_admin_limits_are_not_overwritten(self):
        self.user.send_limit_per_tx = Decimal('50.00')
        self.user.send_limit_daily = Decimal('80.00')
        self.user.limits_manually_set = True
        self.user.save()
        apply_usage_based_limits(self.user)
        self.user.refresh_from_db()
        self.assertEqual(self.user.send_limit_per_tx, Decimal('50.00'))
        self.assertEqual(self.user.send_limit_daily, Decimal('80.00'))

    def test_system_setting_changes_base_limits(self):
        SystemSetting.objects.create(key='max_single_transfer_limit', value='2000.00')
        SystemSetting.objects.create(key='max_daily_transfer_limit', value='8000.00')
        snapshot = compute_limit_snapshot(self.user)
        self.assertEqual(snapshot['send_limit_per_tx'], Decimal('2000.00'))
        self.assertEqual(snapshot['send_limit_daily'], Decimal('8000.00'))
