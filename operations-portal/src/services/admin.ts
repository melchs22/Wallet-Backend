import { request } from '@umijs/max';

export type DashboardStats = { total_users: number; active_users: number; suspended_users: number; closed_users: number; total_wallets: number; p2p_volume_today: string; p2p_volume_week: string; pending_payment_requests: number; frozen_wallets: number; transfer_attempt_rejections_24h: number };
export type AdminUser = { id: number; handle?: string; display_name?: string; email?: string; primary_phone_number?: string; status?: string; kyc_tier?: string; is_staff?: boolean; created_at?: string; wallet?: { id: number; status: string; balance?: string; currency?: string } };
export type AdminTransaction = { id: string; type?: string; sender?: string | { handle?: string }; recipient?: string | { handle?: string }; sender_handle?: string; recipient_handle?: string; amount?: string; currency?: string; status?: string; created_at?: string };
export type AdminList<T> = { results?: T[]; count?: number; next?: string | null };

export type AdminRow = Record<string, unknown>;
export type AdminResourceConfig = { key: string; title: string; description: string; path: string; searchPlaceholder?: string; filters?: string[]; detailTitle?: string; columns: { key: string; label: string; date?: boolean; status?: boolean; statusColors?: Record<string, string> }[]; extract: (data: unknown) => AdminRow[]; actions?: { label: string; method: string; path: (row: AdminRow) => string; icon?: string; confirm?: string }[] };

export const adminRequest = <T>(path: string, options: Record<string, unknown> = {}) => request<T>(path, {
	credentials: 'include',
	headers: {
		...(localStorage.getItem('admin_access_token') ? { Authorization: ['Bearer', localStorage.getItem('admin_access_token')].join(' ') } : {}),
		...(localStorage.getItem('wallet_device_id') ? { 'X-Device-ID': localStorage.getItem('wallet_device_id') } : {}),
		...(options.headers as Record<string, string> | undefined),
	},
	...options,
});

const extractList = (data: unknown, keys: string[] = []) => {
	if (Array.isArray(data)) return data as AdminRow[];
	const record = (data || {}) as Record<string, unknown>;
	for (const key of keys) if (Array.isArray(record[key])) return record[key] as AdminRow[];
	if (Array.isArray(record.results)) return record.results as AdminRow[];
	return [];
};

const standardStatus = ['pending', 'active', 'completed', 'failed', 'approved', 'rejected', 'suspended', 'frozen'];
const resource = (config: Omit<AdminResourceConfig, 'extract'> & { extractKeys?: string[] }): AdminResourceConfig => ({ ...config, extract: (data) => extractList(data, config.extractKeys) });

export function getAdminResourceConfig(pathname: string): AdminResourceConfig {
	const configs: AdminResourceConfig[] = [
		resource({ key: 'users', title: 'Customer accounts', description: 'Search, review, and manage wallet users.', path: '/admin/users', searchPlaceholder: 'Handle, email, phone', filters: ['active', 'suspended', 'closed'], columns: [{ key: 'handle', label: 'Handle' }, { key: 'email', label: 'Email' }, { key: 'status', label: 'Status', status: true }, { key: 'kyc_tier', label: 'KYC' }, { key: 'created_at', label: 'Created', date: true }], actions: [{ label: 'Suspend', method: 'PATCH', path: (row) => `/admin/users/${row.id}/update`, confirm: 'Suspend this account?' }] }),
		resource({ key: 'wallets', title: 'Wallet accounts', description: 'Review balances, currencies, and wallet status.', path: '/admin/crud/wallets', extractKeys: ['wallets'], columns: [{ key: 'id', label: 'Wallet' }, { key: 'user', label: 'User' }, { key: 'currency', label: 'Currency' }, { key: 'balance', label: 'Balance' }, { key: 'status', label: 'Status', status: true, statusColors: { active: 'success', frozen: 'error' } }] }),
		resource({ key: 'transactions', title: 'Transactions', description: 'Inspect the financial ledger and transaction state.', path: '/admin/transactions', searchPlaceholder: 'Reference or handle', filters: standardStatus, columns: [{ key: 'id', label: 'Reference' }, { key: 'type', label: 'Type' }, { key: 'sender', label: 'Sender' }, { key: 'recipient', label: 'Recipient' }, { key: 'amount', label: 'Amount' }, { key: 'status', label: 'Status', status: true }, { key: 'created_at', label: 'Created', date: true }], actions: [{ label: 'Reverse', method: 'POST', path: (row) => `/admin/transactions/${row.id}/reverse`, icon: 'stop', confirm: 'Create a reversal for this transaction?' }] }),
		resource({ key: 'requests', title: 'Payment requests', description: 'Monitor pending, paid, declined, and expired requests.', path: '/admin/requests', columns: [{ key: 'id', label: 'Request' }, { key: 'requester', label: 'Requester' }, { key: 'amount', label: 'Amount' }, { key: 'status', label: 'Status', status: true }, { key: 'created_at', label: 'Created', date: true }] }),
		resource({ key: 'splits', title: 'Bill splits', description: 'Review shared payment activity and participant status.', path: '/admin/splits', columns: [{ key: 'id', label: 'Split' }, { key: 'creator', label: 'Creator' }, { key: 'amount', label: 'Amount' }, { key: 'status', label: 'Status', status: true }, { key: 'created_at', label: 'Created', date: true }] }),
		resource({ key: 'attempts', title: 'Transfer attempts', description: 'Investigate rejected and blocked transfer attempts.', path: '/admin/transfer-attempts', searchPlaceholder: 'User or rejection reason', columns: [{ key: 'user', label: 'User' }, { key: 'amount', label: 'Amount' }, { key: 'rejection_reason', label: 'Reason' }, { key: 'created_at', label: 'Created', date: true }] }),
		resource({ key: 'audit', title: 'Audit trail', description: 'Immutable record of administrative and financial actions.', path: '/admin/audit-log', searchPlaceholder: 'Actor or action', columns: [{ key: 'user', label: 'Actor' }, { key: 'action', label: 'Action' }, { key: 'metadata', label: 'Metadata' }, { key: 'created_at', label: 'When', date: true }] }),
		resource({ key: 'settings', title: 'Platform settings', description: 'Review runtime settings used by wallet operations.', path: '/admin/settings', columns: [{ key: 'key', label: 'Key' }, { key: 'value', label: 'Value' }, { key: 'updated_at', label: 'Updated', date: true }] }),
		resource({ key: 'tasks', title: 'Scheduled tasks', description: 'Monitor, enable, disable, and run Celery schedules.', path: '/admin/tasks/periodic', extractKeys: ['tasks'], columns: [{ key: 'name', label: 'Name' }, { key: 'task', label: 'Task' }, { key: 'enabled', label: 'Enabled', status: true }, { key: 'last_run_at', label: 'Last run', date: true }], actions: [{ label: 'Run now', method: 'POST', path: (row) => `/admin/tasks/periodic/${row.id}/run-now`, icon: 'play', confirm: 'Queue this task immediately?' }, { label: 'Toggle', method: 'POST', path: (row) => `/admin/tasks/periodic/${row.id}/toggle`, icon: 'check' }] }),
		resource({ key: 'support', title: 'Support tickets', description: 'Manage customer conversations and operational escalations.', path: '/admin/support/tickets', extractKeys: ['tickets'], searchPlaceholder: 'Ticket, subject, handle', filters: ['open', 'in_progress', 'waiting_on_user', 'resolved', 'closed'], columns: [{ key: 'ticket_number', label: 'Ticket' }, { key: 'subject', label: 'Subject' }, { key: 'category', label: 'Category' }, { key: 'priority', label: 'Priority', status: true }, { key: 'status', label: 'Status', status: true }, { key: 'updated_at', label: 'Updated', date: true }] }),
		resource({ key: 'kyc', title: 'KYC review', description: 'Approve or reject identity submissions and update user tiers.', path: '/admin/kyc/user-submissions', extractKeys: ['submissions'], filters: ['pending', 'approved', 'rejected'], columns: [{ key: 'user', label: 'Applicant' }, { key: 'document_type', label: 'Document' }, { key: 'status', label: 'Status', status: true }, { key: 'created_at', label: 'Submitted', date: true }], actions: [{ label: 'Approve', method: 'POST', path: (row) => `/admin/kyc/user-submissions/${row.id}/review`, icon: 'check', confirm: 'Approve this submission?' }] }),
		resource({ key: 'mobile-money', title: 'Mobile money', description: 'Monitor top-ups, withdrawals, and provider state.', path: '/admin/mobile-money/transactions', extractKeys: ['transactions'], searchPlaceholder: 'Provider reference or user', filters: standardStatus, columns: [{ key: 'id', label: 'Reference' }, { key: 'user', label: 'User' }, { key: 'provider', label: 'Provider' }, { key: 'amount', label: 'Amount' }, { key: 'status', label: 'Status', status: true }, { key: 'created_at', label: 'Created', date: true }] }),
		resource({ key: 'webhooks', title: 'Failed webhooks', description: 'Retry merchant webhook deliveries that need attention.', path: '/admin/merchants/webhooks/failed', extractKeys: ['failed_webhooks'], columns: [{ key: 'id', label: 'Delivery' }, { key: 'merchant', label: 'Merchant' }, { key: 'event_type', label: 'Event' }, { key: 'status', label: 'Status', status: true }, { key: 'created_at', label: 'Created', date: true }], actions: [{ label: 'Retry', method: 'POST', path: (row) => `/admin/merchants/webhooks/${row.id}/retry`, icon: 'play', confirm: 'Queue webhook delivery again?' }] }),
		resource({ key: 'fee-rules', title: 'Transfer fee rules', description: 'Control fee bands and active pricing rules.', path: '/admin/finance/fee-rules', extractKeys: ['rules'], columns: [{ key: 'min_amount', label: 'Min amount' }, { key: 'max_amount', label: 'Max amount' }, { key: 'fee_type', label: 'Type' }, { key: 'fee_value', label: 'Value' }, { key: 'active', label: 'Active', status: true }] }),
		resource({ key: 'rates', title: 'Exchange rates', description: 'Review the latest FX rates and refresh provider data.', path: '/admin/finance/exchange-rates', extractKeys: ['exchange_rates'], columns: [{ key: 'base_currency', label: 'Base' }, { key: 'quote_currency', label: 'Quote' }, { key: 'rate', label: 'Rate' }, { key: 'valid_from', label: 'Valid from', date: true }] }),
		resource({ key: 'team', title: 'Admin team', description: 'Review staff accounts with access to the control plane.', path: '/admin/team', extractKeys: ['team_members'], columns: [{ key: 'username', label: 'Username' }, { key: 'email', label: 'Email' }, { key: 'is_staff', label: 'Staff', status: true }, { key: 'date_joined', label: 'Joined', date: true }] }),
		resource({ key: 'disputes', title: 'Disputes', description: 'Review customer disputes and resolution state.', path: '/admin/disputes', columns: [{ key: 'id', label: 'Dispute' }, { key: 'user', label: 'User' }, { key: 'reason', label: 'Reason' }, { key: 'status', label: 'Status', status: true }, { key: 'created_at', label: 'Created', date: true }] }),
		resource({ key: 'merchants', title: 'Merchants', description: 'Approve and monitor merchant accounts.', path: '/admin/merchants', columns: [{ key: 'id', label: 'Merchant' }, { key: 'business_name', label: 'Business' }, { key: 'owner', label: 'Owner' }, { key: 'status', label: 'Status', status: true }, { key: 'created_at', label: 'Created', date: true }] }),
	];
	return configs.find((item) => pathname === `/admin/${item.key}` || pathname.startsWith(`/admin/${item.key}/`)) || configs[0];
}
export const getDashboard = () => adminRequest<DashboardStats>('/admin/dashboard');
export const getUsers = (params: Record<string, string | number | undefined>) => adminRequest<AdminList<AdminUser>>('/admin/users', { params });
export const getUserDetail = (id: number) => adminRequest<AdminUser & { balance?: string; wallet_status?: string; send_limit_per_tx?: string; send_limit_daily?: string; recent_transactions?: AdminTransaction[]; recent_transfer_attempts?: AdminRow[]; linked_providers?: AdminRow[]; push_devices?: AdminRow[]; trusted_devices?: AdminRow[]; parental_controls?: AdminRow[] }>(`/admin/users/${id}`);
export const getPushDevices = (query = '') => adminRequest<{ devices: AdminRow[] }>('/admin/devices/push', { params: { query } });
export const togglePushDevice = (id: number) => adminRequest(`/admin/devices/push/${id}/toggle`, { method: 'POST', data: {} });
export const getTrustedDevices = (query = '') => adminRequest<{ devices: AdminRow[] }>('/admin/devices/trusted', { params: { query } });
export const revokeTrustedDevice = (id: number) => adminRequest(`/admin/devices/trusted/${id}/revoke`, { method: 'POST', data: {} });
export const getParentalControls = (params: Record<string, string>) => adminRequest<{ controls: AdminRow[] }>('/admin/parental-controls', { params });
export const updateParentalControl = (id: number, data: AdminRow) => adminRequest(`/admin/parental-controls/${id}`, { method: 'PATCH', data });
export const getTransactions = (params: Record<string, string | number | undefined>) => adminRequest<AdminList<AdminTransaction>>('/admin/transactions', { params });
export const getCrudWallets = () => adminRequest<{ id: number; user: number; currency: string; status: string; balance: string }[]>('/admin/crud/wallets');
export const getKycSubmissions = (status = 'pending') => adminRequest<{ submissions: Record<string, unknown>[] }>('/admin/kyc/user-submissions', { params: { status } });
export const reviewKyc = (id: number, data: Record<string, unknown>) => adminRequest(`/admin/kyc/user-submissions/${id}/review`, { method: 'POST', data });
export const getSupportTickets = (params: Record<string, string | undefined>) => adminRequest<{ tickets: Record<string, unknown>[] }>('/admin/support/tickets', { params });
export const getAuditLog = () => adminRequest<AdminList<Record<string, unknown>>>('/admin/audit-log');
export const updateUser = (id: number, data: Record<string, unknown>) => adminRequest(`/admin/users/${id}/update`, { method: 'PATCH', data });
export const freezeWallet = (id: number, reason: string) => adminRequest(`/admin/users/${id}/freeze-wallet`, { method: 'POST', data: { reason } });
export const runReconciliation = () => adminRequest('/admin/reconciliation/run', { method: 'POST' });
export const refreshRates = () => adminRequest('/admin/finance/exchange-rates/refresh', { method: 'POST' });
