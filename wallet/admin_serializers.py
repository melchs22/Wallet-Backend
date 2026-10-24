from rest_framework import serializers
from django.contrib.auth import get_user_model
from django_celery_beat.models import PeriodicTask
from wallet.models import (
    SupportTicket, SupportTicketMessage, SupportTicketStatus, SupportTicketPriority, SupportTicketCategory,
    UserKYCSubmission, MobileMoneyTransaction, WebhookDelivery, Settlement,
    TransferFeeRule, FeePolicy, FeeWaiver, ExchangeRate, Merchant, Transaction,
    UserNote, TransactionFlag, AlertRule, AlertEvent, AdminMessage
)
from wallet.serializers import UserSerializer, TransactionDetailSerializer

User = get_user_model()


class SupportTicketMessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)

    class Meta:
        model = SupportTicketMessage
        fields = ['id', 'ticket', 'sender', 'is_internal_note', 'message', 'attachment_url', 'created_at']
        read_only_fields = ['id', 'ticket', 'sender', 'created_at']


class SupportTicketSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    assigned_to = UserSerializer(read_only=True)
    messages = SupportTicketMessageSerializer(many=True, read_only=True)
    related_transaction = TransactionDetailSerializer(read_only=True)

    class Meta:
        model = SupportTicket
        fields = [
            'id', 'ticket_number', 'user', 'assigned_to', 'subject',
            'category', 'priority', 'status', 'related_transaction',
            'created_at', 'updated_at', 'closed_at', 'messages'
        ]
        read_only_fields = ['id', 'ticket_number', 'created_at', 'updated_at', 'closed_at']


class SupportTicketCreateSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=True)
    subject = serializers.CharField(max_length=255, required=True)
    category = serializers.ChoiceField(choices=SupportTicketCategory.choices, default=SupportTicketCategory.GENERAL)
    priority = serializers.ChoiceField(choices=SupportTicketPriority.choices, default=SupportTicketPriority.MEDIUM)
    initial_message = serializers.CharField(required=True)
    related_transaction_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class SupportTicketUpdateSerializer(serializers.ModelSerializer):
    assigned_to_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = SupportTicket
        fields = ['category', 'priority', 'status', 'assigned_to_id']

    def update(self, instance, validated_data):
        assigned_to_id = validated_data.pop('assigned_to_id', None)
        if assigned_to_id is not None:
            if assigned_to_id == 0 or assigned_to_id == "":
                instance.assigned_to = None
            else:
                try:
                    agent = User.objects.get(id=assigned_to_id, is_staff=True)
                    instance.assigned_to = agent
                except User.DoesNotExist:
                    raise serializers.ValidationError({'assigned_to_id': 'Invalid staff user ID'})
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        if instance.status in [SupportTicketStatus.RESOLVED, SupportTicketStatus.CLOSED] and not instance.closed_at:
            from django.utils import timezone
            instance.closed_at = timezone.now()
            
        instance.save()
        return instance


class SupportTicketMessageCreateSerializer(serializers.Serializer):
    message = serializers.CharField(required=True)
    is_internal_note = serializers.BooleanField(default=False)
    attachment_url = serializers.URLField(required=False, allow_blank=True, default='')


class PeriodicTaskAdminSerializer(serializers.ModelSerializer):
    schedule_description = serializers.SerializerMethodField()

    class Meta:
        model = PeriodicTask
        fields = [
            'id', 'name', 'task', 'enabled', 'last_run_at',
            'total_run_count', 'description', 'schedule_description'
        ]
        read_only_fields = fields

    def get_schedule_description(self, obj):
        if obj.interval:
            return f"Every {obj.interval.every} {obj.interval.period}"
        elif obj.crontab:
            c = obj.crontab
            return f"Crontab: {c.minute} {c.hour} {c.day_of_month} {c.month_of_year} {c.day_of_week}"
        return "No schedule"


class UserKYCSubmissionAdminSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    reviewed_by = UserSerializer(read_only=True)

    class Meta:
        model = UserKYCSubmission
        fields = [
            'id', 'user', 'document_type', 'document', 'status',
            'reviewer_notes', 'reviewed_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'document', 'created_at', 'updated_at']


class UserKYCReviewSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    target_kyc_tier = serializers.ChoiceField(choices=['tier_1', 'tier_2'], required=False)
    reviewer_notes = serializers.CharField(required=False, allow_blank=True, default='')


class MobileMoneyAdminTransactionSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = MobileMoneyTransaction
        fields = [
            'id', 'user', 'linked_provider', 'type', 'amount', 'fee_amount',
            'currency', 'status', 'provider_transaction_id', 'provider_reference',
            'provider_response', 'failure_reason', 'created_at', 'completed_at'
        ]
        read_only_fields = fields


class FailedWebhookDeliverySerializer(serializers.ModelSerializer):
    merchant_name = serializers.CharField(source='merchant.business_name', read_only=True)

    class Meta:
        model = WebhookDelivery
        fields = [
            'id', 'merchant', 'merchant_name', 'event_type', 'target_url',
            'payload', 'status', 'status_code', 'attempt_count', 'last_error',
            'delivered_at', 'created_at'
        ]
        read_only_fields = fields


class SettlementAdminSerializer(serializers.ModelSerializer):
    merchant_name = serializers.CharField(source='merchant.business_name', read_only=True)

    class Meta:
        model = Settlement
        fields = [
            'id', 'merchant', 'merchant_name', 'amount', 'fees', 'currency',
            'batch_reference', 'status', 'destination', 'created_at', 'completed_at'
        ]
        read_only_fields = ['id', 'batch_reference', 'created_at']


class TransferFeeRuleAdminSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        min_amount = attrs.get('min_amount', getattr(self.instance, 'min_amount', None))
        max_amount = attrs.get('max_amount', getattr(self.instance, 'max_amount', None))
        fee_value = attrs.get('fee_value', getattr(self.instance, 'fee_value', None))
        if min_amount is not None and min_amount < 0:
            raise serializers.ValidationError({'min_amount': 'Minimum amount cannot be negative.'})
        if max_amount is not None and min_amount is not None and max_amount <= min_amount:
            raise serializers.ValidationError({'max_amount': 'Maximum amount must be greater than the minimum amount.'})
        if fee_value is not None and fee_value < 0:
            raise serializers.ValidationError({'fee_value': 'Fee value cannot be negative.'})
        if attrs.get('fee_type', getattr(self.instance, 'fee_type', None)) == 'percentage' and fee_value is not None and fee_value > 100:
            raise serializers.ValidationError({'fee_value': 'Percentage fee cannot exceed 100.'})
        return attrs

    class Meta:
        model = TransferFeeRule
        fields = ['id', 'min_amount', 'max_amount', 'fee_type', 'fee_value', 'active']


class FeePolicyAdminSerializer(serializers.ModelSerializer):
    merchant_name = serializers.CharField(source='merchant.business_name', read_only=True, allow_null=True)

    def validate(self, attrs):
        applies_to = attrs.get('applies_to', getattr(self.instance, 'applies_to', None))
        fee_percent = attrs.get('fee_percent', getattr(self.instance, 'fee_percent', None))
        fee_fixed = attrs.get('fee_fixed', getattr(self.instance, 'fee_fixed', None))
        if applies_to not in ('p2p_transfer', 'merchant_transfer'):
            raise serializers.ValidationError({'applies_to': 'Choose P2P or merchant transfers.'})
        if fee_percent is None and fee_fixed is None:
            raise serializers.ValidationError('Set a percentage fee, a fixed fee, or both.')
        if fee_percent is not None and (fee_percent < 0 or fee_percent > 100):
            raise serializers.ValidationError({'fee_percent': 'Percentage fee must be between 0 and 100.'})
        if fee_fixed is not None and fee_fixed < 0:
            raise serializers.ValidationError({'fee_fixed': 'Fixed fee cannot be negative.'})
        currency = attrs.get('currency', getattr(self.instance, 'currency', ''))
        if currency and len(currency) != 3:
            raise serializers.ValidationError({'currency': 'Currency must be a three-letter code or blank for all currencies.'})
        merchant = attrs.get('merchant', getattr(self.instance, 'merchant', None))
        if applies_to == 'p2p_transfer' and merchant is not None:
            raise serializers.ValidationError({'merchant': 'P2P policies apply to all users and cannot target a merchant.'})
        return attrs

    class Meta:
        model = FeePolicy
        fields = [
            'id', 'name', 'applies_to', 'merchant', 'merchant_name', 'currency',
            'fee_percent', 'fee_fixed', 'priority', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'merchant_name', 'created_at']


class FeeWaiverAdminSerializer(serializers.ModelSerializer):
    user_handle = serializers.CharField(source='user.handle', read_only=True)

    class Meta:
        model = FeeWaiver
        fields = ['id', 'user', 'user_handle', 'applies_to', 'valid_from', 'valid_until', 'reason', 'created_at']


class ExchangeRateAdminSerializer(serializers.ModelSerializer):
    base_currency = serializers.CharField(source='from_currency', read_only=True)
    quote_currency = serializers.CharField(source='to_currency', read_only=True)

    class Meta:
        model = ExchangeRate
        fields = ['id', 'from_currency', 'to_currency', 'base_currency', 'quote_currency', 'rate', 'source', 'valid_from', 'valid_until', 'created_at']


# ============================================================================
# NEW PRODUCTION-READY SERIALIZERS
# ============================================================================

class UserNoteSerializer(serializers.ModelSerializer):
    admin = UserSerializer(read_only=True)

    class Meta:
        model = UserNote
        fields = ['id', 'user', 'admin', 'note', 'created_at', 'updated_at']
        read_only_fields = ['id', 'admin', 'created_at', 'updated_at']


class UserNoteCreateSerializer(serializers.Serializer):
    note = serializers.CharField(required=True)


class TransactionFlagSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = TransactionFlag
        fields = ['id', 'transaction', 'flag_type', 'flag_name', 'description', 'created_by', 'created_at']
        read_only_fields = ['id', 'created_by', 'created_at']


class TransactionFlagCreateSerializer(serializers.Serializer):
    flag_id = serializers.IntegerField(required=True)
    description = serializers.CharField(required=False, allow_blank=True, default='')


class AlertRuleSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = AlertRule
        fields = [
            'id', 'name', 'description', 'alert_type', 'condition', 'threshold',
            'channels', 'enabled', 'last_triggered', 'trigger_count', 'created_by',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'last_triggered', 'trigger_count', 'created_by', 'created_at', 'updated_at']


class AlertRuleCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=True)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    alert_type = serializers.ChoiceField(choices=['warning', 'critical', 'info'], default='warning')
    condition = serializers.CharField(required=True)
    threshold = serializers.CharField(max_length=100, required=True)
    channels = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class AlertEventSerializer(serializers.ModelSerializer):
    rule = AlertRuleSerializer(read_only=True)
    resolved_by = UserSerializer(read_only=True)

    class Meta:
        model = AlertEvent
        fields = [
            'id', 'rule', 'severity', 'message', 'metadata', 'resolved',
            'resolved_at', 'resolved_by', 'created_at'
        ]
        read_only_fields = fields


class AdminMessageSerializer(serializers.ModelSerializer):
    recipient = UserSerializer(read_only=True)
    sender = UserSerializer(read_only=True)

    class Meta:
        model = AdminMessage
        fields = [
            'id', 'recipient', 'sender', 'subject', 'content', 'status',
            'delivery_error', 'created_at', 'read_at'
        ]
        read_only_fields = ['id', 'recipient', 'sender', 'created_at', 'read_at']


class AdminMessageCreateSerializer(serializers.Serializer):
    recipient_handle = serializers.CharField(max_length=100, required=True)
    subject = serializers.CharField(max_length=200, required=True)
    content = serializers.CharField(required=True)
