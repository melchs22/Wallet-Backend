"""Core CRUD APIs for the authenticated admin console.

Financial records remain auditable: transaction DELETE is intentionally rejected,
and transaction PATCH only permits operational metadata/status changes.
"""
from django.contrib.auth.hashers import make_password
from django.db import transaction as db_transaction
from django.db.models import Q
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.serializers import ModelSerializer, ValidationError

from wallet.models import AuditLog, LedgerDirection, LedgerEntry, Transaction, TransactionStatus, TransactionType, User, Wallet


class AdminUserCrudSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'email', 'username', 'handle', 'display_name', 'phone_number',
            'primary_phone_number', 'avatar_url', 'status', 'kyc_tier', 'is_staff',
            'is_agent', 'must_change_password', 'send_limit_per_tx', 'send_limit_daily',
            'limits_manually_set', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        password = self.initial_data.get('password')
        if not password:
            raise ValidationError({'password': 'This field is required when creating a user.'})
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class AdminWalletCrudSerializer(ModelSerializer):
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = ['id', 'user', 'currency', 'default_provider', 'status', 'is_sandbox', 'created_at', 'balance']
        read_only_fields = ['id', 'created_at', 'balance']

    def get_balance(self, obj):
        return str(obj.get_balance())


class AdminTransactionCrudSerializer(ModelSerializer):
    class Meta:
        model = Transaction
        fields = [
            'id', 'type', 'sender', 'recipient', 'amount', 'fee_amount', 'currency',
            'note', 'status', 'related_transaction', 'exchange_rate', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class AdminPeriodicTaskCrudSerializer(ModelSerializer):
    class Meta:
        model = PeriodicTask
        fields = ['id', 'name', 'task', 'enabled', 'description', 'last_run_at', 'total_run_count']
        read_only_fields = ['id', 'last_run_at', 'total_run_count']


def _audit(request, action, metadata):
    AuditLog.objects.create(user=request.user, action=action, metadata=metadata)


def _get_or_404(model, object_id):
    try:
        return model.objects.get(pk=object_id)
    except model.DoesNotExist:
        return None


def _write_admin_ledgers(record):
    if record.status != TransactionStatus.COMPLETED:
        return
    sender_wallet = Wallet.objects.get_or_create(user=record.sender, defaults={'currency': record.currency})[0] if record.sender_id else None
    recipient_wallet = Wallet.objects.get_or_create(user=record.recipient, defaults={'currency': record.currency})[0]
    if record.type == TransactionType.WITHDRAWAL:
        if sender_wallet:
            LedgerEntry.objects.create(wallet=sender_wallet, transaction=record, direction=LedgerDirection.DEBIT, amount=record.amount + record.fee_amount)
    elif record.type == TransactionType.TOPUP:
        LedgerEntry.objects.create(wallet=recipient_wallet, transaction=record, direction=LedgerDirection.CREDIT, amount=record.amount)
    else:
        if sender_wallet:
            LedgerEntry.objects.create(wallet=sender_wallet, transaction=record, direction=LedgerDirection.DEBIT, amount=record.amount)
            if record.fee_amount > 0:
                LedgerEntry.objects.create(wallet=sender_wallet, transaction=record, direction=LedgerDirection.DEBIT, amount=record.fee_amount)
        LedgerEntry.objects.create(wallet=recipient_wallet, transaction=record, direction=LedgerDirection.CREDIT, amount=record.amount)


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def admin_users_crud(request):
    if request.method == 'GET':
        query = request.query_params.get('q', '').strip()
        users = User.objects.order_by('-created_at')
        if query:
            users = users.filter(Q(email__icontains=query) | Q(handle__icontains=query) | Q(primary_phone_number__icontains=query))
        return Response(AdminUserCrudSerializer(users[:200], many=True).data)
    serializer = AdminUserCrudSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    Wallet.objects.get_or_create(user=user, defaults={'currency': request.data.get('currency', 'GNF')})
    _audit(request, 'admin_user_created', {'user_id': user.id})
    return Response(AdminUserCrudSerializer(user).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def admin_user_crud_detail(request, user_id):
    user = _get_or_404(User, user_id)
    if user is None:
        return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response(AdminUserCrudSerializer(user).data)
    if request.method == 'DELETE':
        if user == request.user:
            return Response({'error': 'You cannot delete your own admin account.'}, status=status.HTTP_400_BAD_REQUEST)
        user.status = 'closed'
        user.is_active = False
        user.save(update_fields=['status', 'is_active'])
        _audit(request, 'admin_user_closed', {'user_id': user.id})
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = AdminUserCrudSerializer(user, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    password = request.data.get('password')
    user = serializer.save()
    if password:
        user.password = make_password(password)
        user.save(update_fields=['password'])
    _audit(request, 'admin_user_updated', {'user_id': user.id, 'fields': list(serializer.validated_data)})
    return Response(AdminUserCrudSerializer(user).data)


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def admin_wallets_crud(request):
    if request.method == 'GET':
        wallets = Wallet.objects.select_related('user').order_by('-created_at')
        user_id = request.query_params.get('user_id')
        if user_id:
            wallets = wallets.filter(user_id=user_id)
        return Response(AdminWalletCrudSerializer(wallets[:200], many=True).data)
    serializer = AdminWalletCrudSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    wallet = serializer.save()
    _audit(request, 'admin_wallet_created', {'wallet_id': wallet.id, 'user_id': wallet.user_id})
    return Response(AdminWalletCrudSerializer(wallet).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def admin_wallet_crud_detail(request, wallet_id):
    wallet = _get_or_404(Wallet, wallet_id)
    if wallet is None:
        return Response({'error': 'Wallet not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response(AdminWalletCrudSerializer(wallet).data)
    if request.method == 'DELETE':
        return Response({'error': 'Wallets cannot be deleted because ledger history must remain auditable.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)
    serializer = AdminWalletCrudSerializer(wallet, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    wallet = serializer.save()
    _audit(request, 'admin_wallet_updated', {'wallet_id': wallet.id, 'fields': list(serializer.validated_data)})
    return Response(AdminWalletCrudSerializer(wallet).data)


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def admin_transactions_crud(request):
    if request.method == 'GET':
        transactions = Transaction.objects.select_related('sender', 'recipient').order_by('-created_at')
        user_id = request.query_params.get('user_id')
        status_filter = request.query_params.get('status')
        if user_id:
            transactions = transactions.filter(Q(sender_id=user_id) | Q(recipient_id=user_id))
        if status_filter:
            transactions = transactions.filter(status=status_filter)
        return Response(AdminTransactionCrudSerializer(transactions[:200], many=True).data)
    serializer = AdminTransactionCrudSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    with db_transaction.atomic():
        record = serializer.save()
        _write_admin_ledgers(record)
        _audit(request, 'admin_transaction_created', {'transaction_id': str(record.id)})
    return Response(AdminTransactionCrudSerializer(record).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def admin_transaction_crud_detail(request, transaction_id):
    record = _get_or_404(Transaction, transaction_id)
    if record is None:
        return Response({'error': 'Transaction not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response(AdminTransactionCrudSerializer(record).data)
    if request.method == 'DELETE':
        return Response({'error': 'Transactions cannot be deleted. Create a reversal instead.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)
    serializer = AdminTransactionCrudSerializer(record, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    forbidden = {'amount', 'fee_amount', 'currency', 'sender', 'recipient', 'type'} & set(serializer.validated_data)
    if forbidden:
        return Response({'error': f'Financial fields cannot be changed: {sorted(forbidden)}'}, status=status.HTTP_400_BAD_REQUEST)
    record = serializer.save()
    _audit(request, 'admin_transaction_updated', {'transaction_id': str(record.id), 'fields': list(serializer.validated_data)})
    return Response(AdminTransactionCrudSerializer(record).data)


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def admin_periodic_tasks_crud(request):
    if request.method == 'GET':
        tasks = PeriodicTask.objects.select_related('interval', 'crontab').order_by('name')
        return Response(AdminPeriodicTaskCrudSerializer(tasks, many=True).data)
    serializer = AdminPeriodicTaskCrudSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    interval_every = request.data.get('interval_every')
    interval_period = request.data.get('interval_period', IntervalSchedule.MINUTES)
    if not interval_every:
        return Response({'error': 'interval_every is required for task creation.'}, status=status.HTTP_400_BAD_REQUEST)
    schedule, _ = IntervalSchedule.objects.get_or_create(every=int(interval_every), period=interval_period)
    task = serializer.save(interval=schedule)
    _audit(request, 'admin_periodic_task_created', {'task_id': task.id})
    return Response(AdminPeriodicTaskCrudSerializer(task).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def admin_periodic_task_crud_detail(request, task_id):
    task = _get_or_404(PeriodicTask, task_id)
    if task is None:
        return Response({'error': 'Periodic task not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response(AdminPeriodicTaskCrudSerializer(task).data)
    if request.method == 'DELETE':
        task.delete()
        _audit(request, 'admin_periodic_task_deleted', {'task_id': task_id})
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = AdminPeriodicTaskCrudSerializer(task, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    task = serializer.save()
    _audit(request, 'admin_periodic_task_updated', {'task_id': task.id})
    return Response(AdminPeriodicTaskCrudSerializer(task).data)
