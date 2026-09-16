# Wallet Admin API Reference

Base URL: `/api`

All endpoints in this document require an authenticated administrator. Send the access token using `Authorization: Bearer <token>`. JSON requests must include `Content-Type: application/json`.

## Authentication

- `POST /auth/admin` signs an administrator in.
- `POST /admin/auth/logout` ends the server session.
- `POST /admin/auth/change-password` changes the administrator password.

The CRUD endpoints below use `IsAdminUser`; normal authenticated wallet users cannot call them.

## Core CRUD

### Users

- `GET /admin/crud/users?q=<search>` lists up to 200 users. Search matches email, handle, and primary phone.
- `POST /admin/crud/users` creates a user. Required fields include `email`, `handle`, `display_name`, and `password`.
- `GET /admin/crud/users/{user_id}` returns one user.
- `PATCH /admin/crud/users/{user_id}` updates user profile, status, KYC tier, limits, staff/agent flags, or password.
- `DELETE /admin/crud/users/{user_id}` closes and deactivates the user. The current admin cannot delete itself.

### Wallets

- `GET /admin/crud/wallets?user_id=<id>` lists wallets, including computed ledger balance.
- `POST /admin/crud/wallets` creates a wallet for a user.
- `GET /admin/crud/wallets/{wallet_id}` returns a wallet and computed balance.
- `PATCH /admin/crud/wallets/{wallet_id}` updates currency, provider, status, or sandbox mode.
- `DELETE /admin/crud/wallets/{wallet_id}` is rejected. Wallets and ledger history are retained for auditability.

### Transactions

- `GET /admin/crud/transactions?user_id=<id>&status=<status>` lists transactions.
- `POST /admin/crud/transactions` creates an audited transaction record.
- `GET /admin/crud/transactions/{transaction_id}` returns transaction detail.
- `PATCH /admin/crud/transactions/{transaction_id}` updates operational metadata such as note or status.
- `DELETE /admin/crud/transactions/{transaction_id}` is rejected. Use the reversal endpoint instead.

Financial identity fields (`amount`, `sender`, `recipient`, `currency`, `type`, and `fee_amount`) cannot be changed through PATCH. Existing reversal behavior remains available at `POST /admin/transactions/{transaction_id}/reverse`.

### Celery periodic tasks

- `GET /admin/crud/tasks` lists periodic tasks.
- `POST /admin/crud/tasks` creates an interval task. Required fields: `name`, `task`, `interval_every`; optional `interval_period`, `enabled`, and `description`.
- `GET /admin/crud/tasks/{task_id}` returns a task.
- `PATCH /admin/crud/tasks/{task_id}` updates task name, task path, enabled state, and description.
- `DELETE /admin/crud/tasks/{task_id}` deletes the periodic schedule.
- `POST /admin/tasks/periodic/{task_id}/toggle` toggles an existing schedule.
- `POST /admin/tasks/periodic/{task_id}/run-now` queues immediate execution on Celery.

## Existing Admin Operations

### Dashboard and account operations

- `GET /admin/dashboard`
- `GET /admin/users`
- `GET /admin/users/{user_id}`
- `PATCH /admin/users/{user_id}/update`
- `POST /admin/users/{user_id}/topup`
- `POST /admin/users/{user_id}/freeze-wallet`
- `GET /admin/team`
- `GET /admin/audit-log`
- `GET /admin/settings`
- `PATCH /admin/settings/{key}`

### Transactions and payment resources

- `GET /admin/transactions`
- `GET /admin/transactions/{transaction_id}`
- `POST /admin/transactions/{transaction_id}/reverse`
- `GET /admin/requests`
- `GET /admin/splits`
- `GET /admin/transfer-attempts`
- `GET /admin/disputes`

### Support and compliance

- `GET /admin/support/tickets`
- `POST /admin/support/tickets/create`
- `GET /admin/support/tickets/{ticket_id}`
- `PATCH /admin/support/tickets/{ticket_id}/update`
- `POST /admin/support/tickets/{ticket_id}/messages`
- `GET /admin/support/metrics`
- `GET /admin/kyc/user-submissions`
- `POST /admin/kyc/user-submissions/{submission_id}/review`

### Mobile money, merchants, and webhooks

- `GET /admin/mobile-money/transactions`
- `POST /admin/mobile-money/transactions/{transaction_id}/retry`
- `GET /admin/merchants/webhooks/failed`
- `POST /admin/merchants/webhooks/{delivery_id}/retry`
- `GET /admin/merchants`
- `POST /admin/merchants/{merchant_id}/approve`

### Financial controls

- `GET|POST /admin/finance/fee-rules`
- `POST /admin/finance/fee-waivers`
- `GET /admin/finance/exchange-rates`
- `POST /admin/finance/exchange-rates/refresh`
- `GET /admin/reconciliation/last-run`
- `POST /admin/reconciliation/run` queues `reconcile_balances_task`; pass `{ "fix": true }` only for an intentional repair run.

## Response and error conventions

Successful collection responses are JSON arrays or an object containing a resource collection, depending on the legacy endpoint. New CRUD collection endpoints return a JSON array. New creates return `201`; updates return `200`; deletes return `204` when supported.

Typical errors:

- `400`: invalid input or forbidden financial mutation
- `401`: missing/invalid authentication
- `403`: authenticated user is not an administrator
- `404`: resource does not exist
- `405`: operation is intentionally blocked, such as wallet or transaction deletion
- `500`: unexpected server failure; inspect server logs and audit records

## Operational notes

1. Run migrations before using newly added resources.
2. Use wallet top-up, transfer, reversal, and reconciliation workflows for financial mutations; do not directly edit ledger rows.
3. Every new CRUD write creates an `AuditLog` entry with the acting administrator and affected resource.
4. Celery task creation requires a running Celery worker and django-celery-beat.
5. API schema generation can be used to expose these endpoints in the existing OpenAPI tooling.
