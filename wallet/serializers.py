from rest_framework import serializers
from django.contrib.auth import login
from django.db import models
from .models import (
    User, Wallet, LedgerEntry, KYCTier, UserStatus, LedgerDirection, AuditLog,
    Transaction, TransactionType, TransactionStatus, WalletStatus, Notification,
    TransferAttempt, LinkedProvider, ExchangeRate, PaymentRequest, SplitRequest, SplitParticipant, SystemSetting
)
from django.db import transaction
from django.utils.text import slugify
from decimal import Decimal


class UserSerializer(serializers.ModelSerializer):
    is_staff = serializers.BooleanField(read_only=True)
    must_change_password = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'handle', 'display_name', 'avatar_url', 'kyc_tier', 'status', 'is_staff', 'must_change_password']
        read_only_fields = ['id', 'kyc_tier', 'status', 'is_staff', 'must_change_password']


class WalletSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = ['id', 'currency', 'status', 'balance']
        read_only_fields = ['id', 'currency', 'status', 'balance']

    def get_balance(self, obj):
        return str(obj.get_balance())


class GoogleAuthRequestSerializer(serializers.Serializer):
    code = serializers.CharField(required=True)
    state = serializers.CharField(required=True)


class GoogleAuthResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    wallet = WalletSerializer()
    is_new_user = serializers.BooleanField()


class UserResolveSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    handle = serializers.CharField()
    display_name = serializers.CharField()
    avatar_url = serializers.URLField(allow_blank=True)


class TransferRequestSerializer(serializers.Serializer):
    recipient_handle = serializers.CharField(required=True, max_length=50)
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


class PaymentRequestCreateSerializer(serializers.Serializer):
    payer_handle = serializers.CharField(max_length=50)
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    currency = serializers.CharField(max_length=3)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value


class PaymentRequestSerializer(serializers.ModelSerializer):
    requester_handle = serializers.CharField(source='requester.handle', read_only=True)
    payer_handle = serializers.CharField(source='payer.handle', read_only=True)
    resulting_transaction_id = serializers.UUIDField(source='resulting_transaction.id', read_only=True, allow_null=True)

    class Meta:
        model = PaymentRequest
        fields = ['id', 'requester_handle', 'payer_handle', 'amount', 'currency', 'note', 'status', 'expires_at', 'resulting_transaction_id', 'created_at']


class PaymentRequestCreateSerializer(serializers.Serializer):
    payer_handle = serializers.CharField(max_length=50)
    amount = serializers.DecimalField(max_digits=20, decimal_places=2, min_value=Decimal('0.01'))
    currency = serializers.CharField(max_length=3, default='USD')
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class SplitCreateSerializer(serializers.Serializer):
    total_amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    currency = serializers.CharField(max_length=3)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    participants = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField()),
        min_length=1
    )

    total_amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    currency = serializers.CharField(max_length=3)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    participants = serializers.ListField(child=serializers.DictField(), min_length=1)


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
    kyc_tier = serializers.CharField(source='user.kyc_tier', read_only=True)
    send_limit_per_tx = serializers.DecimalField(
        source='user.send_limit_per_tx', max_digits=20, decimal_places=2, read_only=True
    )
    send_limit_daily = serializers.DecimalField(
        source='user.send_limit_daily', max_digits=20, decimal_places=2, read_only=True
    )

    class Meta:
        model = Wallet
        fields = [
            'id', 'balance', 'currency', 'status', 'kyc_tier', 'send_limit_per_tx',
            'send_limit_daily', 'send_limit_remaining_today'
        ]
        read_only_fields = fields

    def get_balance(self, obj):
        return str(obj.get_balance())

    def get_send_limit_remaining_today(self, obj):
        from django.db.models import Sum
        from django.utils import timezone
        from datetime import timedelta
        
        user = obj.user
        twenty_four_hours_ago = timezone.now() - timedelta(days=1)
        
        # Sum all outgoing transactions in the last 24 hours
        sent_amount = user.sent_transactions.filter(
            created_at__gte=twenty_four_hours_ago,
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        remaining = user.send_limit_daily - sent_amount
        return str(max(remaining, Decimal('0.00')))


class ProfileUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    handle = serializers.CharField(required=False, allow_blank=True, max_length=50)


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
    currency = serializers.CharField(required=False, max_length=3, default='USD')
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
