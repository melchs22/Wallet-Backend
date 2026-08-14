from django.urls import path
from .views import (
    GoogleAuthView, csrf_cookie_view, logout_view, MeView, UserResolveView,
    TransferView, NotificationListView, NotificationDetailView,
    WalletView, TransactionListView, CloseAccountView,
    TransactionDetailView, ReversalView, AdminLoginView,
    admin_dashboard, admin_users_list, admin_user_detail, admin_user_update,
    admin_transactions_list, admin_transaction_detail, admin_transfer_attempts, admin_audit_log
)

urlpatterns = [
    # Authentication
    path('auth/google', GoogleAuthView.as_view(), name='google_auth'),
    path('auth/admin', AdminLoginView.as_view(), name='admin_login'),
    path('csrf', csrf_cookie_view, name='csrf_cookie'),
    path('auth/logout', logout_view, name='logout'),
    path('me', MeView.as_view(), name='me'),
    
    # User resolution
    path('users/resolve', UserResolveView.as_view(), name='user_resolve'),
    
    # Transfers (create transfer)
    path('transfers', TransferView.as_view(), name='transfer'),
    
    # Notifications
    path('notifications', NotificationListView.as_view(), name='notification_list'),
    path('notifications/<int:id>/read', NotificationDetailView.as_view(), name='notification_read'),
    
    # Wallet
    path('wallet', WalletView.as_view(), name='wallet'),
    
    # Transactions (list and detail)
    path('transactions', TransactionListView.as_view(), name='transaction_list'),
    path('transactions/<str:transaction_id>', TransactionDetailView.as_view(), name='transaction_detail'),
    
    # Admin operations
    path('transfers/<str:transaction_id>/reverse', ReversalView.as_view(), name='transaction_reverse'),
    
    # Account management
    path('me/close', CloseAccountView.as_view(), name='close_account'),
    
    # Admin API endpoints
    path('admin/dashboard', admin_dashboard, name='admin_dashboard'),
    path('admin/users', admin_users_list, name='admin_users_list'),
    path('admin/users/<int:user_id>', admin_user_detail, name='admin_user_detail'),
    path('admin/users/<int:user_id>/update', admin_user_update, name='admin_user_update'),
    path('admin/transactions', admin_transactions_list, name='admin_transactions_list'),
    path('admin/transactions/<str:transaction_id>', admin_transaction_detail, name='admin_transaction_detail'),
    path('admin/transactions/<str:transaction_id>/reverse', ReversalView.as_view(), name='admin_transaction_reverse'),
    path('admin/transfer-attempts', admin_transfer_attempts, name='admin_transfer_attempts'),
    path('admin/audit-log', admin_audit_log, name='admin_audit_log'),
]
