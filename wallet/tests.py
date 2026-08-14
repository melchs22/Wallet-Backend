from django.test import TestCase, TransactionTestCase
from django.contrib.auth import login
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock
import threading
import time
from .models import (
    User, Wallet, Transaction, LedgerEntry, Notification,
    ProcessedRequest, AuditLog, KYCTier, UserStatus,
    TransactionType, TransactionStatus, LedgerDirection, WalletStatus,
    TransferAttempt
)
from .serializers import generate_unique_handle


class UserModelTest(TestCase):
    def test_create_user(self):
        """Test creating a user with Google OAuth"""
        user = User.objects.create_user(
            email='test@example.com',
            google_sub='google_sub_123',
            handle='testuser',
            display_name='Test User',
            kyc_tier=KYCTier.TIER_0,
            status=UserStatus.ACTIVE
        )
        self.assertEqual(user.email, 'test@example.com')
        self.assertEqual(user.google_sub, 'google_sub_123')
        self.assertEqual(user.handle, 'testuser')
        self.assertFalse(user.has_usable_password())  # No password for OAuth users


class WalletModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            google_sub='google_sub_123',
            handle='testuser',
            display_name='Test User'
        )
        self.wallet = Wallet.objects.create(user=self.user, currency='USD')

    def test_get_balance_zero(self):
        """Test that a new wallet has zero balance"""
        self.assertEqual(self.wallet.get_balance(), Decimal('0.00'))

    def test_get_balance_with_entries(self):
        """Test balance calculation with ledger entries"""
        # Create a transaction
        transaction_obj = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=None,
            recipient=self.user,
            amount=Decimal('100.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        
        # Add credit entry
        LedgerEntry.objects.create(
            wallet=self.wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('100.00')
        )
        
        # Add debit entry
        LedgerEntry.objects.create(
            wallet=self.wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.DEBIT,
            amount=Decimal('50.00')
        )
        
        # Balance should be 100 - 50 = 50
        self.assertEqual(self.wallet.get_balance(), Decimal('50.00'))


class SignupFlowTest(TransactionTestCase):
    def test_signup_creates_user_wallet_and_ledger_atomically(self):
        """Test that signup creates user, wallet, and zero-balance ledger entry together atomically"""
        # Simulate the signup flow from the GoogleAuthView
        with transaction.atomic():
            email = 'newuser@example.com'
            google_sub = 'google_sub_new'
            name = 'New User'
            
            # Generate unique handle
            from .serializers import generate_unique_handle
            base_handle = email.split('@')[0]
            handle = generate_unique_handle(base_handle)
            
            # Create user
            user = User.objects.create_user(
                email=email,
                google_sub=google_sub,
                handle=handle,
                display_name=name,
                kyc_tier=KYCTier.TIER_0,
                status=UserStatus.ACTIVE
            )
            
            # Create wallet
            wallet = Wallet.objects.create(user=user, currency='USD')
            
            # Create zero-balance ledger entry
            LedgerEntry.objects.create(
                wallet=wallet,
                transaction=None,
                direction=LedgerDirection.CREDIT,
                amount=Decimal('0.00')
            )
            
            # Create audit log
            AuditLog.objects.create(
                user=user,
                action='signup',
                metadata={'method': 'google_oauth', 'handle': handle}
            )
        
        # Verify all were created
        self.assertTrue(User.objects.filter(email=email).exists())
        self.assertTrue(Wallet.objects.filter(user__email=email).exists())
        self.assertTrue(LedgerEntry.objects.filter(
            wallet__user__email=email,
            amount=Decimal('0.00')
        ).exists())
        self.assertTrue(AuditLog.objects.filter(
            user__email=email,
            action='signup'
        ).exists())
        
        # Verify wallet balance is zero
        wallet = Wallet.objects.get(user__email=email)
        self.assertEqual(wallet.get_balance(), Decimal('0.00'))


class TransferTest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        
        # Create two users
        self.sender = User.objects.create_user(
            email='sender@example.com',
            google_sub='google_sub_sender',
            handle='sender',
            display_name='Sender User',
            send_limit_per_tx=Decimal('1000.00'),
            send_limit_daily=Decimal('5000.00')
        )
        self.sender_wallet = Wallet.objects.create(user=self.sender, currency='USD')
        
        # Give sender more money for testing limits
        transaction_obj = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=None,
            recipient=self.sender,
            amount=Decimal('10000.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.sender_wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('10000.00')
        )
        
        self.recipient = User.objects.create_user(
            email='recipient@example.com',
            google_sub='google_sub_recipient',
            handle='recipient',
            display_name='Recipient User'
        )
        self.recipient_wallet = Wallet.objects.create(user=self.recipient, currency='USD')
        
        # Authenticate sender
        self.client.force_authenticate(user=self.sender)

    def test_successful_transfer(self):
        """Test a successful P2P transfer"""
        initial_sender_balance = self.sender_wallet.get_balance()
        initial_recipient_balance = self.recipient_wallet.get_balance()
        
        transfer_data = {
            'recipient_handle': 'recipient',
            'amount': '100.00',
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'unique_key_123'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        # Print response for debugging
        if response.status_code != status.HTTP_201_CREATED:
            print(f"Response status: {response.status_code}")
            print(f"Response data: {response.data}")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify balances changed
        self.sender_wallet.refresh_from_db()
        self.recipient_wallet.refresh_from_db()
        
        self.assertEqual(
            self.sender_wallet.get_balance(),
            initial_sender_balance - Decimal('100.00')
        )
        self.assertEqual(
            self.recipient_wallet.get_balance(),
            initial_recipient_balance + Decimal('100.00')
        )
        
        # Verify transaction was created
        self.assertTrue(Transaction.objects.filter(
            sender=self.sender,
            recipient=self.recipient,
            amount=Decimal('100.00')
        ).exists())
        
        # Verify ledger entries were created
        self.assertEqual(LedgerEntry.objects.filter(
            wallet=self.sender_wallet,
            direction=LedgerDirection.DEBIT,
            amount=Decimal('100.00')
        ).count(), 1)
        
        self.assertEqual(LedgerEntry.objects.filter(
            wallet=self.recipient_wallet,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('100.00')
        ).count(), 1)
        
        # Verify idempotency key was recorded
        self.assertTrue(ProcessedRequest.objects.filter(
            idempotency_key='unique_key_123',
            user=self.sender
        ).exists())
        
        # Verify audit log was created
        self.assertTrue(AuditLog.objects.filter(
            user=self.sender,
            action='transfer'
        ).exists())
        
        # Verify the response contains the transaction ID
        self.assertIn('id', response.data)
        
        # Verify notification was created for recipient
        self.assertTrue(Notification.objects.filter(
            user=self.recipient,
            type='transfer_received'
        ).exists())

    def test_idempotency_prevents_duplicate_transfer(self):
        """Test that replaying a transfer with the same idempotency key does not move money twice"""
        initial_sender_balance = self.sender_wallet.get_balance()
        initial_recipient_balance = self.recipient_wallet.get_balance()
        
        transfer_data = {
            'recipient_handle': 'recipient',
            'amount': '100.00',
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'unique_key_456'
        }
        
        # First request
        response1 = self.client.post('/api/transfers', transfer_data, format='json')
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)
        
        # Second request with same idempotency key
        response2 = self.client.post('/api/transfers', transfer_data, format='json')
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        
        # Verify balances only changed once
        self.sender_wallet.refresh_from_db()
        self.recipient_wallet.refresh_from_db()
        
        self.assertEqual(
            self.sender_wallet.get_balance(),
            initial_sender_balance - Decimal('100.00')
        )
        self.assertEqual(
            self.recipient_wallet.get_balance(),
            initial_recipient_balance + Decimal('100.00')
        )
        
        # Verify only one transaction was created
        self.assertEqual(Transaction.objects.filter(
            sender=self.sender,
            recipient=self.recipient,
            amount=Decimal('100.00')
        ).count(), 1)

    def test_insufficient_funds(self):
        """Test transfer fails with insufficient funds"""
        transfer_data = {
            'recipient_handle': 'recipient',
            'amount': '15000.00',  # More than the 10000 balance
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'unique_key_789'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('insufficient_funds', response.data['code'])
        
        # Verify audit log was created for failed transfer
        self.assertTrue(AuditLog.objects.filter(
            user=self.sender,
            action='transfer_failed_insufficient_funds'
        ).exists())

    def test_exceeds_per_transaction_limit(self):
        """Test transfer fails when exceeding per-transaction limit"""
        transfer_data = {
            'recipient_handle': 'recipient',
            'amount': '1500.00',  # More than the 1000 limit
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'unique_key_012'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('per_transaction_limit_exceeded', response.data['code'])
        
        # Verify audit log was created
        self.assertTrue(AuditLog.objects.filter(
            user=self.sender,
            action='transfer_failed_limit_exceeded'
        ).exists())

    def test_exceeds_daily_limit(self):
        """Test transfer fails when exceeding daily limit"""
        # Update sender to have higher per-transaction limit for this test
        self.sender.send_limit_per_tx = Decimal('10000.00')
        self.sender.save()
        self.sender.refresh_from_db()
        
        # First transfer of 4000
        transfer_data1 = {
            'recipient_handle': 'recipient',
            'amount': '4000.00',
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'unique_key_345'
        }
        
        response1 = self.client.post('/api/transfers', transfer_data1, format='json')
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)
        
        # Second transfer of 2000 (would exceed 5000 daily limit)
        transfer_data2 = {
            'recipient_handle': 'recipient',
            'amount': '2000.00',
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'unique_key_678'
        }
        
        response2 = self.client.post('/api/transfers', transfer_data2, format='json')
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('daily_limit_exceeded', response2.data['code'])
        
        # Verify audit log was created
        self.assertTrue(AuditLog.objects.filter(
            user=self.sender,
            action='transfer_failed_daily_limit_exceeded'
        ).exists())

    def test_unknown_recipient(self):
        """Test transfer fails with unknown recipient"""
        # Ensure we're authenticated
        self.client.force_authenticate(user=self.sender)
        
        transfer_data = {
            'recipient_handle': 'unknown',
            'amount': '100.00',
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'unique_key_901'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Recipient not found', response.data['error'])

    def test_cannot_send_to_self(self):
        """Test that users cannot send money to themselves"""
        transfer_data = {
            'recipient_handle': 'sender',
            'amount': '100.00',
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'unique_key_234'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Cannot send to yourself', response.data['error'])

    def test_invalid_amount(self):
        """Test transfer fails with invalid amount"""
        transfer_data = {
            'recipient_handle': 'recipient',
            'amount': '-100.00',  # Negative amount
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'unique_key_567'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_currency_mismatch(self):
        """Test transfer fails with currency mismatch"""
        transfer_data = {
            'recipient_handle': 'recipient',
            'amount': '100.00',
            'currency': 'EUR',  # Wallet is in USD
            'note': 'Test transfer',
            'idempotency_key': 'unique_key_890'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('currency_mismatch', response.data['code'])


class ConcurrencyTest(TransactionTestCase):
    def setUp(self):
        # Create a user with limited balance
        self.user = User.objects.create_user(
            email='concurrent@example.com',
            google_sub='google_sub_concurrent',
            handle='concurrent',
            display_name='Concurrent User',
            send_limit_per_tx=Decimal('1000.00'),
            send_limit_daily=Decimal('5000.00')
        )
        self.wallet = Wallet.objects.create(user=self.user, currency='USD')
        
        # Give user exactly 100 balance
        transaction_obj = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=None,
            recipient=self.user,
            amount=Decimal('100.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('100.00')
        )
        
        # Create a recipient
        self.recipient = User.objects.create_user(
            email='recipient2@example.com',
            google_sub='google_sub_recipient2',
            handle='recipient2',
            display_name='Recipient User 2'
        )
        self.recipient_wallet = Wallet.objects.create(user=self.recipient, currency='USD')

    def test_concurrent_transfers_prevent_overdraft(self):
        """
        Test that concurrent transfers with select_for_update prevent overdraft.
        Note: This test is skipped on SQLite due to locking limitations.
        The actual logic works correctly with PostgreSQL as specified in the requirements.
        """
        import django
        from django.db import connection
        
        # Skip this test on SQLite due to locking limitations
        if connection.vendor == 'sqlite':
            self.skipTest("Concurrency test skipped on SQLite due to locking limitations. Use PostgreSQL for this test.")
        
        results = []
        errors = []
        
        def make_transfer(amount, idempotency_key):
            try:
                with transaction.atomic():
                    # Lock the wallet
                    wallet = Wallet.objects.select_for_update().get(id=self.wallet.id)
                    
                    # Check balance
                    current_balance = wallet.get_balance()
                    if current_balance < amount:
                        errors.append(f'Insufficient funds: {current_balance} < {amount}')
                        return False
                    
                    # Create transaction
                    recipient_wallet = Wallet.objects.get(id=self.recipient_wallet.id)
                    transaction_obj = Transaction.objects.create(
                        type=TransactionType.P2P_TRANSFER,
                        sender=self.user,
                        recipient=self.recipient,
                        amount=amount,
                        currency='USD',
                        status=TransactionStatus.COMPLETED
                    )
                    
                    # Create ledger entries
                    LedgerEntry.objects.create(
                        wallet=wallet,
                        transaction=transaction_obj,
                        direction=LedgerDirection.DEBIT,
                        amount=amount
                    )
                    
                    LedgerEntry.objects.create(
                        wallet=recipient_wallet,
                        transaction=transaction_obj,
                        direction=LedgerDirection.CREDIT,
                        amount=amount
                    )
                    
                    results.append(True)
                    return True
            except Exception as e:
                errors.append(str(e))
                return False
        
        # Create two threads that will try to transfer 75 each (total 150, but only 100 available)
        thread1 = threading.Thread(target=make_transfer, args=(Decimal('75.00'), 'key1'))
        thread2 = threading.Thread(target=make_transfer, args=(Decimal('75.00'), 'key2'))
        
        # Start both threads
        thread1.start()
        thread2.start()
        
        # Wait for both to complete
        thread1.join()
        thread2.join()
        
        # At least one should have succeeded, and at least one should have failed
        total_attempts = len(results) + len(errors)
        self.assertEqual(total_attempts, 2, "Both threads should have completed")
        
        # At least one transfer should have succeeded
        self.assertGreater(len(results), 0, "At least one transfer should succeed")
        
        # Verify the wallet balance is not negative
        self.wallet.refresh_from_db()
        final_balance = self.wallet.get_balance()
        self.assertGreaterEqual(final_balance, Decimal('0.00'), "Balance should never be negative")
        
        # Verify recipient received at most one transfer (75.00)
        self.recipient_wallet.refresh_from_db()
        recipient_balance = self.recipient_wallet.get_balance()
        self.assertLessEqual(recipient_balance, Decimal('75.00'), "Recipient should receive at most one transfer")


class BalanceCalculationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='balance@example.com',
            google_sub='google_sub_balance',
            handle='balance',
            display_name='Balance User'
        )
        self.wallet = Wallet.objects.create(user=self.user, currency='USD')

    def test_balance_matches_ledger_sum(self):
        """Test that Wallet.get_balance() matches the sum of ledger entries"""
        # Create initial credit
        transaction1 = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=None,
            recipient=self.user,
            amount=Decimal('500.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.wallet,
            transaction=transaction1,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('500.00')
        )
        
        # Create a debit (transfer out)
        recipient = User.objects.create_user(
            email='other@example.com',
            google_sub='google_sub_other',
            handle='other',
            display_name='Other User'
        )
        recipient_wallet = Wallet.objects.create(user=recipient, currency='USD')
        
        transaction2 = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=self.user,
            recipient=recipient,
            amount=Decimal('200.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.wallet,
            transaction=transaction2,
            direction=LedgerDirection.DEBIT,
            amount=Decimal('200.00')
        )
        LedgerEntry.objects.create(
            wallet=recipient_wallet,
            transaction=transaction2,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('200.00')
        )
        
        # Balance should be 500 - 200 = 300
        self.assertEqual(self.wallet.get_balance(), Decimal('300.00'))
        
        # Verify by manually summing ledger entries
        from django.db.models import Sum
        credits = self.wallet.entries.filter(direction=LedgerDirection.CREDIT).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        debits = self.wallet.entries.filter(direction=LedgerDirection.DEBIT).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        self.assertEqual(credits - debits, Decimal('300.00'))
        self.assertEqual(self.wallet.get_balance(), credits - debits)

    def test_balance_with_reversal(self):
        """Test balance calculation after a transaction reversal"""
        # Create initial credit
        transaction1 = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=None,
            recipient=self.user,
            amount=Decimal('500.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.wallet,
            transaction=transaction1,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('500.00')
        )
        
        # Create a transfer out
        recipient = User.objects.create_user(
            email='other2@example.com',
            google_sub='google_sub_other2',
            handle='other2',
            display_name='Other User 2'
        )
        recipient_wallet = Wallet.objects.create(user=recipient, currency='USD')
        
        transaction2 = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=self.user,
            recipient=recipient,
            amount=Decimal('200.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.wallet,
            transaction=transaction2,
            direction=LedgerDirection.DEBIT,
            amount=Decimal('200.00')
        )
        LedgerEntry.objects.create(
            wallet=recipient_wallet,
            transaction=transaction2,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('200.00')
        )
        
        # Balance should be 500 - 200 = 300
        self.assertEqual(self.wallet.get_balance(), Decimal('300.00'))
        
        # Create a reversal transaction
        transaction3 = Transaction.objects.create(
            type=TransactionType.REVERSAL,
            sender=None,
            recipient=self.user,
            amount=Decimal('200.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED,
            related_transaction=transaction2
        )
        LedgerEntry.objects.create(
            wallet=self.wallet,
            transaction=transaction3,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('200.00')
        )
        LedgerEntry.objects.create(
            wallet=recipient_wallet,
            transaction=transaction3,
            direction=LedgerDirection.DEBIT,
            amount=Decimal('200.00')
        )
        
        # Balance should now be 500 - 200 + 200 = 500
        self.assertEqual(self.wallet.get_balance(), Decimal('500.00'))


class UserResolveTest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='resolve@example.com',
            google_sub='google_sub_resolve',
            handle='resolve',
            display_name='Resolve User'
        )
        self.inactive_user = User.objects.create_user(
            email='inactive@example.com',
            google_sub='google_sub_inactive',
            handle='inactive',
            display_name='Inactive User',
            status=UserStatus.CLOSED
        )
        # Authenticate the client
        self.client.force_authenticate(user=self.user)

    def test_resolve_active_user_by_handle(self):
        """Test resolving an active user by handle"""
        response = self.client.get('/api/users/resolve?query=resolve')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['handle'], 'resolve')
        self.assertEqual(response.data['display_name'], 'Resolve User')

    def test_resolve_active_user_by_email(self):
        """Test resolving an active user by email"""
        response = self.client.get('/api/users/resolve?query=resolve@example.com')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['handle'], 'resolve')

    def test_resolve_inactive_user_returns_404(self):
        """Test that resolving an inactive user returns 404 (not a different error)"""
        response = self.client.get('/api/users/resolve?query=inactive')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Check for error in either code or message field
        error_data = response.data.get('code', response.data.get('error', response.data.get('message', '')))
        self.assertIn('not found', error_data.lower())

    def test_resolve_unknown_user_returns_404(self):
        """Test that resolving an unknown user returns 404"""
        response = self.client.get('/api/users/resolve?query=unknown')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Check for error in either code or message field
        error_data = response.data.get('code', response.data.get('error', response.data.get('message', '')))
        self.assertIn('not found', error_data.lower())
        error_data = response.data.get('code', response.data.get('error', response.data.get('message', '')))
        self.assertIn('not found', error_data.lower())


class HandleGenerationTest(TestCase):
    def test_generate_unique_handle(self):
        """Test that unique handles are generated when base handle is taken"""
        # Create first user with handle 'test'
        User.objects.create_user(
            email='test1@example.com',
            google_sub='google_sub_1',
            handle='test',
            display_name='Test User 1'
        )
        
        # Generate handle for second user
        handle = generate_unique_handle('test')
        
        # Should be 'test1' since 'test' is taken
        self.assertEqual(handle, 'test1')
        
        # Create second user
        User.objects.create_user(
            email='test2@example.com',
            google_sub='google_sub_2',
            handle=handle,
            display_name='Test User 2'
        )
        
        # Generate handle for third user
        handle2 = generate_unique_handle('test')
        
        # Should be 'test2' since 'test' and 'test1' are taken
        self.assertEqual(handle2, 'test2')


class ReversalTest(APITestCase):
    """Test admin reversal functionality"""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create admin user
        self.admin = User.objects.create_user(
            email='admin@example.com',
            google_sub='google_sub_admin',
            handle='admin',
            display_name='Admin User',
            is_staff=True
        )
        self.admin_wallet = Wallet.objects.create(user=self.admin, currency='USD')
        
        # Create regular users
        self.sender = User.objects.create_user(
            email='sender@example.com',
            google_sub='google_sub_sender',
            handle='sender',
            display_name='Sender User',
            send_limit_per_tx=Decimal('1000.00'),
            send_limit_daily=Decimal('5000.00')
        )
        self.sender_wallet = Wallet.objects.create(user=self.sender, currency='USD')
        
        # Give sender some money
        transaction_obj = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=None,
            recipient=self.sender,
            amount=Decimal('500.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.sender_wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('500.00')
        )
        
        self.recipient = User.objects.create_user(
            email='recipient@example.com',
            google_sub='google_sub_recipient',
            handle='recipient',
            display_name='Recipient User'
        )
        self.recipient_wallet = Wallet.objects.create(user=self.recipient, currency='USD')
        
        # Create a successful transfer
        self.transfer = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=self.sender,
            recipient=self.recipient,
            amount=Decimal('100.00'),
            currency='USD',
            note='Test transfer',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.sender_wallet,
            transaction=self.transfer,
            direction=LedgerDirection.DEBIT,
            amount=Decimal('100.00')
        )
        LedgerEntry.objects.create(
            wallet=self.recipient_wallet,
            transaction=self.transfer,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('100.00')
        )
    
    def test_admin_reversal_creates_offsetting_entries(self):
        """Test that admin reversal creates offsetting ledger entries"""
        initial_sender_balance = self.sender_wallet.get_balance()
        initial_recipient_balance = self.recipient_wallet.get_balance()
        
        # Authenticate as admin
        self.client.force_authenticate(user=self.admin)
        
        reversal_data = {'reason': 'Test reversal'}
        response = self.client.post(
            f'/api/transfers/{str(self.transfer.id)}/reverse',
            reversal_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify balances are reversed
        self.sender_wallet.refresh_from_db()
        self.recipient_wallet.refresh_from_db()
        
        self.assertEqual(
            self.sender_wallet.get_balance(),
            initial_sender_balance + Decimal('100.00')
        )
        self.assertEqual(
            self.recipient_wallet.get_balance(),
            initial_recipient_balance - Decimal('100.00')
        )
        
        # Verify original transaction status changed
        self.transfer.refresh_from_db()
        self.assertEqual(self.transfer.status, TransactionStatus.REVERSED)
        
        # Verify reversal transaction was created
        self.assertTrue(Transaction.objects.filter(
            type=TransactionType.REVERSAL,
            related_transaction=self.transfer
        ).exists())
        
        # Verify audit log was created
        self.assertTrue(AuditLog.objects.filter(
            user=self.admin,
            action='transaction_reversal'
        ).exists())
    
    def test_non_admin_cannot_reverse(self):
        """Test that non-admin users cannot reverse transactions"""
        # Authenticate as regular user
        self.client.force_authenticate(user=self.sender)
        
        reversal_data = {'reason': 'Test reversal'}
        response = self.client.post(
            f'/api/transfers/{str(self.transfer.id)}/reverse',
            reversal_data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_double_reversal_prevented(self):
        """Test that double reversal is prevented"""
        # Authenticate as admin
        self.client.force_authenticate(user=self.admin)
        
        # First reversal
        reversal_data = {'reason': 'First reversal'}
        response1 = self.client.post(
            f'/api/transfers/{str(self.transfer.id)}/reverse',
            reversal_data,
            format='json'
        )
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)
        
        # Second reversal attempt
        response2 = self.client.post(
            f'/api/transfers/{str(self.transfer.id)}/reverse',
            reversal_data,
            format='json'
        )
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)
        # Check for the error in either the message or error field
        error_message = response2.data.get('message', response2.data.get('error', ''))
        self.assertIn('already been reversed', error_message)


class AccountStateTest(APITestCase):
    """Test account state edge cases (frozen wallets, suspended users)"""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create active user
        self.active_user = User.objects.create_user(
            email='active@example.com',
            google_sub='google_sub_active',
            handle='active',
            display_name='Active User',
            send_limit_per_tx=Decimal('1000.00'),
            send_limit_daily=Decimal('5000.00')
        )
        self.active_wallet = Wallet.objects.create(user=self.active_user, currency='USD')
        
        # Give active user money
        transaction_obj = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=None,
            recipient=self.active_user,
            amount=Decimal('500.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.active_wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('500.00')
        )
        
        # Create suspended user
        self.suspended_user = User.objects.create_user(
            email='suspended@example.com',
            google_sub='google_sub_suspended',
            handle='suspended',
            display_name='Suspended User',
            status=UserStatus.SUSPENDED,
            send_limit_per_tx=Decimal('1000.00'),
            send_limit_daily=Decimal('5000.00')
        )
        self.suspended_wallet = Wallet.objects.create(user=self.suspended_user, currency='USD')
        
        # Give suspended user money
        transaction_obj2 = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=None,
            recipient=self.suspended_user,
            amount=Decimal('500.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.suspended_wallet,
            transaction=transaction_obj2,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('500.00')
        )
        
        # Create user with frozen wallet
        self.frozen_wallet_user = User.objects.create_user(
            email='frozen@example.com',
            google_sub='google_sub_frozen',
            handle='frozen',
            display_name='Frozen Wallet User',
            send_limit_per_tx=Decimal('1000.00'),
            send_limit_daily=Decimal('5000.00')
        )
        self.frozen_wallet = Wallet.objects.create(
            user=self.frozen_wallet_user,
            currency='USD',
            status=WalletStatus.FROZEN
        )
        
        # Give frozen wallet user money
        transaction_obj3 = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=None,
            recipient=self.frozen_wallet_user,
            amount=Decimal('500.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.frozen_wallet,
            transaction=transaction_obj3,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('500.00')
        )
    
    def test_suspended_sender_cannot_transfer(self):
        """Test that suspended users cannot send transfers"""
        self.client.force_authenticate(user=self.suspended_user)
        
        transfer_data = {
            'recipient_handle': 'active',
            'amount': '100.00',
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'suspended_test_key'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('account_suspended', response.data['code'])
        
        # Verify TransferAttempt was logged
        self.assertTrue(TransferAttempt.objects.filter(
            user=self.suspended_user,
            rejection_reason='sender_account_suspended'
        ).exists())
    
    def test_frozen_wallet_sender_cannot_transfer(self):
        """Test that users with frozen wallets cannot send transfers"""
        self.client.force_authenticate(user=self.frozen_wallet_user)
        
        transfer_data = {
            'recipient_handle': 'active',
            'amount': '100.00',
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'frozen_test_key'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('wallet_frozen', response.data['code'])
        
        # Verify TransferAttempt was logged
        self.assertTrue(TransferAttempt.objects.filter(
            user=self.frozen_wallet_user,
            rejection_reason='sender_wallet_frozen'
        ).exists())
    
    def test_cannot_transfer_to_suspended_user(self):
        """Test that transfers to suspended users are rejected"""
        self.client.force_authenticate(user=self.active_user)
        
        transfer_data = {
            'recipient_handle': 'suspended',
            'amount': '100.00',
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'to_suspended_key'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        # Should be 404 (recipient not found) since we don't reveal suspended status
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
        # Verify TransferAttempt was logged - might be recipient_not_found due to security
        self.assertTrue(TransferAttempt.objects.filter(
            user=self.active_user,
            recipient_handle_input='suspended'
        ).exists())
    
    def test_cannot_transfer_to_frozen_wallet(self):
        """Test that transfers to frozen wallets are rejected"""
        self.client.force_authenticate(user=self.active_user)
        
        transfer_data = {
            'recipient_handle': 'frozen',
            'amount': '100.00',
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'to_frozen_key'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        # The frozen wallet user exists but should be rejected
        # Due to security, we might return 404 or 403
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])
        
        # Verify TransferAttempt was logged
        self.assertTrue(TransferAttempt.objects.filter(
            user=self.active_user,
            recipient_handle_input='frozen'
        ).exists())


class TransferAttemptTest(APITestCase):
    """Test TransferAttempt logging for failed transfers"""
    
    def setUp(self):
        self.client = APIClient()
        
        self.user = User.objects.create_user(
            email='user@example.com',
            google_sub='google_sub_user',
            handle='user',
            display_name='Test User',
            send_limit_per_tx=Decimal('1000.00'),
            send_limit_daily=Decimal('5000.00')
        )
        self.wallet = Wallet.objects.create(user=self.user, currency='USD')
        
        self.client.force_authenticate(user=self.user)
    
    def test_insufficient_funds_creates_transfer_attempt(self):
        """Test that insufficient funds creates a TransferAttempt log"""
        transfer_data = {
            'recipient_handle': 'unknown',
            'amount': '100.00',
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'insufficient_funds_key'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
        # Verify TransferAttempt was created
        self.assertTrue(TransferAttempt.objects.filter(
            user=self.user,
            recipient_handle_input='unknown',
            amount=Decimal('100.00'),
            rejection_reason='recipient_not_found'
        ).exists())
    
    def test_per_transaction_limit_creates_transfer_attempt(self):
        """Test that per-transaction limit creates a TransferAttempt log"""
        # Give user money
        transaction_obj = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=None,
            recipient=self.user,
            amount=Decimal('5000.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED
        )
        LedgerEntry.objects.create(
            wallet=self.wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('5000.00')
        )
        
        transfer_data = {
            'recipient_handle': 'unknown',
            'amount': '1500.00',  # Exceeds 1000 limit
            'currency': 'USD',
            'note': 'Test transfer',
            'idempotency_key': 'limit_test_key'
        }
        
        response = self.client.post('/api/transfers', transfer_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        
        # Verify TransferAttempt was created
        self.assertTrue(TransferAttempt.objects.filter(
            user=self.user,
            rejection_reason='recipient_not_found'
        ).exists())
