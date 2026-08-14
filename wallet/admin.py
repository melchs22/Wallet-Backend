from django.contrib import admin
from .models import (
    User, Wallet, Transaction, LedgerEntry, Notification,
    ProcessedRequest, AuditLog, PendingTransfer, TransferAttempt,
    LinkedProvider, ExchangeRate
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['email', 'handle', 'display_name', 'status', 'kyc_tier', 'created_at']
    list_filter = ['status', 'kyc_tier']
    search_fields = ['email', 'handle', 'display_name']
    readonly_fields = ['google_sub', 'created_at', 'handle_changed_at']


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['user', 'currency', 'status', 'created_at']
    list_filter = ['status', 'currency']
    readonly_fields = ['created_at']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'type', 'sender', 'recipient', 'amount', 'currency', 'status', 'created_at']
    list_filter = ['type', 'status', 'currency']
    search_fields = ['sender__email', 'recipient__email', 'note']
    readonly_fields = ['created_at']
    
    # Prevent editing or deleting transactions
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ['wallet', 'transaction', 'direction', 'amount', 'created_at']
    list_filter = ['direction']
    readonly_fields = ['created_at']
    
    # This table is append-only - prevent any updates or deletes
    def has_add_permission(self, request):
        return False  # Entries should only be created via transaction logic
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'type', 'read_at', 'created_at']
    list_filter = ['type']
    readonly_fields = ['created_at']


@admin.register(ProcessedRequest)
class ProcessedRequestAdmin(admin.ModelAdmin):
    list_display = ['idempotency_key', 'user', 'transaction', 'created_at']
    search_fields = ['idempotency_key', 'user__email']
    readonly_fields = ['created_at']
    
    # Prevent editing idempotency keys
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'created_at']
    list_filter = ['action']
    search_fields = ['user__email', 'action']
    readonly_fields = ['created_at']
    
    # Audit logs should be append-only
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PendingTransfer)
class PendingTransferAdmin(admin.ModelAdmin):
    list_display = ['sender', 'recipient_email', 'amount', 'currency', 'status', 'created_at']
    list_filter = ['status', 'currency']
    search_fields = ['recipient_email', 'sender__email']
    readonly_fields = ['claim_token', 'created_at']


@admin.register(TransferAttempt)
class TransferAttemptAdmin(admin.ModelAdmin):
    list_display = ['user', 'recipient_handle_input', 'amount', 'currency', 'rejection_reason', 'created_at']
    list_filter = ['rejection_reason', 'currency']
    search_fields = ['user__email', 'recipient_handle_input']
    readonly_fields = ['created_at']
    
    # This is a log table - prevent edits
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LinkedProvider)
class LinkedProviderAdmin(admin.ModelAdmin):
    list_display = ['user', 'provider', 'masked_reference', 'verification_status', 'created_at']
    list_filter = ['provider', 'verification_status']
    search_fields = ['user__email', 'masked_reference']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ['from_currency', 'to_currency', 'rate', 'source', 'valid_from', 'valid_until']
    list_filter = ['from_currency', 'to_currency', 'source']
    search_fields = ['from_currency', 'to_currency']
    readonly_fields = ['created_at']
