from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from django.utils.crypto import get_random_string
from datetime import timedelta
from .models import ParentalControl, User, Wallet, Transaction
from .serializers import (
    ParentalControlSerializer, ParentalControlLinkSerializer,
    ParentalControlVerifySerializer, ParentalControlUpdateSerializer
)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def link_child_account(request):
    """
    Link a child account by sending a 6-digit verification code to the child's device.
    The parent enters the child's phone number, and a code is sent (simulated).
    """
    serializer = ParentalControlLinkSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    
    child_phone = serializer.validated_data['child_phone']
    
    # Find the child user by phone number
    try:
        child = User.objects.get(primary_phone_number=child_phone)
    except User.DoesNotExist:
        return Response({'error': 'User with this phone number not found'}, status=404)
    
    # Check if already linked
    if ParentalControl.objects.filter(parent=request.user, child=child).exists():
        return Response({'error': 'This account is already linked to you'}, status=400)
    
    # Check if child already has a parent
    if ParentalControl.objects.filter(child=child, status=ParentalControl.Status.ACTIVE).exists():
        return Response({'error': 'This account already has an active parental control'}, status=400)
    
    # Generate 6-digit verification code
    verification_code = get_random_string(6, allowed_chars='0123456789')
    code_expires_at = timezone.now() + timedelta(minutes=15)
    
    # Create pending parental control
    parental_control = ParentalControl.objects.create(
        parent=request.user,
        child=child,
        status=ParentalControl.Status.PENDING,
        verification_code=verification_code,
        code_expires_at=code_expires_at
    )
    
    # In a real implementation, send the code via SMS/Notification
    # For now, we'll return it in the response (for testing)
    return Response({
        'message': 'Verification code sent to child device',
        'verification_code': verification_code,  # TODO: Remove in production, send via SMS/Notification
        'expires_at': code_expires_at.isoformat(),
        'parental_control_id': parental_control.id
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_parental_link(request, control_id):
    """
    Verify a parental control link using the 6-digit code.
    This is called by the child (or parent entering the code from child's device).
    """
    serializer = ParentalControlVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    
    verification_code = serializer.validated_data['verification_code']
    
    try:
        # User can verify if they are the parent or the child
        parental_control = ParentalControl.objects.get(
            id=control_id,
            verification_code=verification_code,
            status=ParentalControl.Status.PENDING
        )
    except ParentalControl.DoesNotExist:
        return Response({'error': 'Invalid or expired verification code'}, status=404)

    if request.user.id not in (parental_control.parent_id, parental_control.child_id):
        return Response({'error': 'You are not a participant in this parental link'}, status=403)
    
    # Check if code has expired
    if parental_control.code_expires_at < timezone.now():
        parental_control.status = ParentalControl.Status.REVOKED
        parental_control.save()
        return Response({'error': 'Verification code has expired'}, status=400)
    
    # Verify the link
    parental_control.status = ParentalControl.Status.ACTIVE
    parental_control.linked_at = timezone.now()
    parental_control.save()
    
    serializer = ParentalControlSerializer(parental_control)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_child_accounts(request):
    """
    List all child accounts for the current user (as parent).
    """
    child_controls = ParentalControl.objects.filter(
        parent=request.user,
        status=ParentalControl.Status.ACTIVE
    ).select_related('child')
    
    serializer = ParentalControlSerializer(child_controls, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_parent_accounts(request):
    """
    List all parent accounts for the current user (as child).
    """
    parent_controls = ParentalControl.objects.filter(
        child=request.user,
        status=ParentalControl.Status.ACTIVE
    ).select_related('parent')
    
    serializer = ParentalControlSerializer(parent_controls, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_child_balance(request, child_id):
    """
    Get child's wallet balance (requires can_view_transactions permission).
    """
    try:
        parental_control = ParentalControl.objects.get(
            parent=request.user,
            child_id=child_id,
            status=ParentalControl.Status.ACTIVE,
            can_view_transactions=True
        )
    except ParentalControl.DoesNotExist:
        return Response({'error': 'No permission to view this account'}, status=403)
    
    try:
        wallet = Wallet.objects.get(user_id=child_id)
    except Wallet.DoesNotExist:
        return Response({'error': 'Wallet not found'}, status=404)
    
    return Response({
        'balance': str(wallet.get_balance()),
        'currency': wallet.currency
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_child_transactions(request, child_id):
    """
    Get child's transaction history (requires can_view_transactions permission).
    """
    try:
        parental_control = ParentalControl.objects.get(
            parent=request.user,
            child_id=child_id,
            status=ParentalControl.Status.ACTIVE,
            can_view_transactions=True
        )
    except ParentalControl.DoesNotExist:
        return Response({'error': 'No permission to view this account'}, status=403)
    
    transactions = Transaction.objects.filter(
        Q(sender_id=child_id) | Q(recipient_id=child_id)
    ).order_by('-created_at')[:50]
    
    from .serializers import TransactionSerializer
    serializer = TransactionSerializer(transactions, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_to_child(request, child_id):
    """
    Send money from parent to child account (requires can_send_money permission).
    """
    try:
        parental_control = ParentalControl.objects.get(
            parent=request.user,
            child_id=child_id,
            status=ParentalControl.Status.ACTIVE,
            can_send_money=True
        )
    except ParentalControl.DoesNotExist:
        return Response({'error': 'No permission to send money to this account'}, status=403)
    
    amount = request.data.get('amount')
    note = request.data.get('note', '')
    
    if not amount:
        return Response({'error': 'Amount is required'}, status=400)
    
    try:
        parent_wallet = Wallet.objects.get(user=request.user)
        child_wallet = Wallet.objects.get(user_id=child_id)
    except Wallet.DoesNotExist:
        return Response({'error': 'Wallet not found'}, status=404)
    
    # Create transfer from parent to child
    from decimal import Decimal
    from .services.transfers import execute_transfer
    
    try:
        transfer = execute_transfer(
            sender_wallet=parent_wallet,
            recipient_user=parental_control.child,
            amount=Decimal(amount),
            currency=parent_wallet.currency,
            note=f"Parental transfer: {note}" if note else "Parental transfer"
        )
        
        return Response({
            'message': 'Transfer successful',
            'transaction_id': str(transfer.id),
            'amount': str(transfer.amount),
            'currency': transfer.currency
        })
    except Exception as e:
        return Response({'error': str(e)}, status=400)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_parental_permissions(request, control_id):
    """
    Update parental control permissions.
    """
    try:
        parental_control = ParentalControl.objects.get(
            id=control_id,
            parent=request.user,
            status=ParentalControl.Status.ACTIVE
        )
    except ParentalControl.DoesNotExist:
        return Response({'error': 'Parental control not found'}, status=404)
    
    serializer = ParentalControlUpdateSerializer(data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    
    # Update permissions
    for field, value in serializer.validated_data.items():
        setattr(parental_control, field, value)
    
    parental_control.save()
    
    serializer = ParentalControlSerializer(parental_control)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def revoke_parental_control(request, control_id):
    """
    Revoke a parental control relationship.
    """
    try:
        parental_control = ParentalControl.objects.get(
            id=control_id,
            parent=request.user
        )
    except ParentalControl.DoesNotExist:
        return Response({'error': 'Parental control not found'}, status=404)
    
    parental_control.status = ParentalControl.Status.REVOKED
    parental_control.save()
    
    return Response({'message': 'Parental control revoked'})
