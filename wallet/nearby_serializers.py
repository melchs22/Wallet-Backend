from decimal import Decimal

from rest_framework import serializers


class NearbyPaymentCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    currency = serializers.CharField(max_length=3)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate_amount(self, value):
        if value <= Decimal('0'):
            raise serializers.ValidationError('Amount must be greater than 0.')
        return value

    def validate_currency(self, value):
        return value.upper()


class NearbyPaymentResolveSerializer(serializers.Serializer):
    code = serializers.RegexField(regex=r'^[A-HJ-NP-Z2-9]{9}$', max_length=9)

    def validate_code(self, value):
        return value.upper()


class NearbyPaymentPaySerializer(serializers.Serializer):
    pin = serializers.RegexField(regex=r'^\d{4}$')
    idempotency_key = serializers.UUIDField()


class NearbyPaymentCounterpartySerializer(serializers.Serializer):
    handle = serializers.CharField()
    display_name = serializers.CharField()
    avatar_url = serializers.CharField(required=False, allow_blank=True)


class NearbyPaymentResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    currency = serializers.CharField()
    note = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    expires_at = serializers.DateTimeField()
    transaction_id = serializers.UUIDField(allow_null=True)
    fee_amount = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        allow_null=True,
    )
    total_debit = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        allow_null=True,
    )
    discovery_code = serializers.CharField(required=False)
    receiver = NearbyPaymentCounterpartySerializer(required=False)
    payer = NearbyPaymentCounterpartySerializer(required=False)
