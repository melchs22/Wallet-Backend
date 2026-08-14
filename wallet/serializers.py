from rest_framework import serializers
from django.contrib.auth import login
from .models import (
    User, Wallet, LedgerEntry, KYCTier, UserStatus, LedgerDirection, AuditLog,
    Transaction, TransactionType, TransactionStatus, WalletStatus
)
from django.db import transaction
from django.utils.text import slugify
from decimal import Decimal


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'handle', 'display_name', 'avatar_url', 'kyc_tier', 'status']
        read_only_fields = ['id', 'kyc_tier', 'status']


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


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = 'wallet.Notification'
        fields = ['id', 'type', 'payload', 'read_at', 'created_at']
        read_only_fields = ['id', 'created_at']


class TransactionSerializer(serializers.ModelSerializer):
    counterparty_handle = serializers.SerializerMethodField()
    counterparty_display_name = serializers.SerializerMethodField()
    counterparty_avatar_url = serializers.SerializerMethodField()
    direction = serializers.SerializerMethodField()

    class Meta:
        model = 'wallet.Transaction'
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

    class Meta:
        model = Wallet
        fields = [
            'balance', 'currency', 'kyc_tier', 'send_limit_per_tx',
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
        model = 'wallet.TransferAttempt'
        fields = ['id', 'recipient_handle_input', 'amount', 'currency', 'rejection_reason', 'created_at']
        read_only_fields = fields


class LinkedProviderSerializer(serializers.ModelSerializer):
    """
    Serializer for linked mobile money providers.
    """
    class Meta:
        model = 'wallet.LinkedProvider'
        fields = ['id', 'provider', 'masked_reference', 'verification_status', 'created_at']
        read_only_fields = fields


class ExchangeRateSerializer(serializers.ModelSerializer):
    """
    Serializer for exchange rates.
    """
    class Meta:
        model = 'wallet.ExchangeRate'
        fields = ['id', 'from_currency', 'to_currency', 'rate', 'source', 'valid_from', 'valid_until']
        read_only_fields = fields
