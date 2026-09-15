# DSD PAY Technical and Security Features

## Purpose

This document describes the technical architecture, implemented product features, security controls, operational behavior, and current integration boundaries of the DSD PAY wallet system. It is based on the Django backend, Flutter mobile application, database models, API routes, services, tests, and deployment configuration in this repository.

Feature status uses the following terms:

- **Implemented**: code exists in the repository and is intended to be usable.
- **Protected**: the server enforces the relevant authorization or integrity rule.
- **Configuration-dependent**: code exists but requires credentials, workers, provider setup, or platform configuration.
- **Foundation**: data structures or service boundaries exist, but a production provider or workflow may still be required.
- **Operational follow-up**: a deployment or security action is required before production use.

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

## 8. Mobile Money

The mobile-money layer supports provider catalogs, linked providers, top-ups, withdrawals, transaction history, and webhook foundations for:

- MTN Mobile Money.
- Airtel Money.
- Orange Money.

Top-up, withdrawal, and provider-linking operations can require OTP step-up verification. Provider-specific production activation remains configuration- and integration-dependent.

### Webhook security

Provider webhooks support:

- Unique webhook/event IDs.
- Timestamp validation.
- HMAC-SHA256 signatures over `timestamp.raw_body`.
- Replay prevention through persisted event IDs.
- Processed and received timestamps.
- Provider transaction IDs and status tracking.

Webhook secrets must be supplied through deployment configuration and must not be stored in source control.

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

### API transport encryption

API transport must use HTTPS with modern TLS in staging and production. TLS encrypts the connection between the Flutter client, reverse proxy, Gunicorn/Django service, and API consumers, protecting bearer tokens, credentials, device metadata, payment data, KYC traffic, and request bodies in transit. The client uses the configured `API_BASE_URL`; production builds must set this to an `https://` origin and must never use the repository's development HTTP default. The reverse proxy must redirect or reject HTTP, serve a valid certificate, disable obsolete TLS versions and ciphers, and set HSTS after HTTPS is verified.

Application-level integrity controls complement TLS: signed access tokens, device-bound tokens, request signatures for device confirmation, HMAC-signed provider webhooks, signed QR payloads, idempotency keys, and server-side authorization. TLS does not replace these controls and does not encrypt data at rest.
- Loading, empty, error, and retry states across major pages.

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

- HMAC-SHA256 webhook signatures.
- Timestamp windows for webhook replay protection.
- Unique webhook event IDs.
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
- Active-provider and active-device filtering.
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
- Webhook HMAC validation and replay/event uniqueness.
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
- Provider credentials and signed webhook configuration for mobile money.
- External exchange-rate provider availability.
- Proper media storage and access policy for KYC documents.
- Secret rotation and revocation procedures.
- Database backups and restore testing.
- Monitoring for failed notifications, failed webhooks, rejected transfers, login anomalies, and reconciliation drift.

### Security follow-up items

- Do not commit Firebase service-account keys or other production secrets to source control.
- Rotate any Firebase key that has been exposed in a repository or shared environment.
- Enforce HTTPS and secure cookies in production.
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
- Mobile-money providers, top-ups, withdrawals, transactions, and webhooks.
- Scheduled transfers.
- Merchant accounts, plans, subscriptions, dashboards, logs, payment links, credentials, KYC, and webhooks.
- Transaction approvals.
- Parental linking, verification, child accounts, parent accounts, child balance, child transactions, parent-to-child transfer, child wallet status, permissions, and unlinking.
- Disputes.
- Staff/admin dashboards, users, transactions, settings, reconciliation, task operations, support, KYC review, mobile-money operations, merchant review, fee controls, exchange rates, team management, and dispute review.

## Summary

DSD PAY is implemented as a ledger-based wallet with server-authoritative authorization, idempotent and atomic money movement, KYC and limit enforcement, device-aware authentication, FCM-driven security workflows, parental account management, merchant payment foundations, operational administration, and a Flutter client for iOS and Android. Features involving Firebase, Celery, mobile-money providers, exchange-rate providers, APNs, PostgreSQL concurrency, and production secrets are implemented in code but remain dependent on correct deployment configuration and operational verification.
