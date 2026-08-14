from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from django.contrib.auth import logout, login, authenticate
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
import requests
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import logging
import json
from .models import (
    User, Wallet, Transaction, LedgerEntry, Notification,
    ProcessedRequest, AuditLog, KYCTier, UserStatus,
    TransactionType, TransactionStatus, LedgerDirection, WalletStatus,
    TransferAttempt, PaymentRequest
)
from .serializers import (
    UserSerializer, WalletSerializer, GoogleAuthRequestSerializer,
    UserResolveSerializer, TransferRequestSerializer, TransferResponseSerializer,
    NotificationSerializer, TransactionSerializer, WalletDetailSerializer,
    ProfileUpdateSerializer, generate_unique_handle, TransactionDetailSerializer,
    ReversalRequestSerializer, ReversalResponseSerializer, TransferAttemptSerializer,
    AdminLoginSerializer, AdminDashboardSerializer, AdminUserListSerializer,
    AdminUserDetailSerializer, AdminUserUpdateSerializer, AdminTransactionListSerializer,
    AdminAuditLogSerializer
)
from django.utils.text import slugify
from decimal import Decimal
from datetime import timedelta
import uuid
from django.db import models
from django.db.models import Sum, Q
from .authentication import issue_access_token

# Configure structured JSON logging
logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
@extend_schema(
    request=GoogleAuthRequestSerializer,
    responses={200: TransferResponseSerializer, 400: dict},
    tags=['Authentication']
)
class GoogleAuthView(APIView):
    """
    Google OAuth authentication using authorization code flow.
    """
    permission_classes = [AllowAny]
    serializer_class = GoogleAuthRequestSerializer

    def post(self, request):
        serializer = GoogleAuthRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        code = serializer.validated_data['code']
        state = serializer.validated_data['state']

        # In production, verify the state parameter matches what we sent
        # For MVP, we'll skip state verification but it should be implemented

        try:
            # Exchange authorization code for tokens
            token_url = "https://oauth2.googleapis.com/token"
            data = {
                'code': code,
                'client_id': request.build_absolute_uri('/').split('//')[1].split('/')[0],  # This should come from settings
                'client_secret': '',  # This should come from settings
                'redirect_uri': '',  # This should come from settings
                'grant_type': 'authorization_code'
            }
            
            # For now, we'll use a simplified approach with google-auth library
            # In production, you'd use the actual client credentials from settings
            from django.conf import settings
            
            # Exchange code for tokens
            token_response = requests.post(
                'https://oauth2.googleapis.com/token',
                data={
                    'code': code,
                    'client_id': settings.GOOGLE_CLIENT_ID,
                    'client_secret': settings.GOOGLE_CLIENT_SECRET,
                    'redirect_uri': f"{settings.FRONTEND_ORIGIN_URL}/auth/callback",
                    'grant_type': 'authorization_code'
                }
            )
            
            if token_response.status_code != 200:
                return Response(
                    {'error': 'Failed to exchange authorization code'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            token_data = token_response.json()
            id_token_str = token_data.get('id_token')
            
            # Verify the ID token
            id_info = id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID
            )
            
            # Check email verification
            if not id_info.get('email_verified'):
                return Response(
                    {'error': 'Email not verified by Google'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            google_sub = id_info['sub']
            email = id_info['email']
            name = id_info.get('name', '')
            picture = id_info.get('picture', '')
            
            # Look up or create user
            try:
                user = User.objects.get(google_sub=google_sub)
                if user.status != UserStatus.ACTIVE:
                    return Response(
                        {'error': 'Account is not active'},
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                # Log the user in
                login(request, user)
                
                # Audit log for login
                AuditLog.objects.create(
                    user=user,
                    action='login',
                    metadata={'method': 'google_oauth'}
                )
                
                is_new_user = False
                
            except User.DoesNotExist:
                # Create new user atomically
                with transaction.atomic():
                    # Generate unique handle
                    base_handle = slugify(email.split('@')[0])[:30]
                    handle = generate_unique_handle(base_handle)
                    
                    user = User.objects.create_user(
                        email=email,
                        google_sub=google_sub,
                        handle=handle,
                        display_name=name,
                        avatar_url=picture,
                        kyc_tier=KYCTier.TIER_0,
                        status=UserStatus.ACTIVE
                    )
                    
                    # Create wallet
                    wallet = Wallet.objects.create(user=user, currency='USD')
                    
                    # Create zero-balance ledger entry
                    LedgerEntry.objects.create(
                        wallet=wallet,
                        transaction=None,  # No transaction for opening balance
                        direction=LedgerDirection.CREDIT,
                        amount=Decimal('0.00')
                    )
                    
                    # Audit log for signup
                    AuditLog.objects.create(
                        user=user,
                        action='signup',
                        metadata={'method': 'google_oauth', 'handle': handle}
                    )
                    
                    # Log the user in
                    login(request, user)
                    
                    is_new_user = True
            
            wallet = user.wallet
            
            response_data = {
                'user': UserSerializer(user).data,
                'wallet': WalletSerializer(wallet).data,
                'is_new_user': is_new_user,
                # Browser privacy controls can reject Render's third-party session
                # cookie when the app is served by Vercel.  Return a signed API
                # token so the frontend can authenticate every API request.
                'access_token': issue_access_token(user),
            }
            
            response = Response(response_data, status=status.HTTP_200_OK)
            
            # Ensure session cookie is set properly
            # Django's login() should handle this, but we force a session save
            request.session.save()
            
            return response
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(
    responses={200: dict},
    tags=['Authentication']
)
@api_view(['GET'])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf_cookie_view(request):
    """Set a CSRF cookie for browser-based API requests."""
    return Response({'detail': 'CSRF cookie set'}, status=status.HTTP_200_OK)


@extend_schema(
    responses={200: dict},
    tags=['Authentication']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """
    Logout the current user.
    """
    logout(request)
    return Response({'message': 'Logged out successfully'}, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
@extend_schema(
    request=AdminLoginSerializer,
    responses={200: dict, 400: dict, 401: dict},
    tags=['Authentication']
)
class AdminLoginView(APIView):
    """
    Admin login using username and password.
    This is separate from the Google OAuth flow used by regular users.
    """
    permission_classes = [AllowAny]
    serializer_class = AdminLoginSerializer

    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        # Authenticate using either the stored username or the email address.
        # Django's default ModelBackend uses the custom model's USERNAME_FIELD,
        # which is set to email in User, so username-only admin accounts fail here.
        user = User.objects.filter(
            Q(username__iexact=username) | Q(email__iexact=username)
        ).first()

        if not user or not user.check_password(password):
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Check if user is staff
        if not user.is_staff:
            return Response(
                {'error': 'Access denied. Admin privileges required.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if user account is active
        if user.status != UserStatus.ACTIVE:
            return Response(
                {'error': 'Account is not active'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Log the user in
        login(request, user)
        
        # Audit log for admin login
        AuditLog.objects.create(
            user=user,
            action='admin_login',
            metadata={'method': 'username_password'}
        )
        
        wallet = user.wallet
        
        response_data = {
            'user': UserSerializer(user).data,
            'wallet': WalletDetailSerializer(wallet).data,
            'access_token': issue_access_token(user),
        }
        
        response = Response(response_data, status=status.HTTP_200_OK)
        request.session.save()
        
        return response


@extend_schema(
    responses={200: UserSerializer, 400: dict},
    tags=['User']
)
class MeView(APIView):
    """
    Get (GET) or update (PATCH) the current user's profile and wallet summary.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get(self, request):
        """
        Get the current user's profile and wallet summary.
        """
        user = request.user
        wallet = user.wallet
        
        response_data = {
            'user': UserSerializer(user).data,
            'wallet': WalletDetailSerializer(wallet).data
        }
        
        return Response(response_data, status=status.HTTP_200_OK)
    
    def patch(self, request):
        """
        Update user profile (display_name and/or handle).
        Enforces 30-day cooldown on handle changes.
        """
        serializer = ProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        display_name = serializer.validated_data.get('display_name')
        handle = serializer.validated_data.get('handle')

        try:
            with transaction.atomic():
                if display_name:
                    user.display_name = display_name
                
                if handle:
                    # Check 30-day cooldown
                    if user.handle_changed_at:
                        cooldown_end = user.handle_changed_at + timedelta(days=30)
                        if timezone.now() < cooldown_end:
                            return Response(
                                {'error': 'Handle can only be changed once every 30 days'},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                    
                    # Check if handle is already taken
                    if User.objects.filter(handle=handle).exclude(id=user.id).exists():
                        return Response(
                            {'error': 'Handle already taken'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    
                    user.handle = handle
                    user.handle_changed_at = timezone.now()
                
                user.save()
                
                # Audit log
                AuditLog.objects.create(
                    user=user,
                    action='profile_update',
                    metadata={'display_name': display_name, 'handle': handle}
                )
            
            return Response(
                UserSerializer(user).data,
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(
    responses={200: UserResolveSerializer, 404: dict},
    tags=['User']
)
class UserResolveView(APIView):
    """
    Resolve a user by handle or email.
    Returns the same generic 404 for both "not found" and "inactive account" to prevent enumeration.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserResolveSerializer

    def get(self, request):
        query = request.query_params.get('query', '').strip()
        
        if not query:
            return Response(
                {'error': 'Query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Try to find by handle or email
            user = User.objects.filter(
                models.Q(handle=query) | models.Q(email=query),
                status=UserStatus.ACTIVE
            ).first()
            
            if not user:
                return Response(
                    {'error': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            response_data = {
                'user_id': str(user.id),
                'handle': user.handle,
                'display_name': user.display_name,
                'avatar_url': user.avatar_url
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {'error': 'An error occurred'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


def create_notification(user, notification_type, payload):
    """
    Create a notification for a user.
    Structured as a separate function for easy conversion to async later.
    """
    Notification.objects.create(
        user=user,
        type=notification_type,
        payload=payload
    )


@extend_schema(
    request=TransferRequestSerializer,
    responses={200: TransferResponseSerializer, 400: dict},
    tags=['Transfers']
)
class TransferView(APIView):
    """
    Send money to another user by handle.
    Implements idempotency and proper locking to prevent double-spending.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TransferRequestSerializer

    def post(self, request):
        serializer = TransferRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        recipient_handle = serializer.validated_data['recipient_handle']
        amount = serializer.validated_data['amount']
        currency = serializer.validated_data['currency']
        note = serializer.validated_data.get('note', '')
        idempotency_key = serializer.validated_data['idempotency_key']

        sender = request.user
        sender_wallet = sender.wallet

        # A4: Check sender account status
        if sender.status != UserStatus.ACTIVE:
            TransferAttempt.objects.create(
                user=sender,
                recipient_handle_input=recipient_handle,
                amount=amount,
                currency=currency,
                rejection_reason='sender_account_suspended'
            )
            logger.warning(
                json.dumps({
                    'event': 'transfer_attempt_rejected',
                    'user_id': str(sender.id),
                    'reason': 'sender_account_suspended',
                    'recipient_handle': recipient_handle,
                    'amount': str(amount),
                    'timestamp': timezone.now().isoformat()
                })
            )
            return Response(
                {'code': 'account_suspended', 'message': 'Your account is suspended and cannot send transfers'},
                status=status.HTTP_403_FORBIDDEN
            )

        # A4: Check sender wallet status
        if sender_wallet.status != WalletStatus.ACTIVE:
            TransferAttempt.objects.create(
                user=sender,
                recipient_handle_input=recipient_handle,
                amount=amount,
                currency=currency,
                rejection_reason='sender_wallet_frozen'
            )
            logger.warning(
                json.dumps({
                    'event': 'transfer_attempt_rejected',
                    'user_id': str(sender.id),
                    'reason': 'sender_wallet_frozen',
                    'recipient_handle': recipient_handle,
                    'amount': str(amount),
                    'timestamp': timezone.now().isoformat()
                })
            )
            return Response(
                {'code': 'wallet_frozen', 'message': 'Your wallet is frozen and cannot send transfers'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Check currency match
        if sender_wallet.currency != currency:
            TransferAttempt.objects.create(
                user=sender,
                recipient_handle_input=recipient_handle,
                amount=amount,
                currency=currency,
                rejection_reason='currency_mismatch'
            )
            return Response(
                {'code': 'currency_mismatch', 'message': 'Currency mismatch'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                # Check idempotency first
                processed_request = ProcessedRequest.objects.filter(
                    idempotency_key=idempotency_key
                ).select_related('transaction').first()
                
                if processed_request:
                    # A5: Alert on repeated idempotency key reuse
                    logger.warning(
                        json.dumps({
                            'event': 'idempotency_key_reuse',
                            'user_id': str(sender.id),
                            'idempotency_key': idempotency_key,
                            'timestamp': timezone.now().isoformat()
                        })
                    )
                    # Return the stored result
                    if processed_request.transaction:
                        return Response(
                            TransferResponseSerializer(processed_request.transaction).data,
                            status=status.HTTP_200_OK
                        )
                    else:
                        return Response(
                            {'error': 'Idempotency key exists but no transaction found'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                
                # Resolve recipient
                try:
                    recipient = User.objects.get(
                        handle=recipient_handle,
                        status=UserStatus.ACTIVE
                    )
                except User.DoesNotExist:
                    # A2: Log failed transfer attempt
                    TransferAttempt.objects.create(
                        user=sender,
                        recipient_handle_input=recipient_handle,
                        amount=amount,
                        currency=currency,
                        rejection_reason='recipient_not_found'
                    )
                    logger.info(
                        json.dumps({
                            'event': 'transfer_attempt_failed',
                            'user_id': str(sender.id),
                            'reason': 'recipient_not_found',
                            'recipient_handle': recipient_handle,
                            'amount': str(amount),
                            'timestamp': timezone.now().isoformat()
                        })
                    )
                    return Response(
                        {'error': 'Recipient not found'},
                        status=status.HTTP_404_NOT_FOUND
                    )
                
                # A4: Check recipient account status
                if recipient.status != UserStatus.ACTIVE:
                    TransferAttempt.objects.create(
                        user=sender,
                        recipient_handle_input=recipient_handle,
                        amount=amount,
                        currency=currency,
                        rejection_reason='recipient_account_suspended'
                    )
                    logger.warning(
                        json.dumps({
                            'event': 'transfer_attempt_rejected',
                            'user_id': str(sender.id),
                            'reason': 'recipient_account_suspended',
                            'recipient_handle': recipient_handle,
                            'amount': str(amount),
                            'timestamp': timezone.now().isoformat()
                        })
                    )
                    return Response(
                        {'error': 'Recipient account is suspended'},
                        status=status.HTTP_403_FORBIDDEN
                    )

                # A4: Check recipient wallet status
                recipient_wallet = recipient.wallet
                if recipient_wallet.status != WalletStatus.ACTIVE:
                    TransferAttempt.objects.create(
                        user=sender,
                        recipient_handle_input=recipient_handle,
                        amount=amount,
                        currency=currency,
                        rejection_reason='recipient_wallet_frozen'
                    )
                    logger.warning(
                        json.dumps({
                            'event': 'transfer_attempt_rejected',
                            'user_id': str(sender.id),
                            'reason': 'recipient_wallet_frozen',
                            'recipient_handle': recipient_handle,
                            'amount': str(amount),
                            'timestamp': timezone.now().isoformat()
                        })
                    )
                    return Response(
                        {'error': 'Recipient wallet is frozen'},
                        status=status.HTTP_403_FORBIDDEN
                    )
                
                # Prevent sending to self
                if recipient == sender:
                    TransferAttempt.objects.create(
                        user=sender,
                        recipient_handle_input=recipient_handle,
                        amount=amount,
                        currency=currency,
                        rejection_reason='cannot_send_to_self'
                    )
                    return Response(
                        {'error': 'Cannot send to yourself'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Lock sender's wallet row
                sender_wallet = Wallet.objects.select_for_update().get(id=sender_wallet.id)
                
                # Check balance
                current_balance = sender_wallet.get_balance()
                if current_balance < amount:
                    TransferAttempt.objects.create(
                        user=sender,
                        recipient_handle_input=recipient_handle,
                        amount=amount,
                        currency=currency,
                        rejection_reason='insufficient_funds'
                    )
                    AuditLog.objects.create(
                        user=sender,
                        action='transfer_failed_insufficient_funds',
                        metadata={
                            'recipient_handle': recipient_handle,
                            'amount': str(amount),
                            'balance': str(current_balance)
                        }
                    )
                    logger.info(
                        json.dumps({
                            'event': 'transfer_attempt_failed',
                            'user_id': str(sender.id),
                            'reason': 'insufficient_funds',
                            'recipient_handle': recipient_handle,
                            'amount': str(amount),
                            'balance': str(current_balance),
                            'timestamp': timezone.now().isoformat()
                        })
                    )
                    return Response(
                        {'code': 'insufficient_funds', 'message': 'Insufficient funds'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Check per-transaction limit
                if amount > sender.send_limit_per_tx:
                    TransferAttempt.objects.create(
                        user=sender,
                        recipient_handle_input=recipient_handle,
                        amount=amount,
                        currency=currency,
                        rejection_reason='per_transaction_limit_exceeded'
                    )
                    AuditLog.objects.create(
                        user=sender,
                        action='transfer_failed_limit_exceeded',
                        metadata={
                            'recipient_handle': recipient_handle,
                            'amount': str(amount),
                            'limit': str(sender.send_limit_per_tx)
                        }
                    )
                    logger.info(
                        json.dumps({
                            'event': 'transfer_attempt_failed',
                            'user_id': str(sender.id),
                            'reason': 'per_transaction_limit_exceeded',
                            'recipient_handle': recipient_handle,
                            'amount': str(amount),
                            'limit': str(sender.send_limit_per_tx),
                            'timestamp': timezone.now().isoformat()
                        })
                    )
                    return Response(
                        {'code': 'per_transaction_limit_exceeded', 'message': 'Amount exceeds per-transaction limit'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Check daily limit
                twenty_four_hours_ago = timezone.now() - timedelta(days=1)
                from django.db.models import Sum
                sent_today = sender.sent_transactions.filter(
                    created_at__gte=twenty_four_hours_ago,
                    status=TransactionStatus.COMPLETED
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                
                if sent_today + amount > sender.send_limit_daily:
                    TransferAttempt.objects.create(
                        user=sender,
                        recipient_handle_input=recipient_handle,
                        amount=amount,
                        currency=currency,
                        rejection_reason='daily_limit_exceeded'
                    )
                    AuditLog.objects.create(
                        user=sender,
                        action='transfer_failed_daily_limit_exceeded',
                        metadata={
                            'recipient_handle': recipient_handle,
                            'amount': str(amount),
                            'sent_today': str(sent_today),
                            'daily_limit': str(sender.send_limit_daily)
                        }
                    )
                    logger.info(
                        json.dumps({
                            'event': 'transfer_attempt_failed',
                            'user_id': str(sender.id),
                            'reason': 'daily_limit_exceeded',
                            'recipient_handle': recipient_handle,
                            'amount': str(amount),
                            'sent_today': str(sent_today),
                            'daily_limit': str(sender.send_limit_daily),
                            'timestamp': timezone.now().isoformat()
                        })
                    )
                    return Response(
                        {'code': 'daily_limit_exceeded', 'message': 'Amount exceeds daily limit'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Create transaction
                transaction_obj = Transaction.objects.create(
                    type=TransactionType.P2P_TRANSFER,
                    sender=sender,
                    recipient=recipient,
                    amount=amount,
                    currency=currency,
                    note=note,
                    status=TransactionStatus.COMPLETED
                )
                
                # Create ledger entries (debit sender, credit recipient)
                LedgerEntry.objects.create(
                    wallet=sender_wallet,
                    transaction=transaction_obj,
                    direction=LedgerDirection.DEBIT,
                    amount=amount
                )
                
                LedgerEntry.objects.create(
                    wallet=recipient_wallet,
                    transaction=transaction_obj,
                    direction=LedgerDirection.CREDIT,
                    amount=amount
                )
                
                # Record idempotency key
                ProcessedRequest.objects.create(
                    idempotency_key=idempotency_key,
                    user=sender,
                    transaction=transaction_obj
                )
                
                # Audit log
                AuditLog.objects.create(
                    user=sender,
                    action='transfer',
                    metadata={
                        'transaction_id': str(transaction_obj.id),
                        'recipient_handle': recipient_handle,
                        'amount': str(amount),
                        'currency': currency
                    }
                )
                
                # A5: Structured logging for successful transfer
                logger.info(
                    json.dumps({
                        'event': 'transfer_completed',
                        'user_id': str(sender.id),
                        'transaction_id': str(transaction_obj.id),
                        'recipient_handle': recipient_handle,
                        'amount': str(amount),
                        'currency': currency,
                        'idempotency_key': idempotency_key,
                        'timestamp': timezone.now().isoformat()
                    })
                )
            
            # Create notification for recipient (outside transaction)
            create_notification(
                recipient,
                'transfer_received',
                {
                    'sender_handle': sender.handle,
                    'sender_display_name': sender.display_name,
                    'amount': str(amount),
                    'currency': currency,
                    'note': note,
                    'transaction_id': str(transaction_obj.id)
                }
            )
            
            return Response(
                TransferResponseSerializer(transaction_obj).data,
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(
                json.dumps({
                    'event': 'transfer_error',
                    'user_id': str(sender.id),
                    'error': str(e),
                    'timestamp': timezone.now().isoformat()
                })
            )
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class NotificationListView(APIView):
    """
    List notifications for the current user.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get(self, request):
        unread_only = request.query_params.get('unread_only', 'false').lower() == 'true'
        
        notifications = request.user.notifications.all()
        
        if unread_only:
            notifications = notifications.filter(read_at__isnull=True)
        
        # Apply cursor pagination
        from rest_framework.pagination import CursorPagination
        paginator = CursorPagination()
        paginator.page_size = 20
        paginator.ordering = '-created_at'
        paginated_notifications = paginator.paginate_queryset(notifications, request)
        
        serializer = NotificationSerializer(paginated_notifications, many=True)
        return paginator.get_paginated_response(serializer.data)


class NotificationDetailView(APIView):
    """
    Mark a notification as read.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def post(self, request, id):
        try:
            notification = request.user.notifications.get(id=id)
            notification.read_at = timezone.now()
            notification.save()
            return Response(
                NotificationSerializer(notification).data,
                status=status.HTTP_200_OK
            )
        except Notification.DoesNotExist:
            return Response(
                {'error': 'Notification not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class WalletView(APIView):
    """
    Get wallet details including balance and limits.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = WalletDetailSerializer

    def get(self, request):
        wallet = request.user.wallet
        serializer = WalletDetailSerializer(wallet)
        return Response(serializer.data, status=status.HTTP_200_OK)


class TransactionListView(APIView):
    """
    List transactions for the current user (sent and received).
    Uses cursor pagination for performance on growing tables.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionSerializer

    def get(self, request):
        from rest_framework.pagination import CursorPagination
        
        # Get transactions where user is sender or recipient
        transactions = request.user.sent_transactions.all() | request.user.received_transactions.all()
        transactions = transactions.distinct().order_by('-created_at')
        
        # Apply cursor pagination
        paginator = CursorPagination()
        paginator.page_size = 20
        paginator.ordering = '-created_at'
        paginated_transactions = paginator.paginate_queryset(transactions, request)
        
        serializer = TransactionSerializer(paginated_transactions, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)


class CloseAccountView(APIView):
    """
    Soft-close the user account.
    Only allowed if wallet balance is zero.
    Notifications are left intact for closed accounts (historical access).
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def post(self, request):
        user = request.user
        wallet = user.wallet
        
        # Check balance
        if wallet.get_balance() != Decimal('0.00'):
            return Response(
                {'error': 'Cannot close account with non-zero balance. Withdraw funds first.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            with transaction.atomic():
                user.status = UserStatus.CLOSED
                user.save()
                
                # Audit log
                AuditLog.objects.create(
                    user=user,
                    action='account_close',
                    metadata={}
                )
            
            return Response(
                {'message': 'Account closed successfully'},
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class TransactionDetailView(APIView):
    """
    Get detailed information about a single transaction.
    Used for admin UI and user dispute resolution.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionDetailSerializer

    def get(self, request, transaction_id):
        try:
            transaction_obj = Transaction.objects.get(id=transaction_id)
            
            # Only allow users to see their own transactions
            if request.user != transaction_obj.sender and request.user != transaction_obj.recipient:
                if not request.user.is_staff:
                    return Response(
                        {'error': 'You do not have permission to view this transaction'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            
            serializer = TransactionDetailSerializer(transaction_obj)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Transaction.DoesNotExist:
            return Response(
                {'error': 'Transaction not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class ReversalView(APIView):
    """
    Admin-only endpoint to reverse a transaction.
    Creates offsetting ledger entries and logs the reason.
    """
    permission_classes = [IsAdminUser]
    serializer_class = ReversalRequestSerializer

    def post(self, request, transaction_id):
        serializer = ReversalRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        reason = serializer.validated_data['reason']

        try:
            with transaction.atomic():
                # Get the original transaction
                original_transaction = Transaction.objects.select_for_update().get(id=transaction_id)

                # Check if already reversed
                if original_transaction.reversals.filter(status=TransactionStatus.COMPLETED).exists():
                    return Response(
                        {'error': 'Transaction has already been reversed'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Lock both wallets involved
                sender_wallet = Wallet.objects.select_for_update().get(user=original_transaction.sender)
                recipient_wallet = Wallet.objects.select_for_update().get(user=original_transaction.recipient)

                # Create reversal transaction
                reversal_transaction = Transaction.objects.create(
                    type=TransactionType.REVERSAL,
                    sender=None,  # System-initiated
                    recipient=original_transaction.sender,  # Credit back to sender
                    amount=original_transaction.amount,
                    currency=original_transaction.currency,
                    note=f"Reversal: {reason}",
                    status=TransactionStatus.COMPLETED,
                    related_transaction=original_transaction
                )

                # Create offsetting ledger entries
                # Credit sender (reverse the debit)
                LedgerEntry.objects.create(
                    wallet=sender_wallet,
                    transaction=reversal_transaction,
                    direction=LedgerDirection.CREDIT,
                    amount=original_transaction.amount
                )

                # Debit recipient (reverse the credit)
                LedgerEntry.objects.create(
                    wallet=recipient_wallet,
                    transaction=reversal_transaction,
                    direction=LedgerDirection.DEBIT,
                    amount=original_transaction.amount
                )

                # Update original transaction status
                original_transaction.status = TransactionStatus.REVERSED
                original_transaction.save()

                # Audit log
                AuditLog.objects.create(
                    user=request.user,
                    action='transaction_reversal',
                    metadata={
                        'original_transaction_id': str(original_transaction.id),
                        'reversal_transaction_id': str(reversal_transaction.id),
                        'reason': reason,
                        'amount': str(original_transaction.amount),
                        'currency': original_transaction.currency
                    }
                )

                # Log the reversal
                logger.info(
                    json.dumps({
                        'event': 'transaction_reversed',
                        'admin_user_id': str(request.user.id),
                        'original_transaction_id': str(original_transaction.id),
                        'reversal_transaction_id': str(reversal_transaction.id),
                        'reason': reason,
                        'amount': str(original_transaction.amount),
                        'timestamp': timezone.now().isoformat()
                    })
                )

                return Response(
                    ReversalResponseSerializer(reversal_transaction).data,
                    status=status.HTTP_201_CREATED
                )

        except Transaction.DoesNotExist:
            return Response(
                {'error': 'Transaction not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(
                json.dumps({
                    'event': 'reversal_failed',
                    'transaction_id': str(transaction_id),
                    'error': str(e),
                    'timestamp': timezone.now().isoformat()
                })
            )
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================================================
# ADMIN API ENDPOINTS
# ============================================================================

@extend_schema(
    responses={200: AdminDashboardSerializer},
    tags=['Admin']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_dashboard(request):
    """
    Admin dashboard with aggregate statistics.
    """
    try:
        # User counts by status
        total_users = User.objects.count()
        active_users = User.objects.filter(status=UserStatus.ACTIVE).count()
        suspended_users = User.objects.filter(status=UserStatus.SUSPENDED).count()
        closed_users = User.objects.filter(status=UserStatus.CLOSED).count()
        
        # Wallet counts
        total_wallets = Wallet.objects.count()
        frozen_wallets = Wallet.objects.filter(status=WalletStatus.FROZEN).count()
        
        # P2P volume
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        
        p2p_volume_today = Transaction.objects.filter(
            type=TransactionType.P2P_TRANSFER,
            status=TransactionStatus.COMPLETED,
            created_at__date=today
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        p2p_volume_week = Transaction.objects.filter(
            type=TransactionType.P2P_TRANSFER,
            status=TransactionStatus.COMPLETED,
            created_at__date__gte=week_ago
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Pending payment requests
        pending_payment_requests = PaymentRequest.objects.filter(
            status=PaymentRequestStatus.PENDING
        ).count()
        
        # Transfer attempt rejections in last 24h
        twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
        transfer_attempt_rejections_24h = TransferAttempt.objects.filter(
            created_at__gte=twenty_four_hours_ago
        ).count()
        
        response_data = {
            'total_users': total_users,
            'active_users': active_users,
            'suspended_users': suspended_users,
            'closed_users': closed_users,
            'total_wallets': total_wallets,
            'p2p_volume_today': str(p2p_volume_today),
            'p2p_volume_week': str(p2p_volume_week),
            'pending_payment_requests': pending_payment_requests,
            'frozen_wallets': frozen_wallets,
            'transfer_attempt_rejections_24h': transfer_attempt_rejections_24h
        }
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(
            json.dumps({
                'event': 'admin_dashboard_error',
                'admin_user_id': str(request.user.id),
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            })
        )
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: AdminUserListSerializer},
    tags=['Admin']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_users_list(request):
    """
    Admin user list with search and filtering.
    """
    try:
        query = request.query_params.get('query', '').strip()
        status_filter = request.query_params.get('status', '').strip()
        cursor = request.query_params.get('cursor', '').strip()
        
        # Build queryset
        users = User.objects.select_related('wallet').all()
        
        # Apply search
        if query:
            users = users.filter(
                Q(handle__icontains=query) | 
                Q(email__icontains=query) |
                Q(display_name__icontains=query)
            )
        
        # Apply status filter
        if status_filter:
            users = users.filter(status=status_filter)
        
        # Apply cursor pagination
        from rest_framework.pagination import CursorPagination
        paginator = CursorPagination()
        paginator.page_size = 50
        paginator.ordering = '-created_at'
        
        if cursor:
            # For simplicity, we'll use offset-based pagination for this implementation
            # In production, you'd want proper cursor-based pagination
            try:
                cursor_offset = int(cursor)
                users = users[cursor_offset:]
            except ValueError:
                pass
        
        paginated_users = paginator.paginate_queryset(users, request)
        serializer = AdminUserListSerializer(paginated_users, many=True)
        
        return paginator.get_paginated_response(serializer.data)
        
    except Exception as e:
        logger.error(
            json.dumps({
                'event': 'admin_users_list_error',
                'admin_user_id': str(request.user.id),
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            })
        )
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: AdminUserDetailSerializer},
    tags=['Admin']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_user_detail(request, user_id):
    """
    Admin user detail view.
    """
    try:
        user = User.objects.select_related('wallet').prefetch_related(
            'sent_transactions', 'received_transactions', 'transfer_attempts', 'linked_providers'
        ).get(id=user_id)
        
        serializer = AdminUserDetailSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    except User.DoesNotExist:
        return Response(
            {'error': 'User not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(
            json.dumps({
                'event': 'admin_user_detail_error',
                'admin_user_id': str(request.user.id),
                'target_user_id': user_id,
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            })
        )
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    request=AdminUserUpdateSerializer,
    responses={200: AdminUserDetailSerializer, 400: dict},
    tags=['Admin']
)
@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def admin_user_update(request, user_id):
    """
    Admin user update with audit logging.
    """
    serializer = AdminUserUpdateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    reason = serializer.validated_data.get('reason')
    if not reason:
        return Response(
            {'error': 'Reason is required for all admin actions'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user_id)
            wallet = user.wallet
            
            # Track changes for audit log
            changes = {}
            
            # Update user status
            if 'status' in serializer.validated_data:
                old_status = user.status
                new_status = serializer.validated_data['status']
                if old_status != new_status:
                    user.status = new_status
                    changes['status'] = {'old': old_status, 'new': new_status}
            
            # Update wallet status
            if 'wallet_status' in serializer.validated_data:
                old_wallet_status = wallet.status
                new_wallet_status = serializer.validated_data['wallet_status']
                if old_wallet_status != new_wallet_status:
                    wallet.status = new_wallet_status
                    changes['wallet_status'] = {'old': old_wallet_status, 'new': new_wallet_status}
            
            # Update send limits
            if 'send_limit_per_tx' in serializer.validated_data:
                old_limit = user.send_limit_per_tx
                new_limit = serializer.validated_data['send_limit_per_tx']
                if old_limit != new_limit:
                    user.send_limit_per_tx = new_limit
                    changes['send_limit_per_tx'] = {'old': str(old_limit), 'new': str(new_limit)}
            
            if 'send_limit_daily' in serializer.validated_data:
                old_limit = user.send_limit_daily
                new_limit = serializer.validated_data['send_limit_daily']
                if old_limit != new_limit:
                    user.send_limit_daily = new_limit
                    changes['send_limit_daily'] = {'old': str(old_limit), 'new': str(new_limit)}
            
            # Update KYC tier
            if 'kyc_tier' in serializer.validated_data:
                old_tier = user.kyc_tier
                new_tier = serializer.validated_data['kyc_tier']
                if old_tier != new_tier:
                    user.kyc_tier = new_tier
                    changes['kyc_tier'] = {'old': old_tier, 'new': new_tier}
            
            # Save changes
            user.save()
            wallet.save()
            
            # Create audit log entry
            AuditLog.objects.create(
                user=request.user,
                action='admin_user_update',
                metadata={
                    'target_user_id': str(user.id),
                    'target_user_handle': user.handle,
                    'changes': changes,
                    'reason': reason
                }
            )
            
            # Log the action
            logger.info(
                json.dumps({
                    'event': 'admin_user_updated',
                    'admin_user_id': str(request.user.id),
                    'target_user_id': str(user.id),
                    'changes': changes,
                    'reason': reason,
                    'timestamp': timezone.now().isoformat()
                })
            )
        
        # Return updated user data
        user.refresh_from_db()
        serializer = AdminUserDetailSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    except User.DoesNotExist:
        return Response(
            {'error': 'User not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(
            json.dumps({
                'event': 'admin_user_update_error',
                'admin_user_id': str(request.user.id),
                'target_user_id': user_id,
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            })
        )
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: AdminTransactionListSerializer},
    tags=['Admin']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_transactions_list(request):
    """
    Admin transaction list with search and filtering.
    """
    try:
        query = request.query_params.get('query', '').strip()
        status_filter = request.query_params.get('status', '').strip()
        type_filter = request.query_params.get('type', '').strip()
        cursor = request.query_params.get('cursor', '').strip()
        
        # Build queryset
        transactions = Transaction.objects.select_related('sender', 'recipient').all()
        
        # Apply search (transaction ID, sender handle, recipient handle)
        if query:
            transactions = transactions.filter(
                Q(id__icontains=query) |
                Q(sender__handle__icontains=query) |
                Q(recipient__handle__icontains=query)
            )
        
        # Apply status filter
        if status_filter:
            transactions = transactions.filter(status=status_filter)
        
        # Apply type filter
        if type_filter:
            transactions = transactions.filter(type=type_filter)
        
        # Apply cursor pagination
        from rest_framework.pagination import CursorPagination
        paginator = CursorPagination()
        paginator.page_size = 50
        paginator.ordering = '-created_at'
        
        if cursor:
            try:
                cursor_offset = int(cursor)
                transactions = transactions[cursor_offset:]
            except ValueError:
                pass
        
        paginated_transactions = paginator.paginate_queryset(transactions, request)
        serializer = AdminTransactionListSerializer(paginated_transactions, many=True)
        
        return paginator.get_paginated_response(serializer.data)
        
    except Exception as e:
        logger.error(
            json.dumps({
                'event': 'admin_transactions_list_error',
                'admin_user_id': str(request.user.id),
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            })
        )
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: TransactionDetailSerializer},
    tags=['Admin']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_transaction_detail(request, transaction_id):
    """
    Admin transaction detail view.
    """
    try:
        transaction_obj = Transaction.objects.select_related('sender', 'recipient').get(id=transaction_id)
        serializer = TransactionDetailSerializer(transaction_obj)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    except Transaction.DoesNotExist:
        return Response(
            {'error': 'Transaction not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(
            json.dumps({
                'event': 'admin_transaction_detail_error',
                'admin_user_id': str(request.user.id),
                'transaction_id': transaction_id,
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            })
        )
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: TransferAttemptSerializer},
    tags=['Admin']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_transfer_attempts(request):
    """
    Admin transfer attempt log with filtering.
    """
    try:
        user_filter = request.query_params.get('user', '').strip()
        reason_filter = request.query_params.get('reason', '').strip()
        cursor = request.query_params.get('cursor', '').strip()
        
        # Build queryset
        attempts = TransferAttempt.objects.select_related('user').all()
        
        # Apply user filter
        if user_filter:
            attempts = attempts.filter(
                Q(user__handle__icontains=user_filter) |
                Q(user__email__icontains=user_filter)
            )
        
        # Apply reason filter
        if reason_filter:
            attempts = attempts.filter(rejection_reason__icontains=reason_filter)
        
        # Apply cursor pagination
        from rest_framework.pagination import CursorPagination
        paginator = CursorPagination()
        paginator.page_size = 50
        paginator.ordering = '-created_at'
        
        if cursor:
            try:
                cursor_offset = int(cursor)
                attempts = attempts[cursor_offset:]
            except ValueError:
                pass
        
        paginated_attempts = paginator.paginate_queryset(attempts, request)
        serializer = TransferAttemptSerializer(paginated_attempts, many=True)
        
        return paginator.get_paginated_response(serializer.data)
        
    except Exception as e:
        logger.error(
            json.dumps({
                'event': 'admin_transfer_attempts_error',
                'admin_user_id': str(request.user.id),
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            })
        )
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: AdminAuditLogSerializer},
    tags=['Admin']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_audit_log(request):
    """
    Admin audit log viewer with filtering.
    """
    try:
        user_filter = request.query_params.get('user', '').strip()
        action_filter = request.query_params.get('action', '').strip()
        cursor = request.query_params.get('cursor', '').strip()
        
        # Build queryset
        logs = AuditLog.objects.select_related('user').all()
        
        # Apply user filter
        if user_filter:
            logs = logs.filter(
                Q(user__handle__icontains=user_filter) |
                Q(user__email__icontains=user_filter)
            )
        
        # Apply action filter
        if action_filter:
            logs = logs.filter(action__icontains=action_filter)
        
        # Apply cursor pagination
        from rest_framework.pagination import CursorPagination
        paginator = CursorPagination()
        paginator.page_size = 50
        paginator.ordering = '-created_at'
        
        if cursor:
            try:
                cursor_offset = int(cursor)
                logs = logs[cursor_offset:]
            except ValueError:
                pass
        
        paginated_logs = paginator.paginate_queryset(logs, request)
        serializer = AdminAuditLogSerializer(paginated_logs, many=True)
        
        return paginator.get_paginated_response(serializer.data)
        
    except Exception as e:
        logger.error(
            json.dumps({
                'event': 'admin_audit_log_error',
                'admin_user_id': str(request.user.id),
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            })
        )
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
