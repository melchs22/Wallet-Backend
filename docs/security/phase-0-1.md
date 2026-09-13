# Phase 0 and Phase 1 Security Controls

## Scope

This phase adds signed mobile-money webhook verification, replay receipts, trusted device records, automatic push OTP challenges, device-bound API tokens, and secure mobile credential storage.

HTTPS enforcement and secret rotation are intentionally deferred.

## Webhook contract

Mobile-money providers must send:

- `X-Webhook-ID`: unique event ID
- `X-Webhook-Timestamp`: Unix timestamp in seconds
- `X-Webhook-Signature`: lowercase hexadecimal HMAC-SHA256

The signed value is `timestamp + "." + raw_request_body`, using `MOBILE_MONEY_WEBHOOK_SECRET` as the HMAC key. Requests outside the five-minute clock-skew window, with an invalid signature, or with a repeated event ID are rejected or ignored.

Configure the shared secret in the deployment environment. Do not place it in source control.

## Automatic push OTP flow

1. The client registers an FCM token and installation ID at `/api/notifications/device`.
2. A sensitive endpoint returns `code=otp_required` when a fresh step-up is absent.
3. The client requests `/api/auth/otp/request` with the purpose and device ID.
4. The server stores only a hashed six-digit code and queues a private FCM data message.
5. Flutter receives the data message in the foreground or background and calls `/api/auth/otp/verify` automatically.
6. Verification returns a short-lived access token bound to the device and purpose.
7. The client stores the upgraded token in Keychain/Keystore-backed secure storage and retries the operation.

Codes expire after five minutes and are locked after three failed attempts. OTP values are never written to notification text or application logs.

## Current step-up endpoints

- Transfers: `POST /api/transfers`
- Mobile-money top-ups: `POST /api/mobile-money/topup`
- Mobile-money withdrawals: `POST /api/mobile-money/withdrawal`
- Provider linking: `POST /api/mobile-money/providers/link`

The backend remains authoritative. The client automation is a convenience and must not be trusted without server verification.

## Operational prerequisites

- Firebase Admin credentials must be available to the worker so `send_otp_push_task` can deliver data messages.
- APNs configuration must be completed in Firebase for iOS delivery.
- Celery worker and broker must be running.
- Provider integrations must implement the webhook contract before production activation.
