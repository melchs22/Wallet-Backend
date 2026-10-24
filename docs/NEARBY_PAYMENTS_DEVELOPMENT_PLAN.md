# Pay Nearby (BLE) — Development Plan

**Status:** Implementation deployed with release gates off; physical-device validation remains
**Planning basis:** Attached BLE “Tap to Pay” proposal and the current Wallet-Backend working copy
**Scope:** Authenticated, in-person payment discovery over Bluetooth Low Energy (BLE), with payment authorization and settlement performed by the existing wallet backend.

## Delivery update

The wallet-user MVP is implemented in the backend and Flutter app. It uses a separate `NearbyPaymentRequest`, a cryptographically random nine-character Base32-style code (45 bits of entropy) with a fixed 120-second lifetime, and stores only the SHA-256 digest server-side. iOS advertises the code in a nine-byte local name; Android advertises it as service data. Android and iOS request scan and advertising permissions after the app's first frame at startup. The payer resolves the code over the authenticated API, explicitly reviews the receiver, amount, fee and total, confirms locally, and submits the transaction PIN. The server still requires the normal transfer step-up/KYC checks and uses the existing P2P settlement service for fees, limits, wallet status, balance and ledger updates. The backend endpoints and migration are deployed on AWS; the production `NEARBY_PAYMENTS_ENABLED` gate is enabled. The mobile entry point requires `--dart-define=ENABLE_NEARBY_PAYMENTS=true`. Production requests are throttled at 10 creates/hour, 20 resolves/minute, and 10 pays/minute per authenticated user. Keep the global backend gate and app build flag intentional and coordinate changes with product/compliance.

Implemented routes are `POST /api/nearby-payments`, `POST /api/nearby-payments/resolve`, `GET /api/nearby-payments/{request_id}`, `POST /api/nearby-payments/{request_id}/pay`, and `POST /api/nearby-payments/{request_id}/cancel`. Discovery is authenticated and rate-limited; status is receiver-only until paid, then also readable by the payer for ambiguous-result recovery. Idempotency keys are stored in secure device storage until the result is confirmed. Expiry is enforced lazily on resolve, status, pay and cancel; no periodic cleanup task is required for correctness.

**Validation completed:** Ten focused Django API/concurrency tests pass on PostgreSQL; the production `0055_nearbypaymentrequest` migration is applied, all three backend services are active, and the live OpenAPI schema contains all five nearby-payment routes. A production settings indentation error that left nearby throttle scopes outside `DEFAULT_THROTTLE_RATES` caused HTTP 500s; it was corrected, Django checks pass, all three effective DRF rates are verified, and an unauthenticated create request now returns the expected HTTP 401 rather than 500. The BLE permission/parser tests pass, the nearby service and tests analyze cleanly, and Android debug plus iOS no-code-sign builds succeed with the nearby flag enabled. The release APK with the feature flag is saved in Downloads. The built Android manifest contains scan, connect and advertise permissions; the iOS app bundle contains `NSBluetoothAlwaysUsageDescription`. Full Flutter tests still encounter an existing startup localization failure in `test/widget_test.dart`; that unrelated startup behavior was not changed. Physical iOS/Android device interoperability and product/compliance rollout approval remain release gates.

## 1. Recommendation

Build this as **Pay Nearby**, a BLE-assisted way to discover and pay an existing DSD Pay user. Merchant acceptance is explicitly deferred; this is not NFC/contactless card acceptance and must not be marketed as such.

BLE should advertise only a short-lived, random discovery code. The payer retrieves the verified recipient and amount from the authenticated server, confirms the payment in the app, and submits it over HTTPS. The server performs all eligibility checks and writes the financial transaction and ledger entries. The receiver learns the final result from the server, with push as a convenience and polling as a fallback.

Deliver this in guarded stages: first prove BLE interoperability on representative physical phones, then build the request lifecycle and backend settlement, then complete Flutter flows, and finally run a limited beta. Do not enable live use until the server-side authorization, idempotency, single-use, concurrency, and recovery criteria below are met.

## 2. Important repository-specific design choices

1. **Do not create a second implementation of existing payment requests.** The repository already has `PaymentRequest`, whose requests are addressed to a known payer and may enter an approval/PIN flow. A proximity request is different: it has an unknown payer until a nearby user accepts and contains a bearer discovery code. Use a distinct `NearbyPaymentRequest` (or equivalent domain model) so the existing request contract and split-payment behavior remain unchanged.
2. **Use the existing amount/currency representation.** The proposed `amount_minor / 100` is not safe to assume for every supported currency. Store/validate the amount in the same decimal representation and precision as the wallet transfer API, or formally define currency minor-unit metadata before using integer minor units.
3. **Reuse existing settlement policy, not just its ledger helper.** The current `execute_p2p_transfer()` service is used for background transfers, while interactive transfer policy also involves KYC, device step-up, OTP, and request validation. Before implementing payment, identify and call one shared settlement path that enforces the same rules as ordinary transfers. Do not let a nearby-specific endpoint bypass existing controls or call a partially equivalent path.
4. **Preserve the existing API transport.** The Flutter app uses `WalletApi`, which handles the session token, signed/enveloped requests, device identity, errors, and transfer idempotency. Add methods there; do not introduce a second HTTP client solely for BLE.
5. **The server, not the device, authorizes payment.** Device biometrics may provide a local confirmation step, but are not a replacement for server-side OTP/step-up, PIN, KYC, limits, balance checks, or idempotency. RSSI is only a user-experience proximity hint.
6. **Treat the discovery code as a temporary capability.** Never place it in analytics, normal logs, crash reports, notification text, or long-lived client storage. Require authentication and authorization on every API operation, expire it quickly, prevent reuse, and redact it from access logs where feasible.
7. **Keep scope to wallet-user payments for the MVP.** Merchant acceptance can follow once recipient identity, payment-request lifecycle, and operational reporting are proven. A merchant flow may require different limits, fees, settlement, and receipt semantics.

## 3. Proposed product flow

### Receiver: “Receive nearby”

1. User chooses a valid amount/currency and optionally a short description.
2. App checks BLE permission, adapter state, and advertising capability.
3. App requests an authenticated nearby-payment session from the backend.
4. Backend returns a one-time code and authoritative request details/expiry.
5. Receiver advertises only the service UUID and code-bearing local name while the screen is active.
6. Receiver sees a waiting state and can cancel. It also displays an existing QR payment fallback.
7. On PAID, EXPIRED, CANCELLED, or FAILED, app stops advertising immediately and renders the backend-confirmed outcome.

### Payer: “Pay nearby”

1. User opens Pay Nearby and grants scan permission; the app scans only for the DSD service.
2. When one or more valid candidates are detected, app stops scanning and fetches candidate details from the authenticated API.
3. App shows recipient name/merchant identity, amount, currency, any applicable fee/total, and expiry. It does not settle on scan or on RSSI.
4. Payer explicitly confirms, completes local biometric/PIN UX as appropriate, then satisfies the backend's normal step-up requirements.
5. App sends one payment request with a stable idempotency key and displays only the backend's final state.
6. If the network result is ambiguous, the client checks the same request/status and retries with the **same** idempotency key; it must not create a fresh payment attempt automatically.

### Failure/fallback behavior

- Bluetooth unsupported/off/denied: explain the issue and offer QR or ordinary recipient lookup.
- Advertising unsupported: receiver uses QR fallback; do not show an indefinitely “waiting” screen.
- More than one candidate: present a list; never silently choose the strongest signal.
- Request expires, is cancelled, has already been paid, or is unavailable: show the server outcome and let the user restart.
- App backgrounds or screen is dismissed: stop local advertising/scanning. On resume, query the session state and do not infer success from a prior screen state.
- Push is delayed/unavailable: receiver polls briefly with backoff; backend state remains authoritative.

## 4. Target architecture

### Backend domain

Add a nearby-payment request record separate from `PaymentRequest`, with at least:

- Opaque random code digest (unique) or an equivalent high-entropy capability representation.
- Receiver, nullable payer, amount, currency, status, created/expiry/paid/cancelled timestamps.
- Resulting `Transaction` reference (nullable until settled).
- A stable operation/idempotency relationship so retries cannot create a second transfer.
- Optional non-sensitive description with existing length/validation conventions.

Suggested states: `OPEN`, `PAID`, `EXPIRED`, `CANCELLED`, and `FAILED` only if the product deliberately persists a terminal failure. Define permitted state transitions before coding. Expiry should be evaluated both lazily on read/pay and by a background cleanup task if operationally useful.

The code should be generated using cryptographically secure randomness, have a short TTL (initial proposal: 120 seconds), be unique, and be unguessable under server-side throttling. Prefer storing a digest rather than the raw code. Validate actual BLE advertisement payload constraints and chosen plugin behavior before fixing code length/encoding.

### API contract (proposal)

All endpoints require an authenticated user token and the existing API envelope:

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/nearby-payments` | Create an open request for the authenticated receiver; validate amount, currency, wallet and account status. Returns the discovery code once. |
| `POST` | `/api/nearby-payments/resolve` | Resolve a code in the request body to payer-safe display and fee information. Unavailable/expired codes share a generic response. |
| `POST` | `/api/nearby-payments/{request_id}/pay` | Pay with a four-digit transaction PIN and UUID idempotency key; exact retries return the settled result. |
| `GET` | `/api/nearby-payments/{request_id}` | Receiver status; after settlement, the authenticated payer may also read the result for recovery. |
| `POST` | `/api/nearby-payments/{request_id}/cancel` | Receiver-only cancellation while still open. |

The precise routing style should follow current URL conventions, and the schema must be included in OpenAPI. Use response shapes that distinguish a pending/unknown network outcome from a definitive failure.

### Settlement transaction

In one database transaction:

1. Lock the nearby request row and re-check that it is open and unexpired.
2. Reject self-payment; verify the payer identity and required KYC/account/wallet state.
3. Apply the ordinary transfer step-up, PIN/OTP, currency, fee, per-transaction/daily limits, and available-balance rules.
4. Lock relevant wallet rows in a consistent order to avoid deadlocks.
5. Settle through the shared existing P2P transfer path with a namespaced idempotency key.
6. Set payer, resulting transaction, and PAID state atomically.
7. Dispatch push/notifications only after commit; notification failure must not roll back or misreport settlement.

An attempted request cannot be paid by a second payer after it has been accepted. A duplicate request using the same idempotency key returns the original outcome; a different payer or conflicting replay receives a clear conflict response. Do not return “success” if the transaction's commit outcome is unknown.

### Flutter components

Keep BLE and payment logic independently testable:

- `lib/ble/ble_constants.dart`: service UUID, advertised prefix, code parsing, scan parameters.
- `lib/ble/ble_permissions.dart`: platform capability, permission/adapter checks, denied/permanently denied behavior, settings guidance.
- `lib/ble/receiver_service.dart`: start/stop advertising; lifecycle-safe and disposable.
- `lib/ble/sender_service.dart`: filtered scanning, candidate deduplication, RSSI reporting as UI metadata only.
- `WalletApi` methods / typed models: create, resolve, pay, status, cancel using existing auth, envelope, idempotency, and error handling.
- Receive Nearby and Pay Nearby screens or feature widgets, added to the current authenticated Services/pay entry points. Existing `main.dart` contains the live navigation and service catalog; the older page files should not be assumed to be the active screens.

All user-facing text must use the app's localization system (English and French at minimum). Use the existing theme and navigation patterns. Ensure BLE operations stop on cancel, route pop, error, app pause, and dispose.

## 5. Development phases and estimates

Planning estimate assumes one backend engineer, one Flutter engineer, and shared QA/product review. Calendar time can be longer due to physical-device access and platform review. Package/API versions must be checked against the app's actual Flutter/Dart toolchain before they are pinned.

### Phase 0 — Product contract and technical spike (3–5 working days)

**Work**

- Confirm MVP is wallet-user P2P only, whether the receiver can set any amount, whether payer must enter a PIN in addition to biometric prompt, and what amount/currency rules apply.
- Trace interactive transfers end-to-end: `TransferView`, fee and limit services, step-up flow, transaction PIN checks, idempotency, envelope middleware, notification/on-commit behavior.
- Finalize API contract, status machine, code length/expiry, rate limits, privacy-safe logging, and QR fallback.
- Verify BLE plugin support, advertise/scan behavior, OS permissions, service UUID filtering, local-name visibility, and foreground restrictions on current supported iOS and Android versions.
- Build a small throwaway or isolated proof-of-capability on at least one physical iPhone and one Android device; do not add dependencies to production app until feasibility is established.

**Exit criteria**

- Written contract and threat model agreed by product/backend/mobile.
- Physical-device proof shows both advertising and scanning work, including expected platform limitations.
- No assumption remains that simulator testing proves BLE functionality.

### Phase 1 — Backend model, API, and settlement (5–8 working days)

**Work**

- Add the request model, migration, serializers, URL routes, OpenAPI descriptions, expiry/state helpers, and endpoint throttles.
- Implement owner-scoped cancel/status and payer-safe lookup.
- Build payment settlement around the authoritative shared transfer logic; address any needed refactor once the interactive path audit is complete.
- Record audit events without recording raw discovery codes. Add safe operation correlation identifiers.
- Add outbox/on-commit dispatch for receiver notifications and ensure polling is an adequate fallback.
- Add cleanup/expiry task only if the current periodic task mechanism is configured and observable; lazy expiry remains mandatory.

**Tests**

- Request create, amount/currency validation, expiry, cancel, lookup, and ownership.
- Unauthenticated calls, unsupported status transitions, self-payment, suspended/frozen wallet, KYC/step-up, insufficient balance, fee/limit enforcement.
- Single-use request, same-key replay, conflicting-key replay, duplicate pay, and two concurrent payers (PostgreSQL).
- Transaction rollback leaves request OPEN and no partial ledger entries.
- Envelope/auth integration and OpenAPI response schema.

**Exit criteria**

- Exactly one completed transaction can be linked to a request.
- All standard transfer controls apply identically to nearby payments.
- Concurrent double-pay test passes against PostgreSQL; SQLite is not accepted as evidence for row-lock correctness.

### Phase 2 — Flutter BLE foundation and API client (5–8 working days, parallel with Phase 1 where contract allows)

**Work**

- Check current plugin compatibility and add only required dependencies (`flutter_blue_plus`, peripheral advertiser, and permission handling; reuse existing `local_auth`).
- Add Android BLE permissions with platform-specific API levels and runtime handling.
- Add the iOS Bluetooth usage description; the existing app already has `NSFaceIDUsageDescription`, so verify its wording and avoid duplicate keys.
- Implement code parsing/encoding, candidate deduplication, RSSI metadata and BLE resource cleanup.
- Add typed nearby-payment API methods to `WalletApi`, including stable idempotency key handling and API envelope compatibility.

**Tests**

- Unit tests for allowed alphabet, prefix parsing, malformed/truncated names, candidate deduplication, and threshold behavior.
- Mocked BLE adapter tests for unsupported, off, denied, revoked, timeout, and stream cancellation.
- API-client tests for auth/envelope, expected error codes, OTP-required response, and retry with the same idempotency key.

**Exit criteria**

- No secrets, amount, account identifiers, tokens, or payment result are broadcast over BLE.
- Scan/advertising streams and subscriptions stop on every terminal/lifecycle path.

### Phase 3 — Receive and pay screens (5–8 working days)

**Work**

- Build receiver amount form, validation, request creation, waiting state, cancel, expiry, final status, and QR fallback.
- Build payer scan state, multiple-candidate picker, server lookup, confirmation summary, biometric/local confirmation, server step-up, and final result.
- Show fee/total if applicable and make recipient/amount/currency unambiguous before payment.
- Implement app lifecycle handling, retry affordances, no-network/ambiguous-response recovery, and safe screen disposal.
- Add entry points to the live Services and/or Receive/Send flows.

**Tests**

- Widget tests for loading, permission denials, unsupported hardware, zero candidates, multiple candidates, expiry, cancellation, pay confirmation, retry, and error messages.
- Verify payer never submits a payment before explicit confirmation.
- Verify a timeout after submit checks/retries the same operation rather than generating a new idempotency key.
- Localization review in English and French; check light/dark appearance, large text, and accessibility labels.

**Exit criteria**

- Complete receiver and payer flows work against an API test environment without BLE hardware using mocks.
- Critical error and recovery states have no stuck loader or false success.

### Phase 4 — Integration, physical-device QA, and limited beta (5–10 working days)

**Work**

- Test at least two physical devices across supported iOS/Android versions and representative manufacturers.
- Test backgrounding, screen lock, Bluetooth toggles, permission revocation, distance/orientation, crowded scans, weak connectivity, and network loss during settlement.
- Measure RSSI distribution; tune only the UX hint, not authorization.
- Add feature flag and server-side kill switch; initially restrict to staff/test accounts.
- Validate monitoring, dashboards, error correlation, and operational runbook for stuck OPEN requests or unknown client outcomes.

**Exit criteria**

- No duplicate ledger postings under repeated taps, request replay, task retries, or ambiguous network responses.
- Every test payment has an auditable request ID and transaction ID; expired/cancelled requests cannot settle.
- Product, engineering, and support owners approve beta readiness and customer-facing copy states this is BLE discovery, not NFC contactless.

### Phase 5 — Rollout and iteration (ongoing)

- Expand beta cohort gradually; retain an immediate kill switch and QR/manual fallback.
- Review success/error and support metrics weekly; disable the feature if payment duplication, unexplained settlement states, or hardware incompatibility exceeds agreed limits.
- Only after wallet-user flow is stable, assess merchant mode, receipts, merchant reporting, and operating/support impact as a separate scoped release.

## 6. Security, privacy, and reliability requirements

- BLE payload contains only a service UUID and temporary opaque code. Never broadcast amount, currency, handle, name, phone, balance, authentication material, or transaction state.
- Discovery code is high-entropy, single-use, short-lived, and rate-limited. API requires authentication, ownership/role checks, and safe responses to invalid or expired codes.
- Avoid logging raw codes in application logs, analytics, traces, URLs where practicable, and crash reports. If route paths contain codes, configure request-log redaction.
- Do not trust device proximity, RSSI, client clocks, app state, biometrics, or client-provided recipient/amount as authorization.
- Settlement is performed only by the server using existing KYC, account, wallet, step-up, PIN, fee, limit, idempotency, and ledger rules.
- Use database row locking and a single atomic state/transfer transition; test against the production database engine.
- Do not issue payment notifications before commit. FCM failure must not reverse a committed payment.
- If the API returns an ambiguous network error after submission, reconcile against the same request and idempotency key before offering a new attempt.
- Record meaningful security/financial audit metadata but never persist biometric data.
- Provide a feature flag, rate limits, metrics, alerting, and a kill switch before any external beta.

## 7. Operational and product metrics

Measure with privacy-preserving identifiers:

- Nearby requests created, cancelled, expired, paid, and failed.
- Conversion rate from scan → verified candidate → confirmation → paid.
- Median and p95 time to identify a payer/receiver and complete payment.
- Expiry rate and cancellation rate; scan timeout and BLE-permission failure rate by OS/device family.
- Payment failures categorized by server reason (limits, KYC, step-up, insufficient funds, expiry, conflict, network).
- Duplicate attempts, idempotent replay count, unknown-outcome count, and ledger discrepancy count (target: zero duplicate postings and zero unexplained variances).
- Receiver notification latency and polling fallback usage.
- Nearby-payment-related support contacts and wrong-recipient complaint rate.

Never use the raw discovery code, precise location, or Bluetooth device identifiers as analytics dimensions.

## 8. Key risks and mitigations

| Risk | Mitigation |
|---|---|
| BLE advertising/scan differences across phones and OS releases | Physical-device spike before dependencies/UI; define supported device matrix; keep QR/manual fallback. |
| Short code guessed or relayed by an attacker nearby | High entropy, short expiry, rate limiting, authenticated lookup/pay, explicit payer confirmation, one-time state transition. Proximity is not identity proof. |
| User mistakes nearby person or amount | Show server-returned identity/amount/currency/fees; require explicit confirmation; handle multiple candidates with selection. |
| Double payment after timeout/retry | Stable idempotency key, locked request state, unique resulting transaction, Postgres concurrency tests, status lookup after ambiguous responses. |
| OTP/step-up cannot complete in the new flow | Reuse existing API client and OTP mechanism; make step-up response a first-class recoverable screen state. |
| iOS foreground restriction interrupts receiver | Stop advertising predictably; show clear waiting state and keep screen active only if product/OS policy allows; status poll on resume; use QR fallback. |
| Privacy leaks through code or device telemetry | Store digest; redact logs; minimize API response; avoid Bluetooth identifiers and code in analytics/crash reporting. |
| The existing transfer path has no single shared policy-complete service | Audit first; extract a shared service with regression tests before implementing nearby settlement. |

## 9. Release checklist

- [ ] Product confirms wallet-user-only MVP, currency/amount rules, expiry, confirmation and fallback behavior.
- [ ] API contract and state machine approved; API envelope and idempotency semantics documented.
- [ ] No duplicate `PaymentRequest` behavior or financial settlement logic has been introduced.
- [ ] Backend unit/API/concurrency tests pass on PostgreSQL.
- [ ] Migration applies cleanly and expiry/cleanup behavior is observable.
- [ ] Flutter analyze/tests pass; API and BLE layers are mockable.
- [ ] iOS/Android permissions and privacy copy are reviewed; existing Face ID declaration is reused.
- [ ] Two-device physical test matrix passes; iOS Simulator is not counted as BLE advertising evidence.
- [ ] QR/manual fallback is available for denied/unsupported Bluetooth.
- [ ] Metrics, rate limits, log redaction, alerts, feature flag, kill switch, and support runbook are ready.
- [ ] Customer-facing language clearly distinguishes BLE discovery from NFC/contactless payment.

## 10. Decisions to confirm before implementation

The plan assumes wallet-user P2P only, a 120-second initial expiry, server-controlled amount/currency rules, and QR/manual fallback. Before Phase 1, product and engineering should confirm:

1. Is the first release for wallet users only, or must merchants receive nearby payments too?
2. Can receiver choose any amount/currency supported by their wallet, or only their wallet's configured currency?
3. Should payer authorization require existing OTP/PIN, local biometrics, or both? Recommendation: retain server-required existing step-up/PIN policy; biometrics is an additional local UX confirmation, never the only authorization.
4. Is 120 seconds acceptable for request expiry, given screen switching and step-up time?
5. Which minimum OS versions/device families must be supported, and who will supply the physical-device test matrix?

## 11. Assumptions and verification limits

- The plan is based on source inspection, not a running mobile/API integration test.
- Flutter BLE plugin APIs and platform-specific advertising constraints must be verified against current package versions and the project's Flutter toolchain during Phase 0.
- The current API client implements a custom authenticated/enveloped request path; new endpoints must be tested through that path, not with a separate raw HTTP client.
- Current interactive transfers and `execute_p2p_transfer()` have different surrounding policy responsibilities. The implementation must reconcile this before selecting the settlement service.
- App Store/Play policy and regional payment compliance are outside this source review and require product/compliance approval before a public rollout.
