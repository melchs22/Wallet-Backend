import csv
import logging
from datetime import datetime, timedelta

from django.conf import settings
from rest_framework import exceptions, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework.response import Response

from wallet.merchant_authentication import MerchantApiKeyAuthentication, MerchantApiKeyRateThrottle
from wallet.authentication import SignedTokenAuthentication
from wallet.merchant_serializers import (
    CheckoutConfirmSerializer,
    FeePreviewQuerySerializer,
    PaymentIntentCreateSerializer,
    PaymentIntentSerializer,
    MerchantDisputeCreateSerializer, MerchantDisputeSerializer,
    MerchantRefundCreateSerializer, MerchantSettlementSerializer,
    MerchantTransactionSerializer,
)
from wallet.models import (
    Dispute, DisputeStatus, Merchant, MerchantTeamMember, MerchantTeamRole,
    PaymentIntent, PaymentIntentStatus,
    Settlement, Transaction, WebhookDelivery, WebhookDeliveryStatus,
)
from wallet.services.limits import merchant_limit_snapshot
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
    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        raise exceptions.NotAuthenticated('A valid merchant API key is required.')
    merchant = getattr(user, 'merchant_account', None)
    if merchant is None:
        raise exceptions.AuthenticationFailed('The API credential is not linked to a merchant account.')
    if not getattr(request, 'merchant_api_mode', None):
        raise exceptions.AuthenticationFailed('Merchant API authentication is required.')
    return merchant


def _team_context(request):
    if not request.user.is_authenticated:
        raise exceptions.NotAuthenticated()
    merchant = getattr(request.user, 'merchant_account', None)
    if merchant and request.user == merchant.user:
        return merchant, MerchantTeamRole.OWNER
    member = MerchantTeamMember.objects.filter(
        user=request.user, is_active=True,
    ).select_related('merchant').first()
    if not member:
        raise exceptions.PermissionDenied('You are not a member of this merchant team.')
    return member.merchant, member.role


def _team_can(role, action):
    return role == MerchantTeamRole.OWNER or (
        role == MerchantTeamRole.ADMIN and action in {'invite', 'update', 'remove', 'list'}
    ) or (role in {MerchantTeamRole.FINANCE, MerchantTeamRole.SUPPORT, MerchantTeamRole.DEVELOPER} and action == 'list')


@api_view(['GET'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_limits(request):
    merchant = _merchant_from_request(request)
    currency = (request.query_params.get('currency') or 'GNF').upper()
    snapshot = merchant_limit_snapshot(merchant, currency)
    return Response({key: str(value) if hasattr(value, 'quantize') else value for key, value in snapshot.items()})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def merchant_team(request):
    merchant, role = _team_context(request)
    if request.method == 'GET':
        if not _team_can(role, 'list'):
            raise exceptions.PermissionDenied()
        members = MerchantTeamMember.objects.filter(merchant=merchant).select_related('user', 'invited_by')
        result = [{
            'id': None, 'email': merchant.user.email, 'user_id': merchant.user_id,
            'role': MerchantTeamRole.OWNER, 'is_active': True,
            'invited_at': merchant.created_at, 'accepted_at': merchant.created_at,
        }]
        result.extend({
            'id': member.id, 'email': member.email, 'user_id': member.user_id,
            'role': member.role, 'is_active': member.is_active,
            'invited_at': member.invited_at, 'accepted_at': member.accepted_at,
        } for member in members)
        return Response(result)
    if not _team_can(role, 'invite'):
        raise exceptions.PermissionDenied()
    email = (request.data.get('email') or '').strip().lower()
    member_role = request.data.get('role', MerchantTeamRole.SUPPORT)
    if not email or '@' not in email:
        return Response({'error': 'A valid email is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if member_role == MerchantTeamRole.OWNER or member_role not in MerchantTeamRole.values:
        return Response({'error': 'Invalid team role.'}, status=status.HTTP_400_BAD_REQUEST)
    user = __import__('wallet.models', fromlist=['User']).User.objects.filter(email__iexact=email).first()
    member, created = MerchantTeamMember.objects.update_or_create(
        merchant=merchant, email=email,
        defaults={'user': user, 'role': member_role, 'is_active': True, 'invited_by': request.user},
    )
    return Response({'id': member.id, 'email': member.email, 'user_id': member.user_id, 'role': member.role,
                     'is_active': member.is_active}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def merchant_team_member(request, member_id):
    merchant, role = _team_context(request)
    try:
        member = MerchantTeamMember.objects.get(id=member_id, merchant=merchant)
    except MerchantTeamMember.DoesNotExist:
        return Response({'error': 'Team member not found.'}, status=status.HTTP_404_NOT_FOUND)
    action = 'remove' if request.method == 'DELETE' else 'update'
    if not _team_can(role, action):
        raise exceptions.PermissionDenied()
    if request.method == 'DELETE':
        if member.role == MerchantTeamRole.OWNER:
            return Response({'error': 'The owner cannot be removed.'}, status=status.HTTP_400_BAD_REQUEST)
        member.is_active = False
        member.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)
    new_role = request.data.get('role')
    if new_role not in MerchantTeamRole.values or new_role == MerchantTeamRole.OWNER:
        return Response({'error': 'Invalid team role.'}, status=status.HTTP_400_BAD_REQUEST)
    member.role = new_role
    member.save(update_fields=['role'])
    return Response({'id': member.id, 'email': member.email, 'user_id': member.user_id,
                     'role': member.role, 'is_active': member.is_active})


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
    idempotency_key = (request.headers.get('Idempotency-Key') or '').strip()
    if len(idempotency_key) > 255:
        return Response({'code': 'invalid_idempotency_key', 'message': 'Idempotency-Key must be 255 characters or fewer.'}, status=status.HTTP_400_BAD_REQUEST)
    existing = PaymentIntent.objects.filter(
        merchant=merchant,
        mode=mode,
        idempotency_key=idempotency_key,
    ).first() if idempotency_key else None

    try:
        intent = create_payment_intent(
            merchant,
            amount=serializer.validated_data['amount'],
            currency=serializer.validated_data['currency'],
            external_reference=serializer.validated_data.get('external_reference', ''),
            description=serializer.validated_data.get('description', ''),
            mode=mode,
            return_url=serializer.validated_data.get('return_url', ''),
            idempotency_key=idempotency_key,
        )
        data = PaymentIntentSerializer(intent).data
        return Response(data, status=status.HTTP_200_OK if existing else status.HTTP_201_CREATED)
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


def _merchant_transactions(merchant, mode):
    return Transaction.objects.filter(
        payment_intents__merchant=merchant,
        payment_intents__mode=mode,
    ).distinct().select_related('sender', 'recipient').prefetch_related('payment_intents')


def _session_merchant_mode(request):
    mode = request.query_params.get('mode', 'sandbox').lower()
    if mode not in ('sandbox', 'live'):
        raise ValueError('Invalid merchant environment')
    if mode == 'live' and request.user.merchant_account.status != 'active':
        raise PermissionError('Live mode is available after merchant approval.')
    return mode


@api_view(['GET'])
@authentication_classes([SignedTokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def merchant_session_transactions(request):
    """Dashboard-only transaction access using the merchant user session."""
    merchant = getattr(request.user, 'merchant_account', None)
    if merchant is None:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)
    try:
        mode = _session_merchant_mode(request)
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except PermissionError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_403_FORBIDDEN)
    queryset = _merchant_transactions(merchant, mode).order_by('-created_at')
    limit = min(max(int(request.query_params.get('limit', 50)), 1), 100)
    return Response(MerchantTransactionSerializer(queryset[:limit], many=True).data)


@api_view(['GET'])
@authentication_classes([SignedTokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def merchant_session_transaction_detail(request, transaction_id):
    merchant = getattr(request.user, 'merchant_account', None)
    if merchant is None:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)
    try:
        mode = _session_merchant_mode(request)
        transaction_obj = _merchant_transactions(merchant, mode).get(pk=transaction_id)
    except (ValueError, PermissionError) as exc:
        return Response({'error': str(exc)}, status=status.HTTP_403_FORBIDDEN)
    except (Transaction.DoesNotExist, ValueError):
        return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)
    return Response(MerchantTransactionSerializer(transaction_obj).data)


@api_view(['GET'])
@authentication_classes([SignedTokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def merchant_session_limits(request):
    """Dashboard-only limits using the merchant user session."""
    merchant = getattr(request.user, 'merchant_account', None)
    if merchant is None:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)
    currency = (request.query_params.get('currency') or merchant.wallet.currency or 'GNF').upper()
    snapshot = merchant_limit_snapshot(merchant, currency)
    return Response({
        key: str(value) if hasattr(value, 'quantize') else value
        for key, value in snapshot.items()
    })


@api_view(['GET'])
@authentication_classes([SignedTokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def merchant_session_settlements(request):
    merchant = getattr(request.user, 'merchant_account', None)
    if merchant is None:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)
    settlements = merchant.settlements.order_by('-created_at')
    requested_status = request.query_params.get('status')
    if requested_status and requested_status != 'all':
        settlements = settlements.filter(status=requested_status)
    return Response(MerchantSettlementSerializer(settlements[:100], many=True).data)


@api_view(['GET'])
@authentication_classes([SignedTokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def merchant_session_disputes(request):
    merchant = getattr(request.user, 'merchant_account', None)
    if merchant is None:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)
    try:
        mode = _session_merchant_mode(request)
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except PermissionError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_403_FORBIDDEN)
    disputes = _merchant_dispute_queryset(merchant, mode)
    requested_status = request.query_params.get('status')
    if requested_status and requested_status != 'all':
        disputes = disputes.filter(status=requested_status)
    return Response(MerchantDisputeSerializer(disputes[:100], many=True).data)


@api_view(['GET'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_transactions(request):
    """List payment transactions belonging to this merchant."""
    merchant = _merchant_from_request(request)
    queryset = _merchant_transactions(merchant, request.merchant_api_mode)
    for field in ('status', 'type', 'currency'):
        value = request.query_params.get(field)
        if value:
            queryset = queryset.filter(**{field: value.lower() if field != 'currency' else value.upper()})
    reference = request.query_params.get('external_reference')
    if reference:
        queryset = queryset.filter(payment_intents__external_reference=reference)
    for name, lookup in (('from', 'created_at__gte'), ('to', 'created_at__lt')):
        value = request.query_params.get(name)
        if value:
            try:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed)
                if name == 'to' and len(value) == 10:
                    parsed = parsed.replace(hour=0, minute=0, second=0) + timedelta(days=1)
                queryset = queryset.filter(**{lookup: parsed})
            except ValueError:
                return Response({'error': f'Invalid {name} date'}, status=status.HTTP_400_BAD_REQUEST)
    queryset = queryset.order_by('-created_at')
    if request.query_params.get('format') == 'csv':
        response = StreamingHttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="merchant-transactions.csv"'
        writer = csv.writer(response)
        writer.writerow(['id', 'type', 'status', 'amount', 'fee_amount', 'currency', 'created_at'])
        for row in queryset[:5000]:
            writer.writerow([row.id, row.type, row.status, row.amount, row.fee_amount, row.currency, row.created_at.isoformat()])
        return response
    limit = min(max(int(request.query_params.get('limit', 50)), 1), 100)
    return Response(MerchantTransactionSerializer(queryset[:limit], many=True).data)


@api_view(['GET'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_transaction_detail(request, transaction_id):
    merchant = _merchant_from_request(request)
    try:
        transaction_obj = _merchant_transactions(merchant, request.merchant_api_mode).get(pk=transaction_id)
    except (Transaction.DoesNotExist, ValueError):
        return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)
    return Response(MerchantTransactionSerializer(transaction_obj).data)


@api_view(['GET'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_settlements(request):
    merchant = _merchant_from_request(request)
    settlements = Settlement.objects.filter(merchant=merchant).order_by('-created_at')
    if request.query_params.get('status'):
        settlements = settlements.filter(status=request.query_params['status'])
    return Response(MerchantSettlementSerializer(settlements[:100], many=True).data)


@api_view(['GET', 'PATCH'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_settings(request):
    merchant = _merchant_from_request(request)
    if request.method == 'PATCH':
        allowed = {'business_name', 'business_email', 'website_url', 'description',
                   'logo_url', 'contact_email', 'contact_phone', 'address', 'tax_id',
                   'webhook_url', 'webhook_events'}
        unknown = set(request.data) - allowed
        if unknown:
            return Response({'error': f'Unsupported settings: {", ".join(sorted(unknown))}'}, status=status.HTTP_400_BAD_REQUEST)
        for field in allowed & set(request.data):
            setattr(merchant, field, request.data[field])
        merchant.save(update_fields=list(allowed & set(request.data)) + ['updated_at'])
    return Response({
        'business_name': merchant.business_name, 'business_email': merchant.business_email,
        'website_url': merchant.website_url, 'description': merchant.description,
        'logo_url': merchant.logo_url, 'contact_email': merchant.contact_email,
        'contact_phone': merchant.contact_phone, 'address': merchant.address,
        'tax_id': merchant.tax_id, 'webhook_url': merchant.webhook_url,
        'webhook_events': merchant.webhook_events,
    })


def _merchant_dispute_queryset(merchant, mode):
    return Dispute.objects.filter(
        transaction__payment_intents__merchant=merchant,
        transaction__payment_intents__mode=mode,
    ).distinct().select_related('transaction')


@api_view(['GET', 'POST'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_disputes(request):
    merchant = _merchant_from_request(request)
    if request.method == 'GET':
        disputes = _merchant_dispute_queryset(merchant, request.merchant_api_mode)
        if request.query_params.get('status'):
            disputes = disputes.filter(status=request.query_params['status'])
        return Response(MerchantDisputeSerializer(disputes[:100], many=True).data)
    serializer = MerchantDisputeCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    try:
        transaction_obj = _merchant_transactions(merchant, request.merchant_api_mode).get(
            pk=serializer.validated_data['transaction_id']
        )
    except (Transaction.DoesNotExist, ValueError):
        return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)
    dispute = Dispute.objects.create(
        transaction=transaction_obj, opened_by=merchant.user,
        reason=serializer.validated_data['reason'],
        evidence_notes=serializer.validated_data['evidence_notes'],
    )
    return Response(MerchantDisputeSerializer(dispute).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_dispute_detail(request, dispute_id):
    try:
        dispute = _merchant_dispute_queryset(_merchant_from_request(request), request.merchant_api_mode).get(pk=dispute_id)
    except Dispute.DoesNotExist:
        return Response({'error': 'Dispute not found'}, status=status.HTTP_404_NOT_FOUND)
    return Response(MerchantDisputeSerializer(dispute).data)


@api_view(['POST'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_refund(request):
    """Create a refund request using the existing dispute workflow."""
    serializer = MerchantRefundCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    merchant = _merchant_from_request(request)
    try:
        transaction_obj = _merchant_transactions(merchant, request.merchant_api_mode).get(pk=serializer.validated_data['transaction_id'])
    except (Transaction.DoesNotExist, ValueError):
        return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)
    dispute = Dispute.objects.create(
        transaction=transaction_obj, opened_by=merchant.user,
        reason=f"Refund requested: {serializer.validated_data['reason']}".strip(),
        evidence_notes=serializer.validated_data['evidence_notes'],
    )
    return Response({'refund_id': dispute.id, 'status': dispute.status, 'transaction_id': str(transaction_obj.id)}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([AllowAny])
@throttle_classes([MerchantApiKeyRateThrottle])
def merchant_webhook_retry(request, delivery_id):
    merchant = _merchant_from_request(request)
    try:
        delivery = WebhookDelivery.objects.get(pk=delivery_id, merchant=merchant)
    except WebhookDelivery.DoesNotExist:
        return Response({'error': 'Webhook delivery not found'}, status=status.HTTP_404_NOT_FOUND)
    if delivery.status == WebhookDeliveryStatus.DELIVERED:
        return Response({'error': 'Webhook has already been delivered'}, status=status.HTTP_409_CONFLICT)
    from wallet.tasks import deliver_webhook_task
    task = deliver_webhook_task.delay(delivery.id)
    return Response({'delivery_id': delivery.id, 'status': 'queued', 'celery_task_id': task.id}, status=status.HTTP_202_ACCEPTED)
