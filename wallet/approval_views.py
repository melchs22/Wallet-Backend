from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from .models import TransactionApproval
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
    
    approval.status = TransactionApproval.ApprovalStatus.APPROVED
    approval.save()
    
    # Process the approved transaction/request
    if approval.transaction:
        # Transaction is already created, just mark as approved
        pass
    elif approval.payment_request:
        # Mark payment request as approved
        from .models import PaymentRequestStatus
        approval.payment_request.status = PaymentRequestStatus.PAID
        approval.payment_request.save()
    elif approval.split_request:
        # Mark split participant as approved
        participant = approval.split_request.participants.filter(
            payment_request=approval.payment_request
        ).first()
        if participant:
            participant.status = 'approved'
            participant.save()
    
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
    approval.save()
    
    # Process the declined transaction/request
    if approval.payment_request:
        from .models import PaymentRequestStatus
        approval.payment_request.status = PaymentRequestStatus.DECLINED
        approval.payment_request.save()
    elif approval.split_request:
        participant = approval.split_request.participants.filter(
            payment_request=approval.payment_request
        ).first()
        if participant:
            participant.status = 'declined'
            participant.save()
    
    serializer = TransactionApprovalSerializer(approval)
    return Response(serializer.data)
