from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import transaction
from decimal import Decimal
import uuid


class CustomUserManager(BaseUserManager):
    def create_user(self, email, google_sub, handle, display_name, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        if not google_sub:
            raise ValueError('The Google sub field must be set')
        if not handle:
            raise ValueError('The Handle field must be set')
        
        email = self.normalize_email(email)
        user = self.model(
            email=email,
            google_sub=google_sub,
            handle=handle,
            display_name=display_name,
            **extra_fields
        )
        user.set_password(None)  # No password for OAuth users
        user.save(using=self._db)
        return user

    def create_superuser(self, email, google_sub, handle, display_name, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, google_sub, handle, display_name, **extra_fields)


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


class LedgerDirection(models.TextChoices):
    DEBIT = 'debit', 'Debit'
    CREDIT = 'credit', 'Credit'


class User(AbstractUser):
    objects = CustomUserManager()
    
    google_sub = models.CharField(max_length=255, unique=True, db_index=True)
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
    created_at = models.DateTimeField(auto_now_add=True)

    # No password field needed - Google OAuth only
    username = None  # Disable the default username field
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['google_sub', 'handle', 'display_name']

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
    )  # B2: Store exchange rate used for cross-currency transfers
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sender', 'created_at']),  # A6: Composite index for history
            models.Index(fields=['recipient', 'created_at']),  # A6: Composite index for history
        ]


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
