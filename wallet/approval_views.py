from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from .models import PaymentRequestStatus, TransactionApproval, ParentalControl
from .serializers import TransactionApprovalSerializer, PinVerifySerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_pending_approvals(request):
    """List all pending approvals for the current user."""
    approvals = TransactionApproval.objects.filter(
        approver=request.user,
        status=TransactionApproval.ApprovalStatus.PENDING
    ).select_related('requester', 'transaction', 'payment_request', 'split_request')
    
    serializer = TransactionApprovalSerializer(approvals, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_transaction(request, approval_id):
    """Approve a pending transaction approval with PIN verification."""
    # Verify PIN
    serializer = PinVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    
    pin = serializer.validated_data['pin']
    
    # Check if user has a PIN set
    if not request.user.transaction_pin:
        return Response({'error': 'No transaction PIN set. Please set it in your profile.'}, status=400)
    
    # Verify PIN
    if not check_password(pin, request.user.transaction_pin):
        if request.user.transaction_pin == pin:
            request.user.transaction_pin = make_password(pin)
            request.user.save(update_fields=['transaction_pin'])
        else:
            return Response({'error': 'Incorrect PIN'}, status=400)
    
    try:
        approval = TransactionApproval.objects.get(
            id=approval_id,
            approver=request.user,
            status=TransactionApproval.ApprovalStatus.PENDING
        )
    except TransactionApproval.DoesNotExist:
        return Response({'error': 'Approval not found or already processed'}, status=404)
    
    # Check if expired
    if approval.expires_at and approval.expires_at < timezone.now():
        approval.status = TransactionApproval.ApprovalStatus.EXPIRED
        approval.save()
        return Response({'error': 'Approval has expired'}, status=400)
    
    from .services.transfers import execute_p2p_transfer
    from .models import SplitParticipant

    if approval.approval_type == 'money_sent':
        # Handle money sent approval - execute transfer from sender to recipient
        recipient_id = approval.metadata.get('recipient_id')
        if recipient_id:
            from .models import User
            try:
                recipient = User.objects.get(id=recipient_id)
                transaction_obj = execute_p2p_transfer(
                    sender=approval.approver,
                    recipient=recipient,
                    amount=approval.amount,
                    currency=approval.currency,
                    note=approval.note,
                    idempotency_key=f'transfer-approval-{approval.id}',
                )
                approval.transaction = transaction_obj
                
                # Notify recipient that transfer completed
                from .views import create_notification
                create_notification(
                    recipient,
                    'transfer_received',
                    {
                        'sender_handle': approval.approver.handle,
                        'sender_display_name': approval.approver.display_name,
                        'amount': str(approval.amount),
                        'currency': approval.currency,
                        'note': approval.note,
                        'transaction_id': str(transaction_obj.id),
                    },
                )
            except Exception as e:
                return Response({'error': str(e)}, status=400)
        approval.status = TransactionApproval.ApprovalStatus.APPROVED
        approval.responded_at = timezone.now()
        approval.save(update_fields=['status', 'responded_at', 'transaction'])
        serializer = TransactionApprovalSerializer(approval)
        return Response(serializer.data)
    
    if approval.approval_type == 'parental_link':
        # Handle parental link approval
        parental_control = ParentalControl.objects.filter(
            parent=approval.requester,
            child=approval.approver,
            status=ParentalControl.Status.PENDING,
        ).first()
        if parental_control:
            parental_control.status = ParentalControl.Status.ACTIVE
            parental_control.linked_at = timezone.now()
            parental_control.save()
        approval.status = TransactionApproval.ApprovalStatus.APPROVED
        approval.responded_at = timezone.now()
        approval.save(update_fields=['status', 'responded_at'])
        serializer = TransactionApprovalSerializer(approval)
        return Response(serializer.data)
    
    if approval.approval_type == 'qr_payment':
        # Handle QR payment approval - execute transfer to recipient
        recipient_id = approval.metadata.get('recipient_id')
        if recipient_id:
            from .models import User
            try:
                recipient = User.objects.get(id=recipient_id)
                transaction_obj = execute_p2p_transfer(
                    sender=approval.approver,
                    recipient=recipient,
                    amount=approval.amount,
                    currency=approval.currency,
                    note=approval.note,
                    idempotency_key=f'qr-approval-{approval.id}',
                )
                approval.transaction = transaction_obj
                
                # Notify recipient that QR payment completed
                from .views import create_notification
                create_notification(
                    recipient,
                    'qr_payment_received',
                    {
                        'payer_handle': approval.approver.handle,
                        'payer_display_name': approval.approver.display_name,
                        'amount': str(approval.amount),
                        'currency': approval.currency,
                        'note': approval.note,
                        'transaction_id': str(transaction_obj.id),
                    },
                )
            except Exception as e:
                return Response({'error': str(e)}, status=400)
        approval.status = TransactionApproval.ApprovalStatus.APPROVED
        approval.responded_at = timezone.now()
        approval.save(update_fields=['status', 'responded_at', 'transaction'])
        serializer = TransactionApprovalSerializer(approval)
        return Response(serializer.data)
    
    if approval.transaction is None:
        if approval.payment_request:
            payment_request = approval.payment_request
            if payment_request.status != PaymentRequestStatus.PENDING:
                return Response({'error': 'Payment request is no longer pending'}, status=400)
            transaction_obj = execute_p2p_transfer(
                sender=approval.approver,
                recipient=approval.requester,
                amount=payment_request.amount,
                currency=payment_request.currency,
                note=payment_request.note or 'Payment for request',
                idempotency_key=f'approval-{approval.id}',
            )
            payment_request.status = PaymentRequestStatus.PAID
            payment_request.resulting_transaction = transaction_obj
            payment_request.save(update_fields=['status', 'resulting_transaction'])
        elif approval.split_request:
            participant = SplitParticipant.objects.select_related('payment_request').filter(
                split_request=approval.split_request,
                payment_request__payer=approval.approver,
                payment_request__status=PaymentRequestStatus.PENDING,
            ).first()
            if not participant:
                return Response({'error': 'Split participant is no longer pending'}, status=400)
            transaction_obj = execute_p2p_transfer(
                sender=approval.approver,
                recipient=approval.requester,
                amount=participant.amount_owed,
                currency=approval.currency,
                note=approval.note,
                idempotency_key=f'approval-{approval.id}',
            )
            participant.payment_request.status = PaymentRequestStatus.PAID
            participant.payment_request.resulting_transaction = transaction_obj
            participant.payment_request.save(update_fields=['status', 'resulting_transaction'])
        else:
            transaction_obj = execute_p2p_transfer(
                sender=approval.requester,
                recipient=approval.approver,
                amount=approval.amount,
                currency=approval.currency,
                note=approval.note,
                idempotency_key=f'approval-{approval.id}',
            )
            approval.transaction = transaction_obj

    approval.status = TransactionApproval.ApprovalStatus.APPROVED
    approval.responded_at = timezone.now()
    approval.save(update_fields=['status', 'responded_at', 'transaction'])
    
    serializer = TransactionApprovalSerializer(approval)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def decline_transaction(request, approval_id):
    """Decline a pending transaction approval with PIN verification."""
    # Verify PIN
    serializer = PinVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    
    pin = serializer.validated_data['pin']
    
    # Check if user has a PIN set
    if not request.user.transaction_pin:
        return Response({'error': 'No transaction PIN set. Please set it in your profile.'}, status=400)
    
    # Verify PIN
    if not check_password(pin, request.user.transaction_pin):
        if request.user.transaction_pin == pin:
            request.user.transaction_pin = make_password(pin)
            request.user.save(update_fields=['transaction_pin'])
        else:
            return Response({'error': 'Incorrect PIN'}, status=400)
    
    try:
        approval = TransactionApproval.objects.get(
            id=approval_id,
            approver=request.user,
            status=TransactionApproval.ApprovalStatus.PENDING
        )
    except TransactionApproval.DoesNotExist:
        return Response({'error': 'Approval not found or already processed'}, status=404)
    
    approval.status = TransactionApproval.ApprovalStatus.DECLINED
    approval.responded_at = timezone.now()
    approval.save(update_fields=['status', 'responded_at'])
    
    # Process the declined transaction/request
    if approval.payment_request:
        approval.payment_request.status = PaymentRequestStatus.DECLINED
        approval.payment_request.save()
    elif approval.split_request:
        participant = approval.split_request.participants.filter(payment_request__payer=request.user).first()
        if participant:
            participant.status = 'declined'
            participant.save()
    
    serializer = TransactionApprovalSerializer(approval)
    return Response(serializer.data)
