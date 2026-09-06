from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import uuid


def default_request_expiry():
    return timezone.now() + timedelta(days=7)


def default_payment_intent_expiry():
    return timezone.now() + timedelta(hours=24)


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, google_sub=None, handle=None, display_name=None, **extra_fields):
        """
        Create and save a regular User with the given email and password.
        """
        if not email:
            raise ValueError('The Email field must be set')
        
        email = self.normalize_email(email)
        
        # Auto-generate display_name from email if not provided
        if not display_name:
            display_name = email.split('@')[0]
        
        # Auto-generate handle from email if not provided
        if not handle:
            handle = display_name.lower()
            # Ensure handle is unique by adding a number if needed
            base_handle = handle
            counter = 1
            while self.filter(handle=handle).exists():
                handle = f"{base_handle}{counter}"
                counter += 1
        
        user = self.model(
            email=email,
            google_sub=google_sub,
            handle=handle,
            display_name=display_name,
            **extra_fields
        )
        
        if password:
            user.set_password(password)
        else:
            user.set_password(None)  # No password for OAuth users
        
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, google_sub=None, handle=None, display_name=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        # Auto-generate handle and display_name if not provided for createsuperuser
        if not display_name:
            display_name = email.split('@')[0]
        if not handle:
            handle = display_name.lower()
            # Ensure handle is unique by adding a number if needed
            base_handle = handle
            counter = 1
            while self.filter(handle=handle).exists():
                handle = f"{base_handle}{counter}"
                counter += 1

        return self.create_user(email, password, google_sub, handle, display_name, **extra_fields)
    
    def create_admin_user(self, username, password, email, **extra_fields):
        """
        Create an admin user with username/password authentication.
        This is separate from OAuth users and used for the admin panel.
        """
        if not username:
            raise ValueError('The Username field must be set')
        if not password:
            raise ValueError('The Password field must be set')
        if not email:
            raise ValueError('The Email field must be set')
        
        email = self.normalize_email(email)
        
        # Set admin-specific defaults
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', False)  # Not necessarily superuser
        extra_fields.setdefault('is_active', True)
        
        extra_fields.setdefault('must_change_password', True)

        user = self.model(
            email=email,
            username=username,
            handle=username,  # Use username as handle for admin users
            display_name=username,
            google_sub=None,  # No Google OAuth for admin users
            **extra_fields
        )
        
        # Ensure is_staff is set after creating the model instance
        user.is_staff = True
        
        user.set_password(password)
        user.save(using=self._db)
        return user


class KYCTier(models.TextChoices):
    TIER_0 = 'tier_0', 'Tier 0'
    TIER_1 = 'tier_1', 'Tier 1'
    TIER_2 = 'tier_2', 'Tier 2'


class UserStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    SUSPENDED = 'suspended', 'Suspended'
    CLOSED = 'closed', 'Closed'


class WalletStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    FROZEN = 'frozen', 'Frozen'


class TransactionType(models.TextChoices):
    P2P_TRANSFER = 'p2p_transfer', 'P2P Transfer'
    REVERSAL = 'reversal', 'Reversal'
    TOPUP = 'topup', 'Top-up'
    WITHDRAWAL = 'withdrawal', 'Withdrawal'


class TransactionStatus(models.TextChoices):
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    REVERSED = 'reversed', 'Reversed'


class PaymentRequestStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PAID = 'paid', 'Paid'
    DECLINED = 'declined', 'Declined'
    CANCELLED = 'cancelled', 'Cancelled'
    EXPIRED = 'expired', 'Expired'


class LedgerDirection(models.TextChoices):
    DEBIT = 'debit', 'Debit'
    CREDIT = 'credit', 'Credit'


class User(AbstractUser):
    objects = CustomUserManager()
    
    username = models.CharField(max_length=150, unique=True, null=True, blank=True)  # Optional for OAuth, required for admin
    google_sub = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)  # Optional for admin users
    email = models.EmailField(unique=True)
    handle = models.CharField(max_length=50, unique=True, db_index=True)
    display_name = models.CharField(max_length=255)
    avatar_url = models.URLField(blank=True)
    kyc_tier = models.CharField(
        max_length=20,
        choices=KYCTier.choices,
        default=KYCTier.TIER_0
    )
    status = models.CharField(
        max_length=20,
        choices=UserStatus.choices,
        default=UserStatus.ACTIVE
    )
    send_limit_per_tx = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('1000.00')
    )
    send_limit_daily = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal('5000.00')
    )
    handle_changed_at = models.DateTimeField(null=True, blank=True)
    is_agent = models.BooleanField(default=False)  # B8: Agent flag for future cash network
    must_change_password = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # For OAuth users, use email as USERNAME_FIELD
    # For admin users, they can use username or email
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []  # No required fields for OAuth users (they come from Google)

    class Meta:
        db_table = 'users'


class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    currency = models.CharField(max_length=3, default='USD')
    status = models.CharField(
        max_length=20,
        choices=WalletStatus.choices,
        default=WalletStatus.ACTIVE
    )
    is_sandbox = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def get_balance(self) -> Decimal:
        """
        Compute the current balance from ledger entries.
        This is the ONLY way balance should ever be read.
        Balance = SUM(credits) - SUM(debits)
        """
        from django.db.models import Sum
        
        credits = self.entries.filter(direction=LedgerDirection.CREDIT).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        debits = self.entries.filter(direction=LedgerDirection.DEBIT).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        return credits - debits

    class Meta:
        db_table = 'wallets'


class Transaction(models.Model):
    type = models.CharField(
        max_length=20,
        choices=TransactionType.choices
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_transactions'
    )
    recipient = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='received_transactions'
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3)
    note = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.COMPLETED
    )
    related_transaction = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversals'
    )
    exchange_rate = models.ForeignKey(
        'ExchangeRate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )  
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sender', 'created_at']),  
            models.Index(fields=['recipient', 'created_at']), 
        ]


class PaymentRequest(models.Model):
    requester = models.ForeignKey(User, on_delete=models.CASCADE, related_name='requests_sent')
    payer = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='requests_received', null=True, blank=True
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3)
    note = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=PaymentRequestStatus.choices, default=PaymentRequestStatus.PENDING
    )
    expires_at = models.DateTimeField(default=default_request_expiry)
    resulting_transaction = models.ForeignKey(
        Transaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='fulfilled_requests'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['requester', 'status', 'created_at']),
            models.Index(fields=['payer', 'status', 'created_at']),
        ]


class SplitRequest(models.Model):
    class SplitStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CANCELLED = 'cancelled', 'Cancelled'
        PAID = 'paid', 'Paid'

    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='splits_created')
    total_amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=SplitStatus.choices, default=SplitStatus.PENDING)
    cancellation_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'split_requests'
        ordering = ['-created_at']


class SplitParticipant(models.Model):
    split_request = models.ForeignKey(SplitRequest, on_delete=models.CASCADE, related_name='participants')
    payment_request = models.OneToOneField(
        PaymentRequest, on_delete=models.CASCADE, related_name='split_participant'
    )
    amount_owed = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        db_table = 'split_participants'


class LedgerEntry(models.Model):
    """
    This table is append-only. Never update or delete entries.
    If a transfer needs to be undone, create a new transaction with offsetting entries.
    """
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name='entries'
    )
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.PROTECT,
        related_name='ledger_entries',
        null=True,
        blank=True
    )
    direction = models.CharField(
        max_length=10,
        choices=LedgerDirection.choices
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ledger_entries'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['wallet', 'created_at']),  # A6: Composite index for balance computation
        ]


class Notification(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    type = models.CharField(max_length=50)
    payload = models.JSONField()
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']


class SystemSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    description = models.TextField(blank=True, default='')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_settings')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'system_settings'
        ordering = ['key']

    def __str__(self):
        return self.key


class ProcessedRequest(models.Model):
    """
    This table enforces idempotency at the database level.
    The unique constraint on idempotency_key prevents duplicate processing.
    """
    idempotency_key = models.CharField(max_length=255, unique=True, db_index=True)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='processed_requests'
    )
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_requests'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'processed_requests'


class AuditLog(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=100)
    metadata = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-created_at']


class PendingTransfer(models.Model):
    """
    Stub model for future "send money to someone not on the app yet" flow.
    """
    recipient_email = models.EmailField()
    claim_token = models.UUIDField(default=uuid.uuid4, unique=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3)
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='pending_transfers'
    )
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pending_transfers'


class TransferAttempt(models.Model):
    """
    Lightweight log of failed transfer attempts for fraud pattern visibility.
    This gives visibility into rejected attempts without polluting Transaction/Ledger.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='transfer_attempts'
    )
    recipient_handle_input = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3)
    rejection_reason = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'transfer_attempts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['rejection_reason', 'created_at']),
        ]


class LinkedProvider(models.Model):
    """
    B1 Foundation: Mobile money provider linkage (MTN MoMo, Airtel Money, Orange Money).
    This provides the structure for future integration while keeping it stubbed for now.
    """
    class ProviderType(models.TextChoices):
        MTN_MOMO = 'mtn_momo', 'MTN MoMo'
        AIRTEL_MONEY = 'airtel_money', 'Airtel Money'
        ORANGE_MONEY = 'orange_money', 'Orange Money'

    class VerificationStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        VERIFIED = 'verified', 'Verified'
        FAILED = 'failed', 'Failed'

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='linked_providers'
    )
    provider = models.CharField(
        max_length=20,
        choices=ProviderType.choices
    )
    masked_reference = models.CharField(max_length=20)  # Last 4 digits only, never full numbers
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING
    )
    provider_metadata = models.JSONField(default=dict, blank=True)  # Provider-specific data
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'linked_providers'
        unique_together = ['user', 'provider']
        indexes = [
            models.Index(fields=['user', 'provider']),
            models.Index(fields=['verification_status']),
        ]


class ExchangeRate(models.Model):
    """
    B2 Foundation: Exchange rates for cross-currency transfers.
    Stores the rate at time of transaction for historical accuracy.
    """
    from_currency = models.CharField(max_length=3)
    to_currency = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=20, decimal_places=8)  # High precision for rates
    source = models.CharField(max_length=50)  # e.g., 'provider_api', 'manual'
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'exchange_rates'
        unique_together = ['from_currency', 'to_currency', 'valid_from']
        indexes = [
            models.Index(fields=['from_currency', 'to_currency', 'valid_from']),
        ]


class DisputeStatus(models.TextChoices):
    OPEN = 'open', 'Open'
    UNDER_REVIEW = 'under_review', 'Under Review'
    RESOLVED_REVERSED = 'resolved_reversed', 'Resolved (Reversed)'
    RESOLVED_DENIED = 'resolved_denied', 'Resolved (Denied)'


class Dispute(models.Model):
    """
    User-facing dispute flow for transactions.
    Users can open disputes on transactions they were party to.
    Admins review and resolve through the admin panel, reusing reversal logic.
    """
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.PROTECT,
        related_name='disputes'
    )
    opened_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='disputes_opened'
    )
    reason = models.TextField()
    evidence_notes = models.TextField(blank=True, default='')
    status = models.CharField(
        max_length=20,
        choices=DisputeStatus.choices,
        default=DisputeStatus.OPEN
    )
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='disputes_resolved'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'disputes'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['opened_by', 'status', 'created_at']),
            models.Index(fields=['transaction', 'status']),
        ]


class MobileMoneyTransactionType(models.TextChoices):
    TOPUP = 'topup', 'Top-up'
    WITHDRAWAL = 'withdrawal', 'Withdrawal'


class MobileMoneyTransactionStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PROCESSING = 'processing', 'Processing'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'


class MobileMoneyTransaction(models.Model):
    """
    Track mobile money transactions (top-ups and withdrawals).
    Integrates with MTN MoMo, Airtel Money, and Orange Money.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='mobile_money_transactions'
    )
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name='mobile_money_transactions'
    )
    linked_provider = models.ForeignKey(
        LinkedProvider,
        on_delete=models.PROTECT,
        related_name='mobile_money_transactions'
    )
    type = models.CharField(
        max_length=20,
        choices=MobileMoneyTransactionType.choices
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=20,
        choices=MobileMoneyTransactionStatus.choices,
        default=MobileMoneyTransactionStatus.PENDING
    )
    provider_transaction_id = models.CharField(max_length=100, blank=True, default='')
    provider_reference = models.CharField(max_length=100, blank=True, default='')
    provider_response = models.JSONField(default=dict, blank=True)
    failure_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'mobile_money_transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status', 'created_at']),
            models.Index(fields=['linked_provider', 'status']),
            models.Index(fields=['provider_transaction_id']),
        ]


class ScheduleFrequency(models.TextChoices):
    DAILY = 'daily', 'Daily'
    WEEKLY = 'weekly', 'Weekly'
    BIWEEKLY = 'biweekly', 'Bi-weekly'
    MONTHLY = 'monthly', 'Monthly'
    YEARLY = 'yearly', 'Yearly'


class ScheduledTransferStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    PAUSED = 'paused', 'Paused'
    CANCELLED = 'cancelled', 'Cancelled'
    COMPLETED = 'completed', 'Completed'


class ScheduledTransfer(models.Model):
    """
    Recurring and scheduled transfers.
    Allows users to set up automatic transfers on a schedule.
    """
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='scheduled_transfers'
    )
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='incoming_scheduled_transfers'
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3)
    frequency = models.CharField(
        max_length=20,
        choices=ScheduleFrequency.choices
    )
    next_execution = models.DateTimeField()
    last_execution = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)  # Optional end date
    total_executions = models.IntegerField(default=0)
    max_executions = models.IntegerField(null=True, blank=True)  # Optional max executions
    status = models.CharField(
        max_length=20,
        choices=ScheduledTransferStatus.choices,
        default=ScheduledTransferStatus.ACTIVE
    )
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scheduled_transfers'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sender', 'status', 'next_execution']),
            models.Index(fields=['status', 'next_execution']),  # For background job queries
        ]


class MerchantStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    ACTIVE = 'active', 'Active'
    SUSPENDED = 'suspended', 'Suspended'
    REJECTED = 'rejected', 'Rejected'


class MerchantMode(models.TextChoices):
    SANDBOX = 'sandbox', 'Sandbox'
    LIVE = 'live', 'Live'


class Merchant(models.Model):
    """
    Merchant/Business account model.
    Allows businesses to receive payments via static QR codes.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='merchant_account'
    )
    business_name = models.CharField(max_length=200)
    business_email = models.EmailField(blank=True, default='')
    website_url = models.URLField(blank=True, default='')
    business_type = models.CharField(max_length=100, blank=True, default='')
    description = models.TextField(blank=True, default='')
    status = models.CharField(
        max_length=20,
        choices=MerchantStatus.choices,
        default=MerchantStatus.PENDING
    )
    mode = models.CharField(max_length=10, choices=MerchantMode.choices, default=MerchantMode.SANDBOX)
    webhook_url = models.URLField(blank=True, default='')
    webhook_secret = models.CharField(max_length=64, blank=True, default='')
    sandbox_public_key = models.CharField(max_length=80, blank=True, default='')
    sandbox_secret_hash = models.CharField(max_length=128, blank=True, default='')
    live_public_key = models.CharField(max_length=80, blank=True, default='')
    live_secret_hash = models.CharField(max_length=128, blank=True, default='')
    credentials_issued_at = models.DateTimeField(null=True, blank=True)
    static_qr_code = models.CharField(max_length=255, unique=True, blank=True, null=True)
    static_qr_payload = models.TextField(blank=True, default='')
    static_qr_signature = models.CharField(max_length=255, blank=True, default='')
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name='merchant_accounts'
    )
    sandbox_wallet = models.OneToOneField(
        Wallet,
        on_delete=models.SET_NULL,
        related_name='sandbox_merchant_account',
        null=True,
        blank=True,
    )
    logo_url = models.URLField(blank=True, default='')
    contact_email = models.EmailField(blank=True, default='')
    contact_phone = models.CharField(max_length=20, blank=True, default='')
    address = models.TextField(blank=True, default='')
    tax_id = models.CharField(max_length=50, blank=True, default='')
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_merchants'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchants'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['static_qr_code']),
        ]


class KYCDocument(models.Model):
    class DocumentType(models.TextChoices):
        REGISTRATION = 'registration', 'Business registration'
        OWNER_ID = 'owner_id', 'Owner identity'
        TAX_ID = 'tax_id', 'Tax document'
        SETTLEMENT = 'settlement', 'Settlement destination'

    class ReviewStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        REUPLOAD = 'reupload', 'Re-upload required'

    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='kyc_documents')
    document_type = models.CharField(max_length=30, choices=DocumentType.choices)
    file_url = models.URLField()
    status = models.CharField(max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PENDING)
    reviewer_notes = models.TextField(blank=True, default='')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_kyc_documents')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wallet_kyc_documents'
        ordering = ['-created_at']


class Settlement(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='settlements')
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    fees = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=3)
    batch_reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    destination = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'wallet_settlements'
        ordering = ['-created_at']
