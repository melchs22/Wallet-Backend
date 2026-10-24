import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from wallet.models import (
    AuditLog,
    NearbyPaymentRequest,
    OtpChallenge,
    UserStatus,
    Wallet,
    WalletStatus,
)
from wallet.nearby_serializers import (
    NearbyPaymentCreateSerializer,
    NearbyPaymentPaySerializer,
    NearbyPaymentResponseSerializer,
    NearbyPaymentResolveSerializer,
)
from wallet.services.transfers import TransferExecutionError, execute_p2p_transfer
from wallet.throttles import (
    NearbyPaymentCreateThrottle,
    NearbyPaymentPayThrottle,
    NearbyPaymentResolveThrottle,
)


_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
_REQUEST_TTL = timedelta(minutes=2)


def _feature_disabled_response():
    if settings.NEARBY_PAYMENTS_ENABLED:
        return None
    return Response({
        'code': 'feature_disabled',
        'error': 'Nearby payments are not enabled.',
    }, status=status.HTTP_404_NOT_FOUND)


def _code_digest(code):
    return hashlib.sha256(code.encode('ascii')).hexdigest()


def _request_details(payment_request, *, include_receiver=False):
    transaction_obj = payment_request.resulting_transaction
    fee_amount = transaction_obj.fee_amount if transaction_obj else None
    details = {
        'id': str(payment_request.id),
        'amount': str(payment_request.amount),
        'currency': payment_request.currency,
        'note': payment_request.note,
        'status': payment_request.status,
        'expires_at': payment_request.expires_at.isoformat(),
        'transaction_id': (
            str(payment_request.resulting_transaction_id)
            if payment_request.resulting_transaction_id else None
        ),
        'fee_amount': str(fee_amount) if fee_amount is not None else None,
        'total_debit': (
            str(payment_request.amount + fee_amount)
            if fee_amount is not None else None
        ),
    }
    if include_receiver:
        receiver = payment_request.receiver
        details['receiver'] = {
            'handle': receiver.handle,
            'display_name': receiver.display_name,
            'avatar_url': receiver.avatar_url,
        }
    if payment_request.status == NearbyPaymentRequest.Status.PAID and payment_request.payer_id:
        details['payer'] = {
            'handle': payment_request.payer.handle,
            'display_name': payment_request.payer.display_name,
        }
    return details


def _expire_if_needed(payment_request, now=None):
    now = now or timezone.now()
    if (
        payment_request.status == NearbyPaymentRequest.Status.OPEN
        and payment_request.expires_at <= now
    ):
        payment_request.status = NearbyPaymentRequest.Status.EXPIRED
        payment_request.save(update_fields=['status'])
        AuditLog.objects.create(
            user=payment_request.receiver,
            action='nearby_payment_expired',
            metadata={'request_id': str(payment_request.id)},
        )
    return payment_request


@extend_schema(
    request=NearbyPaymentCreateSerializer,
    responses={201: NearbyPaymentResponseSerializer, 400: dict, 403: dict},
    tags=['Nearby Payments'],
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([NearbyPaymentCreateThrottle])
@transaction.atomic
def create_nearby_payment(request):
    disabled_response = _feature_disabled_response()
    if disabled_response:
        return disabled_response
    serializer = NearbyPaymentCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    receiver = request.user
    if receiver.status != UserStatus.ACTIVE:
        return Response({'code': 'account_unavailable', 'error': 'This account cannot receive payments.'}, status=403)
    try:
        receiver_wallet = receiver.wallet
    except Wallet.DoesNotExist:
        return Response({'code': 'wallet_unavailable', 'error': 'An active wallet is required.'}, status=403)
    if receiver_wallet.status != WalletStatus.ACTIVE:
        return Response({'code': 'wallet_unavailable', 'error': 'An active wallet is required.'}, status=403)

    amount = serializer.validated_data['amount']
    currency = serializer.validated_data['currency']
    if receiver_wallet.currency != currency:
        return Response({
            'code': 'currency_mismatch',
            'error': f'Your wallet currency is {receiver_wallet.currency}.',
        }, status=status.HTTP_400_BAD_REQUEST)

    code = ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(9))
    payment_request = NearbyPaymentRequest.objects.create(
        receiver=receiver,
        code_digest=_code_digest(code),
        amount=amount,
        currency=currency,
        note=serializer.validated_data.get('note', ''),
        expires_at=timezone.now() + _REQUEST_TTL,
    )
    AuditLog.objects.create(
        user=receiver,
        action='nearby_payment_created',
        metadata={
            'request_id': str(payment_request.id),
            'amount': str(amount),
            'currency': currency,
        },
    )
    response_data = _request_details(payment_request)
    response_data['discovery_code'] = code
    return Response(response_data, status=status.HTTP_201_CREATED)


@extend_schema(
    request=NearbyPaymentResolveSerializer,
    responses={200: NearbyPaymentResponseSerializer, 400: dict, 404: dict},
    tags=['Nearby Payments'],
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([NearbyPaymentResolveThrottle])
def resolve_nearby_payment(request):
    disabled_response = _feature_disabled_response()
    if disabled_response:
        return disabled_response
    serializer = NearbyPaymentResolveSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    digest = _code_digest(serializer.validated_data['code'])

    payment_request = NearbyPaymentRequest.objects.select_related('receiver').filter(
        code_digest=digest,
    ).first()
    if not payment_request:
        return Response({'code': 'nearby_request_unavailable', 'error': 'This nearby payment is unavailable.'}, status=404)

    _expire_if_needed(payment_request)
    if payment_request.status != NearbyPaymentRequest.Status.OPEN:
        return Response({'code': 'nearby_request_unavailable', 'error': 'This nearby payment is unavailable.'}, status=404)
    if payment_request.receiver_id == request.user.id:
        return Response({'code': 'self_payment', 'error': 'You cannot pay yourself.'}, status=400)
    if request.user.status != UserStatus.ACTIVE:
        return Response({'code': 'account_unavailable', 'error': 'This account cannot make payments.'}, status=403)
    try:
        payer_wallet = request.user.wallet
    except Wallet.DoesNotExist:
        return Response({'code': 'wallet_unavailable', 'error': 'An active wallet is required.'}, status=403)
    if payer_wallet.status != WalletStatus.ACTIVE:
        return Response({'code': 'wallet_unavailable', 'error': 'An active wallet is required.'}, status=403)
    if payer_wallet.currency != payment_request.currency:
        return Response({
            'code': 'currency_mismatch',
            'error': f'Your wallet currency is {payer_wallet.currency}.',
        }, status=400)
    from wallet.services.fees import calculate_transfer_fee
    fee_amount = calculate_transfer_fee(payment_request.amount)
    details = _request_details(payment_request, include_receiver=True)
    details['fee_amount'] = str(fee_amount)
    details['total_debit'] = str(payment_request.amount + fee_amount)
    return Response(details)


@extend_schema(
    responses={200: NearbyPaymentResponseSerializer, 404: dict},
    tags=['Nearby Payments'],
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def nearby_payment_status(request, request_id):
    disabled_response = _feature_disabled_response()
    if disabled_response:
        return disabled_response
    payment_request = NearbyPaymentRequest.objects.select_for_update().filter(
        pk=request_id,
    ).first()
    if (
        not payment_request
        or request.user.id not in (payment_request.receiver_id, payment_request.payer_id)
    ):
        return Response({'error': 'Nearby payment request not found.'}, status=404)
    _expire_if_needed(payment_request)
    return Response(_request_details(
        payment_request,
        include_receiver=payment_request.payer_id == request.user.id,
    ))


@extend_schema(
    request=NearbyPaymentPaySerializer,
    responses={200: NearbyPaymentResponseSerializer, 400: dict, 403: dict, 404: dict, 409: dict},
    tags=['Nearby Payments'],
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([NearbyPaymentPayThrottle])
@transaction.atomic
def pay_nearby_payment(request, request_id):
    disabled_response = _feature_disabled_response()
    if disabled_response:
        return disabled_response
    payment_request = NearbyPaymentRequest.objects.select_for_update().filter(
        pk=request_id,
    ).first()
    if not payment_request:
        return Response({'error': 'Nearby payment request not found.'}, status=404)

    serializer = NearbyPaymentPaySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    idempotency_key = str(serializer.validated_data['idempotency_key'])
    idempotency_hash = hashlib.sha256(idempotency_key.encode('ascii')).hexdigest()

    if payment_request.status == NearbyPaymentRequest.Status.PAID:
        if (
            payment_request.payer_id == request.user.id
            and payment_request.idempotency_hash == idempotency_hash
            and payment_request.resulting_transaction_id
        ):
            return Response(_request_details(payment_request))
        return Response({
            'code': 'nearby_request_unavailable',
            'error': 'This nearby payment is no longer available.',
        }, status=status.HTTP_409_CONFLICT)

    _expire_if_needed(payment_request)
    if payment_request.status != NearbyPaymentRequest.Status.OPEN:
        return Response({
            'code': 'nearby_request_unavailable',
            'error': 'This nearby payment is no longer available.',
        }, status=status.HTTP_409_CONFLICT)
    if payment_request.receiver_id == request.user.id:
        return Response({'code': 'self_payment', 'error': 'You cannot pay yourself.'}, status=400)

    from wallet.views import step_up_required, user_has_approved_kyc

    if step_up_required(request, OtpChallenge.Purpose.TRANSFER):
        return Response({
            'code': 'otp_required',
            'purpose': OtpChallenge.Purpose.TRANSFER,
            'error': 'Fresh device verification is required before making this payment.',
        }, status=403)
    if not user_has_approved_kyc(request.user):
        return Response({
            'code': 'kyc_required',
            'error': 'KYC verification is required before sending money.',
        }, status=403)
    if not request.user.transaction_pin:
        return Response({
            'code': 'transaction_pin_required',
            'error': 'Set a transaction PIN before making this payment.',
        }, status=400)

    pin = serializer.validated_data['pin']
    if not check_password(pin, request.user.transaction_pin):
        if request.user.transaction_pin == pin:
            request.user.transaction_pin = make_password(pin)
            request.user.save(update_fields=['transaction_pin'])
        else:
            return Response({'code': 'incorrect_pin', 'error': 'Incorrect transaction PIN.'}, status=400)

    now = timezone.now()
    if payment_request.expires_at <= now:
        _expire_if_needed(payment_request, now)
        return Response({
            'code': 'nearby_request_unavailable',
            'error': 'This nearby payment has expired.',
        }, status=status.HTTP_409_CONFLICT)

    try:
        with transaction.atomic():
            transaction_obj = execute_p2p_transfer(
                sender=request.user,
                recipient=payment_request.receiver,
                amount=payment_request.amount,
                currency=payment_request.currency,
                note=payment_request.note,
                idempotency_key=(
                    f'nearby-{payment_request.id}-{idempotency_hash}'
                ),
            )
    except TransferExecutionError as error:
        return Response(error.detail, status=error.status_code)

    payment_request.payer = request.user
    payment_request.status = NearbyPaymentRequest.Status.PAID
    payment_request.paid_at = now
    payment_request.resulting_transaction = transaction_obj
    payment_request.idempotency_hash = idempotency_hash
    payment_request.save(update_fields=[
        'payer', 'status', 'paid_at', 'resulting_transaction', 'idempotency_hash',
    ])
    AuditLog.objects.create(
        user=request.user,
        action='nearby_payment_paid',
        metadata={
            'request_id': str(payment_request.id),
            'transaction_id': str(transaction_obj.id),
            'receiver_id': payment_request.receiver_id,
            'amount': str(payment_request.amount),
            'currency': payment_request.currency,
        },
    )
    payment_request.payer = request.user
    payment_request.resulting_transaction = transaction_obj
    return Response(_request_details(payment_request))


@extend_schema(
    request=None,
    responses={200: NearbyPaymentResponseSerializer, 404: dict, 409: dict},
    tags=['Nearby Payments'],
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def cancel_nearby_payment(request, request_id):
    disabled_response = _feature_disabled_response()
    if disabled_response:
        return disabled_response
    payment_request = NearbyPaymentRequest.objects.select_for_update().filter(
        pk=request_id,
        receiver=request.user,
    ).first()
    if not payment_request:
        return Response({'error': 'Nearby payment request not found.'}, status=404)

    _expire_if_needed(payment_request)
    if payment_request.status == NearbyPaymentRequest.Status.OPEN:
        payment_request.status = NearbyPaymentRequest.Status.CANCELLED
        payment_request.cancelled_at = timezone.now()
        payment_request.save(update_fields=['status', 'cancelled_at'])
        AuditLog.objects.create(
            user=request.user,
            action='nearby_payment_cancelled',
            metadata={'request_id': str(payment_request.id)},
        )
    elif payment_request.status == NearbyPaymentRequest.Status.PAID:
        return Response({
            'code': 'already_paid',
            'error': 'A completed nearby payment cannot be cancelled.',
        }, status=status.HTTP_409_CONFLICT)
    return Response(_request_details(payment_request))
