# DSD PAY Technical and Security Features

## Purpose

This document describes the technical architecture, implemented product features, security controls, operational behavior, and current integration boundaries of the DSD PAY wallet system. It is based on the Django backend, Flutter mobile application, database models, API routes, services, tests, and deployment configuration in this repository.

It is also a partner-facing integration reference. It distinguishes repository foundations from a live connection to any bank, mobile-money operator, regulator, or payment network. Provider-specific onboarding, certification, and production operation must be confirmed separately.

Feature status uses the following terms:

- **Implemented**: code exists in the repository and is intended to be usable.
- **Protected**: the server enforces the relevant authorization or integrity rule.
- **Configuration-dependent**: code exists but requires credentials, workers, provider setup, or platform configuration.
- **Foundation**: data structures or service boundaries exist, but a production provider or workflow may still be required.
- **Simulated**: code returns or queues a locally generated result and does not execute a transaction on an external financial rail.
- **Operational follow-up**: a deployment or security action is required before production use.

## Contents

- [System architecture](#1-system-architecture)
- [Accounts and authentication](#2-user-accounts-and-authentication)
- [Trusted devices and request security](#3-device-trust-and-request-security)
- [Step-up authentication and PINs](#4-step-up-authentication-and-transaction-pins)
- [Wallet, ledger, and transfers](#5-wallet-ledger-and-transfers)
- [Requests, approvals, QR, and splits](#6-payment-requests-approvals-qr-and-bill-splits)
- [Family and parental controls](#7-family-and-parental-controls)
- [Bank and mobile-money integrations](#8-bank-and-mobile-money-integrations)
- [Merchant platform](#9-merchant-platform)
- [Scheduled transfers](#10-scheduled-transfers)
- [KYC and compliance](#11-kyc-and-compliance)
- [Disputes and support](#12-disputes-and-support)
- [Notifications and FCM](#13-notifications-and-fcm)
- [Admin and operations](#14-admin-and-operations)
- [Exchange rates and currency](#15-exchange-rates-and-multi-currency-foundations)
- [Client experience](#16-client-experience-features)
- [Cybersecurity controls](#17-cybersecurity-controls)
- [Test coverage](#18-test-and-verification-coverage)
- [Operational dependencies and boundaries](#19-operational-dependencies-and-known-boundaries)
- [API capability index](#20-api-capability-index)
- [Detailed system feature catalogue](#21-detailed-system-feature-catalogue-and-workflow-reference)

## 1. System Architecture

### Backend

- Django 5.x project with Django REST Framework.
- PostgreSQL production database configuration.
- Cursor pagination for growing transaction and administrative lists.
- OpenAPI schema and Swagger/ReDoc documentation through `drf-spectacular`.
- Celery task integration with Redis as the broker/result infrastructure.
- Django admin for operational management and security review.
- WhiteNoise static-file serving and CORS configuration for the mobile/web clients.
- Environment-driven configuration for secrets, database settings, OAuth, Firebase, webhook signing, CORS, cookies, throttling, and token lifetime.

### Mobile client

- Flutter application targeting iOS and Android.
- HTTP API client with bearer-token authentication, request timeouts, structured API errors, and secure local session storage.
- Firebase Core, Firebase Analytics, Firebase Cloud Messaging, local notifications, secure storage, biometric/device authentication, QR scanning, QR rendering, photo saving, file picking, sharing, and PDF generation.
- Localized English and French resources.
- Adaptive iOS/Android navigation and security prompts.

### Financial integrity model

Balances are not stored as mutable wallet totals. The wallet balance is computed from ledger entries:

```text
balance = sum(credit ledger entries) - sum(debit ledger entries)
```

Money uses decimal arithmetic. Money-moving operations use database transactions and row locking where required. Idempotency keys protect against duplicate requests caused by retries, double taps, or unreliable networks.

## 2. User Accounts and Authentication

### User accounts

The custom user model supports:

- Email identity.
- Optional username for administrative accounts.
- Phone number and primary phone number.
- Unique user handle.
- Display name and avatar URL.
- KYC tier and account status.
- Transaction PIN stored as a hash.
- Per-transaction and daily sending limits.
- Usage-based limit progression.
- Agent flag for future agent-network operations.
- Main-device identifier for device-management policy.
- Account closure workflow.

### Account creation

The email signup flow creates the user, wallet, and initial zero-value ledger entry atomically. Signup requires:

- Email.
- Password.
- Display name.
- Four-digit transaction/wallet PIN.
- Matching password confirmation.
- Terms acceptance.
- Optional phone and country information.

The Flutter signup form validates the four-digit PIN locally and the backend validates it using a strict four-digit pattern. The PIN is the fallback security credential for devices that do not support biometric or device-credential authentication.

### Login

Supported account login paths include:

- Email/password login.
- Phone/password login with country-code normalization.
- Google OAuth authorization-code exchange.
- Separate staff/admin username-password authentication.

The mobile client persists only the signed access token and device identity in secure storage. API tokens are signed server-side and can contain a device binding and temporary step-up purpose.

### Session behavior

- Bearer access tokens are accepted by `SignedTokenAuthentication`.
- Token expiry is controlled by `API_ACCESS_TOKEN_MAX_AGE`.
- Device-bound tokens are rejected when the request presents a different device ID.
- Authenticated `401` responses clear the local access token and return the app to login.
- Normal logout clears the access token but preserves the device identity, allowing the same trusted device to log back in without unnecessary confirmation.
- Explicit remote device revocation clears the device ID and signing key on the target device.
- Startup restore is bounded by timeouts and a watchdog so a failed storage, API, Firebase, or notification operation cannot hold the app on a loading screen indefinitely.

## 3. Device Trust and Request Security

### Trusted devices

The backend stores trusted device records containing:

- User relationship.
- Stable installation/device ID.
- Device name and platform.
- Public signing key.
- Trust and revocation state.
- First-seen and last-seen timestamps.

The first device for an account is trusted automatically. Additional devices create a pending login request and receive no access token until an existing trusted device approves them.

### New-device confirmation

The flow is:

1. A new device submits credentials, device ID, device name, and public key.
2. If the account has active trusted devices, the backend creates a five-minute pending request.
3. The backend creates a notification and sends an FCM approval event to active trusted devices.
4. The new device polls the request status without an access token.
5. An existing trusted device opens an approval modal.
6. The trusted device authenticates locally with biometrics or device credential where available.
7. The confirmation request is signed with the trusted device's private key.
8. The backend verifies the signature, atomically resolves the request, and, on approval, registers the new device as trusted.
9. The new device receives a device-bound access token through the status-poll response.

Pending states are `pending`, `approved`, `denied`, and `expired`. The backend rejects duplicate resolution attempts and expired requests.

### Device-bound signatures

The confirmation endpoint signs a deterministic payload containing:

```text
HTTP method | request path | Unix timestamp | SHA-256(raw request body)
```

The backend enforces:

- Device ID header presence.
- Timestamp header presence.
- Signature header presence.
- Approximately 60-second timestamp tolerance.
- Active, trusted, non-revoked device lookup.
- Public-key signature verification.
- RSA/PEM and Ed25519/raw-key compatibility in the verifier.
- Device last-seen update after successful verification.

The client stores a generated Ed25519 private key in Flutter secure storage and sends the corresponding public key during device registration. The private key is never sent to the backend.

### Main-device policy

The first active trusted device remains the main device. Only the main device may manage the trusted-device list. The server rejects:

- Device-management requests from non-main devices.
- Attempts to revoke the main device itself.
- Access from revoked trusted devices.

When all device records are removed or reset, the legacy main-device pointer is cleared and the next login becomes the new first trusted device.

### Remote logout

A main device can revoke another trusted device. The server:

1. Marks the target device untrusted and records the revocation time.
2. Deactivates the target device's FCM registrations.
3. Sends a targeted `device_revoked` FCM event.
4. Causes the target app to clear its access token, device ID, and private signing key as soon as the event is delivered.
5. Prevents future authenticated use server-side even if FCM delivery is delayed.

## 4. Step-Up Authentication and Transaction PINs

Sensitive operations use fresh step-up verification when required. The OTP system supports purposes including login, transfer, withdrawal, provider linking, and administrative login.

The step-up flow:

- Creates a challenge bound to the user and trusted device.
- Stores only a hash of the six-digit OTP.
- Expires challenges after five minutes.
- Locks a challenge after repeated invalid attempts.
- Delivers private FCM data messages.
- Returns a short-lived token bound to the device and purpose.
- Retries the original operation only after server verification.

Transaction approvals use the user's four-digit transaction PIN. This is separate from the device biometric/app-lock layer and remains available as an account-level fallback.

## 5. Wallet, Ledger, and Transfers

### Wallets

Each user receives a one-to-one wallet with:

- Currency.
- Active/frozen status.
- Default mobile-money provider.
- Sandbox/live classification where applicable.
- Computed balance from ledger entries.

The mobile app displays balance privacy controls, formatted currency values, sending limits, daily remaining amount, and usage progression.

### Ledger and transactions

The transaction system supports:

- P2P transfers.
- Reversals.
- Top-ups.
- Withdrawals.
- Transaction status tracking.
- Fees and fee policies.
- Sender and recipient relationships.
- Notes and idempotency keys.
- Related transactions for reversals.

Ledger entries are append-oriented financial records. Failed transfer attempts are retained separately for fraud visibility and operational analysis.

### Transfer protections

- Idempotency prevents duplicate money movement.
- Decimal values avoid floating-point errors.
- Database transactions protect multi-row updates.
- Row locks prevent concurrent overspending in PostgreSQL.
- Account status and wallet status are checked.
- KYC eligibility is checked.
- Per-transaction and daily limits are checked.
- Currency compatibility is checked.
- Insufficient funds are rejected.
- Step-up authentication can be required before execution.
- Reversals create offsetting ledger entries and prevent double reversal.

### Limits

The system supports:

- Per-transaction limits.
- Daily sending limits.
- Usage-based increases after completed transfer milestones.
- KYC-tier bonuses.
- System-configured base limits.
- Manually fixed limits that are not automatically overwritten.
- Parent-managed child limits through parental controls.
- Admin-managed limits with audit reasons.

## 6. Payment Requests, Approvals, QR, and Bill Splits

### Payment requests

Users can:

- Create payment requests.
- List incoming and outgoing requests.
- View request details.
- Pay requests.
- Decline requests.
- Cancel requests.
- Receive notification records and push notifications.
- Handle expiry and approval states.

### Transaction approvals

Approval records support payment and parental-link approval workflows. Pending approvals are listed through the API and displayed through mobile approval prompts. Approval actions require the applicable PIN and server-side relationship checks.

### QR payments

The backend supports:

- Generating a signed personal QR payload.
- Verifying QR payload signatures.
- Paying from a verified QR payload.
- QR payment notifications.

The Flutter app scans QR codes, displays personal QR codes, and can save a rendered QR image to Photos or fall back to the platform share sheet. QR image sharing uses a valid non-zero share anchor on iOS/iPadOS.

### Bill splitting

The split-payment feature supports:

- Creating a split bill.
- Adding participants directly or through QR.
- Viewing split details.
- Cancelling splits.
- Participant amounts and status tracking.
- Notifications related to split requests.

## 7. Family and Parental Controls

### Relationship model

A `ParentalControl` links a parent and child account. The child must approve the link through the existing approval/PIN workflow before the relationship becomes active.

The relationship stores independent permissions for:

- Viewing child transactions and balance.
- Controlling child wallet status.
- Sending money to the child.
- Setting the child's spending limits.

### Parent capabilities

For an active relationship, the parent can:

- View the child's live wallet balance.
- View recent child transactions.
- Send money to the child's wallet.
- Set per-transaction spending limits.
- Set daily spending limits.
- Freeze the child wallet.
- Unfreeze the child wallet.
- Unlink/revoke the relationship.

Each action is checked on the backend. Permission failures return a `parental_restriction` error code and are surfaced in the mobile app.

### Child-account behavior

The profile response exposes whether the logged-in user is an active child account or parent account. The mobile client hides the Family feature from linked child accounts so children do not see parent-management controls.

## 8. Bank and Mobile-Money Integrations

This section describes the current integration boundary and the additional work required before external money movement can be described as production-ready. The wallet ledger remains the DSD PAY record of wallet value; a provider's authorization, transfer, callback, and settlement records are separate external facts that must be correlated and reconciled.

### 8.1 Current capability and status

| Capability | Current repository behavior | Status and production boundary |
|---|---|---|
| Mobile-money catalog | Provider types include MTN MoMo, Airtel Money, and Orange Money; a provider catalog is also exposed. | **Foundation**. A catalog entry is not proof of provider onboarding or connectivity. |
| User provider linking | `POST /api/mobile-money/providers/link` stores a provider and masked phone reference, but sets the relationship to `verified` and marks the response/metadata as simulated. The supplied phone is also retained in provider metadata. | **Simulated**. There is no demonstrated provider-side account ownership challenge. OTP step-up authenticates the DSD PAY user; it does not by itself verify ownership of the external account. Treat the full phone as sensitive personal data and minimize, protect, and retain it only as necessary. |
| Mobile-money top-up | The endpoint creates a local transaction with a synthetic provider reference and queues a locally simulated completion. The webhook-processing task credits the wallet ledger for a completed top-up. | **Simulated**. No MTN, Airtel, or Orange API request, provider authorization, external settlement, or request-level idempotency is performed. |
| Mobile-money withdrawal | The endpoint checks the linked-provider record and wallet balance, creates a withdrawal and a detached debit ledger hold, then queues a locally simulated completion. | **Simulated**. No provider payout or request-level idempotency is implemented. The hold is not linked to a unique ledger operation; failed processing removes detached debit entries by wallet and amount, so equal-value concurrent withdrawals can affect one another. This must be corrected before live use. |
| Mobile-money callback | One generic endpoint verifies HMAC-SHA256 over the timestamp and raw body, enforces a five-minute timestamp window, and stores a globally unique event ID before queueing processing. | **Foundation**. It is not a provider-specific adapter or certification. A single `MOBILE_MONEY_WEBHOOK_SECRET` is used; provider-specific authentication, payload mapping, and isolated credentials are not implemented. `processed_at` is currently set after enqueue, not after business processing; if enqueue fails, the stored event can cause a provider retry to be treated as already received. |
| Bank directory and merchant account | `Bank` and `MerchantBankAccount` records describe banks and merchant payout destinations. Merchant account creation accepts account name/number and sets `is_verified=True` locally. | **Foundation / simulated verification**. They do not provide consumer bank account linking, open-banking access, or a bank transfer rail. The withdrawal path does not enforce the `is_verified` field, and local creation is not bank-side account verification. Sensitive account-data controls and partner-backed verification are required. |
| Merchant bank withdrawal | The merchant withdrawal workflow creates a local debit and marks the withdrawal completed with a simulated provider response. | **Simulated**. No bank API, payment switch, or external settlement is called. Merchant settlement records and bank details must not be presented as proof of a completed bank payout. |

### 8.2 Required provider transaction lifecycle

Each partner adapter must map that partner's contract to a common internal operation lifecycle without treating a request acknowledgement as settlement:

1. Validate the authenticated user or merchant, account and wallet state, KYC/limits, currency, amount, destination, and step-up requirement.
2. Accept or generate an idempotency key for the financial operation. Persist the operation and an internal correlation reference before making a retryable external call; persist the provider reference when the partner returns it.
3. Submit the operation using the partner's authenticated API, timeout, and idempotency semantics. Store only the minimum provider response needed for support, audit, and reconciliation.
4. Represent acceptance, processing, success, failure, and indeterminate/timeout outcomes distinctly. A network timeout is not proof that the provider failed to execute.
5. Verify and normalize authenticated callbacks, or poll through a documented provider status API. Enforce duplicate and out-of-order event handling and ensure only a valid terminal transition can settle the operation.
6. In one database transaction, finalize the operation and post the corresponding ledger entries exactly once. Link any withdrawal reservation/hold to that operation; release or settle only that hold.
7. Reconcile DSD PAY operations against provider transaction reports and bank settlement statements. Escalate unmatched, delayed, reversed, and amount/currency-mismatched records for controlled review.

The partner contract must define accepted currencies and amount precision, fees, FX ownership and quote expiry, destination validation, provider references, status mapping, timeouts, callback retries, reversal/refund semantics, settlement timing, cutoffs, and support escalation. Preserve immutable operation and status history sufficient to trace DSD PAY IDs to provider IDs and settlement records.

### 8.3 Integration security requirements

- Use TLS for all API and callback traffic. Use partner-supported mutual TLS, IP restrictions, or equivalent network controls where required by the signed integration contract; do not rely on source IP alone as callback authentication.
- Store separate credentials and callback secrets per provider, environment, and purpose in protected deployment secret storage. Apply least privilege, access logging, rotation, revocation, and a tested incident procedure. Never place credentials or real account data in source control, logs, support tickets, or test fixtures.
- Verify callbacks over the exact raw request bytes before parsing; use constant-time signature comparison, strict timestamp and event-ID checks, and durable per-provider event uniqueness. A shared generic HMAC check is not a substitute for the provider's required signature, certificate, token, or mTLS scheme.
- Persist callback receipt, dispatch, processing, and terminal outcome as separate states. A failed enqueue or worker outage must remain safely retryable and alertable; acknowledge an event only under the provider's agreed delivery contract.
- Bind each callback to a known provider, operation, provider reference, currency, amount, and allowed state transition. Do not allow untrusted callback fields to choose the user, wallet, amount, or ledger posting.
- Prove external-account ownership through the partner's supported authorization or challenge flow before marking an account verified. Mask account identifiers in user/admin views; encrypt or otherwise protect any retained phone/account details, restrict access, and define retention/deletion rules.
- Require server-side authorization and fresh step-up for relevant user actions; apply separate staff roles, reason capture, audit logging, and dual control for manual financial adjustments and high-risk production actions.
- Do not place provider secrets or authentication material in callback response bodies or client-visible transaction data. Redact provider payloads before persistence where they may contain credentials or unnecessary personal data.

### 8.4 Bank integration boundary

Bank connectivity is not currently implemented as a general wallet-to-bank integration. Existing bank models are associated with merchant payout destinations; merchant withdrawals currently complete through a simulated path. A production bank integration therefore requires an agreed API, switch, or payment-gateway route; bank-side customer/account verification as applicable; authenticated payout initiation; asynchronous status handling; settlement reporting; and reconciliation. Do not claim direct bank connectivity, open banking, or user bank transfers based only on the bank directory or merchant account records.

### 8.5 Partner onboarding and launch gates

For each bank or mobile-money partner, complete and approve:

1. **Commercial, legal, and compliance scope:** supported use cases, operating jurisdictions, KYC/AML responsibilities, customer disclosures, limits, fees, safeguarding/settlement model, dispute handling, data protection, retention, and incident contacts.
2. **Technical onboarding:** partner API and callback specifications, sandbox/UAT accounts, authentication and certificates, credential owners, currencies and precision, callback URL/network policy, rate limits, timeouts, retry rules, and versioning/change notices.
3. **Sandbox integration:** account-link ownership proof, top-up, withdrawal, success/failure, insufficient funds, timeout/unknown outcome, duplicate request, duplicate/out-of-order callback, cancellation/reversal, and reconciliation file/report scenarios.
4. **Security and financial validation:** invalid signature and replay rejection, secret rotation, access-control tests, concurrency and idempotency tests, single ledger settlement, withdrawal hold release, balanced postings, and settlement variance handling.
5. **UAT and controlled production launch:** partner certification, runbooks, dashboards and alerts, support ownership, rollback/disable controls, production credentials, limited rollout, and sign-off by engineering, security, operations, and the partner.

Production activation is partner-, country-, and environment-specific. Passing local tests or displaying a provider in the catalog does not establish approval, certification, regulatory compliance, or live connectivity.

## 9. Merchant Platform

Merchant functionality includes:

- Merchant account creation.
- Merchant approval workflow.
- Merchant plans and subscriptions.
- Live and sandbox modes.
- Public and secret merchant API keys.
- Merchant-scoped authentication.
- Payment-intent creation and confirmation.
- Checkout payment movement.
- Merchant fees and fee policies.
- Fee waivers.
- Merchant dashboard data.
- Merchant activity logs.
- Payment links and deactivation.
- Merchant KYC documents.
- Credential management.
- Merchant webhook configuration and delivery.
- Failed webhook review and retry operations.

Merchant public keys cannot authenticate as secret keys. Sandbox payments use sandbox wallets and do not affect live balances. Payment intents expire and cannot be confirmed after expiry. Webhook delivery tracks attempts and supports retry handling.

## 10. Scheduled Transfers

Users can:

- Create recurring transfers.
- Choose schedule frequency.
- List scheduled transfers.
- View scheduled-transfer details.
- Pause schedules.
- Resume schedules.
- Cancel schedules.

Celery beat/task configuration provides the scheduling foundation. Production behavior depends on Celery workers, broker availability, and periodic-task configuration.

## 11. KYC and Compliance

The KYC system supports:

- KYC document submission.
- Multipart document upload.
- Document type validation.
- Submission listing.
- Admin review of submissions.
- Approval and rejection workflow.
- KYC tier tracking.
- KYC gating for money movement.
- KYC document storage through Django media storage.
- Merchant KYC document handling.

The mobile app supports document selection for common image and PDF formats and displays transaction eligibility guidance.

## 12. Disputes and Support

### Disputes

Users can:

- Create disputes.
- List their disputes.
- View dispute details.
- Resolve disputes where authorized.

Administrators can list and resolve disputes through protected admin routes.

### Support

The admin support system includes:

- Support tickets.
- Ticket status, priority, and category.
- Assignment to staff.
- Related transactions.
- Ticket messages.
- Ticket metrics.
- Admin create, list, detail, update, and message operations.

## 13. Notifications and FCM

### Notification records

Notifications are persisted with:

- Recipient user.
- Notification type.
- JSON payload.
- Read timestamp.
- Creation timestamp.

The app supports unread counts, notification listing, read marking, local alerts, and FCM-triggered flows.

### FCM events

Implemented event categories include:

- Transaction updates.
- Payment requests.
- Split requests.
- Parental-link requests and decisions.
- OTP challenges.
- New-device login approval.
- Remote device revocation.
- Security notices.

The Flutter app handles foreground messages, background notification taps, and terminated-app launch messages. Critical revocation events clear local sessions immediately. Firebase Admin delivery requires a valid service-account credential, Firebase project setup, and APNs configuration for iOS.

## 14. Admin and Operations

The Django admin and protected admin API support:

- User search, detail, status updates, wallet updates, KYC updates, and limit updates.
- Transaction search and detail.
- Transaction reversal.
- Transfer-attempt fraud review.
- Audit-log review.
- Notification review and mark-read action.
- Push-device visibility and deactivation.
- Trusted-device listing, filtering, revocation, deletion, and full user device reset.
- Pending login visibility through model administration.
- Merchant review.
- KYC review.
- Dispute review.
- Support ticket operations.
- Mobile-money transaction review.
- Failed webhook retry.
- Fee-rule and fee-waiver management.
- Exchange-rate refresh.
- Periodic task inspection and manual execution.
- Reconciliation operations.

Administrative changes are intended to be auditable, and sensitive admin APIs require staff authorization. Admin actions that modify financial or account state use reason fields where implemented.

### Device reset behavior

The trusted-device admin controls can revoke or delete device records. A complete reset also:

- Deactivates push registrations.
- Expires pending login requests.
- Clears the user's main-device pointer.
- Causes the next successful login to become the first trusted device.

## 15. Exchange Rates and Multi-Currency Foundations

The exchange-rate service supports:

- Fetching latest rates from an external rate source.
- Persisting historical exchange-rate rows.
- Selecting active rates.
- Refreshing configured currency pairs.
- Using wallet currencies to determine refresh targets.
- Cross-currency support foundations for remittance and merchant flows.

External rate-source availability and refresh scheduling are operational dependencies.

## 16. Client Experience Features

The Flutter application includes:

- Authentication and account creation.
- Localized English/French UI.
- Wallet home screen.
- Balance privacy toggle.
- Transaction and activity views.
- Date filtering for activity.
- PDF transaction-statement export.
- Share-sheet integration.
- QR generation, scanning, verification, and photo saving.
- P2P transfer form and validation.
- Payment requests.
- Bill splits.
- Mobile-money provider and activity views.
- Scheduled transfers.
- KYC submission and status views.
- Disputes.
- Notifications.
- Approval prompts.
- Parental controls.
- Profile editing.
- Biometric/app lock.
- Trusted-device management.
- Remote logout response.
- Responsive/adaptive platform UI.
- Loading, empty, error, and retry states across major pages.

### API transport encryption

API transport must use HTTPS with modern TLS in staging and production. TLS encrypts the connection between the Flutter client, reverse proxy, Gunicorn/Django service, and API consumers, protecting bearer tokens, credentials, device metadata, payment data, KYC traffic, and request bodies in transit. The client uses the configured `API_BASE_URL`; production builds must set this to an `https://` origin and must never use the repository's development HTTP default. The reverse proxy must redirect or reject HTTP, serve a valid certificate, disable obsolete TLS versions and ciphers, and set HSTS after HTTPS is verified.

Application-level integrity controls complement TLS: signed access tokens, device-bound tokens, request signatures for device confirmation, HMAC-signed provider webhooks, signed QR payloads, idempotency keys, and server-side authorization. TLS does not replace these controls and does not encrypt data at rest.

## 17. Cybersecurity Controls

### Authentication and authorization

- Signed expiring bearer tokens.
- Device-bound access tokens.
- Separate admin authentication path.
- Explicit DRF permission classes.
- Staff-only admin endpoints.
- Parent/child relationship authorization.
- Merchant API-key authentication separated from user authentication.
- Revoked and untrusted device rejection.
- Account and wallet status enforcement.

### Cryptography and integrity

- HMAC-SHA256 verification for the current generic mobile-money webhook contract.
- Five-minute timestamp windows and unique event IDs for replay/deduplication foundations.
- Provider-specific callback credentials, adapters, and durable callback-processing state are not yet implemented.
- Signed QR payloads.
- RSA/Ed25519 device-signature verification.
- SHA-256 body hashing in request-signature payloads.
- Password hashing through Django.
- Transaction PIN hashing.
- OTP hashing rather than plaintext storage.
- Private mobile keys held in secure storage.

### Financial controls

- Append-oriented ledger entries.
- Computed balances.
- Decimal money arithmetic.
- Idempotency keys.
- Atomic database transactions.
- Row-level locking for concurrency-sensitive operations.
- Duplicate reversal prevention.
- Daily and per-transaction limits.
- KYC gating.
- Failed-attempt logging.
- Wallet freeze and account suspension enforcement.
- Balance reconciliation command and admin operation.

### Abuse resistance

- Anonymous and user throttling.
- Separate OTP request and OTP verification throttles.
- OTP attempt limits and lockout.
- Pending-login expiry.
- Pending-request duplicate prevention.
- Generic user-resolution not-found behavior to reduce account enumeration.
- Active catalog entries and active-device filtering; catalog visibility does not prove a live provider connection.
- Server-authoritative permission checks.

### Mobile protection

- Keychain/Keystore-backed secure storage through Flutter secure storage.
- iOS Face ID/device-passcode support.
- Android biometric/device-credential support.
- Four-digit wallet PIN fallback for unsupported devices.
- App lock on background/resume.
- Remote logout handling through FCM.
- Session cleanup on authenticated `401` responses.
- Bounded startup and recovery UI.
- No private signing key sent to the backend.

### Web and platform controls

- Django security middleware.
- CSRF configuration and API handling.
- CORS allow-list configuration.
- Secure-cookie configuration options.
- HTTP-only session cookies.
- X-Frame-Options middleware.
- Production `DEBUG=False` default.
- Environment-driven secrets and database configuration.

## 18. Test and Verification Coverage

The repository includes tests for:

- Signup, wallet creation, and initial ledger state.
- Balance calculation.
- Idempotent transfer behavior.
- Transfer validation and insufficient funds.
- Limit violations and usage-based limit progression.
- KYC and account-state restrictions.
- Frozen wallets and suspended users.
- PostgreSQL concurrency protection against overdrafts.
- Admin transaction reversals.
- OTP hashing, expiry, single-use behavior, and lockout.
- Step-up token purpose/device binding.
- Generic mobile-money webhook HMAC, timestamp-window, and event-ID checks. These tests do not establish provider-specific authentication, callback mapping, durable dispatch recovery, or live settlement behavior.
- Exchange-rate fetching, historical refresh, and wallet-currency targeting.
- Merchant live/sandbox separation.
- Merchant fee calculation and fee priority.
- Payment-intent expiry and webhook retries.
- Merchant key separation.
- Security phase 0/1 controls.

The strongest concurrency guarantees require PostgreSQL. Local syntax and Flutter analyzer checks are useful but do not replace integration testing on physical iOS/Android devices and a production-like PostgreSQL/Celery/Firebase environment.

## 19. Operational Dependencies and Known Boundaries

The following are required for a complete production deployment:

- PostgreSQL configured with production credentials.
- Django migrations applied, including trusted-device and pending-login migrations.
- A strong production Django `SECRET_KEY`.
- `DEBUG=False`.
- Correct `ALLOWED_HOSTS`, CORS, CSRF, and secure-cookie settings.
- HTTPS in front of the API and secure transport for production clients.
- Celery worker and Redis broker running.
- Celery beat/periodic tasks configured for cleanup, reconciliation, scheduled transfers, and webhook work.
- Valid Firebase Admin service-account JSON stored as a protected deployment secret.
- Firebase Cloud Messaging project configuration.
- APNs configuration for iOS notifications.
- Android notification permission and Firebase configuration.
- Partner-approved, provider-specific credentials and callback configuration for each live mobile-money or bank integration. Current mobile-money linking/top-up/withdrawal and merchant bank-withdrawal paths are simulated; do not enable them for real-money use until an adapter, lifecycle, reconciliation, and partner UAT are complete.
- External exchange-rate provider availability.
- Proper media storage and access policy for KYC documents.
- Secret rotation and revocation procedures.
- Database backups and restore testing.
- Monitoring for failed notifications, failed webhooks, rejected transfers, login anomalies, and reconciliation drift.

### Security follow-up items

- Do not commit Firebase service-account keys or other production secrets to source control.
- Rotate any Firebase key that has been exposed in a repository or shared environment.
- Audit repository files and history for any real provider, merchant, webhook, Firebase, or bank credentials; treat exposed credentials as compromised, revoke/rotate them, and move active secrets to protected deployment storage.
- Enforce HTTPS and secure cookies in production.
- Do not activate provider linking or money movement while the current simulated provider flows are reachable in a live environment.
- Replace the generic shared-secret webhook foundation with provider-specific authentication and a durable inbox/outbox or equivalent retry-safe processing lifecycle; distinguish callback receipt from completed financial processing.
- Link each withdrawal hold to its specific operation and make reserve, release, settlement, and reversal atomic and idempotent.
- Implement independent provider/bank statement reconciliation. The current wallet reconciliation only compares to `balance_cache` when that attribute exists; the `Wallet` model does not define it, so the current job does not provide an independent ledger-drift check.
- Add provider contract tests for per-partner authentication, account verification, duplicate/out-of-order callbacks, dispatch failure recovery, uncertain outcomes, settlement files, and exactly-once ledger posting.
- Consider applying device request signatures to additional high-risk authenticated endpoints beyond login confirmation.
- Add automated tests specifically for pending-login approval, device revocation, parental permission denial, and child-account UI visibility.
- Test FCM behavior on real iOS and Android devices in foreground, background, and terminated states.
- Review admin permissions and audit coverage before production launch.

## 20. API Capability Index

The backend route groups currently cover:

- Authentication, signup, Google OAuth, logout, password changes, OTP, login status, login confirmation, and trusted-device management.
- User profile, user resolution, country catalog, legal documents, and provider catalog.
- Wallet details, transfers, transaction history, transaction detail, reversals, and account closure.
- Notifications and push-device registration.
- Payment requests.
- QR generation, verification, and payment.
- Bill splits.
- KYC submissions.
- Mobile-money provider catalogs, linking, top-up, withdrawal, transaction-history, and webhook endpoints; the current linking and money-movement paths are simulated.
- Merchant bank-account and withdrawal records; external bank payout execution is currently simulated.
- Scheduled transfers.
- Merchant accounts, plans, subscriptions, dashboards, logs, payment links, credentials, KYC, and webhooks.
- Transaction approvals.
- Parental linking, verification, child accounts, parent accounts, child balance, child transactions, parent-to-child transfer, child wallet status, permissions, and unlinking.
- Disputes.
- Staff/admin dashboards, users, transactions, settings, reconciliation, task operations, support, KYC review, mobile-money operations, merchant review, fee controls, exchange rates, team management, and dispute review.

## 21. Detailed System Feature Catalogue and Workflow Reference

This catalogue summarizes the product and operations workflows visible in the current API, models, services, and mobile client. Endpoint names describe the current route surface, not a guarantee that an external provider is connected. Unless otherwise stated, `/api` is the API prefix and user workflows require a valid authenticated user token. The API schema and endpoint-specific permission classes remain authoritative where a legacy route differs.

### 21.1 Registration, identity, and account lifecycle

**User-facing capabilities**

- Register using email, password, display name, a four-digit transaction PIN, terms acceptance, and optional phone/country/language values.
- Sign in with email or phone and password, or exchange a Google authorization code.
- Retrieve the authenticated profile, resolve another user by handle or phone for payment flows, change a password, request and confirm password reset, and log out.
- Read supported-country/dial-code data, published legal documents, and app-update policy.
- Request account closure; closure is soft and is rejected while the wallet has a non-zero balance.

**Representative routes**

- `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/google`, `POST /api/auth/logout`
- `GET /api/me`, `POST /api/auth/change-password`, `POST /api/auth/password-reset/request`, `POST /api/auth/password-reset/confirm`
- `GET /api/users/resolve`, `GET /api/users/resolve-by-phone`, `GET /api/countries`
- `GET /api/legal/{slug}`, `GET /api/legal/{slug}/html`, `GET /api/app/update-status`, `POST /api/me/close`

**Server-side behavior and safeguards**

- Email, phone, and handle are identity/contact attributes with uniqueness constraints where defined. Phone normalization is used in lookup flows.
- The signup view is intended to create the user, wallet, and initial ledger record atomically. Passwords use Django password hashing; transaction PINs are hashed when verified/set.
- Closed/suspended states affect authentication and/or money movement. Account closure deactivates the account and removes trusted/push-device registrations while retaining financial history.
- User-resolution endpoints are sensitive to account enumeration. Generic not-found responses, throttles, and limited returned identity data should be preserved.

**Boundaries**

- A successful Google code exchange establishes application sign-in; it does not itself complete identity verification or KYC.
- Supported-country/legal-document catalogs do not establish a regulatory permission or provider corridor.
- The account-close endpoint is not a data-erasure workflow; legal retention, privacy requests, and deletion policy need separate operational/legal definition.

### 21.2 Authentication, step-up, devices, and administrator access

**User authentication sequence**

1. The client submits credentials and installation metadata. Login may register the first device or create a pending approval for an additional device.
2. A pending device polls a short-lived status resource but receives no ordinary API session until approval.
3. A trusted device approves or denies the request using its device signing key; the server validates state, expiry, timestamp, and signature.
4. Sensitive operations require a fresh, purpose-bound step-up token. OTP challenges are purpose- and device-associated, stored as hashes, expire after five minutes, and have verification-attempt controls.
5. Logout removes the current session token. Device revocation additionally invalidates trusted-device state server-side and deactivates push registration; FCM provides a client-side cleanup signal but is not the enforcement boundary.

**Representative routes**

- `GET /api/auth/login/status/{request_id}`, `POST /api/auth/login/confirm`
- `GET /api/auth/devices`, `POST /api/auth/devices/{device_id}/revoke`
- `POST /api/auth/otp/request`, `POST /api/auth/otp/verify`
- `POST /api/auth/admin`, `POST /api/admin/auth/login`, `POST /api/admin/auth/logout`, `POST /api/admin/auth/change-password`
- `POST /api/admin/auth/totp/setup`, `POST /api/admin/auth/totp/confirm`, `POST /api/admin/auth/totp/verify`

**Security distinctions**

- Local biometric/app lock is a client-access control. Server-side transaction authorization, PIN verification, session validation, and step-up checks are separate.
- Device public keys are used to verify signatures; private keys remain in mobile secure storage. Signed request coverage is specific to implemented device-confirmation/security flows; do not infer that every money API request has device-level request signatures.
- Admin login/TOTP is separate from ordinary customer login. Staff-only route checks and role scoping must be reviewed before granting access to financial data/actions.
- OTP delivery depends on configured Firebase/FCM and, where used, the SMS delivery configuration. A challenge record does not prove successful delivery to the user.

### 21.3 Wallet, ledger, transfer, fee, and reversal workflows

**Wallet and activity**

- A user has a wallet record with currency, active/frozen status, default mobile-money provider, and sandbox classification.
- The displayed balance is computed from credit and debit `LedgerEntry` records. Ledger records are intended to be append-oriented; corrections should be compensating transactions, not mutation/deletion of historical postings.
- Transaction list/detail APIs expose user-visible activity, cursor pagination, date filtering, counterparties, amounts, status, fee, and related reversal data where available.
- Wallet responses include balance/limit information. The current model is one wallet per user, so multi-wallet-per-currency claims are not supported by the current schema.

**P2P transfer sequence**

1. The client previews the amount, recipient/country, currency, applicable fee/rate information, and total debit where the preview route supports it.
2. The transfer request validates recipient, currency, amount, KYC eligibility, account/wallet state, available balance, limits, and purpose-bound step-up.
3. A required idempotency key associates a retry with the prior result, preventing a repeated request from creating another transfer.
4. The backend executes money movement atomically, locks the sender wallet for concurrency-sensitive balance checks, records the transaction, debit/credit ledger entries and fee postings, records audit/idempotency state, then dispatches notifications.
5. The response/receipt is the application result. A network timeout should be resolved by retrying with the same idempotency key or reading transaction state, not by issuing an unrelated second request.

**Representative routes**

- `GET /api/wallet`, `POST /api/transfers/preview`, `POST /api/transfers`
- `GET /api/transactions`, `GET /api/transactions/{transaction_id}`, `POST /api/transfers/{transaction_id}/reverse`

**Fees, limits, and reversal**

- Fee rules can be flat or percentage-based and scoped by use case/currency/merchant; fee waivers and platform-wallet postings are supported in the relevant transfer paths.
- User transfer ceilings combine configured base limits, completed-transfer/volume progress, KYC-tier bonuses, and administrator-fixed limits. Daily use is calculated in the configured business timezone.
- Merchant limits are separate from consumer send limits and include per-transaction, daily, and monthly ceilings.
- Reversals are represented as linked compensating transactions and must be authorized and prevented from being applied more than once. Admin manual credits, reversals, and limit overrides need a recorded reason and suitably restricted operator workflow.

**Known integrity boundaries**

- PostgreSQL row-lock semantics are required for the strongest concurrent overspend protection; SQLite development behavior is not equivalent.
- The independent balance-reconciliation gap is recorded in Section 19. A computed ledger balance alone does not compare the ledger with a bank/provider statement or an independent expected balance.
- The generic ledger model does not itself prove that external funding/payout settled. Provider operation state and ledger posting must be correlated.

### 21.4 Requests, approvals, QR, splits, and nearby payments

**Payment requests**

- A user can request an amount from a specified payer or create a request resolved by another user, list incoming/outgoing requests, and inspect request details.
- The payer can pay, decline, or cancel an eligible request. Requests expire and retain a status and optional resulting transaction link.
- The transition to paid must be tied to exactly one resulting transfer; expiry and repeat actions must not result in a second settlement.
- Routes: `POST /api/requests/create`, `GET /api/requests`, `GET /api/requests/{id}`, and `/pay`, `/decline`, `/cancel` actions.

**Approvals**

- Pending approval records support transaction-related confirmation, payment-request/split scenarios, QR-payment confirmation, and parental-link approval.
- An approver lists pending items, reviews the amount/currency/note/requester context, and accepts or declines before expiry.
- Approval endpoints check the authenticated approver and, for financial approval types, validate the transaction PIN before executing or releasing the associated action.
- Routes: `GET /api/approvals/pending`, `POST /api/approvals/{id}/approve`, `POST /api/approvals/{id}/decline`.

**QR**

- A user QR payload is signed server-side and can be displayed, scanned, verified, and used to identify the payee.
- A payment does not become trusted merely because a QR was scanned: the server checks signature/type/expiry and the payer supplies/confirms the amount; current flow can create a PIN approval before transfer execution.
- Static merchant QR and merchant QR checkout are separate from personal QR. A displayed merchant/user QR is not a bank or mobile-money authorization.

**Bill splits**

- A creator sets total amount/currency/note and participants; participant payment requests track their amounts and payment state.
- Participants can be added through the supported QR participant flow, inspect their share, and pay through the underlying payment/approval flow. The creator can inspect/cancel a split.
- Routes: `POST /api/splits`, `GET /api/splits/{id}`, `POST /api/splits/{id}/cancel`, `POST /api/splits/{id}/add-participant-qr`.

**Nearby payments**

- Backend routes create a short-lived request, resolve a nearby code, inspect status, pay, and cancel. The code is stored as a digest; requests expire and carry an idempotency hash/result transaction.
- BLE discovery/transport is a mobile-client feature; BLE proximity is not proof of identity or payment. The final amount, payer, authorization, and settlement must be confirmed by the backend.
- `NEARBY_PAYMENTS_ENABLED` is false by default in settings. The feature must remain disabled until the deployment flag, mobile-client support, reviewed settlement path, security, and concurrency tests have all been validated.
- Routes: `POST /api/nearby-payments`, `POST /api/nearby-payments/resolve`, `GET /api/nearby-payments/{request_id}`, plus `/pay` and `/cancel`.

### 21.5 Mobile money, bank payout, and provider integrations

Section 8 is the authoritative status and partner-launch description for this domain. In brief: provider catalog, user-link records, transaction records, and a generic signed callback foundation exist; the current linking/top-up/withdrawal paths are simulated, and merchant bank withdrawal is simulated.

**Interfaces currently exposed**

- `GET /api/mobile-money/provider-catalog`: active catalog items.
- `GET /api/mobile-money/providers`: current user's linked-provider records.
- `POST /api/mobile-money/providers/link`: creates/updates a simulated relationship; current code marks it verified without external ownership proof.
- `POST /api/mobile-money/topup`, `POST /api/mobile-money/withdrawal`: create provider transaction records and execute local simulated behavior.
- `GET /api/mobile-money/transactions`: current user's provider-transaction history, filterable by type/status.
- `POST /api/mobile-money/webhook`: generic HMAC/timestamp/event-ID callback entry point; not yet provider-specific or failure-durable.
- Merchant bank routes: `GET /api/merchants/banks`, `GET|POST /api/merchants/me/bank-accounts`, and `GET|POST /api/merchants/me/withdrawals`; bank-account creation currently stores the submitted account data and marks it verified locally, and withdrawal execution is simulated.

**Provider connection requirements**

- Implement one adapter at a time against a named provider's sandbox and contract; do not select behavior from a client-supplied provider label without server-side provider configuration.
- Persist an internal operation before the provider call, use partner-specific idempotency, preserve unknown outcomes after timeouts, and settle only after authenticated provider evidence.
- Store the operation-to-provider correlation, amount/currency/destination snapshot, status history, and financial ledger links. Use operation-scoped holds for withdrawals.
- Map all provider result codes to explicit internal pending/success/failure/unknown states. Handle repeated and out-of-order webhooks and provider polling as well as callback delivery.
- Reconcile transaction exports and settlement reports on a controlled schedule; report missing, duplicated, mismatched, late, reversed, and unrecognized records to an assigned operator.
- Treat bank account numbers, wallet phone numbers, KYC documents, API credentials, and callback payloads as sensitive data; minimize collection, mask presentation, restrict access, redact logs, set retention periods, and protect backups.

### 21.6 Merchant onboarding, checkout, API keys, settlements, and webhooks

**Merchant lifecycle and dashboard**

- A user creates a business account with business profile/contact information, which enters an approval lifecycle. Staff may approve/reject/suspend merchants and review business KYC documents.
- Merchant plans describe subscription price, API/webhook/QR/KYC capabilities, and plan-level transaction limits. A merchant subscription records plan and billing-period state.
- Merchant dashboard, transactions, transaction detail, activity logs, limits, settlements, and dispute views are scoped to the authenticated merchant.
- Merchant teams support invitations and roles such as owner, admin, finance, support, and developer. Invitation acceptance and active-membership checks should govern access; API keys must be restricted to the merchant/mode.

**Checkout and payment-intent flow**

1. An API client authenticates with its merchant secret key and selects sandbox or live mode.
2. It creates a payment intent with amount/currency, optional external reference/description/return URL, and idempotency key.
3. The backend checks merchant/subscription status and per-transaction/daily/monthly limits; the intent has a bounded expiry and checkout URL.
4. The payer reviews the merchant and amount, authenticates, and confirms payment. The backend validates intent state/expiry, wallet state/currency, fees, idempotency, and mode, then atomically records the transaction and ledger movement.
5. The merchant retrieves the intent/transaction or receives a signed asynchronous webhook. The return URL/client redirect is not proof of payment; merchant server state must be checked.

**API surface**

- `/api/merchant-api/payment-intents`, `/limits`, `/payment-intents/{id}`, `/payment-intents/{id}/cancel`
- `/api/merchant-api/transactions`, `/transactions/{id}`, `/settlements`, `/settings`, `/refunds`, `/disputes`, `/disputes/{id}`
- `/api/merchants/create`, `/api/merchants/me`, `/subscription`, `/qr`, `/dashboard`, `/transactions`, `/limits`, `/settlements`
- `/api/merchants/me/payment-links`, `/payment-links/{intent_id}/deactivate`, `/kyc-documents`, `/credentials`, `/webhook`, `/logs`, `/team`

**Merchant key and callback security**

- Public identifiers/public keys are not secrets. Secret keys are mode-specific and must be transmitted only over TLS, stored/handled as credentials, rotated/revoked, and never placed in app bundles or browser code.
- Webhook events are signed and have delivery records, attempts, and retry operations. Consumers must verify signatures, use delivery/event IDs for idempotency, acknowledge promptly, and query the API to resolve unknown delivery state.
- Merchant webhook delivery is distinct from inbound bank/mobile-money provider callbacks. The two directions have separate trust, authentication, retry, and incident procedures.
- Sandbox records/wallets should not affect live funds. Ensure UI, credentials, callback URLs, and reports visibly label sandbox versus live mode.

**Payout caveat**

Bank directory, account records, settlement records, and payout schedule settings exist, but the current merchant bank withdrawal path debits locally and marks completion with a simulated response. Do not represent the path as an executed external bank settlement.

### 21.7 Utility payments and external billers

- The API models water and electricity bill payments, stores an account number, amount/currency, provider reference, status, and response, and allows the authenticated user to list their history.
- `POST /api/utilities/pay` currently creates a locally generated `UTIL-...` reference, marks the utility payment completed, creates a completed utility transaction, and debits the ledger inside a database transaction.
- **This is not an external biller integration.** There is no demonstrated account validation, bill lookup, biller API request, external confirmation, callback, refund, or settlement reconciliation. The completed status currently means the local simulation completed, not that the utility provider was paid.
- Before live use, add biller-specific adapters, idempotency, pending/unknown states, payment confirmation, protected account identifiers, receipts, reversal/refund handling, and biller reconciliation.

### 21.8 Scheduled transfers

- Users create schedules to an existing active recipient using matching-currency wallets and choose daily, weekly, biweekly, monthly, or yearly frequency, start date, optional end date/max executions, name, and note.
- Owners list/detail/edit/pause/resume/cancel only their own schedules. Terminal schedules cannot be edited. Audit records are written for schedule creation/updates.
- Celery runs due schedules through a background transfer executor; the worker checks current account/wallet state, balance, transfer limits, and fees at execution time, then records a normal P2P transfer or reports failure.
- A schedule is configuration-dependent on a functioning broker, worker, and periodic task. A failed execution currently advances the schedule rather than retrying that specific occurrence.
- Monthly/yearly scheduling currently uses fixed 30/365-day increments rather than calendar-month/year rules. Define timezone, month-end/leap-year, missed-payment, retry, and user-notification behavior before treating schedules as bill-grade automation.

### 21.9 KYC, limits, disputes, and customer protection

**KYC**

- Users submit typed identity documents through multipart upload and can inspect their submissions/status. Staff review, approve, or reject submissions, record reviewer notes, and update KYC tier.
- KYC tier participates in transfer eligibility/limit calculation. KYC approval does not itself establish sanctions screening, PEP screening, ongoing monitoring, or a regulatory program.
- User documents are stored in configured media storage. Production needs private access controls, encryption/access logging, retention/deletion rules, malware/content controls, backup protection, and authorized reviewer access.
- Merchant KYC files are a separate merchant onboarding resource.

**Limits and controls**

- User limits are per-transaction and daily; progression can depend on completed transfer count/volume and KYC tier. An administrator can manually lock limits.
- Merchant limits are per-transaction, daily, and monthly by currency. Fee policies and waivers are separate from principal/limit calculation.
- Account suspension, wallet freeze, transaction PIN/step-up, and parental permissions are server-enforced gates in relevant actions. Limit errors should remain explicit and discoverable to operations.

**Disputes**

- A user can open a dispute only on a transaction they sent or received, include reason/evidence notes, and list/detail their own cases.
- Administrators review and resolve cases; a reversal may be linked where appropriate. A dispute record is not an automatic chargeback or refund, and the case process needs defined evidence, communication, decision, and SLA procedures.

**Support**

- Staff can create/list/detail/assign/update support tickets, set category/priority/status, associate a transaction, post customer-facing messages or internal notes, and view support metrics.
- Support messages and notes can include sensitive personal/financial data; staff role restrictions, redaction, retention, and audit controls are required.

### 21.10 Notifications, communication, localization, and app experience

- The backend persists in-app notification records and can deliver push notifications through Firebase Cloud Messaging. The in-app record is the durable user-facing history; push is a best-effort transport.
- Notification domains include transfers, requests, splits, approvals, KYC/security, OTP, new-device approvals, parental-link decisions, and device revocation.
- Push-device registrations are associated with users and can be deactivated by admin/device revocation. FCM/APNs delivery requires valid provider configuration, credentials, and platform permissions.
- The mobile client supports English/French localization, account/profile and wallet views, transaction list/detail, balance privacy, transfers, merchant checkout, requests, QR, split flows, nearby payments, utilities, mobile-money screens, schedules, KYC, disputes, notifications, approvals, parental controls, device management, and app-lock/security prompts.
- Client-side validation and navigation are usability controls, not authorization. The backend must repeat validation, ownership checks, amount/currency checks, state transitions, and limit/step-up checks.
- The app supports transaction-statement PDF generation/share. An asynchronous transaction export task currently returns `not_implemented`; do not describe large-scale backend export generation as implemented.

### 21.11 Exchange rates and currency behavior

- Exchange-rate services can fetch configured external rates, persist rate rows, identify active rates, and refresh currency pairs used by supported countries/wallets.
- Transfer preview can show receive-currency/rate/fee information where a supported country and active rate are available. A preview is not a locked quote or a completed cross-border settlement.
- Transactions store an exchange-rate reference where applicable; the rate-source availability and refresh schedule are operational dependencies.
- The wallet model is one-to-one with the user and stores a single currency. Cross-currency wallet ownership, quote lock/expiry, settlement routing, spread disclosures, and external remittance execution are not established by exchange-rate rows alone.

### 21.12 Administrator and finance operations

The admin surface includes Django admin, protected admin REST endpoints, and an operations portal. Representative capabilities include:

- **Identity/account:** search/detail/update users, activate/suspend/close, freeze wallets, change KYC/limits, record user notes, and perform bulk operations.
- **Financial records:** search transactions/payment requests/splits, inspect transfer attempts, reverse transactions, manage fee rules/waivers, view fee revenue, and inspect merchant settlements.
- **Risk/compliance:** review KYC, disputes, transaction flags, parental controls, trusted devices, push registrations, and alert rules.
- **Partner/payment operations:** review mobile-money transaction records, retry selected tasks/deliveries, inspect failed merchant webhooks, review merchant onboarding, and manage merchant bank-account/withdrawal records.
- **Customer support:** operate ticket queues, assignments, messages, metrics, and communications.
- **Platform operations:** view health/analytics/reports, read/update system settings, inspect/toggle/run periodic tasks, view reconciliation status, and request a reconciliation run.
- **Core CRUD safeguards:** transaction deletion and wallet deletion are intentionally rejected in admin CRUD; financial identity fields cannot be casually changed through metadata patching. Use supported reversal/top-up workflows rather than deleting ledger history.

Admin access is a high-impact control plane. Before partner production use, define least-privilege roles, separate read from write permissions, reason capture, approval/dual-control for high-risk actions, sensitive-field masking, audit retention, staff offboarding, privileged-session monitoring, and production runbooks. A staff flag alone should not be assumed to provide fine-grained segregation of duties.

### 21.13 Background work, cleanup, and reliability

Celery tasks currently cover:

- Scheduled transfer execution.
- Payment-request expiry and payment-intent expiry.
- Merchant webhook delivery/retries.
- Mobile-money webhook processing.
- Push notification and OTP delivery.
- Exchange-rate refresh.
- Wallet reconciliation.
- Session/notification/processed-request cleanup and transfer-attempt archival.
- Merchant key provisioning on approval and a basic queue health check.

Each task class has different retry guarantees. Task dispatch is not proof of execution; queue age, worker health, retries, terminal failures, duplicate execution, and manual replay must be observable. In particular, the current mobile-money webhook records an event before enqueue and can mark it processed at enqueue time; this is not a durable callback inbox. The transaction export task is a placeholder. Scheduled-task configuration and Celery Beat must be deployed and monitored independently of web-process health.

### 21.14 API conventions and integration contract expectations

- The API is JSON-oriented, documented through OpenAPI/Swagger/ReDoc, and uses explicit per-view authentication/permission classes alongside configured bearer/session authentication.
- The backend applies anonymous and authenticated throttles and has distinct OTP and nearby-payment limits. Effective rates and allowed origins depend on deployment settings.
- User financial requests should include an idempotency key where supported; providers and merchants must persist and reuse the same key on retries.
- Responses should be interpreted as API-operation state, not external settlement proof. External money movement requires provider-confirmed operation state and reconciliation.
- Partner-specific API contracts must define versioning, authentication, request/response schemas, amount/currency precision, timeout/unknown outcome behavior, idempotency retention, callbacks, retry/acknowledgement, status transitions, reversal/refund, settlement files, error codes, and escalation.
- Production monitoring must correlate user/API request IDs, internal transaction/operation IDs, provider transaction IDs, callback event IDs, Celery task IDs, ledger postings, and settlement lines without logging credentials or unnecessary personal data.

### 21.15 Detailed current limitations and launch blockers

The following are material feature-state constraints in the inspected repository and should appear in partner discussions until resolved:

1. Mobile-money linking is simulated, stores the supplied phone in provider metadata, and marks the record verified without provider ownership verification.
2. Mobile-money top-up and withdrawal endpoints use synthetic provider IDs and local simulated completions; they do not call MTN, Airtel, or Orange APIs.
3. Mobile-money withdrawal holds are not operation-scoped; the failure handler deletes detached debit entries based on wallet and amount, risking interference between equal-value operations.
4. Mobile-money callbacks use one generic configured secret; callback receipt and business processing are conflated, dispatch failure is not durable, and `processed_at` does not mean the ledger workflow completed.
5. Merchant bank-account creation stores caller-supplied account details and marks the record verified locally without bank-side proof; the withdrawal view does not enforce that flag. Merchant bank withdrawal then debits locally and marks completion with a simulated response.
6. Utility payments locally generate a reference, debit the ledger, and mark complete without calling a water/electricity biller.
7. Wallet balance reconciliation has no independent expected balance in the `Wallet` model and does not perform provider/bank reconciliation.
8. Transfer preview/FX information is not a guaranteed quote or a full cross-border payout capability; the wallet model stores one currency per user.
9. Monthly/yearly schedule arithmetic uses fixed-day intervals, and a failed occurrence advances rather than retrying that occurrence.
10. Nearby-payment feature flag is off by default; BLE proximity must never substitute for server authorization.
11. Backend transaction export is a placeholder; client-side PDF statement generation is a separate local feature.
12. Django settings contain development/fallback configuration and the password-validator list is empty. Production must explicitly inject strong secrets/credentials, fail deployment checks for unsafe defaults, enforce a password policy appropriate to account passwords, and verify `DEBUG`, host, TLS, cookie, CORS, and CSRF settings. Never copy secret values into this document or logs.
13. Provider integration, certification, regulatory authorization, safeguarding model, sanctions/AML program, incident SLAs, and production partner connectivity cannot be inferred from repository code and require partner/legal/operations approval.

These are not merely documentation caveats. Any live-money launch must block the affected routes or put them behind a production-disabled feature gate until the relevant provider adapter, ledger/callback lifecycle, security review, tests, reconciliation, monitoring, and partner UAT are complete.

## Summary

DSD PAY is implemented as a ledger-based wallet with server-authoritative authorization, idempotent and atomic P2P money movement, KYC and limit enforcement, device-aware authentication, FCM-driven security workflows, parental account management, merchant payment foundations, operational administration, and a Flutter client for iOS and Android. Mobile-money and merchant bank withdrawal records and endpoints exist, but the inspected provider-linking and payout paths are simulated rather than connected to live financial rails. No bank or mobile-money partner approval, certification, or production connectivity is implied. Live integration requires provider-specific adapters, corrected operation/hold/callback lifecycle, independent settlement reconciliation, partner UAT, and production security/operational sign-off.
