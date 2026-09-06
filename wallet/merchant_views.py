import logging

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response

from wallet.merchant_authentication import MerchantApiKeyAuthentication, MerchantApiKeyRateThrottle
from wallet.merchant_serializers import (
    CheckoutConfirmSerializer,
    FeePreviewQuerySerializer,
    PaymentIntentCreateSerializer,
    PaymentIntentSerializer,
)
from wallet.models import Merchant, PaymentIntent, PaymentIntentStatus, WebhookDelivery
from wallet.services.fees import preview_merchant_transfer_fee, resolve_fee
from wallet.services.payment_intents import (
    PaymentIntentError,
    cancel_payment_intent,
    confirm_payment_intent,
    create_payment_intent,
    get_checkout_public_detail,
)
from wallet.models import FeeAppliesTo

logger = logging.getLogger(__name__)


def _merchant_from_request(request):
    return request.user.merchant_account


@api_view(['POST'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_create_payment_intent(request):
    serializer = PaymentIntentCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    merchant = _merchant_from_request(request)
    mode = request.merchant_api_mode

    try:
        intent = create_payment_intent(
            merchant,
            amount=serializer.validated_data['amount'],
            currency=serializer.validated_data['currency'],
            external_reference=serializer.validated_data.get('external_reference', ''),
            description=serializer.validated_data.get('description', ''),
            mode=mode,
            return_url=serializer.validated_data.get('return_url', ''),
        )
        data = PaymentIntentSerializer(intent).data
        return Response(data, status=status.HTTP_201_CREATED)
    except PaymentIntentError as exc:
        return Response({'code': exc.code, 'message': exc.message}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_get_payment_intent(request, intent_id):
    merchant = _merchant_from_request(request)
    try:
        intent = PaymentIntent.objects.get(id=intent_id, merchant=merchant, mode=request.merchant_api_mode)
    except PaymentIntent.DoesNotExist:
        return Response({'error': 'Payment intent not found'}, status=status.HTTP_404_NOT_FOUND)
    return Response(PaymentIntentSerializer(intent).data)


@api_view(['POST'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_cancel_payment_intent(request, intent_id):
    merchant = _merchant_from_request(request)
    try:
        intent = PaymentIntent.objects.get(id=intent_id, merchant=merchant, mode=request.merchant_api_mode)
        cancel_payment_intent(intent)
        return Response(PaymentIntentSerializer(intent).data)
    except PaymentIntent.DoesNotExist:
        return Response({'error': 'Payment intent not found'}, status=status.HTTP_404_NOT_FOUND)
    except PaymentIntentError as exc:
        return Response({'code': exc.code, 'message': exc.message}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([AllowAny])
def checkout_public_detail(request, intent_id):
    try:
        intent = PaymentIntent.objects.select_related('merchant').get(pk=intent_id)
    except PaymentIntent.DoesNotExist:
        return Response({'error': 'Payment intent not found'}, status=status.HTTP_404_NOT_FOUND)
    return Response(get_checkout_public_detail(intent))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def checkout_confirm(request, intent_id):
    serializer = CheckoutConfirmSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        intent = PaymentIntent.objects.select_related('merchant').get(pk=intent_id)
        transaction_obj = confirm_payment_intent(
            intent,
            request.user,
            serializer.validated_data['idempotency_key'],
        )
        intent.refresh_from_db()
        return Response({
            'status': intent.status,
            'transaction_id': str(transaction_obj.id),
            'return_url': intent.return_url,
        })
    except PaymentIntent.DoesNotExist:
        return Response({'error': 'Payment intent not found'}, status=status.HTTP_404_NOT_FOUND)
    except PaymentIntentError as exc:
        code_map = {
            'insufficient_funds': status.HTTP_400_BAD_REQUEST,
            'expired': status.HTTP_400_BAD_REQUEST,
            'invalid_status': status.HTTP_400_BAD_REQUEST,
        }
        return Response({'code': exc.code, 'message': exc.message}, status=code_map.get(exc.code, status.HTTP_400_BAD_REQUEST))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def transfer_fee_preview(request):
    serializer = FeePreviewQuerySerializer(data=request.query_params)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    amount = serializer.validated_data['amount']
    currency = serializer.validated_data['currency']
    transfer_type = serializer.validated_data['type']

    if transfer_type == 'merchant_transfer':
        merchant_id = serializer.validated_data.get('merchant_id')
        if not merchant_id:
            return Response({'error': 'merchant_id is required for merchant_transfer'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(preview_merchant_transfer_fee(amount, merchant_id, currency))

    fee_amount, policy = resolve_fee(amount, FeeAppliesTo.P2P_TRANSFER, user=request.user, currency=currency)
    total = amount + fee_amount
    return Response({
        'amount': str(amount),
        'fee_amount': str(fee_amount),
        'total_amount': str(total),
        'currency': currency,
        'fee_policy_id': policy.id if policy else None,
    })


@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_generate_merchant_api_keys(request, merchant_id):
    from wallet.models import Merchant, MerchantMode
    from wallet.merchant_serializers import MerchantApiKeyRevealSerializer
    from wallet.services.merchants import generate_merchant_api_keys

    mode = request.data.get('mode', MerchantMode.LIVE)
    if mode not in (MerchantMode.LIVE, MerchantMode.SANDBOX):
        return Response({'error': 'Invalid mode'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        merchant = Merchant.objects.get(pk=merchant_id)
    except Merchant.DoesNotExist:
        return Response({'error': 'Merchant not found'}, status=status.HTTP_404_NOT_FOUND)

    public_key, secret_key = generate_merchant_api_keys(merchant, mode)
    return Response(MerchantApiKeyRevealSerializer({
        'public_key': public_key,
        'secret_key': secret_key,
        'mode': mode,
    }).data)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_merchant_webhook_deliveries(request, merchant_id):
    from wallet.merchant_serializers import WebhookDeliverySerializer

    deliveries = WebhookDelivery.objects.filter(merchant_id=merchant_id).order_by('-created_at')[:100]
    return Response(WebhookDeliverySerializer(deliveries, many=True).data)
