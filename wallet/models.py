from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import uuid


def default_request_expiry():
    return timezone.now() + timedelta(minutes=2)


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


class SupportedCountry(models.Model):
    code = models.CharField(max_length=2, unique=True)
    name = models.CharField(max_length=100)
    dial_code = models.CharField(max_length=8)
    currency = models.CharField(max_length=3, default='GNF')
    flag = models.CharField(max_length=8, blank=True, default='')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.dial_code})'


class LegalDocument(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=200)
    body_html = models.TextField()
    published = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slug']

    def __str__(self):
        return self.title


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
    phone_number = models.CharField(max_length=30, unique=True, null=True, blank=True, db_index=True)
    primary_phone_number = models.CharField(max_length=30, unique=True, null=True, blank=True, db_index=True, help_text="Primary phone number for transfers and payments")
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
    limits_manually_set = models.BooleanField(default=False)
    handle_changed_at = models.DateTimeField(null=True, blank=True)
    is_agent = models.BooleanField(default=False)  # B8: Agent flag for future cash network
    must_change_password = models.BooleanField(default=False)
    transaction_pin = models.CharField(max_length=128, null=True, blank=True, help_text="Hashed 4-digit PIN for transaction approvals")
    current_device_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Single active device login token")
    created_at = models.DateTimeField(auto_now_add=True)

    # For OAuth users, use email as USERNAME_FIELD
    # For admin users, they can use username or email
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []  # No required fields for OAuth users (they come from Google)

    class Meta:
        db_table = 'users'


class ParentalControl(models.Model):
    """
    Parental control relationship between a parent and child account.
    Parents can control child's balance, view transactions, and send money.
    """
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACTIVE = 'active', 'Active'
        REVOKED = 'revoked', 'Revoked'
    
    parent = models.ForeignKey(User, on_delete=models.CASCADE, related_name='child_accounts')
    child = models.ForeignKey(User, on_delete=models.CASCADE, related_name='parent_accounts')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    verification_code = models.CharField(max_length=6, help_text="6-digit code sent to child's device for verification")
    code_expires_at = models.DateTimeField(help_text="When the verification code expires")
    linked_at = models.DateTimeField(null=True, blank=True, help_text="When the parental control was successfully linked")
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Parental control permissions
    can_view_transactions = models.BooleanField(default=True, help_text="Parent can view child's transactions")
    can_control_balance = models.BooleanField(default=True, help_text="Parent can control child's balance")
    can_send_money = models.BooleanField(default=True, help_text="Parent can send money to child")
    can_set_limits = models.BooleanField(default=True, help_text="Parent can set child's spending limits")
    
    class Meta:
        db_table = 'parental_controls'
        unique_together = ['parent', 'child']
        verbose_name = 'Parental Control'
        verbose_name_plural = 'Parental Controls'


class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    currency = models.CharField(max_length=3, default='GNF')
    default_provider = models.CharField(
        max_length=20,
        default='orange_money',
        help_text="Default mobile money provider for this wallet (orange_money, mtn_momo, airtel_money)"
    )
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
    fee_amount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
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


class PushDevice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='push_devices')
    token = models.CharField(max_length=512, unique=True)
    device_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    platform = models.CharField(max_length=20, blank=True, default='')
    device_name = models.CharField(max_length=120, blank=True, default='')
    active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'push_devices'
        ordering = ['-last_seen_at']


class TrustedDevice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='trusted_devices')
    device_id = models.CharField(max_length=255, unique=True, db_index=True)
    device_name = models.CharField(max_length=120, blank=True, default='')
    platform = models.CharField(max_length=20, blank=True, default='')
    public_key_pem = models.TextField(blank=True, default='')
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    is_trusted = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'trusted_devices'
        ordering = ['-last_seen_at']


class PendingLoginRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        DENIED = 'denied', 'Denied'
        EXPIRED = 'expired', 'Expired'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pending_login_requests')
    new_device_id = models.CharField(max_length=255)
    new_device_name = models.CharField(max_length=120, blank=True, default='')
    new_device_public_key_pem = models.TextField()
    requesting_ip = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by_device = models.ForeignKey(TrustedDevice, null=True, blank=True, on_delete=models.SET_NULL, related_name='resolved_login_requests')

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'status', 'created_at'])]

    def is_expired(self):
        return timezone.now() >= self.created_at + timedelta(minutes=5)


class OtpChallenge(models.Model):
    class Purpose(models.TextChoices):
        LOGIN = 'login', 'Login'
        TRANSFER = 'transfer', 'Transfer'
        WITHDRAWAL = 'withdrawal', 'Withdrawal'
        PROVIDER_LINK = 'provider_link', 'Provider link'
        ADMIN_LOGIN = 'admin_login', 'Admin login'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otp_challenges')
    device = models.ForeignKey(TrustedDevice, on_delete=models.SET_NULL, null=True, blank=True, related_name='otp_challenges')
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    code_hash = models.CharField(max_length=128)
    dev_code = models.CharField(max_length=6, blank=True, default='')
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    locked_until = models.DateTimeField(null=True, blank=True)
    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'otp_challenges'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'purpose', 'created_at']),
            models.Index(fields=['expires_at', 'consumed_at']),
        ]


class MobileMoneyWebhookEvent(models.Model):
    event_id = models.CharField(max_length=255, unique=True)
    provider_transaction_id = models.CharField(max_length=255, db_index=True)
    status = models.CharField(max_length=30)
    signature = models.CharField(max_length=128)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'mobile_money_webhook_events'
        ordering = ['-received_at']


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


class AppUpdatePolicy(models.Model):
    class Platform(models.TextChoices):
        IOS = 'ios', 'iOS'
        ANDROID = 'android', 'Android'

    platform = models.CharField(max_length=10, choices=Platform.choices, unique=True)
    minimum_version = models.CharField(max_length=30, default='1.0.0')
    update_url = models.URLField(max_length=500)
    enabled = models.BooleanField(default=False)
    title = models.CharField(max_length=120, default='Update required')
    message = models.TextField(default='Please update the app to continue.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'app_update_policies'
        ordering = ['platform']

    def __str__(self):
        return f'{self.get_platform_display()} update policy'


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


class ProviderCatalog(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    logo_url = models.URLField(blank=True, default='')
    payment_options = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class TransferFeeRule(models.Model):
    class FeeType(models.TextChoices):
        FLAT = 'flat', 'Flat amount'
        PERCENTAGE = 'percentage', 'Percentage'

    min_amount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
    max_amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    fee_type = models.CharField(max_length=20, choices=FeeType.choices, default=FeeType.PERCENTAGE)
    fee_value = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal('0.00'))
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['min_amount']


class UserKYCSubmission(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='kyc_submissions')
    document_type = models.CharField(max_length=40)
    document = models.FileField(upload_to='kyc/users/')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reviewer_notes = models.TextField(blank=True, default='')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='user_kyc_reviews')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


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
    fee_amount = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('0.00'))
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


class FeeAppliesTo(models.TextChoices):
    P2P_TRANSFER = 'p2p_transfer', 'P2P Transfer'
    MERCHANT_TRANSFER = 'merchant_transfer', 'Merchant Transfer'


class PaymentIntentStatus(models.TextChoices):
    CREATED = 'created', 'Created'
    PENDING_PAYMENT = 'pending_payment', 'Pending Payment'
    SUCCEEDED = 'succeeded', 'Succeeded'
    FAILED = 'failed', 'Failed'
    EXPIRED = 'expired', 'Expired'
    CANCELLED = 'cancelled', 'Cancelled'


class MerchantMode(models.TextChoices):
    SANDBOX = 'sandbox', 'Sandbox'
    LIVE = 'live', 'Live'


class MerchantPlan(models.Model):
    """Commercial plan and server-side capability limits for a merchant."""
    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True, default='')
    monthly_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=3, default='GNF')
    monthly_transaction_limit = models.PositiveIntegerField(null=True, blank=True)
    transaction_fee_percent = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal('0.000'))
    api_access = models.BooleanField(default=False)
    webhook_access = models.BooleanField(default=False)
    qr_payments = models.BooleanField(default=True)
    kyc_support = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchant_plans'
        ordering = ['monthly_price', 'id']


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
    public_identifier = models.SlugField(max_length=80, unique=True, blank=True, null=True, db_index=True)
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
    webhook_events = models.JSONField(default=list, blank=True)
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
    logo = models.FileField(upload_to='merchants/logos/%Y/%m/', blank=True, null=True)
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


class MerchantLimit(models.Model):
    """Transaction volume limits for a merchant, independent of user send limits."""
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='transaction_limits')
    currency = models.CharField(max_length=3, default='GNF')
    per_transaction = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('100000.00'))
    daily = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('1000000.00'))
    monthly = models.DecimalField(max_digits=20, decimal_places=2, default=Decimal('10000000.00'))
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchant_limits'
        constraints = [
            models.UniqueConstraint(fields=['merchant', 'currency'], name='unique_merchant_limit_currency'),
        ]


class MerchantTeamRole(models.TextChoices):
    OWNER = 'owner', 'Owner'
    ADMIN = 'admin', 'Admin'
    FINANCE = 'finance', 'Finance'
    SUPPORT = 'support', 'Support'
    DEVELOPER = 'developer', 'Developer'


class MerchantTeamMember(models.Model):
    """A merchant's team membership and pending invitations."""
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='team_members')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='merchant_team_memberships')
    email = models.EmailField()
    full_name = models.CharField(max_length=255, blank=True, default='')
    phone_number = models.CharField(max_length=30, blank=True, default='')
    role = models.CharField(max_length=20, choices=MerchantTeamRole.choices, default=MerchantTeamRole.SUPPORT)
    is_active = models.BooleanField(default=True)
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sent_merchant_invitations')
    invited_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    credentials_issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'merchant_team_members'
        constraints = [
            models.UniqueConstraint(fields=['merchant', 'email'], name='unique_merchant_team_email'),
        ]
        indexes = [models.Index(fields=['merchant', 'is_active', 'role'])]

    def __str__(self):
        return f'{self.email} ({self.role})'


class FeePolicy(models.Model):
    name = models.CharField(max_length=100)
    applies_to = models.CharField(max_length=30, choices=FeeAppliesTo.choices)
    fee_percent = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    fee_fixed = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True, default='')
    priority = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, null=True, blank=True, related_name='fee_policies')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fee_policies'
        ordering = ['-priority', '-created_at']


class FeeWaiver(models.Model):
    applies_to = models.CharField(max_length=30, choices=FeeAppliesTo.choices)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True, default='')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='fee_waivers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fee_waivers'


class PaymentIntent(models.Model):
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3)
    description = models.TextField(blank=True, default='')
    external_reference = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=20, choices=PaymentIntentStatus.choices, default=PaymentIntentStatus.CREATED)
    mode = models.CharField(max_length=10, choices=MerchantMode.choices)
    return_url = models.URLField(blank=True, default='')
    expires_at = models.DateTimeField(default=default_payment_intent_expiry)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='payment_intents')
    payer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_intents')
    resulting_transaction = models.ForeignKey('Transaction', on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_intents')
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_intents'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['merchant', 'status', 'created_at']),
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['external_reference']),
            models.Index(fields=['merchant', 'mode', 'idempotency_key']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['merchant', 'mode', 'idempotency_key'],
                condition=models.Q(idempotency_key__isnull=False),
                name='unique_merchant_intent_idempotency',
            ),
        ]


class WebhookDeliveryStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    DELIVERED = 'delivered', 'Delivered'
    FAILED = 'failed', 'Failed'


class WebhookDelivery(models.Model):
    Status = WebhookDeliveryStatus

    event_type = models.CharField(max_length=50)
    target_url = models.URLField()
    payload = models.JSONField()
    status = models.CharField(max_length=20, choices=WebhookDeliveryStatus.choices, default=WebhookDeliveryStatus.PENDING)
    status_code = models.IntegerField(null=True, blank=True)
    attempt_count = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, default='')
    delivered_at = models.DateTimeField(null=True, blank=True)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='webhook_deliveries')
    payment_intent = models.ForeignKey(PaymentIntent, on_delete=models.CASCADE, related_name='webhook_deliveries')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'webhook_deliveries'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['merchant', 'status', 'created_at']),
            models.Index(fields=['payment_intent', 'event_type']),
        ]


class MerchantApiKey(models.Model):
    mode = models.CharField(max_length=10, choices=MerchantMode.choices)
    public_key = models.CharField(max_length=80, unique=True, db_index=True)
    secret_key_prefix = models.CharField(max_length=20, db_index=True)
    secret_key_hash = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='api_keys')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'merchant_api_keys'
        unique_together = [('merchant', 'mode')]
        indexes = [models.Index(fields=['secret_key_prefix', 'is_active'])]


class MerchantSubscription(models.Model):
    """The current plan selection and billing period for a merchant."""
    class Status(models.TextChoices):
        TRIALING = 'trialing', 'Trialing'
        ACTIVE = 'active', 'Active'
        PAST_DUE = 'past_due', 'Past due'
        CANCELED = 'canceled', 'Canceled'

    merchant = models.OneToOneField(Merchant, on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey(MerchantPlan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIALING)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    cancel_at_period_end = models.BooleanField(default=False)
    provider_reference = models.CharField(max_length=120, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchant_subscriptions'


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


class MerchantPayoutSchedule(models.Model):
    class Frequency(models.TextChoices):
        DAILY = 'daily', 'Daily'
        WEEKLY = 'weekly', 'Weekly'
        MONTHLY = 'monthly', 'Monthly'

    merchant = models.OneToOneField(Merchant, on_delete=models.CASCADE, related_name='payout_schedule')
    frequency = models.CharField(max_length=20, choices=Frequency.choices, default=Frequency.DAILY)
    destination = models.CharField(max_length=255, blank=True, default='')
    enabled = models.BooleanField(default=True)
    next_payout_at = models.DateTimeField(null=True, blank=True)
    last_payout_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchant_payout_schedules'


class TransactionApproval(models.Model):
    """
    Model for transaction approval requests.
    When users send money, request money, or split bills, recipients can receive approval prompts.
    """
    class ApprovalStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        DECLINED = 'declined', 'Declined'
        EXPIRED = 'expired', 'Expired'

    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='approval_requests',
        null=True,
        blank=True
    )
    payment_request = models.ForeignKey(
        PaymentRequest,
        on_delete=models.CASCADE,
        related_name='approval_requests',
        null=True,
        blank=True
    )
    split_request = models.ForeignKey(
        SplitRequest,
        on_delete=models.CASCADE,
        related_name='approval_requests',
        null=True,
        blank=True
    )
    approver = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='incoming_approvals'
    )
    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='outgoing_approvals'
    )
    status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING
    )
    approval_type = models.CharField(
        max_length=50,
        help_text="Type of approval: money_received, payment_request, split_bill"
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3)
    note = models.TextField(blank=True, default='')
    expires_at = models.DateTimeField(default=default_request_expiry)
    responded_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    webhook_delivered = models.BooleanField(default=False)
    webhook_delivery_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'transaction_approvals'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['approver', 'status', 'created_at']),
            models.Index(fields=['requester', 'status', 'created_at']),
            models.Index(fields=['status', 'expires_at']),
        ]


class SupportTicketStatus(models.TextChoices):
    OPEN = 'open', 'Open'
    IN_PROGRESS = 'in_progress', 'In Progress'
    WAITING_ON_USER = 'waiting_on_user', 'Waiting on User'
    RESOLVED = 'resolved', 'Resolved'
    CLOSED = 'closed', 'Closed'


class SupportTicketPriority(models.TextChoices):
    LOW = 'low', 'Low'
    MEDIUM = 'medium', 'Medium'
    HIGH = 'high', 'High'
    URGENT = 'urgent', 'Urgent'


class SupportTicketCategory(models.TextChoices):
    BILLING = 'billing', 'Billing & Top-ups'
    TRANSFER = 'transfer', 'Transfer Issues'
    ACCOUNT = 'account', 'Account & Access'
    KYC = 'kyc', 'KYC & Verification'
    FRAUD = 'fraud', 'Security & Fraud'
    GENERAL = 'general', 'General Inquiry'


class SupportTicket(models.Model):
    ticket_number = models.CharField(max_length=30, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='support_tickets')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_support_tickets')
    subject = models.CharField(max_length=255)
    category = models.CharField(max_length=30, choices=SupportTicketCategory.choices, default=SupportTicketCategory.GENERAL)
    priority = models.CharField(max_length=20, choices=SupportTicketPriority.choices, default=SupportTicketPriority.MEDIUM)
    status = models.CharField(max_length=20, choices=SupportTicketStatus.choices, default=SupportTicketStatus.OPEN)
    related_transaction = models.ForeignKey('Transaction', on_delete=models.SET_NULL, null=True, blank=True, related_name='support_tickets')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'support_tickets'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['status', 'priority']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f"{self.ticket_number} - {self.subject}"


class SupportTicketMessage(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    is_internal_note = models.BooleanField(default=False, help_text="Visible only to staff")
    message = models.TextField()
    attachment_url = models.URLField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'support_ticket_messages'
        ordering = ['created_at']

    def __str__(self):
        return f"Msg on {self.ticket.ticket_number} by {self.sender.handle}"


# ============================================================================
# NEW PRODUCTION-READY MODELS
# ============================================================================

class UserNote(models.Model):
    """Internal admin notes on users for collaboration and tracking."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_notes')
    admin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notes_authored')
    note = models.TextField(help_text="Internal note about this user")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_notes'
        ordering = ['-created_at']

    def __str__(self):
        return f"Note on {self.user.handle} by {self.admin.handle}"


class TransactionFlag(models.Model):
    """Flags and tags for transaction categorization and tracking."""
    FLAG_TYPES = [
        ('flag', 'Flag'),
        ('tag', 'Tag'),
        ('priority', 'Priority'),
    ]
    
    FLAG_NAMES = [
        ('high_risk', 'High Risk'),
        ('requires_review', 'Requires Review'),
        ('suspicious', 'Suspicious'),
        ('vip', 'VIP'),
        ('priority', 'Priority'),
        ('compliance', 'Compliance'),
        ('fraud_investigation', 'Fraud Investigation'),
    ]
    
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='flags')
    flag_type = models.CharField(max_length=20, choices=FLAG_TYPES, default='flag')
    flag_name = models.CharField(max_length=50, choices=FLAG_NAMES)
    description = models.TextField(blank=True, help_text="Additional context for this flag")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='flags_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'transaction_flags'
        ordering = ['-created_at']
        unique_together = [['transaction', 'flag_name']]

    def __str__(self):
        return f"{self.flag_name} on {self.transaction.id}"


class AlertRule(models.Model):
    """Configurable alert rules for system monitoring."""
    ALERT_TYPES = [
        ('warning', 'Warning'),
        ('critical', 'Critical'),
        ('info', 'Info'),
    ]
    
    CHANNELS = [
        ('email', 'Email'),
        ('webhook', 'Webhook'),
        ('sms', 'SMS'),
        ('slack', 'Slack'),
    ]
    
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES, default='warning')
    condition = models.TextField(help_text="Python-like condition expression")
    threshold = models.CharField(max_length=100, help_text="Threshold value for condition")
    channels = models.JSONField(default=list, help_text="List of notification channels")
    enabled = models.BooleanField(default=True)
    last_triggered = models.DateTimeField(null=True, blank=True)
    trigger_count = models.IntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='alert_rules_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'alert_rules'
        ordering = ['name']

    def __str__(self):
        return self.name


class AlertEvent(models.Model):
    """Log of triggered alert events."""
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name='events')
    severity = models.CharField(max_length=20)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='alerts_resolved')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'alert_events'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.rule.name} - {self.created_at}"


class AdminMessage(models.Model):
    """Direct messages from admins to users."""
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('failed', 'Failed'),
    ]
    
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_messages_received')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_messages_sent')
    subject = models.CharField(max_length=200)
    content = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='sent')
    delivery_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'admin_messages'
        ordering = ['-created_at']

    def __str__(self):
        return f"Message to {self.recipient.handle}: {self.subject}"
