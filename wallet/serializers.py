from rest_framework import serializers
from django.contrib.auth import login
from django.db import models
from .models import (
    User, Wallet, Transaction, LedgerEntry, Notification,
    ProcessedRequest, AuditLog, KYCTier, UserStatus,
    TransactionType, TransactionStatus, LedgerDirection, WalletStatus,
    TransferAttempt, PaymentRequest, PaymentRequestStatus, SplitRequest, SplitParticipant,
    LinkedProvider, ProviderCatalog, ExchangeRate, Dispute, DisputeStatus, MobileMoneyTransaction, MobileMoneyTransactionType, MobileMoneyTransactionStatus, SystemSetting, ScheduledTransfer, ScheduleFrequency, ScheduledTransferStatus, Merchant, MerchantStatus, MerchantPlan, MerchantSubscription, TransactionApproval, ParentalControl, SupportedCountry, LegalDocument, TransferFeeRule, UserKYCSubmission
)
from django.db import transaction
from django.utils.text import slugify
from decimal import Decimal


class UserSerializer(serializers.ModelSerializer):
    is_staff = serializers.BooleanField(read_only=True)
    must_change_password = serializers.BooleanField(read_only=True)
    has_transaction_pin = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'phone_number', 'primary_phone_number', 'handle', 'display_name', 'avatar_url', 'kyc_tier', 'status', 'is_staff', 'must_change_password', 'has_transaction_pin']
        read_only_fields = ['id', 'kyc_tier', 'status', 'is_staff', 'must_change_password']

    def get_has_transaction_pin(self, obj):
        return bool(obj.transaction_pin)


class WalletSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = ['id', 'currency', 'default_provider', 'status', 'balance']
        read_only_fields = ['id', 'currency', 'default_provider', 'status', 'balance']

    def get_balance(self, obj):
        return str(obj.get_balance())


class GoogleAuthRequestSerializer(serializers.Serializer):
    code = serializers.CharField(required=True)
    state = serializers.CharField(required=True)


class EmailSignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    display_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=30)
    primary_phone_number = serializers.CharField(required=False, allow_blank=True, max_length=30)
    transaction_pin = serializers.RegexField(regex=r'^\d{4}$', write_only=True, required=True, help_text="4-digit PIN for transaction approvals")
    confirm_password = serializers.CharField(write_only=True, min_length=8)
    terms_accepted = serializers.BooleanField(write_only=True)
    country_code = serializers.CharField(required=False, allow_blank=True, max_length=2)
    device_id = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        if not attrs['terms_accepted']:
            raise serializers.ValidationError({'terms_accepted': 'You must accept the terms and conditions.'})
        return attrs


class EmailLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=False, allow_blank=False)
    email = serializers.EmailField(required=False)
    country_code = serializers.CharField(required=False, allow_blank=True, max_length=2)
    device_id = serializers.CharField(required=False, allow_blank=True, max_length=255)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if not attrs.get('identifier') and not attrs.get('email'):
            raise serializers.ValidationError({'identifier': 'Email or phone number is required.'})
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        return attrs


class SupportedCountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportedCountry
        fields = ['code', 'name', 'dial_code', 'flag']


class LegalDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalDocument
        fields = ['slug', 'title', 'body_html', 'updated_at']


class ProviderCatalogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderCatalog
        fields = ['code', 'name', 'logo_url']


class UserKYCSubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserKYCSubmission
        fields = ['id', 'document_type', 'document', 'status', 'reviewer_notes', 'created_at', 'updated_at']
        read_only_fields = ['id', 'status', 'reviewer_notes', 'created_at', 'updated_at']


class GoogleAuthResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    wallet = WalletSerializer()
    is_new_user = serializers.BooleanField()


class UserResolveSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    handle = serializers.CharField()
    display_name = serializers.CharField()
    phone_number = serializers.CharField(allow_blank=True, required=False)
    avatar_url = serializers.URLField(allow_blank=True)


class TransferRequestSerializer(serializers.Serializer):
    recipient_phone = serializers.CharField(required=True, max_length=30, help_text="Recipient's phone number")
    amount = serializers.DecimalField(required=True, max_digits=20, decimal_places=2)
    currency = serializers.CharField(required=True, max_length=3)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    idempotency_key = serializers.CharField(required=True, max_length=255)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than 0")
        # Check that amount has at most 2 decimal places for USD
        if value.as_tuple().exponent < -2:
            raise serializers.ValidationError("Amount cannot have more than 2 decimal places")
        return value


class TransferResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    currency = serializers.CharField()
    note = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    created_at = serializers.DateTimeField()


class PaymentRequestSerializer(serializers.ModelSerializer):
    requester_handle = serializers.CharField(source='requester.handle', read_only=True)
    payer_handle = serializers.CharField(source='payer.handle', read_only=True)
    resulting_transaction_id = serializers.UUIDField(source='resulting_transaction.id', read_only=True, allow_null=True)

    class Meta:
        model = PaymentRequest
        fields = ['id', 'requester_handle', 'payer_handle', 'amount', 'currency', 'note', 'status', 'expires_at', 'resulting_transaction_id', 'created_at']


class PaymentRequestCreateSerializer(serializers.Serializer):
    payer_phone = serializers.CharField(max_length=30, help_text="Payer's phone number")
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, min_value=Decimal('0.01'))
    currency = serializers.CharField(max_length=3, default='GNF')
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class SplitCreateSerializer(serializers.Serializer):
    total_amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    currency = serializers.CharField(max_length=3)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    participants = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
        help_text="List of participants with phone and amount fields"
    )

    def validate_participants(self, value):
        """Validate that each participant has phone and amount fields."""
        for participant in value:
            if 'phone' not in participant or 'amount' not in participant:
                raise serializers.ValidationError("Each participant must have 'phone' and 'amount' fields")
        return value


class SplitSerializer(serializers.ModelSerializer):
    creator_handle = serializers.CharField(source='creator.handle', read_only=True)
    participants = serializers.SerializerMethodField()
    class Meta:
        model = SplitRequest
        fields = ['id', 'creator_handle', 'total_amount', 'currency', 'note', 'created_at', 'participants']
    def get_participants(self, obj):
        return [{'handle': p.payment_request.payer.handle, 'amount_owed': str(p.amount_owed), 'payment_request': PaymentRequestSerializer(p.payment_request).data} for p in obj.participants.select_related('payment_request__payer')]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'type', 'payload', 'read_at', 'created_at']
        read_only_fields = ['id', 'created_at']


class PushDeviceSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=512)
    device_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    platform = serializers.CharField(max_length=20, required=False, allow_blank=True)


class TransactionSerializer(serializers.ModelSerializer):
    counterparty_handle = serializers.SerializerMethodField()
    counterparty_display_name = serializers.SerializerMethodField()
    counterparty_avatar_url = serializers.SerializerMethodField()
    direction = serializers.SerializerMethodField()

    class Meta:
        # DRF requires the model class here. A string passes import-time checks
        # but fails when the transaction feed is serialized.
        model = Transaction
        fields = [
            'id', 'type', 'counterparty_handle', 'counterparty_display_name',
            'counterparty_avatar_url', 'amount', 'currency', 'note', 'status',
            'direction', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_counterparty_handle(self, obj):
        request = self.context.get('request')
        if request and request.user:
            if obj.sender == request.user:
                return obj.recipient.handle
            else:
                return obj.sender.handle if obj.sender else None
        return None

    def get_counterparty_display_name(self, obj):
        request = self.context.get('request')
        if request and request.user:
            if obj.sender == request.user:
                return obj.recipient.display_name
            else:
                return obj.sender.display_name if obj.sender else None
        return None

    def get_counterparty_avatar_url(self, obj):
        request = self.context.get('request')
        if request and request.user:
            if obj.sender == request.user:
                return obj.recipient.avatar_url
            else:
                return obj.sender.avatar_url if obj.sender else None
        return None

    def get_direction(self, obj):
        request = self.context.get('request')
        if request and request.user:
            if obj.sender == request.user:
                return 'sent'
            else:
                return 'received'
        return None


class WalletDetailSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()
    send_limit_remaining_today = serializers.SerializerMethodField()
    usage = serializers.SerializerMethodField()
    kyc_tier = serializers.CharField(source='user.kyc_tier', read_only=True)
    send_limit_per_tx = serializers.DecimalField(
        source='user.send_limit_per_tx', max_digits=20, decimal_places=2, read_only=True
    )
    send_limit_daily = serializers.DecimalField(
        source='user.send_limit_daily', max_digits=20, decimal_places=2, read_only=True
    )
    limits_manually_set = serializers.BooleanField(source='user.limits_manually_set', read_only=True)

    class Meta:
        model = Wallet
        fields = [
            'id', 'balance', 'currency', 'status', 'kyc_tier', 'send_limit_per_tx',
            'send_limit_daily', 'send_limit_remaining_today', 'limits_manually_set', 'usage'
        ]
        read_only_fields = fields

    def get_balance(self, obj):
        return str(obj.get_balance())

    def get_send_limit_remaining_today(self, obj):
        from wallet.services.limits import get_daily_remaining
        
        # Use the new function that auto-resets at midnight in business timezone
        remaining = get_daily_remaining(obj.user)
        return str(remaining)

    def get_usage(self, obj):
        from wallet.services.limits import compute_limit_snapshot
        snapshot = compute_limit_snapshot(obj.user)
        return {
            'completed_transfers': snapshot['completed_transfers'],
            'volume_sent': str(snapshot['volume_sent']),
            'current_step': snapshot['current_step'],
            'max_steps': snapshot['max_steps'],
            'transfers_per_step': snapshot['transfers_per_step'],
            'transfers_until_next_increase': snapshot['transfers_until_next_increase'],
            'per_tx_increase': str(snapshot['per_tx_increase']),
            'daily_increase': str(snapshot['daily_increase']),
            'next_send_limit_per_tx': str(snapshot['next_send_limit_per_tx']),
            'next_send_limit_daily': str(snapshot['next_send_limit_daily']),
        }


class ProfileUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    handle = serializers.CharField(required=False, allow_blank=True, max_length=50)
    primary_phone_number = serializers.CharField(required=False, allow_blank=True, max_length=30)
    transaction_pin = serializers.RegexField(regex=r'^\d{4}$', required=False)


def generate_unique_handle(base_handle):
    """
    Generate a unique handle by appending digits if the base handle is taken.
    """
    from .models import User
    
    handle = base_handle
    counter = 1
    while User.objects.filter(handle=handle).exists():
        handle = f"{base_handle}{counter}"
        counter += 1
    return handle


class TransactionDetailSerializer(serializers.ModelSerializer):
    """
    Detailed transaction serializer for single transaction view.
    Includes reversal status and related transaction info.
    """
    sender_handle = serializers.SerializerMethodField()
    sender_display_name = serializers.SerializerMethodField()
    recipient_handle = serializers.SerializerMethodField()
    recipient_display_name = serializers.SerializerMethodField()
    reversal_status = serializers.SerializerMethodField()
    related_transaction_id = serializers.UUIDField(source='related_transaction.id', allow_null=True)

    class Meta:
        model = Transaction
        fields = [
            'id', 'type', 'sender_handle', 'sender_display_name',
            'recipient_handle', 'recipient_display_name', 'amount', 'currency',
            'note', 'status', 'reversal_status', 'related_transaction_id',
            'created_at'
        ]
        read_only_fields = fields

    def get_sender_handle(self, obj):
        return obj.sender.handle if obj.sender else None

    def get_sender_display_name(self, obj):
        return obj.sender.display_name if obj.sender else None

    def get_recipient_handle(self, obj):
        return obj.recipient.handle if obj.recipient else None

    def get_recipient_display_name(self, obj):
        return obj.recipient.display_name if obj.recipient else None

    def get_reversal_status(self, obj):
        # Check if this transaction has been reversed
        if obj.type == TransactionType.REVERSAL:
            return 'is_reversal'
        return 'reversed' if obj.reversals.filter(status=TransactionStatus.COMPLETED).exists() else 'none'


class ReversalRequestSerializer(serializers.Serializer):
    """
    Serializer for admin reversal requests.
    """
    reason = serializers.CharField(required=True, max_length=500)


class ReversalResponseSerializer(serializers.ModelSerializer):
    """
    Serializer for reversal response.
    """
    class Meta:
        model = Transaction
        fields = ['id', 'type', 'amount', 'currency', 'status', 'created_at']


class TransferAttemptSerializer(serializers.ModelSerializer):
    """
    Serializer for transfer attempt logs.
    """
    class Meta:
        model = TransferAttempt
        fields = ['id', 'recipient_handle_input', 'amount', 'currency', 'rejection_reason', 'created_at']
        read_only_fields = fields


class LinkedProviderSerializer(serializers.ModelSerializer):
    """
    Serializer for linked mobile money providers.
    """
    class Meta:
        model = LinkedProvider
        fields = ['id', 'provider', 'masked_reference', 'verification_status', 'created_at']
        read_only_fields = fields


class ExchangeRateSerializer(serializers.ModelSerializer):
    """
    Serializer for exchange rates.
    """
    class Meta:
        model = ExchangeRate
        fields = ['id', 'from_currency', 'to_currency', 'rate', 'source', 'valid_from', 'valid_until']
        read_only_fields = fields


class AdminLoginSerializer(serializers.Serializer):
    """
    Serializer for admin username/password login.
    """
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)


class AdminChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, min_length=8)


class AdminBroadcastNotificationSerializer(serializers.Serializer):
    target = serializers.ChoiceField(choices=['all', 'status:active', 'status:suspended', 'status:closed', 'user'])
    user_id = serializers.IntegerField(required=False, allow_null=True)
    type = serializers.CharField(required=True, max_length=100)
    payload = serializers.JSONField(required=True)


class SystemSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSetting
        fields = ['key', 'value', 'description', 'updated_at']
        read_only_fields = ['key', 'updated_at']


class AdminDashboardSerializer(serializers.Serializer):
    """
    Serializer for admin dashboard statistics.
    """
    total_users = serializers.IntegerField()
    active_users = serializers.IntegerField()
    suspended_users = serializers.IntegerField()
    closed_users = serializers.IntegerField()
    total_wallets = serializers.IntegerField()
    p2p_volume_today = serializers.DecimalField(max_digits=20, decimal_places=2)
    p2p_volume_week = serializers.DecimalField(max_digits=20, decimal_places=2)
    pending_payment_requests = serializers.IntegerField()
    frozen_wallets = serializers.IntegerField()
    transfer_attempt_rejections_24h = serializers.IntegerField()


class AdminUserListSerializer(serializers.ModelSerializer):
    """
    Serializer for admin user list.
    Includes all user records, not only staff members, so admins can review
    system and operational accounts alongside standard users.
    """
    balance = serializers.SerializerMethodField()
    wallet_status = serializers.CharField(source='wallet.status', read_only=True)
    is_staff = serializers.BooleanField(read_only=True)
    is_agent = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'email', 'handle', 'display_name', 'status', 'wallet_status',
            'kyc_tier', 'balance', 'is_staff', 'is_agent', 'created_at'
        ]
        read_only_fields = fields

    def get_balance(self, obj):
        return str(obj.wallet.get_balance()) if hasattr(obj, 'wallet') else '0.00'


class AdminUserDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for admin user detail.
    """
    balance = serializers.SerializerMethodField()
    wallet_status = serializers.CharField(source='wallet.status', read_only=True)
    recent_transactions = serializers.SerializerMethodField()
    recent_transfer_attempts = serializers.SerializerMethodField()
    linked_providers = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'handle', 'display_name', 'avatar_url', 'status', 'kyc_tier',
            'send_limit_per_tx', 'send_limit_daily', 'balance', 'wallet_status',
            'is_staff', 'is_agent', 'created_at', 'recent_transactions', 
            'recent_transfer_attempts', 'linked_providers'
        ]
        read_only_fields = ['id', 'created_at', 'is_staff']
    
    def get_balance(self, obj):
        return str(obj.wallet.get_balance()) if hasattr(obj, 'wallet') else '0.00'
    
    def get_recent_transactions(self, obj):
        from .models import Transaction
        recent = Transaction.objects.filter(
            models.Q(sender=obj) | models.Q(recipient=obj)
        ).order_by('-created_at')[:5]
        return TransactionDetailSerializer(recent, many=True).data
    
    def get_recent_transfer_attempts(self, obj):
        recent = obj.transfer_attempts.order_by('-created_at')[:5]
        return TransferAttemptSerializer(recent, many=True).data
    
    def get_linked_providers(self, obj):
        return LinkedProviderSerializer(obj.linked_providers.all(), many=True).data


class AdminUserUpdateSerializer(serializers.Serializer):
    """
    Serializer for admin user updates.
    """
    status = serializers.CharField(required=False)
    wallet_status = serializers.CharField(required=False)
    send_limit_per_tx = serializers.DecimalField(required=False, max_digits=20, decimal_places=2)
    send_limit_daily = serializers.DecimalField(required=False, max_digits=20, decimal_places=2)
    kyc_tier = serializers.CharField(required=False)
    reason = serializers.CharField(required=True, max_length=500)


class AdminTopUpSerializer(serializers.Serializer):
    """Serializer for admin wallet top-ups."""
    amount = serializers.DecimalField(required=True, max_digits=20, decimal_places=2, min_value=Decimal('0.01'))
    currency = serializers.CharField(required=False, max_length=3, default='GNF')
    note = serializers.CharField(required=False, allow_blank=True, max_length=500, default='')
    reason = serializers.CharField(required=True, max_length=500)


class AdminTransactionListSerializer(serializers.ModelSerializer):
    """
    Serializer for admin transaction list.
    """
    sender_handle = serializers.CharField(source='sender.handle', read_only=True, allow_null=True)
    recipient_handle = serializers.CharField(source='recipient.handle', read_only=True)
    reversal_status = serializers.SerializerMethodField()
    
    class Meta:
        model = Transaction
        fields = [
            'id', 'type', 'sender_handle', 'recipient_handle', 'amount', 'currency',
            'status', 'reversal_status', 'created_at'
        ]
        read_only_fields = fields
    
    def get_reversal_status(self, obj):
        if obj.type == TransactionType.REVERSAL:
            return 'is_reversal'
        return 'reversed' if obj.reversals.filter(status=TransactionStatus.COMPLETED).exists() else 'none'


class AdminAuditLogSerializer(serializers.ModelSerializer):
    """
    Serializer for admin audit log.
    """
    user_handle = serializers.CharField(source='user.handle', read_only=True, allow_null=True)
    user_email = serializers.CharField(source='user.email', read_only=True, allow_null=True)
    
    class Meta:
        model = AuditLog
        fields = ['id', 'user_handle', 'user_email', 'action', 'metadata', 'created_at']
        read_only_fields = fields


class DisputeCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a dispute on a transaction.
    """
    transaction_id = serializers.UUIDField(required=True)
    reason = serializers.CharField(required=True, max_length=1000)
    evidence_notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class DisputeSerializer(serializers.ModelSerializer):
    """
    Serializer for dispute details.
    """
    opened_by_handle = serializers.CharField(source='opened_by.handle', read_only=True)
    opened_by_display_name = serializers.CharField(source='opened_by.display_name', read_only=True)
    transaction_id = serializers.UUIDField(source='transaction.id', read_only=True)
    resolved_by_handle = serializers.CharField(source='resolved_by.handle', read_only=True, allow_null=True)
    
    class Meta:
        model = Dispute
        fields = [
            'id', 'transaction_id', 'opened_by_handle', 'opened_by_display_name',
            'reason', 'evidence_notes', 'status', 'resolved_by_handle',
            'resolved_at', 'resolution_notes', 'created_at', 'updated_at'
        ]
        read_only_fields = fields


class DisputeResolveSerializer(serializers.Serializer):
    """
    Serializer for admin dispute resolution.
    """
    resolution = serializers.ChoiceField(choices=['reverse', 'deny'], required=True)
    resolution_notes = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class MobileMoneyTransactionSerializer(serializers.ModelSerializer):
    """
    Serializer for mobile money transactions.
    """
    class Meta:
        model = MobileMoneyTransaction
        fields = [
            'id', 'user', 'wallet', 'linked_provider', 'type', 'amount', 'fee_amount', 'currency',
            'status', 'provider_transaction_id', 'provider_reference', 'provider_response',
            'failure_reason', 'created_at', 'updated_at', 'completed_at'
        ]
        read_only_fields = ['id', 'user', 'wallet', 'provider_response', 'created_at', 'updated_at', 'completed_at']


class MobileMoneyTopupSerializer(serializers.Serializer):
    """
    Serializer for mobile money top-up requests.
    """
    linked_provider_id = serializers.IntegerField(required=True)
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, required=True)
    currency = serializers.CharField(max_length=3, required=True)


class MobileMoneyWithdrawalSerializer(serializers.Serializer):
    """
    Serializer for mobile money withdrawal requests.
    """
    linked_provider_id = serializers.IntegerField(required=True)
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, required=True)
    currency = serializers.CharField(max_length=3, required=True)


class ScheduledTransferSerializer(serializers.ModelSerializer):
    """
    Serializer for scheduled transfers.
    """
    recipient_phone = serializers.CharField(source='recipient.primary_phone_number', read_only=True)

    class Meta:
        model = ScheduledTransfer
        fields = [
            'id', 'sender', 'recipient', 'recipient_phone', 'amount', 'currency',
            'frequency', 'next_execution', 'last_execution', 'end_date',
            'total_executions', 'max_executions', 'status', 'note',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'sender', 'recipient', 'last_execution', 'total_executions', 'created_at', 'updated_at']


class ScheduledTransferCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a scheduled transfer.
    """
    recipient_phone = serializers.CharField(required=True, max_length=30)
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, required=True)
    currency = serializers.CharField(max_length=3, required=True)
    frequency = serializers.ChoiceField(choices=ScheduleFrequency.choices, required=True)
    start_date = serializers.DateTimeField(required=True)
    end_date = serializers.DateTimeField(required=False, allow_null=True)
    max_executions = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class MerchantSerializer(serializers.ModelSerializer):
    """
    Serializer for merchant accounts.
    """
    user_handle = serializers.CharField(source='user.handle', read_only=True)
    wallet_currency = serializers.CharField(source='wallet.currency', read_only=True)
    plan = serializers.SerializerMethodField()

    class Meta:
        model = Merchant
        fields = [
            'id', 'user', 'user_handle', 'business_name',
            'business_type', 'description', 'status',
            'static_qr_code', 'static_qr_payload', 'static_qr_signature',
            'wallet', 'wallet_currency', 'logo_url', 'contact_email', 'contact_phone',
            'address', 'tax_id', 'approved_by', 'approved_at', 'rejection_reason',
            'created_at', 'updated_at', 'plan', 'website_url', 'business_email',
            'sandbox_public_key', 'live_public_key', 'credentials_issued_at'
        ]
        read_only_fields = ['id', 'user', 'static_qr_code', 'static_qr_payload', 'static_qr_signature',
                           'approved_by', 'approved_at', 'rejection_reason', 'created_at', 'updated_at',
                           'sandbox_public_key', 'live_public_key', 'credentials_issued_at']

    def get_plan(self, obj):
        subscription = getattr(obj, 'subscription', None)
        if not subscription:
            return None
        return MerchantPlanSerializer(subscription.plan).data | {
            'status': subscription.status,
            'current_period_end': subscription.current_period_end,
            'cancel_at_period_end': subscription.cancel_at_period_end,
        }


class MerchantPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantPlan
        fields = [
            'code', 'name', 'description', 'monthly_price', 'currency',
            'monthly_transaction_limit', 'transaction_fee_percent',
            'api_access', 'webhook_access', 'qr_payments', 'kyc_support',
        ]


class MerchantSubscriptionSerializer(serializers.ModelSerializer):
    plan = MerchantPlanSerializer(read_only=True)

    class Meta:
        model = MerchantSubscription
        fields = ['status', 'plan', 'current_period_start', 'current_period_end', 'cancel_at_period_end']


class MerchantCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a merchant account application.
    """
    business_name = serializers.CharField(required=True, max_length=200)
    business_type = serializers.CharField(required=False, allow_blank=True, max_length=100)
    description = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    wallet_id = serializers.IntegerField(required=True)
    logo_url = serializers.URLField(required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(required=False, allow_blank=True, max_length=20)
    address = serializers.CharField(required=False, allow_blank=True, max_length=500)
    tax_id = serializers.CharField(required=False, allow_blank=True, max_length=50)
    plan_code = serializers.SlugField(required=False, default='starter', max_length=30)


class MerchantApprovalSerializer(serializers.Serializer):
    """
    Serializer for admin merchant approval/rejection.
    """
    action = serializers.ChoiceField(choices=['approve', 'reject'], required=True)
    rejection_reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class TransactionApprovalSerializer(serializers.ModelSerializer):
    """
    Serializer for transaction approval requests.
    """
    requester_handle = serializers.CharField(source='requester.handle', read_only=True)
    requester_display_name = serializers.CharField(source='requester.display_name', read_only=True)
    requester_phone = serializers.CharField(source='requester.primary_phone_number', read_only=True)
    requester_phone_last4 = serializers.SerializerMethodField()
    approver_handle = serializers.CharField(source='approver.handle', read_only=True)
    approver_display_name = serializers.CharField(source='approver.display_name', read_only=True)
    
    class Meta:
        model = TransactionApproval
        fields = [
            'id', 'approval_type', 'status', 'amount', 'currency', 'note',
            'requester_handle', 'requester_display_name', 'requester_phone',
            'requester_phone_last4',
            'approver_handle', 'approver_display_name',
            'transaction_id', 'payment_request_id', 'split_request_id',
            'expires_at', 'created_at'
        ]
        read_only_fields = fields

    def get_requester_phone_last4(self, obj):
        phone = (obj.requester.primary_phone_number or obj.requester.phone_number or '').strip()
        digits = ''.join(character for character in phone if character.isdigit())
        return digits[-4:] if len(digits) >= 4 else digits


class ParentalControlSerializer(serializers.ModelSerializer):
    """
    Serializer for parental control relationships.
    """
    parent_email = serializers.EmailField(source='parent.email', read_only=True)
    parent_display_name = serializers.CharField(source='parent.display_name', read_only=True)
    child_email = serializers.EmailField(source='child.email', read_only=True)
    child_display_name = serializers.CharField(source='child.display_name', read_only=True)
    
    class Meta:
        model = ParentalControl
        fields = [
            'id', 'parent_id', 'child_id', 'parent_email', 'parent_display_name', 'child_email', 'child_display_name',
            'status', 'can_view_transactions', 'can_control_balance', 'can_send_money', 'can_set_limits',
            'linked_at', 'created_at'
        ]
        read_only_fields = fields


class ParentalControlLinkSerializer(serializers.Serializer):
    """
    Serializer for linking a child account with a verification code.
    """
    child_phone = serializers.CharField(max_length=30, help_text="Child's phone number")


class ParentalControlVerifySerializer(serializers.Serializer):
    """
    Serializer for verifying a parental control link with a code.
    """
    verification_code = serializers.RegexField(regex=r'^\d{6}$', help_text="6-digit verification code")


class ParentalControlUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating parental control permissions.
    """
    can_view_transactions = serializers.BooleanField(required=False)
    can_control_balance = serializers.BooleanField(required=False)
    can_send_money = serializers.BooleanField(required=False)
    can_set_limits = serializers.BooleanField(required=False)


class PinVerifySerializer(serializers.Serializer):
    """
    Serializer for PIN verification.
    """
    pin = serializers.RegexField(regex=r'^\d{4}$', help_text="4-digit transaction PIN")
