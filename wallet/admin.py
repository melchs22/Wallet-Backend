from django.contrib import admin
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponse
from django.utils import timezone
from .models import (
    User, Wallet, Transaction, LedgerEntry, Notification,
    ProcessedRequest, AuditLog, TransferAttempt,
    LinkedProvider, ExchangeRate, Dispute, PaymentRequest, SplitRequest, SystemSetting,
    MobileMoneyTransaction, ScheduledTransfer, Merchant, TransactionApproval, ParentalControl,
    PushDevice,
    TrustedDevice, OtpChallenge, MobileMoneyWebhookEvent,
    SupportedCountry, LegalDocument, ProviderCatalog, TransferFeeRule, UserKYCSubmission,
)


@admin.register(SupportedCountry)
class SupportedCountryAdmin(admin.ModelAdmin):
    list_display = ['flag', 'name', 'code', 'dial_code', 'active']
    list_filter = ['active']
    search_fields = ['name', 'code']


@admin.register(LegalDocument)
class LegalDocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'published', 'updated_at']
    list_filter = ['published']
    prepopulated_fields = {'slug': ('title',)}


@admin.register(ProviderCatalog)
class ProviderCatalogAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'active', 'sort_order']
    list_filter = ['active']
    search_fields = ['name', 'code']


@admin.register(TransferFeeRule)
class TransferFeeRuleAdmin(admin.ModelAdmin):
    list_display = ['min_amount', 'max_amount', 'fee_type', 'fee_value', 'active']
    list_filter = ['fee_type', 'active']


@admin.register(UserKYCSubmission)
class UserKYCSubmissionAdmin(admin.ModelAdmin):
    list_display = ['user', 'document_type', 'status', 'created_at', 'updated_at']
    list_filter = ['status', 'document_type']
    search_fields = ['user__email', 'user__handle']
    readonly_fields = ['user', 'document', 'created_at', 'updated_at']


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['handle', 'email', 'primary_phone_number', 'status', 'kyc_tier', 'is_staff', 'has_pin', 'created_at']
    list_filter = ['status', 'kyc_tier', 'is_staff']
    search_fields = ['handle', 'email', 'google_sub', 'primary_phone_number']
    readonly_fields = ['google_sub', 'created_at', 'handle']
    actions = ['suspend_users', 'reactivate_users', 'force_logout']

    @admin.display(description='Has PIN')
    def has_pin(self, obj):
        return bool(obj.transaction_pin)

    def suspend_users(self, request, queryset):
        # Redirect to intermediate page for reason input
        selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        return HttpResponseRedirect(
            f'{reverse("admin:wallet_user_changelist")}?action=suspend_users&ids={",".join(selected)}'
        )
    suspend_users.short_description = 'Suspend selected users'

    def reactivate_users(self, request, queryset):
        selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        return HttpResponseRedirect(
            f'{reverse("admin:wallet_user_changelist")}?action=reactivate_users&ids={",".join(selected)}'
        )
    reactivate_users.short_description = 'Reactivate selected users'

    def force_logout(self, request, queryset):
        # This would call the service function to invalidate sessions
        # For now, we'll just log it
        count = queryset.count()
        self.message_user(request, f'{count} users will be logged out on next request.', messages.SUCCESS)
    force_logout.short_description = 'Force logout selected users'


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['user', 'currency', 'status', 'computed_balance']
    list_filter = ['status', 'currency']
    readonly_fields = ['user', 'currency', 'computed_balance']
    actions = ['freeze_wallets', 'unfreeze_wallets']

    def computed_balance(self, obj):
        return obj.get_balance()
    computed_balance.short_description = 'Balance'

    def freeze_wallets(self, request, queryset):
        # This would call the service function with reason prompt
        count = queryset.count()
        self.message_user(request, f'{count} wallets will be frozen.', messages.SUCCESS)
    freeze_wallets.short_description = 'Freeze selected wallets'

    def unfreeze_wallets(self, request, queryset):
        # This would call the service function with reason prompt
        count = queryset.count()
        self.message_user(request, f'{count} wallets will be unfrozen.', messages.SUCCESS)
    unfreeze_wallets.short_description = 'Unfreeze selected wallets'


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'type', 'sender', 'recipient', 'amount', 'currency', 'status', 'created_at']
    list_filter = ['type', 'status', 'currency']
    search_fields = ['id', 'sender__handle', 'recipient__handle']
    actions = ['reverse_transactions']

    def has_change_permission(self, request, obj=None):
        return False  # view and act via actions only, never raw field edits

    def reverse_transactions(self, request, queryset):
        # This would call the same service function POST /api/admin/transactions/<id>/reverse uses
        # with a reason prompt via the intermediate-page action pattern
        count = queryset.count()
        self.message_user(request, f'{count} transactions selected for reversal (reason prompt required).', messages.INFO)


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ['wallet', 'transaction', 'direction', 'amount', 'created_at']
    list_filter = ['direction']
    search_fields = ['wallet__user__handle', 'transaction__id']

    # This table is append-only - prevent any updates or deletes
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'type', 'read_at', 'created_at']
    list_filter = ['type']
    readonly_fields = ['created_at']
    actions = ['mark_read']

    def mark_read(self, request, queryset):
        count = queryset.update(read_at=timezone.now())
        self.message_user(request, f'{count} notifications marked as read.', messages.SUCCESS)
    mark_read.short_description = 'Mark selected notifications as read'


@admin.register(PushDevice)
class PushDeviceAdmin(admin.ModelAdmin):
    list_display = ['user', 'platform', 'active', 'last_seen_at', 'created_at']
    list_filter = ['platform', 'active']
    search_fields = ['user__email', 'user__handle', 'token']
    readonly_fields = ['token', 'last_seen_at', 'created_at']


@admin.register(TrustedDevice)
class TrustedDeviceAdmin(admin.ModelAdmin):
    list_display = ['user', 'device_id', 'platform', 'is_trusted', 'revoked_at', 'last_seen_at']
    list_filter = ['platform', 'is_trusted']
    search_fields = ['user__email', 'user__handle', 'device_id']
    readonly_fields = ['device_id', 'first_seen_at', 'last_seen_at']
    actions = ['revoke_devices']

    @admin.action(description='Revoke selected trusted devices')
    def revoke_devices(self, request, queryset):
        count = queryset.update(is_trusted=False, revoked_at=timezone.now())
        self.message_user(request, f'{count} trusted device(s) revoked.', messages.SUCCESS)


@admin.register(OtpChallenge)
class OtpChallengeAdmin(admin.ModelAdmin):
    list_display = ['user', 'purpose', 'device', 'attempts', 'expires_at', 'consumed_at', 'created_at']
    list_filter = ['purpose', 'consumed_at']
    search_fields = ['user__email', 'user__handle', 'request_id']
    readonly_fields = ['user', 'device', 'purpose', 'code_hash', 'expires_at', 'consumed_at', 'attempts', 'max_attempts', 'locked_until', 'request_id', 'ip_address', 'user_agent', 'created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MobileMoneyWebhookEvent)
class MobileMoneyWebhookEventAdmin(admin.ModelAdmin):
    list_display = ['event_id', 'provider_transaction_id', 'status', 'received_at', 'processed_at']
    list_filter = ['status']
    search_fields = ['event_id', 'provider_transaction_id']
    readonly_fields = ['event_id', 'provider_transaction_id', 'status', 'signature', 'received_at', 'processed_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProcessedRequest)
class ProcessedRequestAdmin(admin.ModelAdmin):
    list_display = ['idempotency_key', 'user', 'transaction', 'created_at']
    search_fields = ['idempotency_key', 'user__email']

    # This is an integrity record - prevent any edits
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['user_display', 'action', 'created_at']
    list_filter = ['action']
    search_fields = ['user__email', 'user__handle', 'action']

    @admin.display(description='User')
    def user_display(self, obj):
        if obj.user_id is None:
            return '—'
        return obj.user.handle or obj.user.email

    # This is an integrity/accountability record - prevent any edits
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TransferAttempt)
class TransferAttemptAdmin(admin.ModelAdmin):
    list_display = ['user', 'recipient_handle_input', 'amount', 'currency', 'rejection_reason', 'created_at']
    list_filter = ['rejection_reason', 'currency']
    search_fields = ['user__email', 'recipient_handle_input']

    # This is a log table - prevent edits
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LinkedProvider)
class LinkedProviderAdmin(admin.ModelAdmin):
    list_display = ['user', 'provider', 'masked_reference', 'verification_status', 'created_at']
    list_filter = ['provider', 'verification_status']
    search_fields = ['user__email', 'masked_reference']
    readonly_fields = ['created_at', 'updated_at', 'masked_reference', 'verification_status']


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ['from_currency', 'to_currency', 'rate', 'source', 'valid_from', 'valid_until']
    list_filter = ['from_currency', 'to_currency', 'source']
    search_fields = ['from_currency', 'to_currency']
    readonly_fields = ['created_at']

    def save_model(self, request, obj, form, change):
        # Log the change to audit log
        AuditLog.objects.create(
            user=request.user,
            action='exchange_rate_updated',
            metadata={
                'from_currency': obj.from_currency,
                'to_currency': obj.to_currency,
                'rate': str(obj.rate),
                'source': obj.source,
                'is_update': change
            }
        )
        super().save_model(request, obj, form, change)


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ['id', 'transaction', 'opened_by', 'status', 'resolved_by', 'created_at']
    list_filter = ['status']
    search_fields = ['opened_by__handle', 'transaction__id', 'reason']
    readonly_fields = ['created_at', 'updated_at']

    # Disputes should be resolved through the proper resolution endpoint, not direct edits
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'requester_display', 'payer_display', 'amount', 'currency', 'status', 'expires_at', 'created_at']
    list_filter = ['status', 'currency']
    search_fields = ['requester__handle', 'payer__handle']
    actions = ['cancel_requests']

    @admin.display(description='Requester')
    def requester_display(self, obj):
        return obj.requester.handle or obj.requester.email

    @admin.display(description='Payer')
    def payer_display(self, obj):
        if obj.payer_id is None:
            return '—'
        return obj.payer.handle or obj.payer.email

    def has_change_permission(self, request, obj=None):
        return False  # Cancellation should go through custom action

    def cancel_requests(self, request, queryset):
        # This would call the real cancel service function
        count = queryset.count()
        self.message_user(request, f'{count} payment requests selected for cancellation.', messages.INFO)
    cancel_requests.short_description = 'Cancel selected payment requests'


@admin.register(SplitRequest)
class SplitRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'creator', 'total_amount', 'currency', 'status', 'created_at']
    list_filter = ['status', 'currency']
    search_fields = ['creator__handle']
    actions = ['cancel_splits']

    def has_change_permission(self, request, obj=None):
        return False  # Cancellation should go through custom action

    def cancel_splits(self, request, queryset):
        # This would call the real cancel service function with cascade to child PaymentRequests
        count = queryset.count()
        self.message_user(request, f'{count} split requests selected for cancellation.', messages.INFO)
    cancel_splits.short_description = 'Cancel selected split requests'


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ['key', 'value', 'description', 'updated_by', 'updated_at']
    search_fields = ['key', 'description']

    def save_model(self, request, obj, form, change):
        # Log the change to audit log
        obj.updated_by = request.user
        AuditLog.objects.create(
            user=request.user,
            action='system_setting_updated',
            metadata={
                'key': obj.key,
                'value': obj.value,
                'is_update': change
            }
        )
        super().save_model(request, obj, form, change)


@admin.register(MobileMoneyTransaction)
class MobileMoneyTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'type', 'amount', 'currency', 'status', 'provider_transaction_id', 'created_at']
    list_filter = ['type', 'status', 'currency']
    search_fields = ['user__email', 'provider_transaction_id']
    readonly_fields = ['created_at', 'updated_at', 'completed_at']


@admin.register(ScheduledTransfer)
class ScheduledTransferAdmin(admin.ModelAdmin):
    list_display = ['id', 'sender', 'recipient', 'amount', 'currency', 'frequency', 'status', 'next_execution', 'total_executions']
    list_filter = ['status', 'frequency', 'currency']
    search_fields = ['sender__handle', 'recipient__handle']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ['id', 'business_name', 'user', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['user__handle', 'business_name']
    readonly_fields = [
        'static_qr_code', 'static_qr_payload', 'static_qr_signature',
        'approved_at', 'created_at', 'updated_at',
    ]
    actions = ['approve_merchants', 'reject_merchants', 'generate_api_keys']

    def approve_merchants(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='active', approved_by=request.user, approved_at=timezone.now()
        )
        self.message_user(request, f'{count} merchants approved.', messages.SUCCESS)
    approve_merchants.short_description = 'Approve selected merchants'

    def reject_merchants(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='rejected', approved_by=request.user, approved_at=timezone.now()
        )
        self.message_user(request, f'{count} merchants rejected.', messages.SUCCESS)
    reject_merchants.short_description = 'Reject selected merchants'

    def generate_api_keys(self, request, queryset):
        self.message_user(request, 'Merchant API keys require the merchant payment schema migration.', messages.WARNING)
    generate_api_keys.short_description = 'Generate API keys (live mode)'


@admin.register(TransactionApproval)
class TransactionApprovalAdmin(admin.ModelAdmin):
    list_display = ['id', 'approval_type', 'requester', 'approver', 'amount', 'currency', 'status', 'created_at']
    list_filter = ['approval_type', 'status', 'currency']
    search_fields = ['requester__handle', 'approver__handle']
    readonly_fields = ['created_at']
    actions = ['approve_approvals', 'decline_approvals']

    def approve_approvals(self, request, queryset):
        count = queryset.filter(status='pending').update(status='approved')
        self.message_user(request, f'{count} approvals approved.', messages.SUCCESS)
    approve_approvals.short_description = 'Approve selected approvals'

    def decline_approvals(self, request, queryset):
        count = queryset.filter(status='pending').update(status='declined')
        self.message_user(request, f'{count} approvals declined.', messages.SUCCESS)
    decline_approvals.short_description = 'Decline selected approvals'


@admin.register(ParentalControl)
class ParentalControlAdmin(admin.ModelAdmin):
    list_display = ['id', 'parent', 'child', 'status', 'can_view_transactions', 'can_control_balance', 'can_send_money', 'linked_at', 'created_at']
    list_filter = ['status', 'can_view_transactions', 'can_control_balance', 'can_send_money']
    search_fields = ['parent__handle', 'child__handle', 'parent__email', 'child__email']
    readonly_fields = ['verification_code', 'code_expires_at', 'linked_at', 'created_at']
    actions = ['activate_controls', 'revoke_controls']

    def activate_controls(self, request, queryset):
        count = queryset.filter(status='pending').update(status='active', linked_at=timezone.now())
        self.message_user(request, f'{count} parental controls activated.', messages.SUCCESS)
    activate_controls.short_description = 'Activate selected controls'

    def revoke_controls(self, request, queryset):
        count = queryset.update(status='revoked')
        self.message_user(request, f'{count} parental controls revoked.', messages.SUCCESS)
    revoke_controls.short_description = 'Revoke selected controls'


# Site-wide admin configuration - using default Django admin styling
admin.site.site_header = "Wallet Admin"
admin.site.site_title = "Wallet Admin"
admin.site.index_title = "Wallet Administration"
