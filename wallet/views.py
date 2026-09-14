from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from django.contrib.auth import logout, login, authenticate
from django.contrib.auth.hashers import make_password
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
import requests
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import logging
import json
import hmac
import hashlib
import base64
from django.conf import settings
from .models import (
    User, Wallet, Transaction, LedgerEntry, Notification, PushDevice, TrustedDevice, PendingLoginRequest, OtpChallenge, MobileMoneyWebhookEvent,
    ProcessedRequest, AuditLog, KYCTier, UserStatus,
    TransactionType, TransactionStatus, LedgerDirection, WalletStatus,
    TransferAttempt, PaymentRequest, PaymentRequestStatus, SplitRequest, SplitParticipant, SystemSetting, Dispute, DisputeStatus, ExchangeRate, MobileMoneyTransaction, MobileMoneyTransactionType, MobileMoneyTransactionStatus, LinkedProvider, ProviderCatalog, SupportedCountry, LegalDocument, TransferFeeRule, UserKYCSubmission, ScheduledTransfer, ScheduleFrequency, ScheduledTransferStatus, Merchant, MerchantStatus, MerchantPlan, MerchantSubscription, KYCDocument, Settlement, TransactionApproval,
)
from .serializers import (
    UserSerializer, WalletSerializer, GoogleAuthRequestSerializer,
    EmailSignupSerializer, EmailLoginSerializer,
    UserResolveSerializer, TransferRequestSerializer, TransferResponseSerializer,
    NotificationSerializer, PushDeviceSerializer, TransactionSerializer, WalletDetailSerializer,
    ProfileUpdateSerializer, generate_unique_handle, TransactionDetailSerializer,
    ReversalRequestSerializer, ReversalResponseSerializer, TransferAttemptSerializer,
    AdminLoginSerializer, AdminChangePasswordSerializer, AdminDashboardSerializer,
    AdminUserListSerializer, AdminUserDetailSerializer, AdminUserUpdateSerializer,
    AdminTopUpSerializer, AdminTransactionListSerializer, AdminAuditLogSerializer,
    SystemSettingSerializer, PaymentRequestCreateSerializer, PaymentRequestSerializer,
    SplitCreateSerializer, DisputeCreateSerializer, DisputeSerializer, DisputeResolveSerializer,
    MobileMoneyTransactionSerializer, MobileMoneyTopupSerializer, MobileMoneyWithdrawalSerializer,
    ScheduledTransferSerializer, ScheduledTransferCreateSerializer,
    MerchantSerializer, MerchantCreateSerializer, MerchantApprovalSerializer,
    MerchantPlanSerializer, MerchantSubscriptionSerializer, ChangePasswordSerializer,
    SupportedCountrySerializer, LegalDocumentSerializer, ProviderCatalogSerializer,
    UserKYCSubmissionSerializer, OtpChallengeRequestSerializer, OtpChallengeVerifySerializer, LoginConfirmationSerializer
)
from django.utils.text import slugify
from decimal import Decimal
from datetime import timedelta
import uuid
import secrets
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Sum, Q
from django.core.exceptions import ValidationError
from .authentication import issue_access_token
from .throttles import OtpRequestThrottle, OtpVerifyThrottle
from .services.security import (
    create_otp_challenge,
    device_id_from_request,
    get_or_create_device,
    verify_device_signature,
    token_is_step_up_verified,
    valid_webhook_signature,
)

# Configure structured JSON logging
logger = logging.getLogger(__name__)


def user_has_approved_kyc(user):
    if user.kyc_tier != KYCTier.TIER_0:
        return True
    return UserKYCSubmission.objects.filter(user=user, status=UserKYCSubmission.Status.APPROVED).exists()


def get_qr_signing_secret():
    """Get the secret key for QR code signing."""
    return getattr(settings, 'QR_SIGNING_SECRET', 'default-qr-secret-change-in-production')


def verify_qr_signature(payload_json, signature):
    """Verify the HMAC signature of a QR payload."""
    secret = get_qr_signing_secret()
    expected_signature = hmac.new(
        secret.encode(),
        payload_json.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected_signature)


@api_view(['GET'])
@permission_classes([AllowAny])
def merchant_plans(request):
    """Return active plans for the public pricing page."""
    return Response(MerchantPlanSerializer(MerchantPlan.objects.filter(is_active=True), many=True).data)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def merchant_subscription(request):
    """Read or change the authenticated merchant's plan selection."""
    merchant = Merchant.objects.filter(user=request.user).first()
    if not merchant:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'POST':
        plan_code = request.data.get('plan_code', 'starter')
        plan = MerchantPlan.objects.filter(code=plan_code, is_active=True).first()
        if not plan:
            return Response({'error': 'Plan not found'}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        subscription, _ = MerchantSubscription.objects.update_or_create(
            merchant=merchant,
            defaults={
                'plan': plan,
                'status': MerchantSubscription.Status.ACTIVE if plan.monthly_price else MerchantSubscription.Status.TRIALING,
                'current_period_start': now,
                'current_period_end': now + timedelta(days=30),
                'cancel_at_period_end': False,
            },
        )
        return Response(MerchantSubscriptionSerializer(subscription).data)

    subscription = getattr(merchant, 'subscription', None)
    if not subscription:
        return Response({'error': 'Subscription not configured'}, status=status.HTTP_404_NOT_FOUND)
    return Response(MerchantSubscriptionSerializer(subscription).data)


def merchant_monthly_usage(merchant):
    """Return the current period's payment-intent count and configured limit."""
    subscription = getattr(merchant, 'subscription', None)
    if not subscription:
        return {'used': 0, 'limit': None, 'remaining': None}
    used = merchant.payment_intents.filter(created_at__gte=subscription.current_period_start).count()
    limit = subscription.plan.monthly_transaction_limit
    return {'used': used, 'limit': limit, 'remaining': max(limit - used, 0) if limit is not None else None}


@extend_schema(
    request=EmailSignupSerializer,
    responses={201: dict, 400: dict, 409: dict},
    tags=['Authentication']
)
class EmailSignupView(APIView):
    permission_classes = [AllowAny]
    serializer_class = EmailSignupSerializer

    def post(self, request):
        serializer = EmailSignupSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email'].strip().lower()
        password = serializer.validated_data['password']
        display_name = (serializer.validated_data.get('display_name') or email.split('@')[0]).strip()
        phone_number = serializer.validated_data.get('phone_number', '').strip()
        primary_phone_number = serializer.validated_data.get('primary_phone_number', phone_number).strip()
        transaction_pin = serializer.validated_data.get('transaction_pin', '').strip()
        country_code = serializer.validated_data.get('country_code', '').strip().upper()
        device_id = (serializer.validated_data.get('device_id') or '').strip()

        if country_code and not SupportedCountry.objects.filter(code=country_code, active=True).exists():
            return Response({'error': 'This country is not currently supported.'}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email__iexact=email).exists():
            return Response({'error': 'An account with this email already exists.'}, status=status.HTTP_409_CONFLICT)

        base_handle = slugify(display_name)[:30] or slugify(email.split('@')[0])[:30] or 'walletuser'
        with transaction.atomic():
            handle = generate_unique_handle(base_handle)
            user = User.objects.create_user(
                email=email,
                password=password,
                handle=handle,
                display_name=display_name,
                phone_number=phone_number if phone_number else None,
                primary_phone_number=primary_phone_number if primary_phone_number else None,
                kyc_tier=KYCTier.TIER_0,
                status=UserStatus.ACTIVE,
                current_device_id=device_id or None,
            )
            # Set transaction PIN
            if transaction_pin:
                user.transaction_pin = make_password(transaction_pin)
                user.save()
            wallet = Wallet.objects.create(user=user, currency='GNF', default_provider='orange_money')
            LedgerEntry.objects.create(
                wallet=wallet,
                transaction=None,
                direction=LedgerDirection.CREDIT,
                amount=Decimal('0.00'),
            )
            from wallet.services.limits import apply_usage_based_limits
            apply_usage_based_limits(user)
            AuditLog.objects.create(
                user=user,
                action='signup',
                metadata={'method': 'email_password', 'handle': handle},
            )

        login(request, user)
        response_data = {
            'user': UserSerializer(user).data,
            'wallet': WalletSerializer(user.wallet).data,
            'access_token': issue_access_token(user, device_id=device_id or None),
            'is_new_user': True,
        }
        request.session.save()
        return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([AllowAny])
def supported_countries(request):
    return Response(SupportedCountrySerializer(SupportedCountry.objects.filter(active=True), many=True).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def legal_document(request, slug):
    try:
        document = LegalDocument.objects.get(slug=slug, published=True)
    except LegalDocument.DoesNotExist:
        return Response({'error': 'Document not found'}, status=status.HTTP_404_NOT_FOUND)
    return Response(LegalDocumentSerializer(document).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def legal_document_html(request, slug):
    try:
        document = LegalDocument.objects.get(slug=slug, published=True)
    except LegalDocument.DoesNotExist:
        return HttpResponse('<h1>Document not found</h1>', status=404, content_type='text/html')
    return HttpResponse(document.body_html, content_type='text/html')


@api_view(['GET'])
@permission_classes([AllowAny])
def provider_catalog(request):
    return Response(ProviderCatalogSerializer(ProviderCatalog.objects.filter(active=True), many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    serializer = ChangePasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    if not request.user.check_password(serializer.validated_data['old_password']):
        return Response({'error': 'Current password is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)
    request.user.set_password(serializer.validated_data['new_password'])
    request.user.save(update_fields=['password'])
    return Response({'message': 'Password changed successfully.'})


class UserKYCSubmissionView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        submissions = UserKYCSubmission.objects.filter(user=request.user)
        return Response(UserKYCSubmissionSerializer(submissions, many=True).data)

    def post(self, request):
        serializer = UserKYCSubmissionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        submission = serializer.save(user=request.user)
        return Response(UserKYCSubmissionSerializer(submission).data, status=status.HTTP_201_CREATED)


@method_decorator(csrf_exempt, name='dispatch')
@extend_schema(
    request=EmailLoginSerializer,
    responses={200: dict, 400: dict, 401: dict},
    tags=['Authentication']
)
class EmailLoginView(APIView):
    permission_classes = [AllowAny]
    serializer_class = EmailLoginSerializer

    def post(self, request):
        serializer = EmailLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        identifier = (serializer.validated_data.get('identifier') or serializer.validated_data.get('email') or '').strip()
        password = serializer.validated_data['password']
        country_code = serializer.validated_data.get('country_code', '').strip().upper()
        device_id = (serializer.validated_data.get('device_id') or '').strip()
        if '@' in identifier:
            user = authenticate(request, username=identifier.lower(), password=password)
        else:
            country = SupportedCountry.objects.filter(code=country_code, active=True).first() if country_code else None
            dial_code = country.dial_code if country else ''
            phone_candidates = [identifier]
            if dial_code and not identifier.startswith('+'):
                phone_candidates.append(f'{dial_code}{identifier.lstrip("0")}')
            user = User.objects.filter(
                Q(primary_phone_number__in=phone_candidates) | Q(phone_number__in=phone_candidates)
            ).first()
            if user is not None and not user.check_password(password):
                user = None
        if user is None:
            return Response({'error': 'Invalid email/phone or password.'}, status=status.HTTP_401_UNAUTHORIZED)

        if user.status != UserStatus.ACTIVE:
            return Response({'error': 'Account is not active.'}, status=status.HTTP_403_FORBIDDEN)

        device = TrustedDevice.objects.filter(
            user=user, device_id=device_id, is_trusted=True, revoked_at__isnull=True,
        ).first() if device_id else None
        trusted_exists = user.trusted_devices.filter(is_trusted=True, revoked_at__isnull=True).exists()
        public_key_pem = (serializer.validated_data.get('public_key_pem') or '').strip()
        if device is None and trusted_exists:
            if not device_id or not public_key_pem:
                return Response({'error': 'A device ID and public signing key are required for new-device login.'}, status=status.HTTP_400_BAD_REQUEST)
            pending = PendingLoginRequest.objects.create(
                user=user,
                new_device_id=device_id,
                new_device_name=serializer.validated_data.get('device_name', '').strip(),
                new_device_public_key_pem=public_key_pem,
                requesting_ip=request.META.get('REMOTE_ADDR'),
            )
            create_notification(user, 'new_device_login', {
                'type': 'new_device_login',
                'request_id': str(pending.id),
                'new_device_name': pending.new_device_name or 'A new device',
                'created_at': pending.created_at.isoformat(),
                'title': 'Approve new device sign-in',
                'message': f"Approve sign-in from {pending.new_device_name or 'a new device'}.",
            })
            return Response({'status': 'pending_confirmation', 'request_id': str(pending.id), 'expires_in': 300}, status=status.HTTP_202_ACCEPTED)

        if device is None and device_id:
            get_or_create_device(
                user, device_id,
                device_name=serializer.validated_data.get('device_name', ''),
                public_key_pem=public_key_pem,
            )

        if device is None and user.current_device_id and device_id and device_id != user.current_device_id:
            previous_device = user.current_device_id
            for device in PushDevice.objects.filter(user=user, active=True).exclude(device_id=device_id or '').exclude(device_id=''):
                create_notification(
                    user,
                    'device_signed_in_elsewhere',
                    {
                        'title': 'Security notice',
                        'message': f'A new device signed in to your account. Previous device {previous_device} was signed out.',
                        'previous_device_id': previous_device,
                        'new_device_id': device_id,
                    },
                )
            user.current_device_id = device_id
            user.save(update_fields=['current_device_id'])
        elif device is None and device_id:
            user.current_device_id = device_id
            user.save(update_fields=['current_device_id'])

        login(request, user)
        wallet = getattr(user, 'wallet', None)
        if wallet is None:
            wallet = Wallet.objects.create(user=user, currency='GNF')
            LedgerEntry.objects.create(
                wallet=wallet,
                transaction=None,
                direction=LedgerDirection.CREDIT,
                amount=Decimal('0.00'),
            )

        AuditLog.objects.create(
            user=user,
            action='login',
            metadata={'method': 'email_password'},
        )

        response_data = {
            'user': UserSerializer(user).data,
            'wallet': WalletSerializer(wallet).data,
            'access_token': issue_access_token(user, device_id=device_id or None),
            'is_new_user': False,
        }
        request.session.save()
        return Response(response_data, status=status.HTTP_200_OK)


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
        device_id = serializer.validated_data.get('device_id', '').strip()

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
                    
                    # Create wallet with default Orange Money provider
                    wallet = Wallet.objects.create(user=user, currency='GNF', default_provider='orange_money')
                    
                    # Create zero-balance ledger entry
                    LedgerEntry.objects.create(
                        wallet=wallet,
                        transaction=None,  # No transaction for opening balance
                        direction=LedgerDirection.CREDIT,
                        amount=Decimal('0.00')
                    )
                    from wallet.services.limits import apply_usage_based_limits
                    apply_usage_based_limits(user)
                    
                    # Audit log for signup
                    AuditLog.objects.create(
                        user=user,
                        action='signup',
                        metadata={'method': 'google_oauth', 'handle': handle}
                    )
                    
                    # Log the user in
                    login(request, user)
                    
                    is_new_user = True

            if device_id:
                try:
                    get_or_create_device(user, device_id)
                except ValueError:
                    return Response({'code': 'device_conflict', 'error': 'This device is registered to another account.'}, status=status.HTTP_409_CONFLICT)
                user.current_device_id = device_id
                user.save(update_fields=['current_device_id'])
            
            wallet = user.wallet
            
            response_data = {
                'user': UserSerializer(user).data,
                'wallet': WalletSerializer(wallet).data,
                'is_new_user': is_new_user,
                # Browser privacy controls can reject Render's third-party session
                # cookie when the app is served by Vercel.  Return a signed API
                # token so the frontend can authenticate every API request.
                'access_token': issue_access_token(user, device_id=device_id or None),
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

        user = User.objects.filter(
            Q(username__iexact=username) | Q(email__iexact=username)
        ).first()

        if not user:
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if not user.is_staff:
            return Response(
                {'error': 'Access denied. Admin privileges required.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if not user.check_password(password):
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        if user.status != UserStatus.ACTIVE:
            return Response(
                {'error': 'Account is not active'},
                status=status.HTTP_403_FORBIDDEN
            )

        login(request, user)

        AuditLog.objects.create(
            user=user,
            action='admin_login',
            metadata={'method': 'username_password'}
        )

        wallet = user.wallet

        response_data = {
            'user': UserSerializer(user).data,
            'wallet': WalletDetailSerializer(wallet).data,
            'access_token': issue_access_token(user, device_id=(request.META.get('HTTP_X_DEVICE_ID') or '').strip() or None),
            'must_change_password': bool(user.must_change_password),
        }

        response = Response(response_data, status=status.HTTP_200_OK)
        request.session.save()

        return response


@extend_schema(
    request=AdminLoginSerializer,
    responses={200: dict, 400: dict, 401: dict},
    tags=['Authentication']
)
@api_view(['POST'])
@csrf_exempt
@permission_classes([AllowAny])
def admin_auth_login(request):
    """Admin username/password login endpoint with staff checks and password-change gate."""
    serializer = AdminLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    username = serializer.validated_data['username']
    password = serializer.validated_data['password']

    user = User.objects.filter(
        Q(username__iexact=username) | Q(email__iexact=username)
    ).first()

    if not user:
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    if not user.is_staff:
        return Response({'error': 'Access denied. Admin privileges required.'}, status=status.HTTP_403_FORBIDDEN)

    if not user.check_password(password):
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    if user.status != UserStatus.ACTIVE:
        return Response({'error': 'Account is not active'}, status=status.HTTP_403_FORBIDDEN)

    login(request, user)
    AuditLog.objects.create(user=user, action='admin_login', metadata={'method': 'username_password'})

    wallet = getattr(user, 'wallet', None)
    if wallet is None:
        wallet = Wallet.objects.create(user=user, currency='GNF', status=WalletStatus.ACTIVE)
        LedgerEntry.objects.create(wallet=wallet, transaction=None, direction=LedgerDirection.CREDIT, amount=Decimal('0.00'))

    response_data = {
        'user': UserSerializer(user).data,
        'wallet': WalletDetailSerializer(wallet).data,
        'access_token': issue_access_token(user),
        'must_change_password': bool(user.must_change_password),
    }

    request.session.save()
    return Response(response_data, status=status.HTTP_200_OK)


@extend_schema(
    responses={200: dict},
    tags=['Authentication']
)
@api_view(['POST'])
@csrf_exempt
@permission_classes([IsAuthenticated])
def admin_auth_logout(request):
    logout(request)
    return Response({'message': 'Logged out successfully'}, status=status.HTTP_200_OK)


@extend_schema(
    request=AdminChangePasswordSerializer,
    responses={200: dict, 400: dict},
    tags=['Authentication']
)
@api_view(['POST'])
@csrf_exempt
@permission_classes([IsAuthenticated])
def admin_change_password(request):
    serializer = AdminChangePasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    if not user.is_staff:
        return Response({'error': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)

    current_password = serializer.validated_data['current_password']
    new_password = serializer.validated_data['new_password']

    if not user.check_password(current_password):
        return Response({'error': 'Current password is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_password)
    user.must_change_password = False
    user.save(update_fields=['password', 'must_change_password'])

    AuditLog.objects.create(
        user=user,
        action='admin_change_password',
        metadata={'changed_by': str(user.id)}
    )

    logout(request)
    return Response({'message': 'Password changed successfully. Please sign in again.'}, status=status.HTTP_200_OK)


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
        from wallet.services.limits import apply_usage_based_limits
        apply_usage_based_limits(user)
        wallet = user.wallet
        
        response_data = {
            'user': UserSerializer(user).data,
            'wallet': WalletDetailSerializer(wallet).data
        }
        
        return Response(response_data, status=status.HTTP_200_OK)
    

@extend_schema(
    responses={200: UserResolveSerializer, 404: dict},
    tags=['User']
)
class UserResolveView(APIView):
    """
    Resolve a user by handle, email, or phone number.
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
            # Try to find by handle, email, or phone number
            user = User.objects.filter(
                models.Q(handle=query) | models.Q(email=query) | models.Q(primary_phone_number=query),
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
                'avatar_url': user.avatar_url,
                'primary_phone_number': user.primary_phone_number
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {'error': 'An error occurred'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(
    responses={200: dict, 404: dict},
    tags=['User']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def resolve_user_by_phone(request):
    """
    Resolve a user by phone number specifically.
    Returns user details when a phone number is entered in the transfer/request forms.
    """
    phone_number = request.query_params.get('phone_number', '').strip()
    
    if not phone_number:
        return Response(
            {'error': 'phone_number parameter is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        user = User.objects.filter(
            primary_phone_number=phone_number,
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
            'avatar_url': user.avatar_url,
            'primary_phone_number': user.primary_phone_number,
            'wallet_currency': user.wallet.currency,
            'wallet_provider': user.wallet.default_provider
        }
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response(
            {'error': 'An error occurred'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def create_notification(user, notification_type, payload):
    """
    Create and deliver a notification after the current transaction commits.
    """
    from wallet.services.notifications import create_notification_record

    notification = create_notification_record(user, notification_type, payload)

    def dispatch_delivery():
        try:
            from wallet.services.notifications import deliver_notification
            deliver_notification(notification.id)
        except Exception:
            logger.exception('notification_delivery_failed', extra={'notification_id': notification.id})

    transaction.on_commit(dispatch_delivery)
    return notification


class PushDeviceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PushDeviceSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        device_id = serializer.validated_data.get('device_id', '')
        if device_id:
            try:
                get_or_create_device(
                    request.user,
                    device_id,
                    platform=serializer.validated_data.get('platform', ''),
                    device_name=serializer.validated_data.get('device_name', ''),
                    public_key_pem=serializer.validated_data.get('public_key_pem', ''),
                )
            except ValueError as error:
                return Response({'error': str(error)}, status=status.HTTP_409_CONFLICT)

        from .models import PushDevice
        device, _ = PushDevice.objects.update_or_create(
            token=serializer.validated_data['token'],
            defaults={
                'user': request.user,
                'device_id': serializer.validated_data.get('device_id', ''),
                'platform': serializer.validated_data.get('platform', ''),
                'active': True,
            },
        )
        if serializer.validated_data.get('device_id'):
            request.user.current_device_id = serializer.validated_data['device_id']
            request.user.save(update_fields=['current_device_id'])
        return Response({'id': device.id, 'registered': True}, status=status.HTTP_200_OK)

    def delete(self, request):
        token = request.data.get('token')
        if token:
            from .models import PushDevice
            PushDevice.objects.filter(user=request.user, token=token).update(active=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([AllowAny])
def login_status(request, request_id):
    try:
        pending = PendingLoginRequest.objects.select_related('user').get(id=request_id)
    except PendingLoginRequest.DoesNotExist:
        return Response({'error': 'Login request not found.'}, status=status.HTTP_404_NOT_FOUND)
    if pending.status == PendingLoginRequest.Status.PENDING and pending.is_expired():
        pending.status = PendingLoginRequest.Status.EXPIRED
        pending.resolved_at = timezone.now()
        pending.save(update_fields=['status', 'resolved_at'])
    response = {'status': pending.status}
    if pending.status == PendingLoginRequest.Status.APPROVED:
        response['access_token'] = issue_access_token(pending.user, device_id=pending.new_device_id)
        wallet = getattr(pending.user, 'wallet', None)
        response['user'] = UserSerializer(pending.user).data
        response['wallet'] = WalletSerializer(wallet).data if wallet else None
    return Response(response)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def confirm_login(request):
    serializer = LoginConfirmationSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    device, error = verify_device_signature(request, request.user)
    if error:
        return Response({'error': error}, status=status.HTTP_401_UNAUTHORIZED)
    with transaction.atomic():
        try:
            pending = PendingLoginRequest.objects.select_for_update().get(
                id=serializer.validated_data['request_id'], user=request.user,
            )
        except PendingLoginRequest.DoesNotExist:
            return Response({'error': 'Login request not found.'}, status=status.HTTP_404_NOT_FOUND)
        if pending.status != PendingLoginRequest.Status.PENDING:
            return Response({'status': pending.status}, status=status.HTTP_409_CONFLICT)
        if pending.is_expired():
            pending.status = PendingLoginRequest.Status.EXPIRED
            pending.resolved_at = timezone.now()
            pending.save(update_fields=['status', 'resolved_at'])
            return Response({'status': pending.status}, status=status.HTTP_410_GONE)
        pending.status = PendingLoginRequest.Status.APPROVED if serializer.validated_data['decision'] == 'approve' else PendingLoginRequest.Status.DENIED
        pending.resolved_by_device = device
        pending.resolved_at = timezone.now()
        pending.save(update_fields=['status', 'resolved_by_device', 'resolved_at'])
    if pending.status == PendingLoginRequest.Status.APPROVED:
        get_or_create_device(
            request.user, pending.new_device_id,
            device_name=pending.new_device_name,
            public_key_pem=pending.new_device_public_key_pem,
        )
    return Response({'status': pending.status})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def trusted_devices(request):
    current_device_id = device_id_from_request(request)
    if not current_device_id or current_device_id != request.user.current_device_id:
        return Response({'error': 'Only the main device can manage trusted devices.'}, status=status.HTTP_403_FORBIDDEN)
    devices = request.user.trusted_devices.filter(is_trusted=True, revoked_at__isnull=True)
    return Response([{
        'device_id': device.device_id,
        'device_name': device.device_name or 'Trusted device',
        'platform': device.platform,
        'last_seen_at': device.last_seen_at,
        'is_current': device.device_id == current_device_id,
    } for device in devices])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def revoke_trusted_device(request, device_id):
    current_device_id = device_id_from_request(request)
    if not current_device_id or current_device_id != request.user.current_device_id:
        return Response({'error': 'Only the main device can manage trusted devices.'}, status=status.HTTP_403_FORBIDDEN)
    if device_id == current_device_id:
        return Response({'error': 'The main device cannot revoke itself.'}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        device = request.user.trusted_devices.select_for_update().filter(
            device_id=device_id, is_trusted=True, revoked_at__isnull=True,
        ).first()
        if not device:
            return Response({'error': 'Trusted device not found.'}, status=status.HTTP_404_NOT_FOUND)
        device.is_trusted = False
        device.revoked_at = timezone.now()
        device.save(update_fields=['is_trusted', 'revoked_at'])
        PushDevice.objects.filter(user=request.user, device_id=device_id, active=True).update(active=False)
    create_notification(request.user, 'device_revoked', {
        'type': 'device_revoked',
        'target_device_id': device_id,
        'device_id': device_id,
        'title': 'Device signed out',
        'message': 'This device was signed out remotely.',
    })
    return Response({'revoked': True, 'device_id': device_id})


class OtpChallengeRequestView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [OtpRequestThrottle]

    def post(self, request):
        serializer = OtpChallengeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        device_id = serializer.validated_data.get('device_id') or device_id_from_request(request)
        if not device_id:
            return Response({'code': 'device_required', 'error': 'A registered device is required for OTP verification.'}, status=status.HTTP_400_BAD_REQUEST)
        challenge, code = create_otp_challenge(
            request.user,
            serializer.validated_data['purpose'],
            request,
            device_id=device_id,
            platform=serializer.validated_data.get('platform', ''),
            device_name=serializer.validated_data.get('device_name', ''),
        )
        from wallet.tasks import send_otp_push_task
        send_otp_push_task.delay(str(challenge.request_id), code)
        return Response({
            'challenge_id': str(challenge.request_id),
            'expires_at': challenge.expires_at,
            'delivery': 'push',
        }, status=status.HTTP_201_CREATED)


class OtpChallengeVerifyView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [OtpVerifyThrottle]

    def post(self, request):
        serializer = OtpChallengeVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            challenge = OtpChallenge.objects.select_related('device').get(
                request_id=serializer.validated_data['challenge_id'],
                user=request.user,
            )
        except OtpChallenge.DoesNotExist:
            return Response({'code': 'invalid_challenge', 'error': 'Verification challenge not found.'}, status=status.HTTP_404_NOT_FOUND)
        from wallet.services.security import verify_otp_challenge, STEP_UP_TTL
        verified, error = verify_otp_challenge(challenge, serializer.validated_data['code'])
        if not verified:
            return Response({'code': 'otp_invalid', 'error': error}, status=status.HTTP_400_BAD_REQUEST)
        device_id = challenge.device.device_id if challenge.device_id else device_id_from_request(request)
        token = issue_access_token(
            request.user,
            device_id=device_id,
            step_up_purpose=challenge.purpose,
            step_up_until=(timezone.now() + STEP_UP_TTL).timestamp(),
        )
        return Response({'verified': True, 'access_token': token, 'expires_in': int(STEP_UP_TTL.total_seconds())})


def step_up_required(request, purpose):
    token = request.auth if isinstance(request.auth, str) else ''
    return not token_is_step_up_verified(token, request.user, request)


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

        recipient_phone = serializer.validated_data['recipient_phone']
        amount = serializer.validated_data['amount']
        currency = serializer.validated_data['currency']
        note = serializer.validated_data.get('note', '')
        idempotency_key = serializer.validated_data['idempotency_key']

        sender = request.user
        if step_up_required(request, OtpChallenge.Purpose.TRANSFER):
            return Response({'code': 'otp_required', 'purpose': OtpChallenge.Purpose.TRANSFER, 'error': 'Fresh device verification is required before sending money.'}, status=status.HTTP_403_FORBIDDEN)
        if not user_has_approved_kyc(sender):
            return Response({'error': 'KYC verification is required before sending money. Please submit your ID details first.'}, status=status.HTTP_403_FORBIDDEN)
        from wallet.services.limits import apply_usage_based_limits
        apply_usage_based_limits(sender)
        sender_wallet = sender.wallet

        # A4: Check sender account status
        if sender.status != UserStatus.ACTIVE:
            TransferAttempt.objects.create(
                user=sender,
                recipient_handle_input=recipient_phone,
                amount=amount,
                currency=currency,
                rejection_reason='sender_account_suspended'
            )
            logger.warning(
                json.dumps({
                    'event': 'transfer_attempt_rejected',
                    'user_id': str(sender.id),
                    'reason': 'sender_account_suspended',
                    'recipient_phone': recipient_phone,
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
                recipient_handle_input=recipient_phone,
                amount=amount,
                currency=currency,
                rejection_reason='sender_wallet_frozen'
            )
            logger.warning(
                json.dumps({
                    'event': 'transfer_attempt_rejected',
                    'user_id': str(sender.id),
                    'reason': 'sender_wallet_frozen',
                    'recipient_phone': recipient_phone,
                    'amount': str(amount),
                    'timestamp': timezone.now().isoformat()
                })
            )
            return Response(
                {'code': 'wallet_frozen', 'message': 'Your wallet is frozen and cannot send transfers'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Check currency match - reject if sender's wallet currency doesn't match requested currency
        if sender_wallet.currency != currency:
            TransferAttempt.objects.create(
                user=sender,
                recipient_handle_input=recipient_phone,
                amount=amount,
                currency=currency,
                rejection_reason='currency_mismatch'
            )
            return Response(
                {'code': 'currency_mismatch', 'message': f'Sender wallet currency is {sender_wallet.currency}, but requested {currency}'},
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
                
                # Resolve recipient by phone number
                try:
                    recipient = User.objects.get(
                        primary_phone_number=recipient_phone,
                        status=UserStatus.ACTIVE
                    )
                except User.DoesNotExist:
                    # A2: Log failed transfer attempt
                    TransferAttempt.objects.create(
                        user=sender,
                        recipient_handle_input=recipient_phone,
                        amount=amount,
                        currency=currency,
                        rejection_reason='recipient_not_found'
                    )
                    logger.info(
                        json.dumps({
                            'event': 'transfer_attempt_failed',
                            'user_id': str(sender.id),
                            'reason': 'recipient_not_found',
                            'recipient_phone': recipient_phone,
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
                        recipient_handle_input=recipient_phone,
                        amount=amount,
                        currency=currency,
                        rejection_reason='recipient_account_suspended'
                    )
                    logger.warning(
                        json.dumps({
                            'event': 'transfer_attempt_rejected',
                            'user_id': str(sender.id),
                            'reason': 'recipient_account_suspended',
                            'recipient_phone': recipient_phone,
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
                        recipient_handle_input=recipient_phone,
                        amount=amount,
                        currency=currency,
                        rejection_reason='recipient_wallet_frozen'
                    )
                    logger.warning(
                        json.dumps({
                            'event': 'transfer_attempt_rejected',
                            'user_id': str(sender.id),
                            'reason': 'recipient_wallet_frozen',
                            'recipient_phone': recipient_phone,
                            'amount': str(amount),
                            'timestamp': timezone.now().isoformat()
                        })
                    )
                    return Response(
                        {'error': 'Recipient wallet is frozen'},
                        status=status.HTTP_403_FORBIDDEN
                    )

                # Handle cross-currency transfers with rate-lock mechanism
                exchange_rate_obj = None
                converted_amount = amount
                
                if sender_wallet.currency != recipient_wallet.currency:
                    # Cross-currency transfer - look up exchange rate
                    try:
                        from wallet.services.exchange_rates import get_active_exchange_rate

                        exchange_rate_obj = get_active_exchange_rate(
                            sender_wallet.currency,
                            recipient_wallet.currency,
                        )
                        
                        if not exchange_rate_obj:
                            TransferAttempt.objects.create(
                                user=sender,
                                recipient_handle_input=recipient_phone,
                                amount=amount,
                                currency=currency,
                                rejection_reason='no_exchange_rate'
                            )
                            return Response(
                                {'code': 'no_exchange_rate', 'message': f'No exchange rate available for {sender_wallet.currency} to {recipient_wallet.currency}'},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        
                        # Calculate recipient's amount using the locked rate
                        converted_amount = amount * exchange_rate_obj.rate
                        
                    except Exception as e:
                        logger.error(f'exchange_rate_lookup_error: {str(e)}')
                        TransferAttempt.objects.create(
                            user=sender,
                            recipient_handle_input=recipient_phone,
                            amount=amount,
                            currency=currency,
                            rejection_reason='exchange_rate_error'
                        )
                        return Response(
                            {'code': 'exchange_rate_error', 'message': 'Error looking up exchange rate'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR
                        )
                
                # Prevent sending to self
                if recipient == sender:
                    TransferAttempt.objects.create(
                        user=sender,
                        recipient_handle_input=recipient_phone,
                        amount=amount,
                        currency=currency,
                        rejection_reason='cannot_send_to_self'
                    )
                    return Response(
                        {'error': 'Cannot send to yourself'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                sender_wallet = Wallet.objects.select_for_update().get(id=sender_wallet.id)
                from wallet.services.fees import calculate_transfer_fee
                fee_amount = calculate_transfer_fee(amount)
                total_debit = amount + fee_amount
                current_balance = sender_wallet.get_balance()
                if current_balance < total_debit:
                    return Response(
                        {'code': 'insufficient_funds', 'message': 'Insufficient funds'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if total_debit > sender.send_limit_per_tx:
                    return Response(
                        {'code': 'per_transaction_limit_exceeded', 'message': 'Amount exceeds per-transaction limit'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                from wallet.services.limits import get_daily_sent_amount
                if get_daily_sent_amount(sender) + total_debit > sender.send_limit_daily:
                    return Response(
                        {'code': 'daily_limit_exceeded', 'message': 'Amount exceeds daily limit'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Check for existing pending approval to prevent duplicates
                pending_approval = TransactionApproval.objects.filter(
                    requester=sender,
                    approver=sender,
                    approval_type='money_sent',
                    status=TransactionApproval.ApprovalStatus.PENDING,
                    note=note,
                    amount=amount,
                ).order_by('-created_at').first()
                if pending_approval:
                    return Response(
                        {'status': 'pending_approval', 'approval_id': pending_approval.id},
                        status=status.HTTP_202_ACCEPTED,
                    )

                # Create approval request for sender to confirm with PIN
                approval = TransactionApproval.objects.create(
                    approver=sender,
                    requester=sender,
                    approval_type='money_sent',
                    amount=amount,
                    currency=currency,
                    note=note,
                    metadata={'recipient_id': recipient.id}
                )
                
                # Notify recipient about incoming transfer
                create_notification(
                    recipient,
                    'incoming_transfer',
                    {
                        'sender_handle': sender.handle,
                        'sender_display_name': sender.display_name,
                        'amount': str(amount),
                        'currency': currency,
                        'note': note,
                    },
                )
                
                return Response(
                    {'status': 'pending_approval', 'approval_id': approval.id},
                    status=status.HTTP_202_ACCEPTED,
                )
                
                # Lock sender's wallet row
                sender_wallet = Wallet.objects.select_for_update().get(id=sender_wallet.id)
                
                # Check balance
                current_balance = sender_wallet.get_balance()
                if current_balance < amount:
                    TransferAttempt.objects.create(
                        user=sender,
                        recipient_handle_input=recipient_phone,
                        amount=amount,
                        currency=currency,
                        rejection_reason='insufficient_funds'
                    )
                    AuditLog.objects.create(
                        user=sender,
                        action='transfer_failed_insufficient_funds',
                        metadata={
                            'recipient_phone': recipient_phone,
                            'amount': str(amount),
                            'balance': str(current_balance)
                        }
                    )
                    logger.info(
                        json.dumps({
                            'event': 'transfer_attempt_failed',
                            'user_id': str(sender.id),
                            'reason': 'insufficient_funds',
                            'recipient_phone': recipient_phone,
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
                        recipient_handle_input=recipient_phone,
                        amount=amount,
                        currency=currency,
                        rejection_reason='per_transaction_limit_exceeded'
                    )
                    AuditLog.objects.create(
                        user=sender,
                        action='transfer_failed_limit_exceeded',
                        metadata={
                            'recipient_phone': recipient_phone,
                            'amount': str(amount),
                            'limit': str(sender.send_limit_per_tx)
                        }
                    )
                    logger.info(
                        json.dumps({
                            'event': 'transfer_attempt_failed',
                            'user_id': str(sender.id),
                            'reason': 'per_transaction_limit_exceeded',
                            'recipient_phone': recipient_phone,
                            'amount': str(amount),
                            'limit': str(sender.send_limit_per_tx),
                            'timestamp': timezone.now().isoformat()
                        })
                    )
                    return Response(
                        {'code': 'per_transaction_limit_exceeded', 'message': 'Amount exceeds per-transaction limit'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Check daily limit (auto-resets at midnight)
                from wallet.services.limits import get_daily_sent_amount
                sent_today = get_daily_sent_amount(sender)
                
                if sent_today + amount > sender.send_limit_daily:
                    TransferAttempt.objects.create(
                        user=sender,
                        recipient_handle_input=recipient_phone,
                        amount=amount,
                        currency=currency,
                        rejection_reason='daily_limit_exceeded'
                    )
                    AuditLog.objects.create(
                        user=sender,
                        action='transfer_failed_daily_limit_exceeded',
                        metadata={
                            'recipient_phone': recipient_phone,
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
                            'recipient_phone': recipient_phone,
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
                
                # Create transaction with exchange rate if cross-currency
                transaction_obj = Transaction.objects.create(
                    type=TransactionType.P2P_TRANSFER,
                    sender=sender,
                    recipient=recipient,
                    amount=amount,
                    currency=sender_wallet.currency,  # Always store in sender's currency
                    note=note,
                    status=TransactionStatus.COMPLETED,
                    exchange_rate=exchange_rate_obj  # Store the locked rate for cross-currency transfers
                )
                
                # Create ledger entries (debit sender, credit recipient with converted amount)
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
                    amount=converted_amount  # Use converted amount for recipient
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
                        'recipient_phone': recipient_phone,
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
                        'recipient_phone': recipient_phone,
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
            
            # Create transaction approval request
            from wallet.services.webhooks import create_transaction_approval
            create_transaction_approval(
                transaction=transaction_obj,
                approver=recipient,
                requester=sender,
                approval_type='money_received',
                amount=amount,
                currency=currency,
                note=note
            )

            apply_usage_based_limits(sender)
            
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

        from wallet.services.notifications import remove_expired_approval_notifications
        remove_expired_approval_notifications(request.user)
        
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
        from wallet.services.limits import apply_usage_based_limits
        apply_usage_based_limits(request.user)
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
        since = request.query_params.get('since')
        until = request.query_params.get('until')
        if since:
            transactions = transactions.filter(created_at__date__gte=since)
        if until:
            transactions = transactions.filter(created_at__date__lte=until)
        
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
    responses={200: dict},
    tags=['Admin']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_requests_list(request):
    try:
        status_filter = request.query_params.get('status', '').strip()
        queryset = PaymentRequest.objects.select_related('requester', 'payer').order_by('-created_at')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return Response(
            [
                {
                    'id': pr.id,
                    'requester_handle': pr.requester.handle,
                    'payer_handle': pr.payer.handle if pr.payer else None,
                    'amount': str(pr.amount),
                    'currency': pr.currency,
                    'status': pr.status,
                    'note': pr.note,
                    'created_at': pr.created_at.isoformat(),
                }
                for pr in queryset
            ],
            status=status.HTTP_200_OK,
        )
    except Exception as exc:
        logger.exception('admin_requests_list_error')
        return Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    responses={200: dict},
    tags=['Admin']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_splits_list(request):
    try:
        status_filter = request.query_params.get('status', '').strip()
        queryset = SplitRequest.objects.select_related('creator').prefetch_related('participants__payment_request__payer').order_by('-created_at')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        result = []
        for split in queryset:
            result.append({
                'id': split.id,
                'creator_handle': split.creator.handle,
                'total_amount': str(split.total_amount),
                'currency': split.currency,
                'note': split.note,
                'status': split.status,
                'created_at': split.created_at.isoformat(),
                'participants': [
                    {
                        'payment_request_id': participant.payment_request_id,
                        'payer_handle': participant.payment_request.payer.handle if participant.payment_request.payer else None,
                        'amount_owed': str(participant.amount_owed),
                    }
                    for participant in split.participants.all()
                ],
            })
        return Response(result, status=status.HTTP_200_OK)
    except Exception as exc:
        logger.exception('admin_splits_list_error')
        return Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def ensure_default_system_settings():
    """Seed a small, usable settings catalog so the admin UI is never blank."""
    defaults = [
        {
            'key': 'default_currency',
            'value': 'GNF',
            'description': 'Default fiat currency for new wallet accounts.'
        },
        {
            'key': 'max_daily_transfer_limit',
            'value': '5000.00',
            'description': 'Default max daily transfer threshold for a user.'
        },
        {
            'key': 'max_single_transfer_limit',
            'value': '1000.00',
            'description': 'Default single-transfer limit.'
        },
        {
            'key': 'usage_transfers_per_step',
            'value': '5',
            'description': 'Completed outgoing transfers required to raise sending limits by one step.'
        },
        {
            'key': 'usage_volume_per_step',
            'value': '50000.00',
            'description': 'Completed outgoing volume that also raises sending limits by one step.'
        },
        {
            'key': 'usage_per_tx_increase',
            'value': '500.00',
            'description': 'Amount added to the per-transaction limit for each usage step.'
        },
        {
            'key': 'usage_daily_increase',
            'value': '2500.00',
            'description': 'Amount added to the daily sending limit for each usage step.'
        },
        {
            'key': 'usage_max_steps',
            'value': '10',
            'description': 'Maximum number of usage-based limit increases.'
        },
        {
            'key': 'kyc_tier_1_per_tx_bonus',
            'value': '2000.00',
            'description': 'Extra per-transaction limit granted at KYC tier 1.'
        },
        {
            'key': 'kyc_tier_1_daily_bonus',
            'value': '10000.00',
            'description': 'Extra daily sending limit granted at KYC tier 1.'
        },
        {
            'key': 'kyc_tier_2_per_tx_bonus',
            'value': '10000.00',
            'description': 'Extra per-transaction limit granted at KYC tier 2.'
        },
        {
            'key': 'kyc_tier_2_daily_bonus',
            'value': '50000.00',
            'description': 'Extra daily sending limit granted at KYC tier 2.'
        },
        {
            'key': 'kyc_required_for_large_transfers',
            'value': 'true',
            'description': 'Require KYC verification before large transfers are allowed.'
        },
        {
            'key': 'fraud_review_email',
            'value': 'security@kesho.app',
            'description': 'Primary email for review escalations and alerts.'
        },
    ]

    for item in defaults:
        SystemSetting.objects.get_or_create(
            key=item['key'],
            defaults={
                'value': item['value'],
                'description': item['description'],
                'updated_by': None,
            }
        )

    return SystemSetting.objects.order_by('key')


def apply_admin_topup(admin_user, target_user, amount, currency='GNF', note='', reason=''):
    """Create a ledger-safe top-up as admin -> target with both sides mirrored in ledger entries."""
    if amount <= 0:
        raise ValidationError('Top-up amount must be greater than zero.')

    if target_user.is_staff:
        raise ValidationError('Admin top-ups are only supported for operational users.')

    with transaction.atomic():
        admin = User.objects.select_for_update().get(pk=admin_user.pk)
        target = User.objects.select_for_update().get(pk=target_user.pk)

        admin_wallet = getattr(admin, 'wallet', None)
        if admin_wallet is None:
            admin_wallet = Wallet.objects.create(user=admin, currency=currency, status=WalletStatus.ACTIVE)
            LedgerEntry.objects.create(
                wallet=admin_wallet,
                transaction=None,
                direction=LedgerDirection.CREDIT,
                amount=Decimal('0.00')
            )

        target_wallet = getattr(target, 'wallet', None)
        if target_wallet is None:
            target_wallet = Wallet.objects.create(user=target, currency=currency, status=WalletStatus.ACTIVE)
            LedgerEntry.objects.create(
                wallet=target_wallet,
                transaction=None,
                direction=LedgerDirection.CREDIT,
                amount=Decimal('0.00')
            )

        if target_wallet.status != WalletStatus.ACTIVE:
            raise ValidationError('Target wallet is not active and cannot receive a top-up.')

        transaction_obj = Transaction.objects.create(
            type=TransactionType.TOPUP,
            sender=admin,
            recipient=target,
            amount=amount,
            currency=currency,
            note=note or 'Admin-initiated wallet top-up',
            status=TransactionStatus.COMPLETED,
        )

        LedgerEntry.objects.create(
            wallet=admin_wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.DEBIT,
            amount=amount,
        )

        LedgerEntry.objects.create(
            wallet=target_wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.CREDIT,
            amount=amount,
        )

        AuditLog.objects.create(
            user=admin,
            action='admin_topup',
            metadata={
                'target_user_id': str(target.id),
                'target_user_handle': target.handle,
                'amount': str(amount),
                'currency': currency,
                'reason': reason,
            }
        )

        create_notification(
            target,
            'wallet_topup',
            {
                'admin_handle': admin.handle,
                'amount': str(amount),
                'currency': currency,
                'note': note or 'Admin-initiated wallet top-up',
                'transaction_id': str(transaction_obj.id),
            },
        )

        return transaction_obj


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
        regular_users = User.objects.filter(is_staff=False)

        # User counts by status
        total_users = regular_users.count()
        active_users = regular_users.filter(status=UserStatus.ACTIVE).count()
        suspended_users = regular_users.filter(status=UserStatus.SUSPENDED).count()
        closed_users = regular_users.filter(status=UserStatus.CLOSED).count()

        # Wallet counts
        total_wallets = Wallet.objects.filter(user__is_staff=False).count()
        frozen_wallets = Wallet.objects.filter(user__is_staff=False, status=WalletStatus.FROZEN).count()

        # P2P volume
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)

        p2p_volume_today = Transaction.objects.filter(
            type=TransactionType.P2P_TRANSFER,
            status=TransactionStatus.COMPLETED,
            created_at__date=today,
            sender__is_staff=False,
            recipient__is_staff=False,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        p2p_volume_week = Transaction.objects.filter(
            type=TransactionType.P2P_TRANSFER,
            status=TransactionStatus.COMPLETED,
            created_at__date__gte=week_ago,
            sender__is_staff=False,
            recipient__is_staff=False,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Pending payment requests
        pending_payment_requests = PaymentRequest.objects.filter(
            requester__is_staff=False,
            status=PaymentRequestStatus.PENDING,
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

        # Exclude internal staff accounts from the operational user list.
        users = User.objects.select_related('wallet').filter(is_staff=False)

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
        ).filter(is_staff=False).get(id=user_id)

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
    request=AdminTopUpSerializer,
    responses={200: AdminUserDetailSerializer, 400: dict},
    tags=['Admin']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_topup_user(request, user_id):
    """Top up a non-admin user wallet using a balanced debit/credit ledger entry."""
    serializer = AdminTopUpSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    amount = serializer.validated_data['amount']
    currency = serializer.validated_data.get('currency', 'GNF')
    note = serializer.validated_data.get('note', '')
    reason = serializer.validated_data.get('reason', '').strip()

    if not reason:
        return Response(
            {'error': 'Reason is required for all admin actions'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        target_user = User.objects.select_related('wallet').filter(is_staff=False).get(id=user_id)
        transaction_obj = apply_admin_topup(
            request.user,
            target_user,
            amount,
            currency=currency,
            note=note,
            reason=reason,
        )

        serializer_out = AdminUserDetailSerializer(target_user)
        return Response(serializer_out.data, status=status.HTTP_200_OK)

    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    except ValidationError as exc:
        message = exc.message if hasattr(exc, 'message') else str(exc)
        return Response({'code': 'validation_error', 'message': message}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        logger.error(
            json.dumps({
                'event': 'admin_topup_error',
                'admin_user_id': str(request.user.id),
                'target_user_id': user_id,
                'error': str(exc),
                'timestamp': timezone.now().isoformat(),
            })
        )
        return Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
                    user.limits_manually_set = True
                    changes['send_limit_per_tx'] = {'old': str(old_limit), 'new': str(new_limit)}
            
            if 'send_limit_daily' in serializer.validated_data:
                old_limit = user.send_limit_daily
                new_limit = serializer.validated_data['send_limit_daily']
                if old_limit != new_limit:
                    user.send_limit_daily = new_limit
                    user.limits_manually_set = True
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
            if 'kyc_tier' in changes and not user.limits_manually_set:
                from wallet.services.limits import apply_usage_based_limits
                apply_usage_based_limits(user)
            
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


@extend_schema(
    responses={200: dict},
    tags=['Admin']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_reconciliation_last_run(request):
    from wallet.services.reconciliation import get_reconciliation_last_run

    return Response(get_reconciliation_last_run() or {'status': 'never_run'}, status=status.HTTP_200_OK)


@extend_schema(
    responses={202: dict},
    tags=['Admin']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_reconciliation_run(request):
    from wallet.tasks import reconcile_balances_task

    fix = request.data.get('fix', False)
    async_result = reconcile_balances_task.delay(fix=fix)
    return Response(
        {'status': 'queued', 'task_id': async_result.id},
        status=status.HTTP_202_ACCEPTED,
    )


@extend_schema(
    responses={200: dict},
    tags=['Admin']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_settings_list(request):
    try:
        settings = SystemSetting.objects.order_by('key')
        if not settings.exists():
            settings = ensure_default_system_settings()
        serializer = SystemSettingSerializer(settings, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Exception as exc:
        logger.exception('admin_settings_list_error')
        return Response({'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    request=SystemSettingSerializer,
    responses={200: dict, 400: dict},
    tags=['Admin']
)
@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def admin_settings_update(request, key):
    try:
        setting = SystemSetting.objects.get(key=key)
    except SystemSetting.DoesNotExist:
        return Response({'error': 'Setting not found'}, status=status.HTTP_404_NOT_FOUND)

    value = request.data.get('value')
    if value is None:
        return Response({'error': 'Value is required.'}, status=status.HTTP_400_BAD_REQUEST)

    old_value = setting.value
    setting.value = str(value)
    setting.updated_by = request.user
    setting.save(update_fields=['value', 'updated_by', 'updated_at'])

    AuditLog.objects.create(
        user=request.user,
        action='admin_setting_update',
        metadata={'key': key, 'old_value': old_value, 'new_value': setting.value, 'reason': request.data.get('reason', '')},
    )
    return Response({'key': setting.key, 'value': setting.value, 'description': setting.description, 'updated_at': setting.updated_at.isoformat()}, status=status.HTTP_200_OK)


# ---- REQUEST MONEY (A1) ENDPOINTS ----

@extend_schema(
    request=PaymentRequestCreateSerializer,
    responses={201: PaymentRequestSerializer, 400: dict},
    tags=['Requests']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def create_payment_request(request):
    """Create a payment request from requester to payer."""
    serializer = PaymentRequestCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    requester = request.user
    payer_phone = serializer.validated_data['payer_phone']
    amount = serializer.validated_data['amount']
    currency = serializer.validated_data['currency']
    from wallet.services.fees import resolve_withdrawal_fee
    fee_amount, _ = resolve_withdrawal_fee(amount, currency)
    note = serializer.validated_data.get('note', '')
    
    try:
        if amount.as_tuple().exponent < -2:
            raise ValidationError('Amount cannot have more than 2 decimal places')
        
        if requester.primary_phone_number == payer_phone:
            return Response(
                {'error': 'You cannot request money from yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payer = User.objects.filter(primary_phone_number=payer_phone, status=UserStatus.ACTIVE).first()
        if not payer:
            return Response(
                {'error': 'Payer not found or inactive'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if not hasattr(payer, 'wallet') or payer.wallet.status != WalletStatus.ACTIVE:
            return Response(
                {'error': 'Payer wallet is not active'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment_request = PaymentRequest.objects.create(
            requester=requester,
            payer=payer,
            amount=amount,
            currency=currency,
            note=note,
            status=PaymentRequestStatus.PENDING
        )
        
        # Create transaction approval request
        from wallet.services.webhooks import create_payment_request_approval
        approval = create_payment_request_approval(payment_request)
        create_notification(
            payer,
            'payment_request_received',
            {
                'approval_id': approval.id,
                'requester_display_name': requester.display_name,
                'amount': str(amount),
                'currency': currency,
                'note': note,
                'payment_request_id': payment_request.id,
            }
        )
        
        return Response(
            PaymentRequestSerializer(payment_request).data,
            status=status.HTTP_201_CREATED
        )
    
    except ValidationError as exc:
        return Response(
            {'error': str(exc.message) if hasattr(exc, 'message') else str(exc)},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f'create_payment_request_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: PaymentRequestSerializer},
    tags=['Requests']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_payment_requests(request):
    """List payment requests for the authenticated user (sent or received)."""
    try:
        direction = request.query_params.get('direction', 'received').strip()
        status_filter = request.query_params.get('status', '').strip()
        cursor = request.query_params.get('cursor', '').strip()
        
        if direction == 'sent':
            requests_qs = PaymentRequest.objects.filter(requester=request.user)
        elif direction == 'received':
            requests_qs = PaymentRequest.objects.filter(payer=request.user)
        else:
            return Response(
                {'error': 'direction must be "sent" or "received"'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if status_filter:
            requests_qs = requests_qs.filter(status=status_filter)
        
        now = timezone.now()
        requests_qs.filter(status=PaymentRequestStatus.PENDING, expires_at__lt=now).update(
            status=PaymentRequestStatus.EXPIRED
        )
        
        from rest_framework.pagination import CursorPagination
        paginator = CursorPagination()
        paginator.page_size = 20
        paginator.ordering = '-created_at'
        
        paginated = paginator.paginate_queryset(requests_qs, request)
        serializer = PaymentRequestSerializer(paginated, many=True)
        return paginator.get_paginated_response(serializer.data)
    
    except Exception as e:
        logger.error(f'get_payment_requests_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: PaymentRequestSerializer},
    tags=['Requests']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_payment_request_detail(request, request_id):
    """Get a single payment request."""
    try:
        payment_request = PaymentRequest.objects.get(id=request_id)
        
        if request.user != payment_request.requester and request.user != payment_request.payer:
            return Response(
                {'error': 'Access denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if payment_request.status == PaymentRequestStatus.PENDING and payment_request.expires_at < timezone.now():
            payment_request.status = PaymentRequestStatus.EXPIRED
            payment_request.save()
        
        return Response(
            PaymentRequestSerializer(payment_request).data,
            status=status.HTTP_200_OK
        )
    
    except PaymentRequest.DoesNotExist:
        return Response(
            {'error': 'Request not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'get_payment_request_detail_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    request=TransferRequestSerializer,
    responses={200: PaymentRequestSerializer, 400: dict},
    tags=['Requests']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def pay_payment_request(request, request_id):
    """Pay a payment request (payer accepts)."""
    if step_up_required(request, OtpChallenge.Purpose.TRANSFER):
        return Response({'code': 'otp_required', 'purpose': OtpChallenge.Purpose.TRANSFER, 'error': 'Fresh device verification is required before paying this request.'}, status=status.HTTP_403_FORBIDDEN)
    if not user_has_approved_kyc(request.user):
        return Response({'error': 'KYC verification is required before sending money. Please submit your ID details first.'}, status=status.HTTP_403_FORBIDDEN)
    try:
        payment_request = PaymentRequest.objects.select_for_update().get(id=request_id)
        
        if request.user != payment_request.payer:
            return Response(
                {'error': 'Only the payer can pay this request'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if payment_request.status != PaymentRequestStatus.PENDING:
            return Response(
                {'error': f'Request status is {payment_request.status}, not pending'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if payment_request.expires_at < timezone.now():
            payment_request.status = PaymentRequestStatus.EXPIRED
            payment_request.save(update_fields=['status'])
            return Response({'error': 'This request has expired'}, status=status.HTTP_400_BAD_REQUEST)

        # Check for existing pending approval to prevent duplicates
        approval = payment_request.approval_requests.filter(
            approver=request.user,
            status=TransactionApproval.ApprovalStatus.PENDING,
        ).order_by('-created_at').first()
        if approval:
            return Response(
                {'status': 'pending_approval', 'approval_id': approval.id},
                status=status.HTTP_202_ACCEPTED,
            )

        # Create approval request for payer to confirm with PIN
        approval = TransactionApproval.objects.create(
            approver=request.user,
            requester=payment_request.requester,
            approval_type='payment_request',
            amount=payment_request.amount,
            currency=payment_request.currency,
            note=payment_request.note or 'Payment request',
            payment_request=payment_request,
        )
        create_notification(
            request.user,
            'payment_request_received',
            {
                'approval_id': approval.id,
                'requester_handle': payment_request.requester.handle,
                'requester_display_name': payment_request.requester.display_name,
                'amount': str(payment_request.amount),
                'currency': payment_request.currency,
                'note': payment_request.note,
            },
        )
        return Response(
            {'status': 'pending_approval', 'approval_id': approval.id},
            status=status.HTTP_202_ACCEPTED,
        )

        payer = request.user
        from wallet.services.limits import apply_usage_based_limits
        apply_usage_based_limits(payer)
        requester = payment_request.requester
        amount = payment_request.amount
        currency = payment_request.currency
        note = payment_request.note or 'Payment for request'
        
        idempotency_key = request.data.get('idempotency_key', '')
        if not idempotency_key:
            return Response(
                {'error': 'idempotency_key is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if ProcessedRequest.objects.filter(idempotency_key=idempotency_key).exists():
            existing = ProcessedRequest.objects.get(idempotency_key=idempotency_key)
            if existing.transaction:
                payment_request.refresh_from_db()
                return Response(
                    PaymentRequestSerializer(payment_request).data,
                    status=status.HTTP_200_OK
                )
        
        with transaction.atomic():
            payer_wallet = payer.wallet
            requester_wallet = requester.wallet
            
            if payer.status != UserStatus.ACTIVE:
                return Response(
                    {'code': 'payer_account_suspended', 'message': 'Payer account is suspended'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if payer_wallet.status != WalletStatus.ACTIVE:
                return Response(
                    {'code': 'payer_wallet_frozen', 'message': 'Payer wallet is frozen'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            current_balance = payer_wallet.get_balance()
            if current_balance < amount:
                return Response(
                    {'code': 'insufficient_funds', 'message': 'Insufficient funds'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if amount > payer.send_limit_per_tx:
                return Response(
                    {'code': 'per_transaction_limit_exceeded', 'message': 'Amount exceeds per-transaction limit'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check daily limit (auto-resets at midnight)
            from wallet.services.limits import get_daily_sent_amount
            sent_today = get_daily_sent_amount(payer)
            
            if sent_today + amount > payer.send_limit_daily:
                return Response(
                    {'code': 'daily_limit_exceeded', 'message': 'Amount exceeds daily limit'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            transaction_obj = Transaction.objects.create(
                type=TransactionType.P2P_TRANSFER,
                sender=payer,
                recipient=requester,
                amount=amount,
                currency=currency,
                note=note,
                status=TransactionStatus.COMPLETED
            )
            
            LedgerEntry.objects.create(
                wallet=payer_wallet,
                transaction=transaction_obj,
                direction=LedgerDirection.DEBIT,
                amount=amount
            )
            
            LedgerEntry.objects.create(
                wallet=requester_wallet,
                transaction=transaction_obj,
                direction=LedgerDirection.CREDIT,
                amount=amount
            )
            
            ProcessedRequest.objects.create(
                idempotency_key=idempotency_key,
                user=payer,
                transaction=transaction_obj
            )
            
            payment_request.status = PaymentRequestStatus.PAID
            payment_request.resulting_transaction = transaction_obj
            payment_request.save()
            
            AuditLog.objects.create(
                user=payer,
                action='payment_request_paid',
                metadata={
                    'payment_request_id': payment_request.id,
                    'transaction_id': str(transaction_obj.id),
                    'requester_handle': requester.handle,
                    'amount': str(amount)
                }
            )
        
        create_notification(
            requester,
            'payment_request_paid',
            {
                'payer_handle': payer.handle,
                'payer_display_name': payer.display_name,
                'amount': str(amount),
                'currency': currency,
                'payment_request_id': payment_request.id,
                'transaction_id': str(transaction_obj.id)
            }
        )
        
        return Response(
            PaymentRequestSerializer(payment_request).data,
            status=status.HTTP_200_OK
        )
    
    except PaymentRequest.DoesNotExist:
        return Response(
            {'error': 'Request not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'pay_payment_request_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: PaymentRequestSerializer},
    tags=['Requests']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def decline_payment_request(request, request_id):
    """Decline a payment request."""
    try:
        payment_request = PaymentRequest.objects.get(id=request_id)
        
        if request.user != payment_request.payer:
            return Response(
                {'error': 'Only the payer can decline this request'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if payment_request.status != PaymentRequestStatus.PENDING:
            return Response(
                {'error': f'Request status is {payment_request.status}, not pending'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment_request.status = PaymentRequestStatus.DECLINED
        payment_request.save()
        
        create_notification(
            payment_request.requester,
            'payment_request_declined',
            {
                'payer_handle': request.user.handle,
                'payer_display_name': request.user.display_name,
                'amount': str(payment_request.amount),
                'currency': payment_request.currency,
                'payment_request_id': payment_request.id
            }
        )
        
        AuditLog.objects.create(
            user=request.user,
            action='payment_request_declined',
            metadata={'payment_request_id': payment_request.id}
        )
        
        return Response(
            PaymentRequestSerializer(payment_request).data,
            status=status.HTTP_200_OK
        )
    
    except PaymentRequest.DoesNotExist:
        return Response(
            {'error': 'Request not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'decline_payment_request_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: PaymentRequestSerializer},
    tags=['Requests']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_payment_request(request, request_id):
    """Cancel a payment request (requester only)."""
    try:
        payment_request = PaymentRequest.objects.get(id=request_id)
        
        if request.user != payment_request.requester:
            return Response(
                {'error': 'Only the requester can cancel this request'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if payment_request.status != PaymentRequestStatus.PENDING:
            return Response(
                {'error': f'Request status is {payment_request.status}, not pending'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment_request.status = PaymentRequestStatus.CANCELLED
        payment_request.save()
        
        AuditLog.objects.create(
            user=request.user,
            action='payment_request_cancelled',
            metadata={'payment_request_id': payment_request.id}
        )
        
        return Response(
            PaymentRequestSerializer(payment_request).data,
            status=status.HTTP_200_OK
        )
    
    except PaymentRequest.DoesNotExist:
        return Response(
            {'error': 'Request not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'cancel_payment_request_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ---- QR CODE PAYMENTS (A2) ----

import hmac
import hashlib
import base64
from django.conf import settings

def get_qr_signing_secret():
    """Get the QR signing secret from environment or settings."""
    return getattr(settings, 'QR_SIGNING_SECRET', 'dev-secret-key')

@extend_schema(
    responses={200: dict},
    tags=['QR']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_qr_payload(request):
    """Generate a signed QR payload for the current user."""
    try:
        amount = request.query_params.get('amount', '').strip()
        note = request.query_params.get('note', '').strip()
        
        user = request.user
        exp = int((timezone.now() + timedelta(hours=24)).timestamp())
        
        payload = {
            'type': 'pay',
            'handle': user.handle,
            'phone': user.primary_phone_number,
            'exp': exp
        }
        if amount:
            payload['amount'] = amount
        if note:
            payload['note'] = note
        
        payload_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        secret = get_qr_signing_secret()
        signature = hmac.new(
            secret.encode(),
            payload_json.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return Response(
            {
                'payload': payload_json,
                'signature': signature,
                'encoded': base64.b64encode((payload_json + '|' + signature).encode()).decode()
            },
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        logger.error(f'get_qr_payload_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    request={'type': 'object', 'properties': {'encoded': {'type': 'string'}}},
    responses={200: dict, 400: dict},
    tags=['QR']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_qr_payload(request):
    """Verify and decode a QR code payload."""
    try:
        encoded = request.data.get('encoded', '').strip()
        
        if not encoded:
            return Response(
                {'error': 'Encoded payload is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Decode the base64 payload
        try:
            decoded = base64.b64decode(encoded).decode()
            payload_json, signature = decoded.rsplit('|', 1)
        except Exception:
            return Response(
                {'error': 'Invalid encoded payload format'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify the signature
        if not verify_qr_signature(payload_json, signature):
            return Response(
                {'error': 'Invalid signature'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Parse the payload
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            return Response(
                {'error': 'Invalid payload JSON'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check expiration
        exp = payload.get('exp')
        if exp:
            from datetime import datetime as dt
            from datetime import timezone as datetime_timezone
            exp_time = dt.fromtimestamp(exp, tz=datetime_timezone.utc)
            if timezone.now() > exp_time:
                return Response(
                    {'error': 'QR code has expired'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Validate payload structure
        if payload.get('type') not in ('pay', 'merchant_pay'):
            return Response(
                {'error': 'Invalid QR code type'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        phone = payload.get('phone')
        if not phone:
            return Response(
                {'error': 'Missing phone in payload'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Resolve the user
        try:
            user = User.objects.get(primary_phone_number=phone, status=UserStatus.ACTIVE)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found or inactive'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response(
            {
                'valid': True,
                'primary_phone_number': user.primary_phone_number,
                'handle': user.handle,
                'display_name': user.display_name,
                'avatar_url': user.avatar_url,
                'amount': payload.get('amount'),
                'note': payload.get('note', '')
            },
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        logger.error(f'verify_qr_payload_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pay_qr_payload(request):
    """Pay a signed user QR code after the payer confirms the amount."""
    encoded = str(request.data.get('encoded', '')).strip()
    amount = request.data.get('amount')
    if step_up_required(request, OtpChallenge.Purpose.TRANSFER):
        return Response({'code': 'otp_required', 'purpose': OtpChallenge.Purpose.TRANSFER, 'error': 'Fresh device verification is required before paying by QR.'}, status=status.HTTP_403_FORBIDDEN)
    if not user_has_approved_kyc(request.user):
        return Response({'error': 'KYC verification is required before scanning or sending QR payments. Please submit your ID details first.'}, status=status.HTTP_403_FORBIDDEN)
    if not encoded or amount in (None, ''):
        return Response({'error': 'encoded and amount are required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        decoded = base64.b64decode(encoded).decode()
        payload_json, signature = decoded.rsplit('|', 1)
        if not verify_qr_signature(payload_json, signature):
            return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)
        payload = json.loads(payload_json)
        if payload.get('type') not in ('pay', 'merchant_pay') or (payload.get('exp') and timezone.now().timestamp() > payload['exp']):
            return Response({'error': 'QR code is invalid or expired'}, status=status.HTTP_400_BAD_REQUEST)
        recipient = User.objects.get(primary_phone_number=payload['phone'], status=UserStatus.ACTIVE)
        if recipient == request.user:
            return Response({'error': 'Cannot pay yourself'}, status=status.HTTP_400_BAD_REQUEST)
        
        # For QR payments, the payer (scanner) is the one initiating the payment
        # so they should be the requester, and we don't require recipient approval
        # Create approval for the payer to confirm with PIN
        from decimal import Decimal
        amount_decimal = Decimal(str(amount))
        currency = request.data.get('currency', 'GNF')
        note = request.data.get('note') or payload.get('note', 'QR payment')
        
        # Check for existing pending approval to prevent duplicates
        pending_approval = TransactionApproval.objects.filter(
            requester=request.user,
            approver=request.user,
            approval_type='qr_payment',
            status=TransactionApproval.ApprovalStatus.PENDING,
            note=note,
            amount=amount_decimal,
        ).order_by('-created_at').first()
        if pending_approval:
            return Response(
                {'status': 'pending_approval', 'approval_id': pending_approval.id},
                status=status.HTTP_202_ACCEPTED,
            )
        
        # Create approval request for payer to confirm with PIN
        approval = TransactionApproval.objects.create(
            approver=request.user,
            requester=request.user,
            approval_type='qr_payment',
            amount=amount_decimal,
            currency=currency,
            note=note,
            metadata={'recipient_id': recipient.id, 'qr_payload': payload}
        )
        
        # Notify recipient about incoming QR payment
        create_notification(
            recipient,
            'incoming_qr_payment',
            {
                'payer_handle': request.user.handle,
                'payer_display_name': request.user.display_name,
                'amount': str(amount_decimal),
                'currency': currency,
                'note': note,
            },
        )
        
        return Response(
            {'status': 'pending_approval', 'approval_id': approval.id},
            status=status.HTTP_202_ACCEPTED,
        )
    except User.DoesNotExist:
        return Response({'error': 'User not found or inactive'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as exc:
        logger.exception('pay_qr_payload_error')
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_linked_providers(request):
    providers = request.user.linked_providers.order_by('-created_at')
    return Response([
        {'id': item.id, 'provider': item.provider, 'masked_reference': item.masked_reference,
         'verification_status': item.verification_status, 'created_at': item.created_at}
        for item in providers
    ])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def link_mobile_money_provider(request):
    if step_up_required(request, OtpChallenge.Purpose.PROVIDER_LINK):
        return Response({'code': 'otp_required', 'purpose': OtpChallenge.Purpose.PROVIDER_LINK, 'error': 'Fresh device verification is required before linking a provider.'}, status=status.HTTP_403_FORBIDDEN)
    provider = str(request.data.get('provider', '')).strip()
    phone = str(request.data.get('phone_number', '')).strip()
    valid = [choice[0] for choice in LinkedProvider.ProviderType.choices]
    if provider not in valid or len(phone) < 7:
        return Response({'error': 'provider and a valid phone_number are required'}, status=status.HTTP_400_BAD_REQUEST)
    linked, _ = LinkedProvider.objects.update_or_create(
        user=request.user, provider=provider,
        defaults={'masked_reference': f'****{phone[-4:]}', 'verification_status': 'verified',
                  'provider_metadata': {'phone_number': phone, 'simulation': True}},
    )
    return Response({'id': linked.id, 'provider': linked.provider, 'masked_reference': linked.masked_reference,
                     'verification_status': linked.verification_status, 'simulation': True}, status=status.HTTP_201_CREATED)


# ---- BILL SPLITTING (A3) ----

@extend_schema(
    request=SplitCreateSerializer,
    responses={201: dict, 400: dict},
    tags=['Splits']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_split(request):
    """Create a bill split with multiple participants."""
    try:
        data = request.data
        creator = request.user
        try:
            total_amount = Decimal(str(data.get('total_amount', '0')))
        except (InvalidOperation, TypeError, ValueError):
            return Response({'error': 'Total amount must be a valid number'}, status=status.HTTP_400_BAD_REQUEST)
        currency = data.get('currency', 'GNF')
        note = data.get('note', '')
        participants_data = data.get('participants', [])
        
        if total_amount <= 0:
            return Response(
                {'error': 'Total amount must be greater than zero'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if creator.status != UserStatus.ACTIVE or creator.wallet.status != WalletStatus.ACTIVE:
            return Response({'error': 'Your account or wallet is not active'}, status=status.HTTP_403_FORBIDDEN)
        
        participants_list = []
        total_assigned = Decimal('0.00')
        participant_phones = set()
        
        for p in participants_data:
            phone = str(p.get('phone', '')).strip()
            amount_str = str(p.get('amount', '')).strip()
            
            if not phone or not amount_str:
                return Response(
                    {'error': 'Each participant must have a phone number and amount'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if phone in participant_phones:
                return Response({'error': f'Participant {phone} was added more than once'}, status=status.HTTP_400_BAD_REQUEST)
            if phone == creator.primary_phone_number:
                return Response({'error': 'You cannot add yourself to your split bill'}, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                amount = Decimal(amount_str)
            except (InvalidOperation, TypeError, ValueError):
                return Response(
                    {'error': f'Invalid amount for {phone}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if amount <= 0:
                return Response(
                    {'error': f'Amount for {phone} must be greater than zero'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            total_assigned += amount
            participant_phones.add(phone)
            participants_list.append({'phone': phone, 'amount': amount})
        
        if total_assigned != total_amount:
            return Response(
                {'error': f'Participant amounts sum to {total_assigned}, not {total_amount}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        with transaction.atomic():
            split = SplitRequest.objects.create(
                creator=creator,
                total_amount=total_amount,
                currency=currency,
                note=note,
                status='pending'
            )
            
            for p in participants_list:
                payer_phone = p['phone']
                amount_owed = p['amount']
                
                payer = User.objects.filter(primary_phone_number=payer_phone, status=UserStatus.ACTIVE).first()
                if not payer:
                    raise ValidationError(f'Payer {payer_phone} not found or inactive')
                
                payment_request = PaymentRequest.objects.create(
                    requester=creator,
                    payer=payer,
                    amount=amount_owed,
                    currency=currency,
                    note=f'Split payment: {note}' if note else 'Split payment',
                    status=PaymentRequestStatus.PENDING
                )
                
                SplitParticipant.objects.create(
                    split_request=split,
                    payment_request=payment_request,
                    amount_owed=amount_owed
                )
                
                # Create transaction approval request for split participant
                from wallet.services.webhooks import create_split_approval
                participant_obj = split.participants.get(payment_request=payment_request)
                approval = create_split_approval(split, participant_obj)
                create_notification(
                    payer,
                    'split_request_received',
                    {
                        'approval_id': approval.id,
                        'creator_display_name': creator.display_name,
                        'amount': str(amount_owed),
                        'currency': currency,
                        'total_split_amount': str(total_amount),
                        'split_id': split.id,
                        'payment_request_id': payment_request.id,
                    }
                )
        
        return Response(
            {
                'id': split.id,
                'creator_handle': creator.handle,
                'total_amount': str(total_amount),
                'currency': currency,
                'note': note,
                'status': split.status,
                'created_at': split.created_at.isoformat(),
                'participants': [
                    {
                        'phone': p['phone'],
                        'amount': str(p['amount']),
                        'status': 'pending'
                    }
                    for p in participants_list
                ]
            },
            status=status.HTTP_201_CREATED
        )
    
    except ValidationError as exc:
        return Response(
            {'error': str(exc.message) if hasattr(exc, 'message') else str(exc)},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f'create_split_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: dict, 400: dict, 404: dict},
    tags=['Splits']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_split(request, split_id):
    """Cancel a split request with cascade to child payment requests."""
    try:
        with transaction.atomic():
            split = SplitRequest.objects.select_for_update().get(id=split_id)

            # Check if the user is the creator
            if request.user != split.creator:
                return Response(
                    {'error': 'Only the creator can cancel this split'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Check if split is already cancelled
            if split.status == SplitRequest.SplitStatus.CANCELLED:
                return Response(
                    {'error': 'Split is already cancelled'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if split is already paid
            if split.status == SplitRequest.SplitStatus.PAID:
                return Response(
                    {'error': 'Cannot cancel a paid split'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Cancel all associated payment requests
            participants = split.participants.select_related('payment_request').all()
            cancelled_count = 0

            for participant in participants:
                payment_request = participant.payment_request
                if payment_request.status == PaymentRequestStatus.PENDING:
                    payment_request.status = PaymentRequestStatus.CANCELLED
                    payment_request.save()
                    cancelled_count += 1

                    # Notify the payer
                    create_notification(
                        payment_request.payer,
                        'payment_request_cancelled',
                        {
                            'requester_handle': split.creator.handle,
                            'split_id': split.id,
                            'payment_request_id': payment_request.id
                        }
                    )

            # Update split status
            split.status = SplitRequest.SplitStatus.CANCELLED
            split.cancellation_reason = request.data.get('reason', 'Cancelled by creator')
            split.save()

            # Audit log
            AuditLog.objects.create(
                user=request.user,
                action='split_cancelled',
                metadata={
                    'split_id': split.id,
                    'cancelled_payment_requests': cancelled_count,
                    'reason': split.cancellation_reason
                }
            )

            return Response(
                {
                    'id': split.id,
                    'status': split.status,
                    'cancelled_payment_requests': cancelled_count,
                    'message': f'Split cancelled and {cancelled_count} payment requests cancelled'
                },
                status=status.HTTP_200_OK
            )

    except SplitRequest.DoesNotExist:
        return Response(
            {'error': 'Split not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'cancel_split_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: dict},
    tags=['Splits']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_split_detail(request, split_id):
    """Get split detail with participant statuses."""
    try:
        split = SplitRequest.objects.prefetch_related(
            'participants__payment_request'
        ).get(id=split_id)
        
        if request.user != split.creator and request.user not in [
            p.payment_request.payer for p in split.participants.all()
        ]:
            return Response(
                {'error': 'Access denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        participants = []
        paid_count = 0
        for participant in split.participants.all():
            pr = participant.payment_request
            if pr.status == PaymentRequestStatus.PAID:
                paid_count += 1
            
            participants.append({
                'phone': pr.payer.primary_phone_number if pr.payer else '',
                'handle': pr.payer.handle if pr.payer else '',
                'display_name': pr.payer.display_name if pr.payer else '',
                'amount': str(participant.amount_owed),
                'status': pr.status,
                'payment_request_id': pr.id
            })
        
        return Response(
            {
                'id': split.id,
                'creator_handle': split.creator.handle,
                'creator_display_name': split.creator.display_name,
                'creator_phone': split.creator.primary_phone_number,
                'total_amount': str(split.total_amount),
                'currency': split.currency,
                'note': split.note,
                'status': split.status,
                'created_at': split.created_at.isoformat(),
                'paid_count': paid_count,
                'total_participants': len(participants),
                'participants': participants
            },
            status=status.HTTP_200_OK
        )
    
    except SplitRequest.DoesNotExist:
        return Response(
            {'error': 'Split not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'get_split_detail_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    request={'type': 'object', 'properties': {'qr_encoded': {'type': 'string'}, 'amount': {'type': 'number'}, 'note': {'type': 'string'}}},
    responses={200: dict, 400: dict},
    tags=['Splits']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_split_participant_by_qr(request, split_id):
    """Add a participant to a split bill by scanning their QR code."""
    try:
        split = SplitRequest.objects.get(id=split_id)
        
        if request.user != split.creator:
            return Response(
                {'error': 'Only the creator can add participants'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if split.status != SplitRequest.SplitStatus.PENDING:
            return Response(
                {'error': 'Can only add participants to pending splits'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        qr_encoded = request.data.get('qr_encoded', '').strip()
        amount = Decimal(str(request.data.get('amount', '0')))
        note = request.data.get('note', '').strip()
        
        if not qr_encoded or amount <= 0:
            return Response(
                {'error': 'QR code and valid amount are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Decode and verify QR code
        try:
            import base64
            decoded = base64.b64decode(qr_encoded).decode()
            payload_json, signature = decoded.rsplit('|', 1)
            
            if not verify_qr_signature(payload_json, signature):
                return Response(
                    {'error': 'Invalid QR signature'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            payload = json.loads(payload_json)
            
            # Check expiration
            exp = payload.get('exp')
            if exp:
                from datetime import datetime as dt
                from datetime import timezone as datetime_timezone
                exp_time = dt.fromtimestamp(exp, tz=datetime_timezone.utc)
                if timezone.now() > exp_time:
                    return Response(
                        {'error': 'QR code has expired'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Get user from QR payload
            handle = payload.get('handle')
            if not handle:
                return Response(
                    {'error': 'Invalid QR code format'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            participant_user = User.objects.get(handle=handle, status=UserStatus.ACTIVE)
            
        except Exception as e:
            return Response(
                {'error': f'Invalid QR code: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if user is already a participant
        existing_participant = split.participants.filter(
            payment_request__payer=participant_user
        ).first()
        
        if existing_participant:
            return Response(
                {'error': 'User is already a participant in this split'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create payment request for the new participant
        with transaction.atomic():
            payment_request = PaymentRequest.objects.create(
                requester=split.creator,
                payer=participant_user,
                amount=amount,
                currency=split.currency,
                note=f'Split payment: {note}' if note else f'Split payment: {split.note}',
                status=PaymentRequestStatus.PENDING
            )
            
            SplitParticipant.objects.create(
                split_request=split,
                payment_request=payment_request,
                amount_owed=amount
            )
            
            # Update split total amount
            split.total_amount += amount
            split.save()
            
            # Create notification and approval request
            create_notification(
                participant_user,
                'split_request_received',
                {
                    'creator_handle': split.creator.handle,
                    'creator_display_name': split.creator.display_name,
                    'amount': str(amount),
                    'currency': split.currency,
                    'total_split_amount': str(split.total_amount),
                    'split_id': split.id,
                    'payment_request_id': payment_request.id
                }
            )
            
            from wallet.services.webhooks import create_split_approval
            participant_obj = split.participants.get(payment_request=payment_request)
            create_split_approval(split, participant_obj)
        
        return Response(
            {
                'message': 'Participant added successfully',
                'participant': {
                    'phone': participant_user.primary_phone_number,
                    'handle': participant_user.handle,
                    'display_name': participant_user.display_name,
                    'amount': str(amount),
                    'status': 'pending'
                },
                'updated_total': str(split.total_amount)
            },
            status=status.HTTP_201_CREATED
        )
        
    except SplitRequest.DoesNotExist:
        return Response(
            {'error': 'Split not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except User.DoesNotExist:
        return Response(
            {'error': 'User from QR code not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'add_split_participant_by_qr_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    request=DisputeCreateSerializer,
    responses={200: DisputeSerializer, 400: dict, 404: dict},
    tags=['Disputes']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_dispute(request):
    """
    Create a dispute on a transaction.
    Users can only dispute transactions they were party to (sender or recipient).
    """
    serializer = DisputeCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    transaction_id = serializer.validated_data['transaction_id']
    reason = serializer.validated_data['reason']
    evidence_notes = serializer.validated_data.get('evidence_notes', '')

    try:
        with transaction.atomic():
            # Get the transaction
            trans = Transaction.objects.get(id=transaction_id)

            # Verify the user was party to the transaction
            if trans.sender != request.user and trans.recipient != request.user:
                return Response(
                    {'error': 'You can only dispute transactions you were party to'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Check if a dispute already exists for this transaction by this user
            if Dispute.objects.filter(transaction=trans, opened_by=request.user).exists():
                return Response(
                    {'error': 'You already have an open dispute for this transaction'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Create the dispute
            dispute = Dispute.objects.create(
                transaction=trans,
                opened_by=request.user,
                reason=reason,
                evidence_notes=evidence_notes,
                status=DisputeStatus.OPEN
            )

            # Audit log
            AuditLog.objects.create(
                user=request.user,
                action='dispute_created',
                metadata={
                    'dispute_id': dispute.id,
                    'transaction_id': str(transaction_id),
                    'reason': reason
                }
            )

            # Notify admins about the new dispute
            logger.info(
                json.dumps({
                    'event': 'dispute_created',
                    'dispute_id': dispute.id,
                    'transaction_id': str(transaction_id),
                    'opened_by': str(request.user.id),
                    'timestamp': timezone.now().isoformat()
                })
            )

            return Response(
                DisputeSerializer(dispute).data,
                status=status.HTTP_201_CREATED
            )

    except Transaction.DoesNotExist:
        return Response(
            {'error': 'Transaction not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'create_dispute_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: DisputeSerializer(many=True), 400: dict},
    tags=['Disputes']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_disputes(request):
    """
    List disputes for the current user.
    Supports filtering by status via query param.
    """
    status_filter = request.query_params.get('status', None)

    disputes = Dispute.objects.filter(opened_by=request.user)

    if status_filter:
        valid_statuses = [choice[0] for choice in DisputeStatus.choices]
        if status_filter not in valid_statuses:
            return Response(
                {'error': f'Invalid status. Valid options: {valid_statuses}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        disputes = disputes.filter(status=status_filter)

    disputes = disputes.order_by('-created_at')

    return Response(
        DisputeSerializer(disputes, many=True).data,
        status=status.HTTP_200_OK
    )


@extend_schema(
    responses={200: DisputeSerializer, 404: dict},
    tags=['Disputes']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dispute_detail(request, dispute_id):
    """
    Get details of a specific dispute.
    Users can only view disputes they opened.
    """
    try:
        dispute = Dispute.objects.get(id=dispute_id)

        # Check if the user owns this dispute or is an admin
        if dispute.opened_by != request.user and not request.user.is_staff:
            return Response(
                {'error': 'Access denied'},
                status=status.HTTP_403_FORBIDDEN
            )

        return Response(
            DisputeSerializer(dispute).data,
            status=status.HTTP_200_OK
        )

    except Dispute.DoesNotExist:
        return Response(
            {'error': 'Dispute not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'get_dispute_detail_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    request=DisputeResolveSerializer,
    responses={200: DisputeSerializer, 400: dict, 404: dict},
    tags=['Disputes']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resolve_dispute(request, dispute_id):
    """
    Resolve a dispute (admin only).
    Can reverse the transaction or deny the dispute.
    """
    if not request.user.is_staff:
        return Response(
            {'error': 'Admin access required'},
            status=status.HTTP_403_FORBIDDEN
        )

    serializer = DisputeResolveSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    resolution = serializer.validated_data['resolution']
    resolution_notes = serializer.validated_data.get('resolution_notes', '')

    try:
        with transaction.atomic():
            dispute = Dispute.objects.select_for_update().get(id=dispute_id)

            # Check if dispute is already resolved
            if dispute.status in [DisputeStatus.RESOLVED_REVERSED, DisputeStatus.RESOLVED_DENIED]:
                return Response(
                    {'error': 'Dispute has already been resolved'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Update dispute status
            if resolution == 'reverse':
                dispute.status = DisputeStatus.UNDER_REVIEW
                dispute.status = DisputeStatus.RESOLVED_REVERSED
                dispute.resolved_by = request.user
                dispute.resolved_at = timezone.now()
                dispute.resolution_notes = resolution_notes
                
            elif resolution == 'deny':
                dispute.status = DisputeStatus.RESOLVED_DENIED
                dispute.resolved_by = request.user
                dispute.resolved_at = timezone.now()
                dispute.resolution_notes = resolution_notes

            dispute.save()

            # Audit log
            AuditLog.objects.create(
                user=request.user,
                action='dispute_resolved',
                metadata={
                    'dispute_id': dispute.id,
                    'resolution': resolution,
                    'resolution_notes': resolution_notes
                }
            )

            # Notify the user who opened the dispute
            create_notification(
                dispute.opened_by,
                'dispute_resolved',
                {
                    'dispute_id': dispute.id,
                    'resolution': resolution,
                    'resolution_notes': resolution_notes,
                    'resolved_by': request.user.handle
                }
            )

            return Response(
                DisputeSerializer(dispute).data,
                status=status.HTTP_200_OK
            )

    except Dispute.DoesNotExist:
        return Response(
            {'error': 'Dispute not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'resolve_dispute_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: DisputeSerializer(many=True)},
    tags=['Disputes']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_list_disputes(request):
    """
    List all disputes (admin only).
    Supports filtering by status via query param.
    """
    if not request.user.is_staff:
        return Response(
            {'error': 'Admin access required'},
            status=status.HTTP_403_FORBIDDEN
        )

    status_filter = request.query_params.get('status', None)

    disputes = Dispute.objects.all()

    if status_filter:
        valid_statuses = [choice[0] for choice in DisputeStatus.choices]
        if status_filter not in valid_statuses:
            return Response(
                {'error': f'Invalid status. Valid options: {valid_statuses}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        disputes = disputes.filter(status=status_filter)

    disputes = disputes.order_by('-created_at')

    return Response(
        DisputeSerializer(disputes, many=True).data,
        status=status.HTTP_200_OK
    )

@extend_schema(
    request=MobileMoneyTopupSerializer,
    responses={201: MobileMoneyTransactionSerializer, 400: dict, 404: dict},
    tags=['Mobile Money']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mobile_money_topup(request):
    """
    Initiate a mobile money top-up.
    User must have a linked mobile money provider account.
    """
    serializer = MobileMoneyTopupSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    if step_up_required(request, OtpChallenge.Purpose.TRANSFER):
        return Response({'code': 'otp_required', 'purpose': OtpChallenge.Purpose.TRANSFER, 'error': 'Fresh device verification is required before adding money.'}, status=status.HTTP_403_FORBIDDEN)

    linked_provider_id = serializer.validated_data['linked_provider_id']
    amount = serializer.validated_data['amount']
    currency = serializer.validated_data['currency']

    try:
        with transaction.atomic():
            # Get the linked provider
            try:
                linked_provider = LinkedProvider.objects.get(
                    id=linked_provider_id,
                    user=request.user,
                    verification_status='verified'
                )
            except LinkedProvider.DoesNotExist:
                return Response(
                    {'error': 'Linked provider not found or not verified'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Get user's wallet in the requested currency
            try:
                wallet = Wallet.objects.get(user=request.user, currency=currency)
            except Wallet.DoesNotExist:
                return Response(
                    {'error': f'Wallet for currency {currency} not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Create mobile money transaction
            mm_transaction = MobileMoneyTransaction.objects.create(
                user=request.user,
                wallet=wallet,
                linked_provider=linked_provider,
                type=MobileMoneyTransactionType.TOPUP,
                amount=amount,
                currency=currency,
                status=MobileMoneyTransactionStatus.PENDING
            )

            # In a real implementation, this would call the provider's API
            # For now, we'll simulate the provider call
            # TODO: Integrate with MTN MoMo, Airtel Money, or Orange Money APIs
            provider_transaction_id = f"PROV-{uuid.uuid4().hex[:16]}"
            mm_transaction.provider_transaction_id = provider_transaction_id
            mm_transaction.status = MobileMoneyTransactionStatus.PROCESSING
            mm_transaction.save()
            from wallet.tasks import process_mobile_money_webhook
            process_mobile_money_webhook.delay(provider_transaction_id, 'completed', {'simulation': True})

            # Audit log
            AuditLog.objects.create(
                user=request.user,
                action='mobile_money_topup_initiated',
                metadata={
                    'mm_transaction_id': mm_transaction.id,
                    'provider_transaction_id': provider_transaction_id,
                    'amount': str(amount),
                    'currency': currency,
                    'provider': linked_provider.provider
                }
            )

            return Response(
                MobileMoneyTransactionSerializer(mm_transaction).data,
                status=status.HTTP_201_CREATED
            )

    except Exception as e:
        logger.error(f'mobile_money_topup_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    request=MobileMoneyWithdrawalSerializer,
    responses={201: MobileMoneyTransactionSerializer, 400: dict, 404: dict},
    tags=['Mobile Money']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mobile_money_withdrawal(request):
    """
    Initiate a mobile money withdrawal.
    User must have sufficient balance and a linked mobile money provider account.
    """
    serializer = MobileMoneyWithdrawalSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    if step_up_required(request, OtpChallenge.Purpose.WITHDRAWAL):
        return Response({'code': 'otp_required', 'purpose': OtpChallenge.Purpose.WITHDRAWAL, 'error': 'Fresh device verification is required before withdrawing money.'}, status=status.HTTP_403_FORBIDDEN)

    linked_provider_id = serializer.validated_data['linked_provider_id']
    amount = serializer.validated_data['amount']
    currency = serializer.validated_data['currency']

    try:
        with transaction.atomic():
            # Get the linked provider
            try:
                linked_provider = LinkedProvider.objects.get(
                    id=linked_provider_id,
                    user=request.user,
                    verification_status='verified'
                )
            except LinkedProvider.DoesNotExist:
                return Response(
                    {'error': 'Linked provider not found or not verified'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Get user's wallet in the requested currency
            try:
                wallet = Wallet.objects.select_for_update().get(user=request.user, currency=currency)
            except Wallet.DoesNotExist:
                return Response(
                    {'error': f'Wallet for currency {currency} not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check balance
            current_balance = wallet.get_balance()
            if current_balance < amount + fee_amount:
                return Response(
                    {'error': 'Insufficient balance'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Create mobile money transaction
            mm_transaction = MobileMoneyTransaction.objects.create(
                user=request.user,
                wallet=wallet,
                linked_provider=linked_provider,
                type=MobileMoneyTransactionType.WITHDRAWAL,
                amount=amount,
                fee_amount=fee_amount,
                currency=currency,
                status=MobileMoneyTransactionStatus.PENDING
            )

            # In a real implementation, this would call the provider's API
            # For now, we'll simulate the provider call
            # TODO: Integrate with MTN MoMo, Airtel Money, or Orange Money APIs
            provider_transaction_id = f"PROV-{uuid.uuid4().hex[:16]}"
            mm_transaction.provider_transaction_id = provider_transaction_id
            mm_transaction.status = MobileMoneyTransactionStatus.PROCESSING
            mm_transaction.save()
            from wallet.tasks import process_mobile_money_webhook
            process_mobile_money_webhook.delay(provider_transaction_id, 'completed', {'simulation': True})

            # Create a debit ledger entry to hold the funds
            LedgerEntry.objects.create(
                wallet=wallet,
                transaction=None,  # Will be updated when completed
                direction=LedgerDirection.DEBIT,
                amount=amount + fee_amount
            )

            # Audit log
            AuditLog.objects.create(
                user=request.user,
                action='mobile_money_withdrawal_initiated',
                metadata={
                    'mm_transaction_id': mm_transaction.id,
                    'provider_transaction_id': provider_transaction_id,
                    'amount': str(amount),
                    'currency': currency,
                    'provider': linked_provider.provider
                }
            )

            return Response(
                MobileMoneyTransactionSerializer(mm_transaction).data,
                status=status.HTTP_201_CREATED
            )

    except Exception as e:
        logger.error(f'mobile_money_withdrawal_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    request={'type': 'object', 'properties': {'provider_transaction_id': {'type': 'string'}, 'status': {'type': 'string'}, 'response': {'type': 'object'}}},
    responses={200: dict, 400: dict, 404: dict},
    tags=['Mobile Money']
)
@api_view(['POST'])
@permission_classes([AllowAny])  # Webhooks are called by providers, not users
def mobile_money_webhook(request):
    """
    Webhook endpoint for mobile money providers to update transaction status.
    Validates the payload, enqueues processing, and returns 200 immediately.
    """
    timestamp = request.META.get('HTTP_X_WEBHOOK_TIMESTAMP', '')
    signature = request.META.get('HTTP_X_WEBHOOK_SIGNATURE', '')
    event_id = request.META.get('HTTP_X_WEBHOOK_ID', '').strip()
    if not event_id or not valid_webhook_signature(request.body, timestamp, signature):
        return Response({'error': 'Invalid webhook signature.'}, status=status.HTTP_401_UNAUTHORIZED)

    provider_transaction_id = request.data.get('provider_transaction_id')
    webhook_status = request.data.get('status')
    provider_response = request.data.get('response', {})

    if not provider_transaction_id or not webhook_status:
        return Response(
            {'error': 'provider_transaction_id and status are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if MobileMoneyWebhookEvent.objects.filter(event_id=event_id).exists():
        return Response({'status': 'already_received'}, status=status.HTTP_200_OK)

    try:
        MobileMoneyWebhookEvent.objects.create(
            event_id=event_id,
            provider_transaction_id=provider_transaction_id,
            status=webhook_status,
            signature=signature,
        )
        from wallet.tasks import process_mobile_money_webhook

        process_mobile_money_webhook.delay(
            provider_transaction_id=provider_transaction_id,
            status=webhook_status,
            provider_response=provider_response,
        )
        MobileMoneyWebhookEvent.objects.filter(event_id=event_id).update(processed_at=timezone.now())
        return Response({'status': 'queued'}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f'mobile_money_webhook_enqueue_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: MobileMoneyTransactionSerializer(many=True)},
    tags=['Mobile Money']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_mobile_money_transactions(request):
    """
    List mobile money transactions for the current user.
    Supports filtering by type and status via query params.
    """
    type_filter = request.query_params.get('type', None)
    status_filter = request.query_params.get('status', None)

    transactions = MobileMoneyTransaction.objects.filter(user=request.user)

    if type_filter:
        valid_types = [choice[0] for choice in MobileMoneyTransactionType.choices]
        if type_filter not in valid_types:
            return Response(
                {'error': f'Invalid type. Valid options: {valid_types}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        transactions = transactions.filter(type=type_filter)

    if status_filter:
        valid_statuses = [choice[0] for choice in MobileMoneyTransactionStatus.choices]
        if status_filter not in valid_statuses:
            return Response(
                {'error': f'Invalid status. Valid options: {valid_statuses}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        transactions = transactions.filter(status=status_filter)

    transactions = transactions.order_by('-created_at')

    return Response(
        MobileMoneyTransactionSerializer(transactions, many=True).data,
        status=status.HTTP_200_OK
    )


@extend_schema(
    request=ScheduledTransferCreateSerializer,
    responses={201: ScheduledTransferSerializer, 400: dict, 404: dict},
    tags=['Scheduled Transfers']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_scheduled_transfer(request):
    """
    Create a new scheduled/recurring transfer.
    """
    if step_up_required(request, OtpChallenge.Purpose.TRANSFER):
        return Response({'code': 'otp_required', 'purpose': OtpChallenge.Purpose.TRANSFER, 'error': 'Fresh device verification is required before scheduling a transfer.'}, status=status.HTTP_403_FORBIDDEN)
    if not user_has_approved_kyc(request.user):
        return Response({'error': 'KYC verification is required before sending money. Please submit your ID details first.'}, status=status.HTTP_403_FORBIDDEN)
    serializer = ScheduledTransferCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    recipient_phone = serializer.validated_data['recipient_phone']
    amount = serializer.validated_data['amount']
    currency = serializer.validated_data['currency']
    frequency = serializer.validated_data['frequency']
    start_date = serializer.validated_data['start_date']
    end_date = serializer.validated_data.get('end_date')
    max_executions = serializer.validated_data.get('max_executions')
    note = serializer.validated_data.get('note', '')

    try:
        with transaction.atomic():
            # Resolve recipient
            try:
                recipient = User.objects.get(
                    primary_phone_number=recipient_phone,
                    status=UserStatus.ACTIVE
                )
            except User.DoesNotExist:
                return Response(
                    {'error': 'Recipient not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check sender's wallet
            try:
                sender_wallet = Wallet.objects.get(user=request.user, currency=currency)
            except Wallet.DoesNotExist:
                return Response(
                    {'error': f'Wallet for currency {currency} not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Check recipient's wallet
            try:
                recipient_wallet = Wallet.objects.get(user=recipient, currency=currency)
            except Wallet.DoesNotExist:
                return Response(
                    {'error': f'Recipient does not have a wallet for currency {currency}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Prevent sending to self
            if recipient == request.user:
                return Response(
                    {'error': 'Cannot create scheduled transfer to yourself'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Create scheduled transfer
            scheduled_transfer = ScheduledTransfer.objects.create(
                sender=request.user,
                recipient=recipient,
                amount=amount,
                currency=currency,
                frequency=frequency,
                next_execution=start_date,
                end_date=end_date,
                max_executions=max_executions,
                status=ScheduledTransferStatus.ACTIVE,
                note=note
            )

            # Audit log
            AuditLog.objects.create(
                user=request.user,
                action='scheduled_transfer_created',
                metadata={
                    'scheduled_transfer_id': scheduled_transfer.id,
                    'recipient_phone': recipient_phone,
                    'amount': str(amount),
                    'currency': currency,
                    'frequency': frequency,
                    'start_date': start_date.isoformat()
                }
            )

            return Response(
                ScheduledTransferSerializer(scheduled_transfer).data,
                status=status.HTTP_201_CREATED
            )

    except Exception as e:
        logger.error(f'create_scheduled_transfer_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: ScheduledTransferSerializer(many=True)},
    tags=['Scheduled Transfers']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_scheduled_transfers(request):
    """
    List scheduled transfers for the current user.
    Supports filtering by status via query param.
    """
    status_filter = request.query_params.get('status', None)

    transfers = ScheduledTransfer.objects.filter(sender=request.user)

    if status_filter:
        valid_statuses = [choice[0] for choice in ScheduledTransferStatus.choices]
        if status_filter not in valid_statuses:
            return Response(
                {'error': f'Invalid status. Valid options: {valid_statuses}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        transfers = transfers.filter(status=status_filter)

    transfers = transfers.order_by('-created_at')

    return Response(
        ScheduledTransferSerializer(transfers, many=True).data,
        status=status.HTTP_200_OK
    )


@extend_schema(
    responses={200: ScheduledTransferSerializer, 404: dict},
    tags=['Scheduled Transfers']
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_scheduled_transfer_detail(request, transfer_id):
    """
    Get details of a specific scheduled transfer.
    """
    try:
        scheduled_transfer = ScheduledTransfer.objects.get(
            id=transfer_id,
            sender=request.user
        )
        return Response(
            ScheduledTransferSerializer(scheduled_transfer).data,
            status=status.HTTP_200_OK
        )
    except ScheduledTransfer.DoesNotExist:
        return Response(
            {'error': 'Scheduled transfer not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@extend_schema(
    responses={200: dict, 404: dict},
    tags=['Scheduled Transfers']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pause_scheduled_transfer(request, transfer_id):
    """
    Pause an active scheduled transfer.
    """
    try:
        with transaction.atomic():
            scheduled_transfer = ScheduledTransfer.objects.select_for_update().get(
                id=transfer_id,
                sender=request.user
            )

            if scheduled_transfer.status != ScheduledTransferStatus.ACTIVE:
                return Response(
                    {'error': 'Can only pause active scheduled transfers'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            scheduled_transfer.status = ScheduledTransferStatus.PAUSED
            scheduled_transfer.save()

            AuditLog.objects.create(
                user=request.user,
                action='scheduled_transfer_paused',
                metadata={'scheduled_transfer_id': transfer_id}
            )

            return Response(
                {'message': 'Scheduled transfer paused'},
                status=status.HTTP_200_OK
            )
    except ScheduledTransfer.DoesNotExist:
        return Response(
            {'error': 'Scheduled transfer not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@extend_schema(
    responses={200: dict, 404: dict},
    tags=['Scheduled Transfers']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resume_scheduled_transfer(request, transfer_id):
    """
    Resume a paused scheduled transfer.
    """
    try:
        with transaction.atomic():
            scheduled_transfer = ScheduledTransfer.objects.select_for_update().get(
                id=transfer_id,
                sender=request.user
            )

            if scheduled_transfer.status != ScheduledTransferStatus.PAUSED:
                return Response(
                    {'error': 'Can only resume paused scheduled transfers'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            scheduled_transfer.status = ScheduledTransferStatus.ACTIVE
            scheduled_transfer.save()

            AuditLog.objects.create(
                user=request.user,
                action='scheduled_transfer_resumed',
                metadata={'scheduled_transfer_id': transfer_id}
            )

            return Response(
                {'message': 'Scheduled transfer resumed'},
                status=status.HTTP_200_OK
            )
    except ScheduledTransfer.DoesNotExist:
        return Response(
            {'error': 'Scheduled transfer not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@extend_schema(
    responses={200: dict, 404: dict},
    tags=['Scheduled Transfers']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_scheduled_transfer(request, transfer_id):
    """
    Cancel a scheduled transfer.
    """
    try:
        with transaction.atomic():
            scheduled_transfer = ScheduledTransfer.objects.select_for_update().get(
                id=transfer_id,
                sender=request.user
            )

            if scheduled_transfer.status in [ScheduledTransferStatus.CANCELLED, ScheduledTransferStatus.COMPLETED]:
                return Response(
                    {'error': 'Cannot cancel a cancelled or completed scheduled transfer'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            scheduled_transfer.status = ScheduledTransferStatus.CANCELLED
            scheduled_transfer.save()

            AuditLog.objects.create(
                user=request.user,
                action='scheduled_transfer_cancelled',
                metadata={'scheduled_transfer_id': transfer_id}
            )

            return Response(
                {'message': 'Scheduled transfer cancelled'},
                status=status.HTTP_200_OK
            )
    except ScheduledTransfer.DoesNotExist:
        return Response(
            {'error': 'Scheduled transfer not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@extend_schema(
    request=MerchantCreateSerializer,
    responses={201: MerchantSerializer, 400: dict},
    tags=['Merchants']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_merchant_account(request):
    """
    Create a merchant account application.
    Requires admin approval before activation.
    """
    serializer = MerchantCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    business_name = serializer.validated_data['business_name']
    business_type = serializer.validated_data.get('business_type', '')
    description = serializer.validated_data.get('description', '')
    wallet_id = serializer.validated_data['wallet_id']
    logo_url = serializer.validated_data.get('logo_url', '')
    contact_email = serializer.validated_data.get('contact_email', '')
    contact_phone = serializer.validated_data.get('contact_phone', '')
    address = serializer.validated_data.get('address', '')
    tax_id = serializer.validated_data.get('tax_id', '')
    plan_code = serializer.validated_data.get('plan_code', 'starter')

    try:
        with transaction.atomic():
            # Check if user already has a merchant account
            if hasattr(request.user, 'merchant_account'):
                return Response(
                    {'error': 'User already has a merchant account'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get wallet
            try:
                wallet = Wallet.objects.get(id=wallet_id, user=request.user)
            except Wallet.DoesNotExist:
                return Response(
                    {'error': 'Wallet not found or does not belong to user'},
                    status=status.HTTP_404_NOT_FOUND
                )

            plan = MerchantPlan.objects.filter(code=plan_code, is_active=True).first()
            if not plan:
                return Response({'error': 'Plan not found'}, status=status.HTTP_400_BAD_REQUEST)

            # Create merchant account
            merchant = Merchant.objects.create(
                user=request.user,
                business_name=business_name,
                business_type=business_type,
                description=description,
                wallet=wallet,
                logo_url=logo_url,
                contact_email=contact_email,
                contact_phone=contact_phone,
                address=address,
                tax_id=tax_id,
                status=MerchantStatus.PENDING
            )
            sandbox_secret = secrets.token_urlsafe(32)
            merchant.sandbox_public_key = f'test_pk_{secrets.token_urlsafe(18)}'
            merchant.sandbox_secret_hash = hashlib.sha256(sandbox_secret.encode()).hexdigest()
            merchant.credentials_issued_at = timezone.now()
            merchant.save(update_fields=['sandbox_public_key', 'sandbox_secret_hash', 'credentials_issued_at'])
            now = timezone.now()
            MerchantSubscription.objects.create(
                merchant=merchant,
                plan=plan,
                status=MerchantSubscription.Status.ACTIVE if plan.monthly_price else MerchantSubscription.Status.TRIALING,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )

            # Audit log
            AuditLog.objects.create(
                user=request.user,
                action='merchant_account_created',
                metadata={'merchant_id': merchant.id, 'business_name': business_name}
            )

            return Response(
                {**MerchantSerializer(merchant).data, 'sandbox_credentials': {'public_key': merchant.sandbox_public_key, 'secret_key': f'test_sk_{sandbox_secret}'}},
                status=status.HTTP_201_CREATED
            )

    except Exception as e:
        logger.error(f'create_merchant_account_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    responses={200: MerchantSerializer, 404: dict},
    tags=['Merchants']
)
@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def get_merchant_account(request):
    """
    Get the current user's merchant account.
    """
    try:
        merchant = Merchant.objects.get(user=request.user)
        if request.method == 'PATCH':
            allowed_fields = ['business_name', 'business_email', 'website_url', 'business_type', 'description', 'logo_url', 'contact_email', 'contact_phone', 'address', 'tax_id']
            for field in allowed_fields:
                if field in request.data:
                    setattr(merchant, field, request.data[field])
            merchant.save(update_fields=[field for field in allowed_fields if field in request.data] + ['updated_at'])
        return Response(
            MerchantSerializer(merchant).data,
            status=status.HTTP_200_OK
        )
    except Merchant.DoesNotExist:
        return Response(
            {'error': 'Merchant account not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'generate_merchant_qr_error: {str(e)}')
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def merchant_logs(request):
    merchant = Merchant.objects.filter(user=request.user).first()
    if not merchant:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)
    deliveries = merchant.webhook_deliveries.select_related('payment_intent').values(
        'id', 'event_type', 'target_url', 'status', 'status_code', 'attempt_count', 'last_error', 'created_at', 'delivered_at'
    )[:100]
    return Response(list(deliveries))


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def merchant_payment_links(request):
    merchant = Merchant.objects.filter(user=request.user).first()
    if not merchant:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'POST':
        if merchant.status != MerchantStatus.ACTIVE:
            return Response({'error': 'Merchant account must be active to create payment links'}, status=status.HTTP_403_FORBIDDEN)
        try:
            amount = Decimal(str(request.data.get('amount', '0')))
            if amount <= 0:
                raise ValueError
            intent = PaymentIntent.objects.create(
                merchant=merchant,
                amount=amount,
                currency=str(request.data.get('currency', merchant.wallet.currency)).upper(),
                description=str(request.data.get('description', '')),
                mode=MerchantMode.SANDBOX,
                status=PaymentIntentStatus.PENDING_PAYMENT,
            )
        except (TypeError, ValueError, ArithmeticError):
            return Response({'error': 'A positive amount is required'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'id': intent.id, 'type': request.data.get('type', 'link'), 'amount': str(intent.amount), 'description': intent.description, 'code': str(intent.id), 'status': 'active', 'times_paid': 0, 'total_collected': '0.00'}, status=status.HTTP_201_CREATED)
    links = PaymentIntent.objects.filter(merchant=merchant).order_by('-created_at')[:100]
    return Response([{'id': link.id, 'type': 'link', 'amount': str(link.amount), 'description': link.description, 'code': str(link.id), 'status': 'active' if link.status == PaymentIntentStatus.PENDING_PAYMENT else link.status, 'times_paid': 0, 'total_collected': '0.00', 'created_at': link.created_at} for link in links])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def deactivate_merchant_payment_link(request, intent_id):
    merchant = Merchant.objects.filter(user=request.user).first()
    intent = PaymentIntent.objects.filter(id=intent_id, merchant=merchant).first()
    if not intent:
        return Response({'error': 'Payment link not found'}, status=status.HTTP_404_NOT_FOUND)
    intent.status = PaymentIntentStatus.CANCELLED
    intent.save(update_fields=['status'])
    return Response({'id': intent.id, 'status': 'cancelled'})


@extend_schema(
    responses={200: dict, 404: dict},
    tags=['Merchants']
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_merchant_qr(request):
    """
    Generate a static QR code for the merchant account.
    QR code allows customers to pay the merchant without specifying amount.
    """
    try:
        with transaction.atomic():
            merchant = Merchant.objects.select_for_update().get(user=request.user)

            if merchant.status != MerchantStatus.ACTIVE:
                return Response(
                    {'error': 'Merchant account must be active to generate QR code'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Generate static QR payload
            payload = {
                'type': 'merchant_pay',
                'merchant_id': merchant.id,
                'handle': request.user.handle,
                'business_name': merchant.business_name,
                'currency': merchant.wallet.currency
            }

            payload_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
            secret = get_qr_signing_secret()
            signature = hmac.new(
                secret.encode(),
                payload_json.encode(),
                hashlib.sha256
            ).hexdigest()

            # Generate unique QR code
            qr_code = f"MERCHANT-{uuid.uuid4().hex[:16].upper()}"

            merchant.static_qr_code = qr_code
            merchant.static_qr_payload = payload_json
            merchant.static_qr_signature = signature
            merchant.save()

            # Audit log
            AuditLog.objects.create(
                user=request.user,
                action='merchant_qr_generated',
                metadata={'merchant_id': merchant.id, 'qr_code': qr_code}
            )

            return Response(
                {
                    'qr_code': qr_code,
                    'payload': payload_json,
                    'signature': signature,
                    'encoded': base64.b64encode((payload_json + '|' + signature).encode()).decode()
                },
                status=status.HTTP_200_OK
            )

    except Merchant.DoesNotExist:
        return Response(
            {'error': 'Merchant account not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def merchant_dashboard(request):
    merchant = Merchant.objects.filter(user=request.user).first()
    if not merchant:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)
    transactions = Transaction.objects.filter(recipient=request.user, status=TransactionStatus.COMPLETED)
    volume = transactions.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    return Response({'merchant': MerchantSerializer(merchant).data, 'today_volume': str(volume),
                     'transaction_count': transactions.count(), 'pending_settlements': '0.00',
                     'available_balance': str(merchant.wallet.get_balance()),
                     'plan_usage': merchant_monthly_usage(merchant),
                     'transactions': list(transactions.values('id', 'amount', 'currency', 'note', 'status', 'created_at')[:50]),
                     'kyc_documents': list(merchant.kyc_documents.values('id', 'document_type', 'status', 'reviewer_notes', 'file_url', 'created_at')),
                     'settlements': list(merchant.settlements.values('id', 'amount', 'fees', 'currency', 'batch_reference', 'status', 'destination', 'created_at'))})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def merchant_kyc_documents(request):
    merchant = Merchant.objects.filter(user=request.user).first()
    if not merchant:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'POST':
        document_type = request.data.get('document_type')
        uploaded_file = request.FILES.get('file')
        file_url = request.data.get('file_url')
        if uploaded_file:
            stored_path = default_storage.save(f'kyc/{merchant.id}/{uploaded_file.name}', uploaded_file)
            file_url = request.build_absolute_uri(default_storage.url(stored_path))
        if not document_type or not file_url:
            return Response({'error': 'document_type and file are required'}, status=status.HTTP_400_BAD_REQUEST)
        document = KYCDocument.objects.create(merchant=merchant, document_type=document_type, file_url=file_url)
        return Response({'id': document.id, 'document_type': document.document_type, 'status': document.status, 'file_url': document.file_url}, status=status.HTTP_201_CREATED)
    return Response(list(merchant.kyc_documents.values('id', 'document_type', 'status', 'reviewer_notes', 'file_url', 'created_at')))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def merchant_credentials(request):
    merchant = Merchant.objects.filter(user=request.user).first()
    if not merchant:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)
    environment = request.data.get('environment', 'sandbox')
    if environment == 'live' and merchant.status != MerchantStatus.ACTIVE:
        return Response({'error': 'Live credentials require an approved merchant account'}, status=status.HTTP_403_FORBIDDEN)
    secret = secrets.token_urlsafe(32)
    public_key = f'{"live" if environment == "live" else "test"}_pk_{secrets.token_urlsafe(18)}'
    if environment == 'live':
        merchant.live_public_key = public_key
        merchant.live_secret_hash = hashlib.sha256(secret.encode()).hexdigest()
    else:
        merchant.sandbox_public_key = public_key
        merchant.sandbox_secret_hash = hashlib.sha256(secret.encode()).hexdigest()
    merchant.credentials_issued_at = timezone.now()
    merchant.save(update_fields=['live_public_key', 'live_secret_hash', 'sandbox_public_key', 'sandbox_secret_hash', 'credentials_issued_at'])
    return Response({'environment': environment, 'public_key': public_key, 'secret_key': f'{"live" if environment == "live" else "test"}_sk_{secret}'})


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def merchant_webhook_config(request):
    merchant = Merchant.objects.filter(user=request.user).first()
    if not merchant:
        return Response({'error': 'Merchant account not found'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'PATCH':
        merchant.webhook_url = str(request.data.get('webhook_url', merchant.webhook_url)).strip()
        merchant.save(update_fields=['webhook_url'])
    return Response({'webhook_url': merchant.webhook_url, 'events': ['payment.success', 'payment.failed', 'refund.processed', 'payout.completed'], 'secret_configured': bool(merchant.webhook_secret)})
@extend_schema(
    responses={200: MerchantSerializer(many=True)},
    tags=['Merchants']
)
@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_list_merchants(request):
    """
    List all merchant accounts (admin only).
    Supports filtering by status via query param.
    """
    status_filter = request.query_params.get('status', None)

    merchants = Merchant.objects.all()

    if status_filter:
        valid_statuses = [choice[0] for choice in MerchantStatus.choices]
        if status_filter not in valid_statuses:
            return Response(
                {'error': f'Invalid status. Valid options: {valid_statuses}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        merchants = merchants.filter(status=status_filter)

    merchants = merchants.order_by('-created_at')

    return Response(
        MerchantSerializer(merchants, many=True).data,
        status=status.HTTP_200_OK
    )


@extend_schema(
    request=MerchantApprovalSerializer,
    responses={200: dict, 400: dict, 404: dict},
    tags=['Merchants']
)
@api_view(['POST'])
@permission_classes([IsAdminUser])
def admin_approve_merchant(request, merchant_id):
    """
    Approve or reject a merchant account (admin only).
    """
    serializer = MerchantApprovalSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    action = serializer.validated_data['action']
    rejection_reason = serializer.validated_data.get('rejection_reason', '')

    try:
        with transaction.atomic():
            merchant = Merchant.objects.select_for_update().get(id=merchant_id)

            if merchant.status != MerchantStatus.PENDING:
                return Response(
                    {'error': 'Can only approve/reject pending merchant accounts'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if action == 'approve':
                merchant.status = MerchantStatus.ACTIVE
                merchant.approved_by = request.user
                merchant.approved_at = timezone.now()
                merchant.save()

                # Audit log
                AuditLog.objects.create(
                    user=request.user,
                    action='merchant_approved',
                    metadata={'merchant_id': merchant.id, 'business_name': merchant.business_name}
                )

                # Notify the merchant
                create_notification(
                    merchant.user,
                    'merchant_account_approved',
                    {
                        'merchant_id': merchant.id,
                        'business_name': merchant.business_name
                    }
                )

                try:
                    from wallet.tasks import generate_merchant_api_keys_task
                    generate_merchant_api_keys_task.delay(merchant.id)
                except Exception:
                    logger.exception('merchant_api_keys_enqueue_failed', extra={'merchant_id': merchant.id})

                return Response(
                    {'message': 'Merchant account approved'},
                    status=status.HTTP_200_OK
                )

            elif action == 'reject':
                merchant.status = MerchantStatus.REJECTED
                merchant.rejection_reason = rejection_reason
                merchant.approved_by = request.user
                merchant.approved_at = timezone.now()
                merchant.save()

                # Audit log
                AuditLog.objects.create(
                    user=request.user,
                    action='merchant_rejected',
                    metadata={
                        'merchant_id': merchant.id,
                        'business_name': merchant.business_name,
                        'rejection_reason': rejection_reason
                    }
                )

                # Notify the merchant
                create_notification(
                    merchant.user,
                    'merchant_account_rejected',
                    {
                        'merchant_id': merchant.id,
                        'business_name': merchant.business_name,
                        'rejection_reason': rejection_reason
                    }
                )

                return Response(
                    {'message': 'Merchant account rejected'},
                    status=status.HTTP_200_OK
                )

    except Merchant.DoesNotExist:
        return Response(
            {'error': 'Merchant account not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f'admin_approve_merchant_error: {str(e)}')
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
