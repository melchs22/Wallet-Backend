# Wallet MVP Backend v2

A Django REST Framework backend for a P2P wallet web application (Venmo/Zelle-style MVP) with enhanced hardening and mobile money integration foundations. Users sign in with Google, get a wallet automatically, and can send money to each other by handle.

## Architecture Highlights

- **Ledger-based balance**: Balance is computed from ledger entries, not stored as a mutable field. This provides auditability and prevents historical data loss.
- **Idempotent transfers**: Every transfer uses an idempotency key to prevent duplicate payments from network retries or double-taps.
- **Atomic transactions**: All money operations use `transaction.atomic()` with `select_for_update()` locking to prevent race conditions.
- **Decimal everywhere**: Money values use Python's `Decimal` type to avoid floating-point precision issues.
- **Google OAuth only**: No password-based auth; Google OAuth is the sole authentication mechanism.
- **Admin reversals**: Staff can reverse transactions with full audit trail and offsetting ledger entries.
- **Failed transfer visibility**: All rejected attempts are logged for fraud pattern detection.
- **Mobile money foundations**: Stub models for MTN MoMo, Airtel Money, and Orange Money integration.
- **Multi-currency support**: Exchange rate storage for cross-border remittance capabilities.
- **Agent network readiness**: User model supports agent types for future cash-in/cash-out flows.

## Tech Stack

- Django 5.1.5
- Django REST Framework 3.15.2
- PostgreSQL (required for production - concurrency testing depends on it)
- Python 3.14+
- drf-spectacular (OpenAPI schema generation)

## Setup

### 1. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required environment variables:

- `DATABASE_URL`: PostgreSQL connection string (e.g., `postgresql://user:password@localhost:5432/walletmvp`)
- `SECRET_KEY`: Django secret key (generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
- `DEBUG`: Set to `True` for development, `False` for production
- `ALLOWED_HOSTS`: Comma-separated list of allowed hostnames (e.g., `localhost,127.0.0.1`)
- `FRONTEND_ORIGIN`: Your frontend URL for CORS (e.g., `http://localhost:3000` or `https://dsd-wallet.vercel.app`)
- `SESSION_COOKIE_SECURE`: Set to `True` in production, `False` for local dev
- `GOOGLE_CLIENT_ID`: Google OAuth client ID
- `GOOGLE_CLIENT_SECRET`: Google OAuth client secret

### 3. Run Migrations

```bash
python manage.py migrate
```

### 4. Create Admin User

The admin panel uses username/password authentication separate from Google OAuth. Create a default admin user:

```bash
python manage.py create_admin
```

This creates an admin user with:
- Username: `TUTU`
- Password: `tutu2005`
- Email: `admin@kesho.wallet`
- Staff privileges: Enabled

You can also create custom admin users:

```bash
python manage.py create_admin --username YOUR_USERNAME --password YOUR_PASSWORD --email YOUR_EMAIL
```

For traditional Django admin access, you can also create a superuser:

```bash
python manage.py createsuperuser
```

### 5. Run the Development Server

```bash
python manage.py runserver
```

The API will be available at `http://localhost:8000/api/`

## API Documentation

Once running, access the interactive API documentation:

- **Swagger UI**: `http://localhost:8000/api/docs/`
- **ReDoc**: `http://localhost:8000/api/redoc/`
- **OpenAPI Schema**: `http://localhost:8000/api/schema/`

## Google OAuth Configuration

### 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Navigate to **APIs & Services** > **Credentials**

### 2. Create OAuth 2.0 Credentials

1. Click **Create Credentials** > **OAuth client ID**
2. Application type: **Web application**
3. Name: `Wallet MVP Backend`
4. Authorized redirect URIs: Add your frontend callback URL, e.g., `http://localhost:3000/auth/callback`
5. Click **Create**

### 3. Configure Consent Screen

1. If prompted, configure the OAuth consent screen
2. For development, you can use "External" user type
3. Add required scopes: `openid`, `email`, `profile`

### 4. Copy Credentials

Copy the **Client ID** and **Client Secret** to your `.env` file as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

## API Endpoints

### Authentication

- `POST /api/auth/google` - Exchange Google authorization code for session
- `POST /api/auth/logout` - Logout current user
- `GET /api/me` - Get current user profile and wallet summary
- `PATCH /api/me` - Update display name and/or handle

### User Resolution

- `GET /api/users/resolve?query=<handle-or-email>` - Resolve user by handle or email

### Transfers

- `POST /api/transfers` - Send money to another user
  - Body: `{ recipient_handle, amount, currency, note, idempotency_key }`
- `GET /api/transfers/<id>` - Get single transaction details (including reversal status)
- `POST /api/admin/transfers/<id>/reverse` - **Admin only** - Reverse a transaction
  - Body: `{ reason }`

### Notifications

- `GET /api/notifications?unread_only=true` - List user's notifications
- `POST /api/notifications/<id>/read` - Mark notification as read

### Wallet

- `GET /api/wallet` - Get wallet details (balance, limits, etc.)

### Transactions

- `GET /api/transfers` - List user's transaction history (cursor paginated)

### Account Management

- `POST /api/me/close` - Close account (only if balance is zero)

### Admin Panel (New)

The admin panel provides a separate interface for administrative operations:

#### Admin Authentication
- `POST /api/auth/admin` - Admin login with username/password
  - Body: `{ username, password }`

#### Admin Dashboard
- `GET /api/admin/dashboard` - Aggregate statistics (user counts, volume, pending requests, etc.)

#### User Management
- `GET /api/admin/users?query=&status=&cursor=` - Searchable, filterable user list
- `GET /api/admin/users/<id>` - Full user details with recent activity
- `PATCH /api/admin/users/<id>` - Update user status, wallet status, limits, KYC tier
  - Body: `{ status?, wallet_status?, send_limit_per_tx?, send_limit_daily?, kyc_tier?, reason }`
  - Note: All admin actions require a `reason` field for audit logging

#### Transaction Oversight
- `GET /api/admin/transactions?query=&status=&type=&cursor=` - Search across all transactions
- `GET /api/admin/transactions/<id>` - Full transaction details
- `POST /api/admin/transactions/<id>/reverse` - Reverse a transaction
  - Body: `{ reason }`

#### Fraud Review
- `GET /api/admin/transfer-attempts?user=&reason=&cursor=` - View failed transfer attempts

#### Audit Log
- `GET /api/admin/audit-log?user=&action=&cursor=` - View all admin actions with full audit trail

**Security Note**: All admin endpoints require `is_staff=True` and are server-side protected. The frontend admin panel is accessible at `/admin` in the Next.js application.

**Responsiveness Note**: The admin panel is primarily designed for desktop/tablet use (768px+). While it remains usable on smaller screens, data tables may require horizontal scrolling on mobile devices. This is an intentional design decision as admin operations are typically performed on larger screens.

## Management Commands

### Balance Reconciliation

Run periodic balance reconciliation to detect any ledger drift:

```bash
python manage.py reconcile_balances
```

This command computes every wallet's balance from the ledger and logs any discrepancies. Run this via cron or a scheduler in production for monitoring.

## Running Tests

```bash
python manage.py test
```

### Important: PostgreSQL Required for Full Test Coverage

The concurrency test that verifies `select_for_update()` prevents overdrafts **requires PostgreSQL** and will be skipped on SQLite. The CI pipeline runs the full test suite against PostgreSQL on every push.

### Key Tests

The test suite includes:

- **Signup flow**: Verifies user, wallet, and zero-balance ledger entry are created atomically
- **Idempotency**: Confirms replaying a transfer with the same key doesn't move money twice
- **Transfer validation**: Tests insufficient funds, limit violations, unknown recipients
- **Concurrency**: (PostgreSQL only) Verifies `select_for_update()` prevents overdraft under concurrent load
- **Balance calculation**: Confirms `Wallet.get_balance()` matches ledger entry sums
- **Account state edge cases**: Tests frozen wallets and suspended users reject transfers
- **Admin reversals**: Verifies reversal creates offsetting entries and prevents double-reversal

## Database Schema

### Core Models

- **User**: Google OAuth-based user with handle, KYC tier, send limits, and agent flag
- **Wallet**: One-to-one with User, stores currency and status (no balance field)
- **Transaction**: Represents money movements (P2P transfers, reversals, top-ups, withdrawals)
- **LedgerEntry**: Append-only ledger of debits/credits (never update or delete)
- **ProcessedRequest**: Idempotency enforcement via unique constraint
- **AuditLog**: Comprehensive audit trail of all significant actions
- **Notification**: User notifications with flexible JSON payload
- **TransferAttempt**: Lightweight log of failed transfer attempts for fraud visibility
- **LinkedProvider**: Mobile money provider linkage (MTN MoMo, Airtel Money, Orange Money)
- **ExchangeRate**: Exchange rates for cross-currency transfers
- **PendingTransfer**: Stub for future "send to non-user" feature

### Balance Calculation

Balance is computed via `Wallet.get_balance()`:

```python
balance = SUM(credits) - SUM(debits)
```

This is the **only** way balance should be read in the codebase.

## Performance Indexes

The following composite indexes have been added for performance:

- `LedgerEntry(wallet_id, created_at)` - Hot path for balance computation and transaction history
- `Transaction(sender_id, created_at)` - Efficient sender history queries
- `Transaction(recipient_id, created_at)` - Efficient recipient history queries
- `TransferAttempt(user_id, created_at)` - Fraud pattern detection
- `TransferAttempt(rejection_reason, created_at)` - Rejection pattern analysis
- `LinkedProvider(user_id, provider)` - Provider lookup optimization
- `ExchangeRate(from_currency, to_currency, valid_from)` - Rate lookup optimization

## Security Considerations

- **Sessions**: HTTP-only, secure cookies with 1-day max age
- **CORS**: Locked down to specific frontend origin with credentials allowed
- **Throttling**: Applied to sensitive endpoints (auth, transfers, user resolution)
- **Audit logging**: All significant actions are logged for dispute resolution
- **No mutable balance**: Ledger-based system prevents silent data corruption
- **Idempotency**: Database-enforced via unique constraint on idempotency keys
- **Structured logging**: JSON-formatted logs for all transfer attempts and failures
- **Account state validation**: Frozen wallets and suspended users reject transfers
- **Admin-only reversals**: Transaction reversals restricted to staff with full audit trail

## Deployment

### PythonAnywhere Deployment

For production deployment to PythonAnywhere, see [PYTHONANYWHERE_DEPLOYMENT.md](PYTHONANYWHERE_DEPLOYMENT.md) for a comprehensive guide covering:

- Project upload and configuration
- PostgreSQL database setup
- Environment variables configuration
- WSGI configuration
- Static files handling
- Security considerations
- Monitoring and maintenance
- Troubleshooting common issues

### Frontend Integration

The backend is designed to work with the DSD Wallet frontend deployed at `https://dsd-wallet.vercel.app`. For Google OAuth setup, see [GOOGLE_OAUTH_SETUP.md](GOOGLE_OAUTH_SETUP.md) which covers:

- Google Cloud Console configuration
- OAuth consent screen setup
- OAuth 2.0 credentials creation
- Environment variable configuration
- Troubleshooting OAuth issues
- Security best practices

### Production Checklist

1. **Use PostgreSQL**: SQLite's locking behavior differs significantly; use Postgres in production
2. **Set DEBUG=False**: Never run with DEBUG enabled in production
3. **Use HTTPS**: Required for secure cookies and OAuth
4. **Configure ALLOWED_HOSTS**: Set to your actual domain(s)
5. **Review rate limits**: Adjust throttling rates based on your traffic patterns
6. **Monitor audit logs**: Set up log aggregation and alerting
7. **Run balance reconciliation**: Schedule periodic reconciliation job (cron/scheduler)
8. **Configure structured logging**: Ensure logs are captured in your log aggregation system
9. **Set up alerts**: Monitor for repeated idempotency key reuse and unusual patterns
10. **Review CORS settings**: Lock down to your actual frontend origin
11. **Deploy to PythonAnywhere**: Follow the PYTHONANYWHERE_DEPLOYMENT.md guide
12. **Configure Google OAuth**: Follow the GOOGLE_OAUTH_SETUP.md guide for frontend integration

### CI/CD

The project includes GitHub Actions CI configuration that:

- Runs the full test suite against PostgreSQL on every push
- Checks for unapplied migrations (fails build if model changes lack migrations)
- Runs balance reconciliation to verify ledger integrity
- Lints code with flake8

## Mobile Money Integration (Foundations)

The system includes stub models for future mobile money integration:

- **LinkedProvider**: Stores mobile money provider linkages (MTN MoMo, Airtel Money, Orange Money)
- **Transaction types**: Added `TOPUP` and `WITHDRAWAL` types for mobile money flows
- **Idempotency pattern**: The same `ProcessedRequest` pattern applies to provider webhooks

**Note**: The actual API integration is not implemented in this version, but the data model supports it without requiring schema changes.

## Multi-Currency Support (Foundations)

The system includes foundations for cross-currency transfers:

- **ExchangeRate model**: Stores historical exchange rates
- **Transaction linkage**: Transactions can reference the exchange rate used
- **Multiple wallets per user**: The architecture supports multiple wallets per user (one per currency)

**Note**: Cross-currency transfer logic is not implemented in this version, but the data model supports it.

## Development Notes

- The Django admin is configured to prevent edits/deletes on critical tables (LedgerEntry, Transaction, AuditLog)
- All money operations use `Decimal` type - never float
- The ledger is append-only; reversals create new offsetting transactions
- Handle changes have a 30-day cooldown to prevent abuse
- Closed accounts retain their notification history for audit purposes
- Failed transfer attempts are logged separately from successful transactions

## Future Enhancements

The schema includes stub models for future features:

- **PendingTransfer**: For sending money to users not yet on the platform
- **KYC tiers**: Currently tier_0 only; schema supports tier_1, tier_2
- **Reversals**: Transaction model supports reversal relationships
- **Bill splitting**: Future feature using existing transfer logic
- **QR code payments**: Per-user or per-transaction QR codes
- **Savings pockets**: Sub-balances within wallets for goals
- **Spending insights**: Transaction categorization and summaries
- **Referral program**: User referral tracking and rewards
- **Agent network**: Cash-in/cash-out via agent users

## Error Response Format

All API errors follow a standardized format:

```json
{
  "code": "error_code",
  "message": "Human-readable error message"
}
```

Common error codes:
- `validation_error` - Invalid request data
- `authentication_failed` - Auth required or failed
- `permission_denied` - Insufficient permissions
- `not_found` - Resource not found
- `rate_limit_exceeded` - Too many requests
- `insufficient_funds` - Wallet balance too low
- `per_transaction_limit_exceeded` - Amount exceeds single transfer limit
- `daily_limit_exceeded` - Amount exceeds daily limit
- `account_suspended` - User account suspended
- `wallet_frozen` - Wallet frozen
- `currency_mismatch` - Currency doesn't match wallet

## License

This is an MVP project for demonstration purposes.
