from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APITestCase

from wallet.models import (
    LedgerDirection,
    LedgerEntry,
    Merchant,
    MerchantMode,
    MerchantStatus,
    Notification,
    PushDevice,
    Transaction,
    TransactionStatus,
    TransactionType,
    User,
    Wallet,
)
from wallet.services.transfers import execute_p2p_transfer
from wallet.services.notifications import (
    _NOTIFICATION_COPY,
    _localized_notification_content,
    deliver_notification,
    should_send_notification_push,
)
from wallet.services.payment_intents import confirm_payment_intent, create_payment_intent


class NotificationLocalizationUnitTests(SimpleTestCase):
    def test_every_notification_type_has_english_and_french_copy(self):
        for notification_type in _NOTIFICATION_COPY:
            with self.subTest(notification_type=notification_type):
                english = _localized_notification_content(notification_type, {}, 'en')
                french = _localized_notification_content(notification_type, {}, 'fr')

                self.assertTrue(all(english))
                self.assertTrue(all(french))
                self.assertNotEqual(english[0], french[0])

    def test_french_fallback_does_not_return_english_copy(self):
        title, message = _localized_notification_content(
            'custom_announcement',
            {'title': 'English title', 'message': 'English message'},
            'fr',
        )

        self.assertEqual(title, 'DSD PAY')
        self.assertEqual(message, 'Vous avez une nouvelle notification de votre portefeuille.')

    def test_account_language_variants_are_normalized(self):
        english = _localized_notification_content('payment_sent', {}, 'en-US')
        french = _localized_notification_content('payment_sent', {}, 'fr-FR')

        self.assertEqual(english[0], 'Payment sent')
        self.assertEqual(french[0], 'Paiement envoyé')

    def test_completed_sender_payment_is_push_eligible(self):
        self.assertTrue(should_send_notification_push('payment_sent'))

    def test_reversal_and_utility_notifications_are_push_eligible(self):
        self.assertTrue(should_send_notification_push('transaction_reversed'))
        self.assertTrue(should_send_notification_push('utility_payment_completed'))

    def test_reversal_notification_copy_uses_preformatted_localized_message(self):
        payload = {
            'message_en': 'Your payment was reversed.',
            'message_fr': 'Votre paiement a été annulé.',
        }

        self.assertEqual(
            _localized_notification_content('transaction_reversed', payload, 'en'),
            ('Transaction reversed', 'Your payment was reversed.'),
        )
        self.assertEqual(
            _localized_notification_content('transaction_reversed', payload, 'fr'),
            ('Transaction annulée', 'Votre paiement a été annulé.'),
        )


class TransferNotificationTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(
            email='notification-sender@example.com',
            handle='notification-sender',
            display_name='Transfer Sender',
        )
        self.recipient = User.objects.create_user(
            email='notification-recipient@example.com',
            handle='notification-recipient',
            display_name='Transfer Recipient',
        )
        self.sender_wallet = Wallet.objects.create(user=self.sender, currency='USD')
        Wallet.objects.create(user=self.recipient, currency='USD')
        LedgerEntry.objects.create(
            wallet=self.sender_wallet,
            transaction=None,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('100.00'),
        )

    def test_completed_transfer_creates_one_notification_per_party(self):
        transaction = execute_p2p_transfer(
            sender=self.sender,
            recipient=self.recipient,
            amount=Decimal('10.00'),
            currency='USD',
            idempotency_key='notification-test-transfer',
        )

        retry_transaction = execute_p2p_transfer(
            sender=self.sender,
            recipient=self.recipient,
            amount=Decimal('10.00'),
            currency='USD',
            idempotency_key='notification-test-transfer',
        )

        self.assertEqual(Notification.objects.count(), 2)
        self.assertEqual(retry_transaction.id, transaction.id)
        received = Notification.objects.get(user=self.recipient)
        sent = Notification.objects.get(user=self.sender)
        self.assertEqual(received.type, 'money_received')
        self.assertEqual(received.payload['sender_display_name'], 'Transfer Sender')
        self.assertEqual(sent.type, 'payment_sent')
        self.assertEqual(sent.payload['recipient_display_name'], 'Transfer Recipient')
        self.assertIn('balance_after', sent.payload)
        self.assertEqual(sent.payload['balance_after'], str(self.sender_wallet.get_balance()))


class PaymentIntentNotificationTests(TestCase):
    def test_successful_merchant_payment_notifies_payer_and_merchant(self):
        payer = User.objects.create_user(
            email='notification-payer@example.com',
            handle='notification-payer',
            display_name='Payment Payer',
        )
        merchant_user = User.objects.create_user(
            email='notification-merchant@example.com',
            handle='notification-merchant',
            display_name='Merchant Owner',
        )
        payer_wallet = Wallet.objects.create(user=payer, currency='USD')
        merchant_wallet = Wallet.objects.create(user=merchant_user, currency='USD')
        LedgerEntry.objects.create(
            wallet=payer_wallet,
            transaction=None,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('100.00'),
        )
        merchant = Merchant.objects.create(
            user=merchant_user,
            business_name='Notification Shop',
            wallet=merchant_wallet,
            status=MerchantStatus.ACTIVE,
        )
        intent = create_payment_intent(
            merchant,
            amount=Decimal('10.00'),
            currency='USD',
            mode=MerchantMode.LIVE,
        )

        with patch('wallet.tasks.deliver_webhook_task.delay'), patch('wallet.tasks.send_notification_task.delay') as dispatch:
            transaction = confirm_payment_intent(intent, payer, 'notification-payment-intent')

        payer_notice = Notification.objects.get(user=payer, type='payment_sent')
        merchant_notice = Notification.objects.get(user=merchant_user, type='merchant_payment_received')
        self.assertEqual(payer_notice.payload['transaction_id'], str(transaction.id))
        self.assertEqual(payer_notice.payload['recipient_display_name'], 'Notification Shop')
        self.assertEqual(merchant_notice.payload['transaction_id'], str(transaction.id))
        self.assertEqual(merchant_notice.payload['payer_display_name'], 'Payment Payer')
        self.assertEqual(dispatch.call_count, 2)


class NotificationLanguageTests(APITestCase):
    def test_notification_payload_uses_selected_account_language(self):
        user = User.objects.create_user(
            email='notification-language@example.com',
            handle='notification-language',
            display_name='Language User',
            language_code='fr',
        )
        Notification.objects.create(
            user=user,
            type='payment_sent',
            payload={
                'title': 'Payment sent',
                'message': 'You paid 10 USD to Transfer Recipient.',
                'amount': '10.00',
                'currency': 'USD',
                'fee_amount': '0.10',
                'balance_after': '89.90',
                'recipient_display_name': 'Transfer Recipient',
            },
        )
        self.client.force_authenticate(user=user)

        response = self.client.get('/api/notifications?unread_only=true')

        self.assertEqual(response.status_code, 200)
        payload = response.data['results'][0]['payload']
        self.assertEqual(payload['title'], 'Paiement envoyé')
        self.assertIn('Transfer Recipient', payload['message'])
        self.assertIn('Votre solde est de 89.90 USD.', payload['message'])


class FCMNotificationDeliveryTests(TestCase):
    @patch('firebase_admin.get_app')
    @patch('firebase_admin.messaging.send_each_for_multicast')
    def test_completed_payment_reversal_and_utility_notifications_are_sent_to_fcm(
        self,
        send_multicast,
        get_firebase_app,
    ):
        user = User.objects.create_user(
            email='fcm-notifications@example.com',
            handle='fcm-notifications',
            display_name='FCM User',
            language_code='fr',
        )
        PushDevice.objects.create(
            user=user,
            token='test-fcm-device-token',
            device_id='test-fcm-device',
            platform='ios',
        )
        get_firebase_app.return_value = object()
        send_multicast.return_value = SimpleNamespace(
            success_count=1,
            failure_count=0,
            responses=[SimpleNamespace(success=True, exception=None)],
        )
        notifications = [
            Notification.objects.create(
                user=user,
                type='payment_sent',
                payload={
                    'amount': '10.00',
                    'currency': 'USD',
                    'recipient_display_name': 'Recipient',
                    'fee_amount': '0.00',
                    'balance_after': '90.00',
                },
            ),
            Notification.objects.create(
                user=user,
                type='payment_request_paid',
                payload={
                    'amount': '10.00',
                    'currency': 'USD',
                    'payer_display_name': 'Payer',
                },
            ),
            Notification.objects.create(
                user=user,
                type='transaction_reversed',
                payload={
                    'message_en': 'Your payment was reversed.',
                    'message_fr': 'Votre paiement a été annulé.',
                    'amount': '10.00',
                    'currency': 'USD',
                },
            ),
            Notification.objects.create(
                user=user,
                type='utility_payment_completed',
                payload={'service': 'Electricity', 'amount': '10.00', 'currency': 'USD'},
            ),
        ]

        for notification in notifications:
            with self.subTest(notification_type=notification.type):
                self.assertEqual(deliver_notification(notification.id)['status'], 'delivered')

        self.assertEqual(send_multicast.call_count, len(notifications))
        sent_types = [call.args[0].data['type'] for call in send_multicast.call_args_list]
        self.assertEqual(
            sent_types,
            ['payment_sent', 'payment_request_paid', 'transaction_reversed', 'utility_payment_completed'],
        )
        reversal_message = send_multicast.call_args_list[2].args[0]
        self.assertEqual(reversal_message.notification.title, 'Transaction annulée')
        self.assertEqual(reversal_message.notification.body, 'Votre paiement a été annulé.')


class ReversalNotificationTests(APITestCase):
    def test_reversal_notifies_both_transaction_parties(self):
        admin = User.objects.create_user(
            email='reversal-admin@example.com',
            handle='reversal-admin',
            display_name='Reversal Admin',
            is_staff=True,
        )
        sender = User.objects.create_user(
            email='reversal-sender@example.com',
            handle='reversal-sender',
            display_name='Reversal Sender',
        )
        recipient = User.objects.create_user(
            email='reversal-recipient@example.com',
            handle='reversal-recipient',
            display_name='Reversal Recipient',
        )
        sender_wallet = Wallet.objects.create(user=sender, currency='USD')
        recipient_wallet = Wallet.objects.create(user=recipient, currency='USD')
        LedgerEntry.objects.create(
            wallet=sender_wallet,
            transaction=None,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('100.00'),
        )
        original = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=sender,
            recipient=recipient,
            amount=Decimal('10.00'),
            currency='USD',
            status=TransactionStatus.COMPLETED,
        )
        LedgerEntry.objects.create(
            wallet=sender_wallet,
            transaction=original,
            direction=LedgerDirection.DEBIT,
            amount=Decimal('10.00'),
        )
        LedgerEntry.objects.create(
            wallet=recipient_wallet,
            transaction=original,
            direction=LedgerDirection.CREDIT,
            amount=Decimal('10.00'),
        )

        self.client.force_authenticate(user=admin)
        response = self.client.post(
            f'/api/transfers/{original.id}/reverse',
            {'reason': 'Customer requested correction'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Notification.objects.filter(type='transaction_reversed').count(), 2)
        credited_notice = Notification.objects.get(user=sender, type='transaction_reversed')
        debited_notice = Notification.objects.get(user=recipient, type='transaction_reversed')
        self.assertIn('reversed', credited_notice.payload['message'])
        self.assertIn('debited from your wallet', debited_notice.payload['message'])
        self.assertEqual(credited_notice.payload['reason'], 'Customer requested correction')
