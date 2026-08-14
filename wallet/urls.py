from django.urls import path
from .views import (
    GoogleAuthView, logout_view, MeView, UserResolveView,
    TransferView, NotificationListView, NotificationDetailView,
    WalletView, TransactionListView, CloseAccountView,
    TransactionDetailView, ReversalView
)

urlpatterns = [
    # Authentication
    path('auth/google', GoogleAuthView.as_view(), name='google_auth'),
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
]
