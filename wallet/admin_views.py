import logging
import json
import uuid
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.db.models import Q, Count, Avg
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter

from django_celery_beat.models import PeriodicTask
from wallet.models import (
    User, Wallet, WalletStatus, SupportTicket, SupportTicketMessage,
    SupportTicketStatus, SupportTicketPriority, SupportTicketCategory,
    UserKYCSubmission, KYCTier, MobileMoneyTransaction, WebhookDelivery,
    Settlement, TransferFeeRule, FeeWaiver, ExchangeRate, AuditLog, Transaction
)
from wallet.admin_serializers import (
    SupportTicketSerializer, SupportTicketCreateSerializer,
    SupportTicketUpdateSerializer, SupportTicketMessageSerializer,
    SupportTicketMessageCreateSerializer, PeriodicTaskAdminSerializer,
    UserKYCSubmissionAdminSerializer, UserKYCReviewSerializer,
    MobileMoneyAdminTransactionSerializer, FailedWebhookDeliverySerializer,
    SettlementAdminSerializer, TransferFeeRuleAdminSerializer,
    FeeWaiverAdminSerializer, ExchangeRateAdminSerializer
)
from wallet.serializers import UserSerializer
from wallet.services.limits import apply_usage_based_limits
from wallet.tasks import deliver_webhook_task, process_mobile_money_webhook, refresh_exchange_rates_task

logger = logging.getLogger(__name__)


# ============================================================================
# 1. TASK & CRONJOB OPERATIONS VIEWS
# ============================================================================

@extend_schema(
    responses={200: PeriodicTaskAdminSerializer(many=True)},
    tags=['Admin - Operations']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_periodic_tasks_list(request):
    """List all registered Celery Beat periodic tasks."""
    tasks = PeriodicTask.objects.select_related('interval', 'crontab').order_by('name')
    serializer = PeriodicTaskAdminSerializer(tasks, many=True)
    return Response({'tasks': serializer.data}, status=status.HTTP_200_OK)


@extend_schema(
    responses={200: dict, 404: dict},
    tags=['Admin - Operations']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_periodic_task_toggle(request, task_id):
    """Enable or disable a Celery Beat periodic cron task schedule."""
    try:
        periodic_task = PeriodicTask.objects.get(id=task_id)
        periodic_task.enabled = not periodic_task.enabled
        periodic_task.save(update_fields=['enabled'])

        AuditLog.objects.create(
            user=request.user,
            action='admin_toggle_periodic_task',
            metadata={'task_name': periodic_task.name, 'enabled': periodic_task.enabled}
        )

        return Response({
            'id': periodic_task.id,
            'name': periodic_task.name,
            'enabled': periodic_task.enabled,
            'message': f"Task schedule {'enabled' if periodic_task.enabled else 'disabled'}."
        }, status=status.HTTP_200_OK)
    except PeriodicTask.DoesNotExist:
        return Response({'error': 'Periodic task not found'}, status=status.HTTP_404_NOT_FOUND)


@extend_schema(
    responses={202: dict, 400: dict, 404: dict},
    tags=['Admin - Operations']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_periodic_task_run_now(request, task_id):
    """Trigger immediate asynchronous execution of a periodic task."""
    try:
        periodic_task = PeriodicTask.objects.get(id=task_id)
        task_name = periodic_task.task

        # Import task dynamically from registry
        from celery import current_app
        celery_task = current_app.tasks.get(task_name)

        if not celery_task:
            return Response({'error': f'Task {task_name} not registered in Celery worker'}, status=status.HTTP_400_BAD_REQUEST)

        async_res = celery_task.delay()

        AuditLog.objects.create(
            user=request.user,
            action='admin_run_periodic_task_now',
            metadata={'task_name': periodic_task.name, 'celery_id': async_res.id}
        )

        return Response({
            'status': 'queued',
            'task_name': periodic_task.name,
            'celery_task_id': async_res.id,
            'message': 'Task execution queued on Celery worker.'
        }, status=status.HTTP_202_ACCEPTED)
    except PeriodicTask.DoesNotExist:
        return Response({'error': 'Periodic task not found'}, status=status.HTTP_404_NOT_FOUND)


# ============================================================================
# 2. SUPPORT TICKET MANAGEMENT VIEWS
# ============================================================================

@extend_schema(
    responses={200: SupportTicketSerializer(many=True)},
    tags=['Admin - Support']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_support_tickets_list(request):
    """Search and filter support tickets."""
    status_param = request.query_params.get('status', '').strip()
    priority_param = request.query_params.get('priority', '').strip()
    category_param = request.query_params.get('category', '').strip()
    assigned_to_param = request.query_params.get('assigned_to', '').strip()
    query = request.query_params.get('query', '').strip()

    tickets = SupportTicket.objects.select_related('user', 'assigned_to', 'related_transaction').prefetch_related('messages')

    if status_param:
        tickets = tickets.filter(status=status_param)
    if priority_param:
        tickets = tickets.filter(priority=priority_param)
    if category_param:
        tickets = tickets.filter(category=category_param)
    if assigned_to_param:
        if assigned_to_param == 'unassigned':
            tickets = tickets.filter(assigned_to__isnull=True)
        elif assigned_to_param == 'me':
            tickets = tickets.filter(assigned_to=request.user)
        else:
            tickets = tickets.filter(assigned_to_id=assigned_to_param)
    if query:
        tickets = tickets.filter(
            Q(ticket_number__icontains=query) |
            Q(subject__icontains=query) |
            Q(user__handle__icontains=query) |
            Q(user__email__icontains=query)
        )

    serializer = SupportTicketSerializer(tickets, many=True)
    return Response({'tickets': serializer.data}, status=status.HTTP_200_OK)


@extend_schema(
    request=SupportTicketCreateSerializer,
    responses={201: SupportTicketSerializer, 400: dict},
    tags=['Admin - Support']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_support_ticket_create(request):
    """Create a support ticket on behalf of a user."""
    serializer = SupportTicketCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user_id = serializer.validated_data['user_id']
    try:
        target_user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({'error': 'Target user not found'}, status=status.HTTP_404_NOT_FOUND)

    related_tx = None
    tx_id = serializer.validated_data.get('related_transaction_id')
    if tx_id:
        try:
            related_tx = Transaction.objects.get(id=tx_id)
        except Transaction.DoesNotExist:
            pass

    ticket_num = f"TKT-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    with transaction.atomic():
        ticket = SupportTicket.objects.create(
            ticket_number=ticket_num,
            user=target_user,
            assigned_to=request.user,
            subject=serializer.validated_data['subject'],
            category=serializer.validated_data['category'],
            priority=serializer.validated_data['priority'],
            status=SupportTicketStatus.OPEN,
            related_transaction=related_tx
        )
        SupportTicketMessage.objects.create(
            ticket=ticket,
            sender=request.user,
            is_internal_note=False,
            message=serializer.validated_data['initial_message']
        )

    AuditLog.objects.create(
        user=request.user,
        action='admin_create_support_ticket',
        metadata={'ticket_number': ticket_num, 'target_user_id': target_user.id}
    )

    out_serializer = SupportTicketSerializer(ticket)
    return Response(out_serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(
    responses={200: SupportTicketSerializer, 404: dict},
    tags=['Admin - Support']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_support_ticket_detail(request, ticket_id):
    """Get full support ticket details and message thread."""
    try:
        ticket = SupportTicket.objects.select_related('user', 'assigned_to', 'related_transaction').prefetch_related('messages__sender').get(id=ticket_id)
        serializer = SupportTicketSerializer(ticket)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except SupportTicket.DoesNotExist:
        return Response({'error': 'Support ticket not found'}, status=status.HTTP_404_NOT_FOUND)


@extend_schema(
    request=SupportTicketUpdateSerializer,
    responses={200: SupportTicketSerializer, 400: dict, 404: dict},
    tags=['Admin - Support']
)
@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def admin_support_ticket_update(request, ticket_id):
    """Update ticket category, priority, status, or assigned staff agent."""
    try:
        ticket = SupportTicket.objects.get(id=ticket_id)
    except SupportTicket.DoesNotExist:
        return Response({'error': 'Support ticket not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = SupportTicketUpdateSerializer(ticket, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    ticket = serializer.save()
    out_serializer = SupportTicketSerializer(ticket)
    return Response(out_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    request=SupportTicketMessageCreateSerializer,
    responses={201: SupportTicketMessageSerializer, 400: dict, 404: dict},
    tags=['Admin - Support']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_support_ticket_add_message(request, ticket_id):
    """Send a reply to the user or post an internal staff note."""
    try:
        ticket = SupportTicket.objects.get(id=ticket_id)
    except SupportTicket.DoesNotExist:
        return Response({'error': 'Support ticket not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = SupportTicketMessageCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    msg = SupportTicketMessage.objects.create(
        ticket=ticket,
        sender=request.user,
        is_internal_note=serializer.validated_data['is_internal_note'],
        message=serializer.validated_data['message'],
        attachment_url=serializer.validated_data.get('attachment_url', '')
    )

    if not serializer.validated_data['is_internal_note'] and ticket.status == SupportTicketStatus.WAITING_ON_USER:
        ticket.status = SupportTicketStatus.IN_PROGRESS
        ticket.save(update_fields=['status', 'updated_at'])

    return Response(SupportTicketMessageSerializer(msg).data, status=status.HTTP_201_CREATED)


@extend_schema(
    responses={200: dict},
    tags=['Admin - Support']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_support_metrics(request):
    """Support operations overview metrics."""
    total_tickets = SupportTicket.objects.count()
    open_tickets = SupportTicket.objects.filter(status=SupportTicketStatus.OPEN).count()
    in_progress = SupportTicket.objects.filter(status=SupportTicketStatus.IN_PROGRESS).count()
    unassigned = SupportTicket.objects.filter(assigned_to__isnull=True).exclude(status__in=[SupportTicketStatus.RESOLVED, SupportTicketStatus.CLOSED]).count()

    category_counts = SupportTicket.objects.values('category').annotate(count=Count('id'))

    return Response({
        'total_tickets': total_tickets,
        'open_tickets': open_tickets,
        'in_progress': in_progress,
        'unassigned': unassigned,
        'by_category': category_counts
    }, status=status.HTTP_200_OK)


@extend_schema(
    responses={200: dict, 400: dict, 404: dict},
    tags=['Admin - Support']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_user_freeze_wallet(request, user_id):
    """Quick action to freeze or unfreeze a user's wallet with support notes."""
    reason = request.data.get('reason', '').strip()
    if not reason:
        return Response({'error': 'Reason is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.select_related('wallet').get(id=user_id)
        wallet = user.wallet
        new_status = WalletStatus.FROZEN if wallet.status == WalletStatus.ACTIVE else WalletStatus.ACTIVE
        wallet.status = new_status
        wallet.save(update_fields=['status'])

        AuditLog.objects.create(
            user=request.user,
            action='admin_freeze_unfreeze_wallet',
            metadata={'target_user_id': user.id, 'new_status': new_status, 'reason': reason}
        )

        return Response({
            'user_id': user.id,
            'wallet_status': wallet.status,
            'message': f"Wallet status updated to {wallet.status}."
        }, status=status.HTTP_200_OK)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)


# ============================================================================
# 3. KYC & COMPLIANCE REVIEW VIEWS
# ============================================================================

@extend_schema(
    responses={200: UserKYCSubmissionAdminSerializer(many=True)},
    tags=['Admin - KYC']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_user_kyc_list(request):
    """List user identity document submissions filtered by status."""
    status_filter = request.query_params.get('status', 'pending').strip()
    submissions = UserKYCSubmission.objects.select_related('user', 'reviewed_by').all()

    if status_filter:
        submissions = submissions.filter(status=status_filter)

    serializer = UserKYCSubmissionAdminSerializer(submissions, many=True)
    return Response({'submissions': serializer.data}, status=status.HTTP_200_OK)


@extend_schema(
    request=UserKYCReviewSerializer,
    responses={200: UserKYCSubmissionAdminSerializer, 400: dict, 404: dict},
    tags=['Admin - KYC']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_user_kyc_review(request, submission_id):
    """Approve or reject user identity submission and update KYC tier."""
    serializer = UserKYCReviewSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    action = serializer.validated_data['action']
    target_tier = serializer.validated_data.get('target_kyc_tier', 'tier_1')
    reviewer_notes = serializer.validated_data.get('reviewer_notes', '')

    try:
        with transaction.atomic():
            sub = UserKYCSubmission.objects.select_for_update().select_related('user').get(id=submission_id)
            user = sub.user

            if action == 'approve':
                sub.status = UserKYCSubmission.Status.APPROVED
                sub.reviewed_by = request.user
                sub.reviewer_notes = reviewer_notes
                sub.save()

                user.kyc_tier = target_tier
                user.save(update_fields=['kyc_tier'])
                apply_usage_based_limits(user)
            else:
                sub.status = UserKYCSubmission.Status.REJECTED
                sub.reviewed_by = request.user
                sub.reviewer_notes = reviewer_notes
                sub.save()

            AuditLog.objects.create(
                user=request.user,
                action='admin_review_user_kyc',
                metadata={'submission_id': sub.id, 'action': action, 'target_tier': target_tier}
            )

            out_serializer = UserKYCSubmissionAdminSerializer(sub)
            return Response(out_serializer.data, status=status.HTTP_200_OK)

    except UserKYCSubmission.DoesNotExist:
        return Response({'error': 'KYC submission not found'}, status=status.HTTP_404_NOT_FOUND)


# ============================================================================
# 4. MOBILE MONEY & WEBHOOK OPERATIONS VIEWS
# ============================================================================

@extend_schema(
    responses={200: MobileMoneyAdminTransactionSerializer(many=True)},
    tags=['Admin - Mobile Money']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_mobile_money_list(request):
    """Filter mobile money top-ups/withdrawals."""
    status_filter = request.query_params.get('status', '').strip()
    query = request.query_params.get('query', '').strip()

    txs = MobileMoneyTransaction.objects.select_related('user', 'linked_provider').order_by('-created_at')

    if status_filter:
        txs = txs.filter(status=status_filter)
    if query:
        txs = txs.filter(
            Q(provider_transaction_id__icontains=query) |
            Q(user__handle__icontains=query) |
            Q(user__phone_number__icontains=query)
        )

    serializer = MobileMoneyAdminTransactionSerializer(txs[:100], many=True)
    return Response({'transactions': serializer.data}, status=status.HTTP_200_OK)


@extend_schema(
    responses={202: dict, 404: dict},
    tags=['Admin - Mobile Money']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_mobile_money_retry(request, transaction_id):
    """Retry status poll or webhook processing for a stuck mobile money transaction."""
    try:
        tx = MobileMoneyTransaction.objects.get(id=transaction_id)
        if not tx.provider_transaction_id:
            return Response({'error': 'Transaction has no provider_transaction_id'}, status=status.HTTP_400_BAD_REQUEST)

        async_res = process_mobile_money_webhook.delay(
            provider_transaction_id=tx.provider_transaction_id,
            status=tx.status
        )

        return Response({
            'status': 'queued',
            'celery_task_id': async_res.id,
            'message': 'Mobile money retry task queued.'
        }, status=status.HTTP_202_ACCEPTED)
    except MobileMoneyTransaction.DoesNotExist:
        return Response({'error': 'Mobile money transaction not found'}, status=status.HTTP_404_NOT_FOUND)


@extend_schema(
    responses={200: FailedWebhookDeliverySerializer(many=True)},
    tags=['Admin - Webhooks']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_failed_webhooks_list(request):
    """List failed merchant webhook delivery logs."""
    deliveries = WebhookDelivery.objects.select_related('merchant', 'payment_intent').filter(
        status=WebhookDelivery.Status.FAILED
    ).order_by('-created_at')
    serializer = FailedWebhookDeliverySerializer(deliveries[:100], many=True)
    return Response({'failed_webhooks': serializer.data}, status=status.HTTP_200_OK)


@extend_schema(
    responses={202: dict, 404: dict},
    tags=['Admin - Webhooks']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_webhook_retry(request, delivery_id):
    """Manually retry delivering a failed merchant webhook."""
    try:
        delivery = WebhookDelivery.objects.get(id=delivery_id)
        async_res = deliver_webhook_task.delay(delivery.id)
        return Response({
            'delivery_id': delivery.id,
            'status': 'queued',
            'celery_task_id': async_res.id,
            'message': 'Webhook redelivery task queued.'
        }, status=status.HTTP_202_ACCEPTED)
    except WebhookDelivery.DoesNotExist:
        return Response({'error': 'Webhook delivery log not found'}, status=status.HTTP_404_NOT_FOUND)


# ============================================================================
# 5. FINANCIAL FEES & FX CONTROL VIEWS
# ============================================================================

@extend_schema(
    responses={200: TransferFeeRuleAdminSerializer(many=True)},
    tags=['Admin - Finance']
)
@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def admin_fee_rules_list_create(request):
    """List or create transfer fee rules."""
    if request.method == 'GET':
        rules = TransferFeeRule.objects.all().order_by('min_amount')
        return Response({'rules': TransferFeeRuleAdminSerializer(rules, many=True).data}, status=status.HTTP_200_OK)

    serializer = TransferFeeRuleAdminSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    rule = serializer.save()
    return Response(TransferFeeRuleAdminSerializer(rule).data, status=status.HTTP_201_CREATED)


@extend_schema(
    request=FeeWaiverAdminSerializer,
    responses={201: FeeWaiverAdminSerializer, 400: dict},
    tags=['Admin - Finance']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_fee_waiver_create(request):
    """Grant custom temporary fee waiver to a user or merchant."""
    serializer = FeeWaiverAdminSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    waiver = serializer.save()
    return Response(FeeWaiverAdminSerializer(waiver).data, status=status.HTTP_201_CREATED)


@extend_schema(
    responses={200: ExchangeRateAdminSerializer(many=True)},
    tags=['Admin - Finance']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_exchange_rates_list(request):
    """List exchange rates."""
    rates = ExchangeRate.objects.all().order_by('-valid_from')[:50]
    return Response({'exchange_rates': ExchangeRateAdminSerializer(rates, many=True).data}, status=status.HTTP_200_OK)


@extend_schema(
    responses={202: dict},
    tags=['Admin - Finance']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_exchange_rates_refresh(request):
    """Trigger instant exchange rate refresh task."""
    async_res = refresh_exchange_rates_task.delay()
    return Response({
        'status': 'queued',
        'celery_task_id': async_res.id,
        'message': 'Exchange rate refresh task queued.'
    }, status=status.HTTP_202_ACCEPTED)


# ============================================================================
# 6. TEAM RBAC VIEWS
# ============================================================================

@extend_schema(
    responses={200: UserSerializer(many=True)},
    tags=['Admin - Team']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_team_list(request):
    """List all administrative staff users."""
    staff_users = User.objects.filter(is_staff=True).order_by('-date_joined')
    return Response({'team_members': UserSerializer(staff_users, many=True).data}, status=status.HTTP_200_OK)
