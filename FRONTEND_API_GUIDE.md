# Frontend API Guide

This document describes all API endpoints, request/response formats, and implementation details for frontend developers building the Wallet MVP frontend.

## Base URL

```
http://localhost:8000/api
```

## Authentication

### Google OAuth Flow

The app uses Google OAuth with server-side authorization code flow.

**1. Frontend initiates Google OAuth**
- Redirect user to Google's OAuth consent screen
- Include a `state` parameter for CSRF protection
- Redirect URI should be configured to match your frontend callback URL

**2. Frontend receives authorization code**
- User is redirected back to your frontend with an authorization code
- Frontend sends this code to the backend

**3. Exchange code for session**
```
POST /api/auth/google
Content-Type: application/json

{
  "code": "authorization_code_from_google",
  "state": "your_csrf_token"
}
```

**Response** (201 Created):
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "handle": "johndoe",
    "display_name": "John Doe",
    "avatar_url": "https://...",
    "kyc_tier": "tier_0",
    "status": "active"
  },
  "wallet": {
    "id": "uuid",
    "currency": "USD",
    "status": "active",
    "balance": "1000.00"
  },
  "is_new_user": true
}
```

**Error Responses:**
- 400: Invalid authorization code or state
- 403: Email not verified by Google

### Session Management

**Logout**
```
POST /api/auth/logout
Content-Type: application/json
```

**Response** (200 OK):
```json
{
  "message": "Logged out successfully"
}
```

**Get Current User Profile**
```
GET /api/me
```

**Response** (200 OK):
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "handle": "johndoe",
    "display_name": "John Doe",
    "avatar_url": "https://...",
    "kyc_tier": "tier_0",
    "status": "active"
  },
  "wallet": {
    "balance": "1000.00",
    "currency": "USD",
    "kyc_tier": "tier_0",
    "send_limit_per_tx": "1000.00",
    "send_limit_daily": "5000.00",
    "send_limit_remaining_today": "4000.00"
  }
}
```

**Error:** 401 Unauthorized (if not logged in)

**Update Profile**
```
PATCH /api/me
Content-Type: application/json

{
  "display_name": "John Updated",
  "handle": "johndoe123"
}
```

**Response** (200 OK):
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "handle": "johndoe123",
  "display_name": "John Updated",
  "avatar_url": "https://...",
  "kyc_tier": "tier_0",
  "status": "active"
}
```

**Error Responses:**
- 400: Invalid handle format, handle already taken, or handle changed within 30-day cooldown
- 401: Unauthorized

## User Resolution

**Find User by Handle or Email**
```
GET /api/users/resolve?query=johndoe
```

**Response** (200 OK):
```json
{
  "user_id": "uuid",
  "handle": "johndoe",
  "display_name": "John Doe",
  "avatar_url": "https://..."
}
```

**Error:** 404 Not Found (generic for both unknown and inactive accounts - prevents enumeration)

## Transfers

**Send Money**
```
POST /api/transfers
Content-Type: application/json

{
  "recipient_handle": "janedoe",
  "amount": "100.00",
  "currency": "USD",
  "note": "Thanks for coffee!",
  "idempotency_key": "unique-request-identifier-12345"
}
```

**Important Notes:**
- `amount` must be a decimal string (not float) with at most 2 decimal places for USD
- `idempotency_key` is REQUIRED - generate a unique identifier per transfer attempt
- If the same `idempotency_key` is sent again, the original result is returned (no duplicate payment)

**Response** (201 Created):
```json
{
  "id": "transaction-uuid",
  "amount": "100.00",
  "currency": "USD",
  "note": "Thanks for coffee!",
  "status": "completed",
  "created_at": "2026-08-13T21:00:00Z"
}
```

**Response** (200 OK - idempotent replay):
```json
{
  "id": "transaction-uuid",
  "amount": "100.00",
  "currency": "USD",
  "note": "Standard error messages
- `insufficient_funds`: Wallet balance too low
- `per_transaction_limit_exceeded`: Amount exceeds single transfer limit
- `daily_limit_exceeded`: Amount exceeds daily limit
- `account_suspended`: Your account is suspended
- `wallet_frozen`: Your wallet is frozen
- `currency_mismatch`: Currency doesn't match wallet
- `recipient_not_found`: User not found
- `cannot_send_to_self`: Cannot send to yourself

**Get Transaction Details**
```
GET /api/transfers/{transaction_id}
```

**Response** (200 OK):
```json
{
  "id": "transaction-uuid",
  "type": "p2p_transfer",
  "sender_handle": "johndoe",
  "sender_display_name": "John Doe",
  "recipient_handle": "janedoe",
  "recipient_display_name": "Jane Doe",
  "amount": "100.00",
  "currency": "USD",
  "note": "Thanks for coffee!",
  "status": "completed",
  "reversal_status": "none",
  "related_transaction_id": null,
  "created_at": "2026-08-13T21:00:00Z"
}
```

**Reversal Status Values:**
- `none`: Transaction has not been reversed
- `is_reversal`: This transaction is itself a reversal
- `reversed`: This transaction has been reversed

**Error:** 404 Not Found, 403 Forbidden (if not your transaction and not staff)

**Get Transaction History**
```
GET /api/transfers?cursor={cursor}&limit=20
```

**Pagination:** Cursor-based (not offset-based) for performance on growing tables

**Response** (200 OK):
```json
{
  "count": 1,
  "next": "cursor_to_next_page",
  "previous": null,
  "results": [
    {
      "id": "transaction-uuid",
      "type": "p2p_transfer",
      "counterparty_handle": "janedoe",
      "counterparty_display_name": "Jane Doe",
      "counterparty_avatar_url": "https://...",
      "amount": "100.",
      "currency": "US",
      "note": "Thanks for coffee!",
      "status": "completed",
      "direction": "sent",
      "created_at": "2026-08-13T21:00:00Z"
    }
  ]
}
```

**Direction Values:**
- `sent`: You sent this money
- `received`: You received this money

## Wallet

**Get Wallet Details**
```
GET /api/wallet
```

**Response** (200 OK):
```json
{
  "balance": "1000.00",
  "currency": "USD",
  "kyc_tier": "tier_0",
  "send_limit_per_tx": "1000.00",
  "send_limit_daily": "5000.00",
  "send_limit_remaining_today": "4000.00"
}
```

## Notifications

**Get Notifications**
```
GET /api/notifications?unread_only=true
```

**Response** (200 OK):
```json
{
  "count": 1,
  "next": "cursor_to_next_page",
  "previous": null,
  "results": [
    {
      "id": 1,
      "type": "transfer_received",
      "payload": {
        "sender_handle": "johndoe",
        "sender_display_name": "John Doe",
        "amount": "100.00",
        "currency": "USD",
        "note": "Thanks for coffee!",
        "transaction_id": "transaction-uuid"
      },
      "read_at": null,
      "created_at": "2026-8-13T21:00:00Z"
    }
  ]
}
```

**Mark Notification as Read**
```
POST /api/notifications/{id}/read
Content-Type: application/json
```

**Response** (200 OK):
```json
{
  "id": 1,
  "type": "transfer_received",
  "payload": {
    "sender_handle": "johndoe",
    "sender_display_name": "John Doe",
    "amount": "100.00",
    "currency": "USD",
    "note": "Thanks for coffee!",
    "transaction_id": "transaction-uuid"
  },
  "read_at": "2026-8-13T21:30:00Z",
  "created_at": "2026-8-13T21:00:00Z"
}
```

**Error:** 404 Not Found

## Account Management

**Close Account**
```
POST /api/me/close
Content-Type: application/json
```

**Response** (200 OK):
```json
{
  "message": "Account closed successfully"
}
```

**Error:**
- 400: Cannot close account with non-zero balance
- 401: Unauthorized

## Admin Endpoints

**Reverse Transaction** (Admin Only)
```
POST /api/transfers/{transaction_id}/reverse
Content-Type: application/json

{
  "reason": "User dispute - unauthorized transaction"
}
```

**Response** (201 Created):
```json
{
  "id": "reversal-uuid",
  "type": "reversal",
  "amount": "100.00",
  "currency": "USD",
  "status": "completed",
  "created_at": "2026-8-13T21:00:00Z"
}
```

**Error Responses:**
- 403 Forbidden: Not an admin user
- 400: Transaction already reversed or invalid reason
- 404 Not Found: Transaction doesn't exist

## Error Response Format

All errors follow this standardized format:

```json
{
  "code": "error_code",
  "message": "Human-readable error message"
}
```

**Common Error Codes:**
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

## API Documentation

Interactive API documentation is available when the server is running:

- **Swagger UI**: http://localhost:8000/api/docs/
- **ReDoc**: http://localhost:8000/api/redoc/
- **OpenAPI Schema**: http://localhost:8000/api/schema/

## CORS Configuration

The API expects CORS requests from the configured frontend origin with credentials allowed. Make sure your frontend includes credentials in requests:

```javascript
// Example fetch with credentials
fetch('http://localhost:8000/api/me', {
  credentials: 'include',
  headers: {
    'Content-Type': 'application/json'
  }
})
```

## Session Management

- Sessions are HTTP-only and secure (HTTPS required in production)
- Session age is 1 day maximum
- Session cookies use Lax same-site policy
- No local storage of sensitive data - rely on session cookies

## Implementation Notes for Frontend

### Idempotency Keys

- **Generate a unique identifier** for each transfer attempt (e.g., UUID v4)
- **Store this key** locally until you receive a response
- **Retry logic**: If a request fails, retry with the same idempotency key
- **Example**:
  ```javascript
  const idempotencyKey = crypto.randomUUID()
  
  async function sendMoney(data) {
    const response = await fetch('/api/transfers', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...data,
        idempotency_key: idempotencyKey
      })
    })
    // Store idempotencyKey in memory/state for retry logic
  }
  ```

### Pagination

- Transaction and notification endpoints use **cursor pagination**
- Use the `next` URL from the response to get the next page
- Store `previous` URL for back navigation
- Don't build offset-based pagination (will skip/duplicate rows on growing tables)

### Error Handling

- Always check the `code` field first, not the `message` (message may change)
- Handle 401 Unauthorized by redirecting to login
- Handle 403 Forbidden by showing permission error
- Handle 429 Rate Limit by showing "too many requests" with retry suggestion

### State Management Recommendations

- Store user profile and wallet balance in state after successful login
- Refresh wallet balance after successful transfers
- Poll notifications periodically or implement WebSocket (future enhancement)
- Handle session expiration by checking for 401 responses

### Security Considerations

- Never store or handle raw Google tokens - use the OAuth flow
- Validate user input before making API calls (handle format, amount validation)
- Display money amounts as formatted strings (never as floats for calculations)
- Don't expose internal IDs in the UI unless necessary
- Handle sensitive actions (account closure) with confirmation dialogs

### Notification Types

Currently supported notification types:
- `transfer_received`: User received money from another user

Future notification types may include:
- `transfer_reversed`: A transfer was reversed by admin
- `account_status_changed`: Account status changed (suspended, etc.)
- `limit_changed`: Send limits were modified

### Transaction Status Values

- `completed`: Transaction processed successfully
- `failed`: Transaction failed (should not happen in normal flow)
- `reversed`: Transaction was reversed by admin

### Transaction Type Values

- `p2p_transfer`: Person-to-person transfer
- `reversal`: Admin reversal of a transaction
- `topup`: Mobile money top-up (future)
- `withdrawal`: Mobile money withdrawal (future)

### Wallet Status Values

- `active`: Wallet can send and receive money
- `frozen`: Wallet is frozen (cannot send or receive)

### User Status Values

- `active`: User can perform all actions
- `suspended`: User is suspended (cannot send transfers)
- `closed`: User account is closed

### KYC Tier Values

- `tier_0`: Basic verification (email verification only)

## Testing with Local Development

For local frontend development, you can test with the provided `.env.example` configuration. The development server uses SQLite by default, but the production system requires PostgreSQL.

**Start the development server:**
```bash
python manage.py runserver
```

The API will be available at `http://localhost:8000/api/`

## Rate Limiting

- Anonymous users: 100 requests per day
- Authenticated users: 1000 requests per day
- Specific endpoints may have additional rate limits
- Rate limit errors return 429 status with `rate_limit_exceeded` code

## Data Types

- **Money**: Always use decimal strings (e.g., "100.00", not 100.00)
- **UUIDs**: String format in API responses
- **Dates**: ISO 8601 format (e.g., "2026-8-13T21:00:00Z")
- **Handles**: Alphanumeric, max 50 characters, case-sensitive

## Future API Enhancements

The backend has foundations for future features:
- Mobile money top-up/withdrawal (MTN MoMo, Airtel Money, Orange Money)
- Multi-currency transfers with exchange rates
- Bill splitting functionality
- QR code payments
- Savings pockets/goals
- Spending insights and categorization
- Referral program
- Agent network for cash-in/cash-out

These are not currently exposed via API but the data model supports them.
