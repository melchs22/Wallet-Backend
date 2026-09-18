from django.urls import path, include
from .views import (
    EmailSignupView, EmailLoginView, GoogleAuthView, csrf_cookie_view, logout_view, MeView, UserResolveView, resolve_user_by_phone,
    TransferView, TransferPreviewView, NotificationListView, NotificationDetailView, PushDeviceView, OtpChallengeRequestView, OtpChallengeVerifyView,
    WalletView, TransactionListView, CloseAccountView,
    TransactionDetailView, ReversalView, AdminLoginView,
    admin_auth_login, admin_auth_logout, admin_change_password,
    admin_dashboard, admin_users_list, admin_user_detail, admin_user_update,
    admin_topup_user, admin_transactions_list, admin_transaction_detail,
    admin_transfer_attempts, admin_audit_log, admin_requests_list, admin_splits_list,
    admin_settings_list, admin_settings_update,
    admin_reconciliation_last_run, admin_reconciliation_run,
    create_payment_request, get_payment_requests, get_payment_request_detail,
    pay_payment_request, decline_payment_request, cancel_payment_request,
    get_qr_payload, verify_qr_payload, create_split, get_split_detail, cancel_split, add_split_participant_by_qr,
    create_dispute, list_disputes, get_dispute_detail, resolve_dispute, admin_list_disputes,
    pay_qr_payload, list_linked_providers, link_mobile_money_provider,
    mobile_money_topup, mobile_money_withdrawal, mobile_money_webhook, list_mobile_money_transactions,
    create_scheduled_transfer, list_scheduled_transfers, get_scheduled_transfer_detail,
    pause_scheduled_transfer, resume_scheduled_transfer, cancel_scheduled_transfer,
    create_merchant_account, get_merchant_account, generate_merchant_qr,
    merchant_dashboard, merchant_payout_schedule, merchant_logs, merchant_payment_links, deactivate_merchant_payment_link, merchant_kyc_documents, merchant_credentials, merchant_webhook_config,
    merchant_plans, merchant_subscription, admin_list_merchants, admin_approve_merchant,
    supported_countries, app_update_status, legal_document, legal_document_html, provider_catalog,
    change_password, UserKYCSubmissionView, login_status, confirm_login, trusted_devices, revoke_trusted_device
)
from .approval_views import list_pending_approvals, approve_transaction, decline_transaction
from .parental_views import (
    link_child_account, verify_parental_link, list_child_accounts, list_parent_accounts,
    get_child_balance, get_child_transactions, send_to_child, set_child_wallet_status, update_parental_permissions, revoke_parental_control
)
from . import admin_views
from . import admin_api
from . import merchant_views


urlpatterns = [
    path('merchant-api/', include('wallet.merchant_urls')),
    # Authentication
    path('auth/google', GoogleAuthView.as_view(), name='google_auth'),
    path('auth/signup', EmailSignupView.as_view(), name='email_signup'),
    path('auth/login', EmailLoginView.as_view(), name='email_login'),
    path('auth/change-password', change_password, name='change_password'),
    path('countries', supported_countries, name='supported_countries'),
    path('app/update-status', app_update_status, name='app_update_status'),
    path('legal/<slug:slug>', legal_document, name='legal_document'),
    path('legal/<slug:slug>/html', legal_document_html, name='legal_document_html'),
    path('mobile-money/provider-catalog', provider_catalog, name='provider_catalog'),
    path('kyc/submissions', UserKYCSubmissionView.as_view(), name='user_kyc_submissions'),
    path('auth/admin', AdminLoginView.as_view(), name='admin_login'),
    path('admin/auth/login', admin_auth_login, name='admin_auth_login'),
    path('admin/auth/logout', admin_auth_logout, name='admin_auth_logout'),
    path('admin/auth/change-password', admin_change_password, name='admin_change_password'),
    path('csrf', csrf_cookie_view, name='csrf_cookie'),
    path('auth/logout', logout_view, name='logout'),
    path('auth/otp/request', OtpChallengeRequestView.as_view(), name='otp_request'),
    path('auth/otp/verify', OtpChallengeVerifyView.as_view(), name='otp_verify'),
    path('auth/login/status/<uuid:request_id>', login_status, name='login_status'),
    path('auth/login/confirm', confirm_login, name='confirm_login'),
    path('auth/devices', trusted_devices, name='trusted_devices'),
    path('auth/devices/<str:device_id>/revoke', revoke_trusted_device, name='revoke_trusted_device'),
    path('me', MeView.as_view(), name='me'),
    path('merchant/team', merchant_views.merchant_team, name='merchant_team'),
    path('merchant/team/<int:member_id>', merchant_views.merchant_team_member, name='merchant_team_member'),
    
    # User resolution
    path('users/resolve', UserResolveView.as_view(), name='user_resolve'),
    path('users/resolve-by-phone', resolve_user_by_phone, name='resolve_user_by_phone'),
    
    # Transfers (create transfer)
    path('transfers', TransferView.as_view(), name='transfer'),
    path('transfers/preview', TransferPreviewView.as_view(), name='transfer_preview'),
    
    # Notifications
    path('notifications', NotificationListView.as_view(), name='notification_list'),
    path('notifications/<int:id>/read', NotificationDetailView.as_view(), name='notification_read'),
    path('notifications/device', PushDeviceView.as_view(), name='notification_device'),
    
    # Wallet
    path('wallet', WalletView.as_view(), name='wallet'),
    
    # Transactions (list and detail)
    path('transactions', TransactionListView.as_view(), name='transaction_list'),
    path('transactions/<str:transaction_id>', TransactionDetailView.as_view(), name='transaction_detail'),
    
    # Admin operations
    path('transfers/<str:transaction_id>/reverse', ReversalView.as_view(), name='transaction_reverse'),
    
    # Account management
    path('me/close', CloseAccountView.as_view(), name='close_account'),
    
    # Payment requests
    path('requests/create', create_payment_request, name='create_payment_request'),
    path('requests', get_payment_requests, name='get_payment_requests'),
    path('requests/<int:request_id>', get_payment_request_detail, name='get_payment_request_detail'),
    path('requests/<int:request_id>/pay', pay_payment_request, name='pay_payment_request'),
    path('requests/<int:request_id>/decline', decline_payment_request, name='decline_payment_request'),
    path('requests/<int:request_id>/cancel', cancel_payment_request, name='cancel_payment_request'),
    
    # QR Code
    path('me/qr-payload', get_qr_payload, name='get_qr_payload'),
    path('qr/verify', verify_qr_payload, name='verify_qr_payload'),
    path('qr/pay', pay_qr_payload, name='pay_qr_payload'),
    
    # Bill Splits
    path('splits', create_split, name='create_split'),
    path('splits/<int:split_id>', get_split_detail, name='get_split_detail'),
    path('splits/<int:split_id>/cancel', cancel_split, name='cancel_split'),
    path('splits/<int:split_id>/add-participant-qr', add_split_participant_by_qr, name='add_split_participant_by_qr'),
    
    # Admin API endpoints
    path('admin/dashboard', admin_dashboard, name='admin_dashboard'),
    path('admin/users', admin_users_list, name='admin_users_list'),
    path('admin/users/<int:user_id>', admin_user_detail, name='admin_user_detail'),
    path('admin/users/<int:user_id>/update', admin_user_update, name='admin_user_update'),
    path('admin/users/<int:user_id>/topup', admin_topup_user, name='admin_user_topup'),
    path('admin/users/<int:user_id>/freeze-wallet', admin_views.admin_user_freeze_wallet, name='admin_user_freeze_wallet'),
    path('admin/transactions', admin_transactions_list, name='admin_transactions_list'),
    path('admin/transactions/<str:transaction_id>', admin_transaction_detail, name='admin_transaction_detail'),
    path('admin/transactions/<str:transaction_id>/reverse', ReversalView.as_view(), name='admin_transaction_reverse'),
    path('admin/requests', admin_requests_list, name='admin_requests_list'),
    path('admin/splits', admin_splits_list, name='admin_splits_list'),
    path('admin/transfer-attempts', admin_transfer_attempts, name='admin_transfer_attempts'),
    path('admin/audit-log', admin_audit_log, name='admin_audit_log'),
    path('admin/settings', admin_settings_list, name='admin_settings_list'),
    path('admin/settings/<str:key>', admin_settings_update, name='admin_settings_update'),
    path('admin/reconciliation/last-run', admin_reconciliation_last_run, name='admin_reconciliation_last_run'),
    path('admin/reconciliation/run', admin_reconciliation_run, name='admin_reconciliation_run'),
    
    # Task Operations & Monitoring
    path('admin/tasks/periodic', admin_views.admin_periodic_tasks_list, name='admin_periodic_tasks_list'),
    path('admin/tasks/periodic/<int:task_id>/toggle', admin_views.admin_periodic_task_toggle, name='admin_periodic_task_toggle'),
    path('admin/tasks/periodic/<int:task_id>/run-now', admin_views.admin_periodic_task_run_now, name='admin_periodic_task_run_now'),

    # Support Ticket System
    path('admin/support/tickets', admin_views.admin_support_tickets_list, name='admin_support_tickets_list'),
    path('admin/support/tickets/create', admin_views.admin_support_ticket_create, name='admin_support_ticket_create'),
    path('admin/support/tickets/<int:ticket_id>', admin_views.admin_support_ticket_detail, name='admin_support_ticket_detail'),
    path('admin/support/tickets/<int:ticket_id>/update', admin_views.admin_support_ticket_update, name='admin_support_ticket_update'),
    path('admin/support/tickets/<int:ticket_id>/messages', admin_views.admin_support_ticket_add_message, name='admin_support_ticket_add_message'),
    path('admin/support/metrics', admin_views.admin_support_metrics, name='admin_support_metrics'),

    # KYC & Compliance Review
    path('admin/kyc/user-submissions', admin_views.admin_user_kyc_list, name='admin_user_kyc_list'),
    path('admin/kyc/user-submissions/<int:submission_id>/review', admin_views.admin_user_kyc_review, name='admin_user_kyc_review'),

    # Mobile Money & Webhook Operations
    path('admin/mobile-money/transactions', admin_views.admin_mobile_money_list, name='admin_mobile_money_list'),
    path('admin/mobile-money/transactions/<int:transaction_id>/retry', admin_views.admin_mobile_money_retry, name='admin_mobile_money_retry'),
    path('admin/merchants/webhooks/failed', admin_views.admin_failed_webhooks_list, name='admin_failed_webhooks_list'),
    path('admin/merchants/webhooks/<int:delivery_id>/retry', admin_views.admin_webhook_retry, name='admin_webhook_retry'),

    # Financial & FX Control
    path('admin/finance/fee-rules', admin_views.admin_fee_rules_list_create, name='admin_fee_rules_list_create'),
    path('admin/finance/fee-waivers', admin_views.admin_fee_waiver_create, name='admin_fee_waiver_create'),
    path('admin/finance/exchange-rates', admin_views.admin_exchange_rates_list, name='admin_exchange_rates_list'),
    path('admin/finance/exchange-rates/refresh', admin_views.admin_exchange_rates_refresh, name='admin_exchange_rates_refresh'),

    # Admin Team Management
    path('admin/team', admin_views.admin_team_list, name='admin_team_list'),
    path('admin/devices/push', admin_views.admin_push_devices_list, name='admin_push_devices_list'),
    path('admin/devices/push/<int:device_id>/toggle', admin_views.admin_push_device_toggle, name='admin_push_device_toggle'),
    path('admin/devices/trusted', admin_views.admin_trusted_devices_list, name='admin_trusted_devices_list'),
    path('admin/devices/trusted/<int:device_id>/revoke', admin_views.admin_trusted_device_revoke, name='admin_trusted_device_revoke'),
    path('admin/parental-controls', admin_views.admin_parental_controls_list, name='admin_parental_controls_list'),
    path('admin/parental-controls/<int:control_id>', admin_views.admin_parental_control_update, name='admin_parental_control_update'),

    # New Production-Ready Admin Endpoints
    path('admin/analytics', admin_views.admin_analytics, name='admin_analytics'),
    path('admin/users/<int:user_id>/notes', admin_views.admin_user_notes, name='admin_user_notes'),
    path('admin/users/bulk-action', admin_views.admin_bulk_user_action, name='admin_bulk_user_action'),
    path('admin/transactions/<str:transaction_id>/flags', admin_views.admin_transaction_flags, name='admin_transaction_flags'),
    path('admin/system/health', admin_views.admin_system_health, name='admin_system_health'),
    path('admin/alerts/rules', admin_views.admin_alert_rules, name='admin_alert_rules'),
    path('admin/settlements', admin_views.admin_settlements, name='admin_settlements'),
    path('admin/reports', admin_views.admin_reports, name='admin_reports'),
    path('admin/system/operations', admin_views.admin_system_operations, name='admin_system_operations'),
    path('admin/communications', admin_views.admin_communications, name='admin_communications'),

    # Core admin CRUD API
    path('admin/crud/users', admin_api.admin_users_crud, name='admin_crud_users'),
    path('admin/crud/users/<int:user_id>', admin_api.admin_user_crud_detail, name='admin_crud_user_detail'),
    path('admin/crud/wallets', admin_api.admin_wallets_crud, name='admin_crud_wallets'),
    path('admin/crud/wallets/<int:wallet_id>', admin_api.admin_wallet_crud_detail, name='admin_crud_wallet_detail'),
    path('admin/crud/transactions', admin_api.admin_transactions_crud, name='admin_crud_transactions'),
    path('admin/crud/transactions/<str:transaction_id>', admin_api.admin_transaction_crud_detail, name='admin_crud_transaction_detail'),
    path('admin/crud/tasks', admin_api.admin_periodic_tasks_crud, name='admin_crud_tasks'),
    path('admin/crud/tasks/<int:task_id>', admin_api.admin_periodic_task_crud_detail, name='admin_crud_task_detail'),

    
    # Disputes
    path('disputes/create', create_dispute, name='create_dispute'),
    path('disputes', list_disputes, name='list_disputes'),
    path('disputes/<int:dispute_id>', get_dispute_detail, name='get_dispute_detail'),
    path('disputes/<int:dispute_id>/resolve', resolve_dispute, name='resolve_dispute'),
    path('admin/disputes', admin_list_disputes, name='admin_list_disputes'),
    
    # Mobile Money
    path('mobile-money/topup', mobile_money_topup, name='mobile_money_topup'),
    path('mobile-money/withdrawal', mobile_money_withdrawal, name='mobile_money_withdrawal'),
    path('mobile-money/webhook', mobile_money_webhook, name='mobile_money_webhook'),
    path('mobile-money/transactions', list_mobile_money_transactions, name='list_mobile_money_transactions'),
    path('mobile-money/providers', list_linked_providers, name='list_linked_providers'),
    path('mobile-money/providers/link', link_mobile_money_provider, name='link_mobile_money_provider'),
    
    # Scheduled Transfers
    path('scheduled-transfers/create', create_scheduled_transfer, name='create_scheduled_transfer'),
    path('scheduled-transfers', list_scheduled_transfers, name='list_scheduled_transfers'),
    path('scheduled-transfers/<int:transfer_id>', get_scheduled_transfer_detail, name='get_scheduled_transfer_detail'),
    path('scheduled-transfers/<int:transfer_id>/pause', pause_scheduled_transfer, name='pause_scheduled_transfer'),
    path('scheduled-transfers/<int:transfer_id>/resume', resume_scheduled_transfer, name='resume_scheduled_transfer'),
    path('scheduled-transfers/<int:transfer_id>/cancel', cancel_scheduled_transfer, name='cancel_scheduled_transfer'),
    
    # Merchant Accounts
    path('merchant-plans', merchant_plans, name='merchant_plans'),
    path('merchants/create', create_merchant_account, name='create_merchant_account'),
    path('merchants/me', get_merchant_account, name='get_merchant_account'),
    path('merchants/me/subscription', merchant_subscription, name='merchant_subscription'),
    path('merchants/me/qr', generate_merchant_qr, name='generate_merchant_qr'),
    path('merchants/me/dashboard', merchant_dashboard, name='merchant_dashboard'),
    path('merchants/me/transactions', merchant_views.merchant_session_transactions, name='merchant_session_transactions'),
    path('merchants/me/transactions/<str:transaction_id>', merchant_views.merchant_session_transaction_detail, name='merchant_session_transaction_detail'),
    path('merchants/me/limits', merchant_views.merchant_session_limits, name='merchant_session_limits'),
    path('merchants/me/settlements', merchant_views.merchant_session_settlements, name='merchant_session_settlements'),
    path('merchants/me/disputes', merchant_views.merchant_session_disputes, name='merchant_session_disputes'),
    path('merchants/me/payout-schedule', merchant_payout_schedule, name='merchant_payout_schedule'),
    path('merchants/me/logs', merchant_logs, name='merchant_logs'),
    path('merchants/me/payment-links', merchant_payment_links, name='merchant_payment_links'),
    path('merchants/me/payment-links/<int:intent_id>/deactivate', deactivate_merchant_payment_link, name='deactivate_merchant_payment_link'),
    path('merchants/me/kyc-documents', merchant_kyc_documents, name='merchant_kyc_documents'),
    path('merchants/me/credentials', merchant_credentials, name='merchant_credentials'),
    path('merchants/me/webhook', merchant_webhook_config, name='merchant_webhook_config'),
    path('admin/merchants', admin_list_merchants, name='admin_list_merchants'),
    path('admin/merchants/<int:merchant_id>/approve', admin_approve_merchant, name='admin_approve_merchant'),
    
    # Transaction Approvals
    path('approvals/pending', list_pending_approvals, name='list_pending_approvals'),
    path('approvals/<int:approval_id>/approve', approve_transaction, name='approve_transaction'),
    path('approvals/<int:approval_id>/decline', decline_transaction, name='decline_transaction'),
    
    # Parental Controls
    path('parental/link', link_child_account, name='link_child_account'),
    path('parental/<int:control_id>/verify', verify_parental_link, name='verify_parental_link'),
    path('parental/children', list_child_accounts, name='list_child_accounts'),
    path('parental/parents', list_parent_accounts, name='list_parent_accounts'),
    path('parental/<int:child_id>/balance', get_child_balance, name='get_child_balance'),
    path('parental/<int:child_id>/transactions', get_child_transactions, name='get_child_transactions'),
    path('parental/<int:child_id>/send', send_to_child, name='send_to_child'),
    path('parental/<int:child_id>/wallet-status', set_child_wallet_status, name='set_child_wallet_status'),
    path('parental/<int:control_id>/permissions', update_parental_permissions, name='update_parental_permissions'),
    path('parental/<int:control_id>/revoke', revoke_parental_control, name='revoke_parental_control'),
]
