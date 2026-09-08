from decimal import Decimal

from rest_framework import serializers

from wallet.models import Merchant, MerchantMode, PaymentIntent, PaymentIntentStatus, WebhookDelivery


class PaymentIntentCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    currency = serializers.CharField(max_length=3)
    external_reference = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    description = serializers.CharField(required=False, allow_blank=True, default='')
    return_url = serializers.URLField(required=False, allow_blank=True, default='')

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        if value.as_tuple().exponent < -2:
            raise serializers.ValidationError('Amount cannot have more than 2 decimal places.')
        return value


class PaymentIntentSerializer(serializers.ModelSerializer):
    checkout_url = serializers.SerializerMethodField()

    class Meta:
        model = PaymentIntent
        fields = [
            'id', 'amount', 'currency', 'external_reference', 'description', 'status',
            'mode', 'payer', 'resulting_transaction', 'expires_at', 'created_at', 'checkout_url',
        ]
        read_only_fields = fields

    def get_checkout_url(self, obj):
        from wallet.services.payment_intents import checkout_url_for_intent
        return checkout_url_for_intent(obj)


class CheckoutConfirmSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=255)


class FeePreviewQuerySerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    currency = serializers.CharField(max_length=3, default='GNF')
    type = serializers.ChoiceField(choices=['merchant_transfer', 'p2p_transfer'], default='merchant_transfer')
    merchant_id = serializers.IntegerField(required=False)


class MerchantApiKeyRevealSerializer(serializers.Serializer):
    public_key = serializers.CharField()
    secret_key = serializers.CharField()
    mode = serializers.ChoiceField(choices=MerchantMode.choices)


class WebhookDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = [
            'id', 'payment_intent', 'event_type', 'target_url', 'payload', 'status',
            'status_code', 'attempt_count', 'last_error', 'delivered_at', 'created_at',
        ]
        read_only_fields = fields


class MerchantDetailAdminSerializer(serializers.ModelSerializer):
    user_handle = serializers.CharField(source='user.handle', read_only=True)
    public_keys = serializers.SerializerMethodField()

    class Meta:
        model = Merchant
        fields = [
            'id', 'business_name', 'business_email', 'website_url', 'status', 'mode',
            'webhook_url', 'user_handle', 'public_keys', 'approved_at', 'created_at',
        ]

    def get_public_keys(self, obj):
        return {
            key.mode: key.public_key
            for key in obj.api_keys.filter(is_active=True)
        }
