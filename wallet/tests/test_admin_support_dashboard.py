from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from wallet.models import (
    User, Wallet, SupportTicket, SupportTicketMessage, SupportTicketStatus,
    SupportTicketPriority, SupportTicketCategory, UserKYCSubmission,
    TransferFeeRule, ExchangeRate
)
from django_celery_beat.models import PeriodicTask, IntervalSchedule
from decimal import Decimal
from django.utils import timezone


class AdminSupportDashboardTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create Admin User
        self.admin_user = User.objects.create_user(
            email='admin@wallet.com',
            username='admin_staff',
            password='Password123!',
            is_staff=True
        )
        self.admin_wallet = Wallet.objects.create(user=self.admin_user, currency='GNF')

        # Create Regular User
        self.regular_user = User.objects.create_user(
            email='user@wallet.com',
            username='regular_user',
            password='Password123!',
            is_staff=False
        )
        self.regular_wallet = Wallet.objects.create(user=self.regular_user, currency='GNF')

        # Authenticate Admin by default
        self.client.force_authenticate(user=self.admin_user)

    def test_admin_support_ticket_lifecycle(self):
        """Test creating ticket, listing, adding message, and updating ticket status."""
        # 1. Create support ticket
        create_url = reverse('admin_support_ticket_create')
        payload = {
            'user_id': self.regular_user.id,
            'subject': 'Delay in Mobile Money Withdrawal',
            'category': 'billing',
            'priority': 'high',
            'initial_message': 'My withdrawal of 100,000 GNF is stuck in processing.'
        }
        res = self.client.post(create_url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        ticket_id = res.data['id']

        # 2. List tickets
        list_url = reverse('admin_support_tickets_list')
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['tickets']), 1)

        # 3. Post reply message
        msg_url = reverse('admin_support_ticket_add_message', kwargs={'ticket_id': ticket_id})
        msg_payload = {
            'message': 'We have re-sent the transaction to MTN MoMo gateway.',
            'is_internal_note': False
        }
        res = self.client.post(msg_url, msg_payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # 4. Update ticket status to resolved
        update_url = reverse('admin_support_ticket_update', kwargs={'ticket_id': ticket_id})
        res = self.client.patch(update_url, {'status': 'resolved'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'resolved')

    def test_admin_periodic_task_toggle(self):
        """Test toggling periodic task schedule state."""
        interval = IntervalSchedule.objects.create(every=5, period=IntervalSchedule.MINUTES)
        task = PeriodicTask.objects.create(
            name='test_reconciliation_task',
            task='wallet.tasks.reconcile_balances_task',
            interval=interval,
            enabled=True
        )

        toggle_url = reverse('admin_periodic_task_toggle', kwargs={'task_id': task.id})
        res = self.client.post(toggle_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data['enabled'])

    def test_admin_user_kyc_review(self):
        """Test reviewing user KYC submission and upgrading KYC tier."""
        sub = UserKYCSubmission.objects.create(
            user=self.regular_user,
            document_type='national_id',
            document='kyc/users/doc123.pdf',
            status='pending'
        )

        review_url = reverse('admin_user_kyc_review', kwargs={'submission_id': sub.id})
        payload = {
            'action': 'approve',
            'target_kyc_tier': 'tier_1',
            'reviewer_notes': 'Document verified.'
        }
        res = self.client.post(review_url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.regular_user.refresh_from_db()
        self.assertEqual(self.regular_user.kyc_tier, 'tier_1')

    def test_admin_user_freeze_wallet(self):
        """Test quick freeze/unfreeze of user wallet."""
        freeze_url = reverse('admin_user_freeze_wallet', kwargs={'user_id': self.regular_user.id})
        res = self.client.post(freeze_url, {'reason': 'Security audit'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.regular_wallet.refresh_from_db()
        self.assertEqual(self.regular_wallet.status, 'frozen')

    def test_non_admin_forbidden_access(self):
        """Ensure regular non-staff user is blocked from admin endpoints."""
        self.client.force_authenticate(user=self.regular_user)
        list_url = reverse('admin_support_tickets_list')
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
