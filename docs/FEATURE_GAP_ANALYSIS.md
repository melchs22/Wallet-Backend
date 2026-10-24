# Wallet Platform: Critical Feature and Improvement Analysis

**Assessment date:** 2026-10-05
**Scope:** The current repository working copy: Django API and services, Flutter client, and the `operations-portal` admin client.

## Executive assessment

The platform already has a broad product surface: user and administrator authentication, wallets and a ledger, P2P transfers, payment requests, QR payments, bill splits, scheduled transfers, transaction approvals, parental controls, KYC submissions, disputes, mobile-money flows, utility payments, merchant payment intents, webhooks, bank/payout records, notifications, and an operations portal. The largest opportunity is not another menu of features. It is making the existing money movement dependable, externally real, easy to understand, and supportable.

The code has sound foundations worth preserving: decimal amounts, a ledger-derived balance, atomic transfer execution, transfer idempotency, device-bound step-up authentication, audit records, and a usable operations surface. However, feature names and API routes sometimes overstate implementation depth. In particular, the mobile-money endpoints generate simulated provider transactions, utility payments are completed with locally generated references, the current reconciliation job does not compare against an independent balance, and the wallet model does not support the multiple currencies described by the older README. These are material differences between “endpoint exists” and “production capability exists.”

### Highest-priority work

| Priority | Finding | Why it should come before expansion |
|---|---|---|
| **P0 — financial correctness** | `reconcile_balances()` only compares a wallet against `balance_cache` when that attribute exists; the `Wallet` model has no such field. The current code therefore has no independent balance to compare and cannot detect ordinary ledger drift. | Reconciliation is a core safeguard for a ledger-based product. Replace the check with a real invariant/reconciliation strategy and test detection as well as repair. See [reconciliation.py](../wallet/services/reconciliation.py) and [models.py](../wallet/models.py). |
| **P0 — external money movement** | Mobile-money top-ups and withdrawals assign synthetic provider references and queue a simulated successful completion. Utility payments record a completed transaction with a locally generated reference, without a utility-provider confirmation. | These flows must be visibly sandbox-only until real provider adapters, callbacks, settlement reconciliation, and failure/refund paths exist. See [views.py](../wallet/views.py) and [mobile_money.py](../wallet/services/mobile_money.py). |
| **P0 — withdrawal hold correctness** | On a failed withdrawal, the webhook handler deletes unlinked debit ledger entries matching wallet and amount, rather than releasing a hold tied to that specific withdrawal. Two equal-value pending withdrawals can therefore interfere with each other. | Give every hold an explicit transaction/reservation identity, then release or settle only that reservation; add concurrent and duplicate callback tests. See [mobile_money.py](../wallet/services/mobile_money.py). |
| **P0 — callback durability** | The mobile-money webhook endpoint records an event before dispatching the Celery task. If dispatch fails, a provider retry with the same event ID is treated as already received, even though processing was not queued. `processed_at` is also set at enqueue time. | Use a durable inbox/outbox state machine with atomic receipt, retryable dispatch, and a distinct processed timestamp. See [views.py](../wallet/views.py) and [tasks.py](../wallet/tasks.py). |
| **P1 — schedule correctness** | Monthly and yearly scheduled transfers advance by fixed 30- and 365-day intervals. This drifts from calendar dates and mishandles leap years. Failed transfers advance the schedule instead of retrying. | Use calendar arithmetic, explicit timezone rules, and a configurable retry/missed-payment policy before advertising “monthly” as a dependable bill-like schedule. See [transfers.py](../wallet/services/transfers.py). |
| **P1 — FX integrity and product gap** | Rate refresh deletes all `ExchangeRate` rows; transactions reference rates with `SET_NULL`, so a refresh can erase historical references. Separately, `Wallet.user` is one-to-one and transfer execution requires matching currency, so this is not yet a multi-currency wallet/remittance product. | Preserve immutable rate history and implement a user-visible, server-priced FX quote and settlement flow before enabling cross-currency transfers. See [exchange_rates.py](../wallet/services/exchange_rates.py) and [models.py](../wallet/models.py). |

These observations describe the checked-in/current working-copy source, not a verified production deployment. Provider contracts, environment configuration, and deployed behavior were not independently exercised for this analysis.

## Module-by-module assessment

### 1. Wallet, ledger, and transaction core

**Present:** A wallet balance is computed from credit and debit ledger entries. Transfers use `Decimal`, atomic database transactions, a row lock on the sender wallet, idempotency records, fee entries, and audit logs. Reversals are intended to use offsetting ledger movements rather than editing history. These are appropriate financial primitives. See [models.py](../wallet/models.py), [transfers.py](../wallet/services/transfers.py), and [views.py](../wallet/views.py).

**Critical assessment:**

- `Wallet.get_balance()` runs separate credit and debit aggregates for each balance read. This is correct as a source of truth but can become an expensive hot path as ledger history grows. Measure query volume and latency before introducing a balance snapshot; any snapshot must remain derived, rebuildable, and regularly reconciled.
- The reconciliation job checks for a `balance_cache` attribute that is not defined on `Wallet`. It may report success without checking the actual ledger invariant. The check also computes totals wallet-by-wallet, which will be costly at scale.
- The audit trail is useful, but critical action coverage, immutable retention, searchable event correlation, and operator attribution should be treated as explicit requirements rather than assumed from the model's existence.
- Financial flows would benefit from a first-class operation lifecycle: initiated, held, submitted, confirmed, failed, reversed, and reconciled. A transaction status alone is not a substitute for provider state and settlement state.

**Meaningful improvements:**

1. Define and test ledger invariants (balanced postings where applicable, no negative available funds, one settlement per provider operation, reversal exactly once).
2. Build reconciliation reports for ledger-to-provider and ledger-to-bank positions, with variance categories, case ownership, and controlled repair approval.
3. Add immutable operation references and a unified transaction detail/receipt with amount, fees, counterparties, timestamps, and status history.
4. Add ledger partitioning/archival and query-performance monitoring only when measured volume justifies it.

### 2. Authentication, account lifecycle, and devices

**Present:** The API supports Google and email/password authentication, password reset/change, OTP challenges, signed access tokens, trusted-device flows, device revocation, push registration, biometric app lock, and administrator TOTP. Step-up checks protect sensitive operations. See [views.py](../wallet/views.py), [security.py](../wallet/services/security.py), [authentication.py](../wallet/authentication.py), and the Flutter [API client](<../wallert app/lib/api.dart>).

**Critical assessment:**

- There are multiple authentication modes and both user and administrator flows. They need a single documented lifecycle and recovery model: device lost, phone changed, email compromised, OTP unavailable, admin recovery, and session revocation.
- A local biometric lock protects access to the app on that device; it should not be presented as a replacement for server-side transaction authorization.
- Account closure exists, but a complete lifecycle also needs data-export, support-assisted recovery, identity correction, dormant-account handling, and documented retention/deletion rules.
- Product identity checks and risk checks need explicit states, expiry, re-review, and escalation. A submitted KYC document should not by itself be confused with verified identity.

**Meaningful improvements:** Add a “security and sessions” center for users, safer recovery and re-verification flows, passkey support where compatible, and a visible device/session history. For staff, enforce distinct roles and approval thresholds for sensitive actions instead of treating every staff account as an interchangeable administrator.

### 3. P2P transfers, payment requests, QR, splits, and approvals

**Present:** The API and Flutter client include recipient resolution by handle/phone, transfer previews and sends, requests to pay, QR verification/payment, split-bill creation, and approval inboxes with PIN confirmation. See [urls.py](../wallet/urls.py), [views.py](../wallet/views.py), [approval_views.py](../wallet/approval_views.py), and the Flutter [main.dart](<../wallert app/lib/main.dart>).

**Critical assessment:**

- The core flows exist, but the end-user experience should make the final amount, fees, recipient identity, currency, and reversibility clear before confirmation. A useful preview must be authoritative and expire if any price or limit input changes.
- Payment requests and splits need visible lifecycle controls: reminders, expiry, partial payment/remaining balance, cancellation, participant replacement, and explicit final state. The backend has expiry and status models, but the client should expose the full lifecycle rather than only creation or approval.
- QR payloads should be short-lived, scoped, non-enumerable, and clearly distinguish a user-payment QR from a merchant QR. The server, not client-parsed content, must determine the payee and amount.
- Transfer receipts, transaction search, date/category filters, repeat payment, and export are natural high-value improvements. The app already has a PDF statement path, which can be expanded into dependable statement and receipt workflows.

**Meaningful improvements:** Add saved/favorite recipients, request reminders, payment templates, a complete activity/search experience, and receipt sharing. Prioritize these after financial status correctness and testable confirmation UX.

### 4. Scheduled transfers

**Present:** Users can create, list, edit, pause, resume, and cancel scheduled transfers. A Celery task runs due transfers via the shared transfer service and logs failures. See [views.py](../wallet/views.py), [transfers.py](../wallet/services/transfers.py), and [tasks.py](../wallet/tasks.py).

**Critical assessment:**

- The “monthly” and “yearly” frequencies use a fixed number of days, not calendar intervals. A schedule on the 31st has no defined behavior in shorter months.
- On an insufficient-funds or other transfer failure, the task advances to the next occurrence without retrying. This is potentially surprising for recurring obligations.
- Execution depends on task scheduling, Celery worker availability, time-zone semantics, and reliable notification delivery. Users need to know whether a payment is queued, attempted, retried, skipped, or completed.

**Meaningful improvements:** Implement calendar-aware intervals and explicit end-of-month rules; add configurable retry windows and missed-payment states; show next run, last result, fee estimate, and editable retry behavior; add per-schedule idempotency and operational alerts.

### 5. Mobile money, cash-in/cash-out, and utility payments

**Present:** Provider catalogs and account links exist. Top-up and withdrawal endpoints create transaction records, and signed webhook verification plus asynchronous status processing are present. The utility module supports water and electricity categories. See [views.py](../wallet/views.py), [mobile_money.py](../wallet/services/mobile_money.py), [security.py](../wallet/services/security.py), and the [UtilityPayment model](../wallet/models.py).

**Critical assessment:**

- The top-up and withdrawal code explicitly marks the provider call as simulated, creates synthetic provider references, and queues a simulated completion. The utility endpoint immediately records completion with a generated local reference. These are useful for development, but must not be confused with real provider settlement.
- The withdrawal hold is currently an unlinked debit (`transaction=None`); failure cleanup matches by wallet and amount instead of a unique hold. This is a correctness defect to fix before integrating real providers.
- Webhook receipt and task dispatch are not failure-safe as described above. Provider callbacks also need a provider-specific mapping, authenticated account context, out-of-order event handling, and reconciliation against provider statements.
- A linked provider account is not the same as proof that provider-side money was moved or a bill was paid.

**Meaningful improvements:** Integrate one provider at a time behind a provider adapter with sandbox/live separation, request signing, provider idempotency, status mapping, callback verification, timeout handling, refund/rollback handling, and daily reconciliation. Add biller lookup/validation, customer-name confirmation, bill reference/receipt, and reversal/escalation workflows before expanding the list of utilities. Do not activate all provider names merely because catalog entries exist.

### 6. FX and multi-currency

**Present:** Exchange-rate fetching has a primary and fallback source, validates rates, supports active country currencies, and stores rate rows. The app can retrieve indicative rates. The transaction model has an optional exchange-rate reference. See [exchange_rates.py](../wallet/services/exchange_rates.py), [models.py](../wallet/models.py), and the Flutter [exchange-rate service](<../wallert app/lib/src/services/exchange_rate_service.dart>).

**Critical assessment:**

- Refresh currently deletes the rate table before bulk-creating the latest set. This removes rate history and, due to the transaction foreign key's `SET_NULL`, can erase the rate association from historical transactions.
- The `Wallet` model is one-to-one with `User`, and transfer execution rejects mismatched wallet currencies. Therefore, stored FX rates do not yet amount to cross-currency wallet balances or remittances.
- An indicative rate fetched by the client is not a safe transaction quote. A financial quote must include server-side rate, spread/fee, source, expiry, rounding, and the recipient's exact receive amount.

**Meaningful improvements:** Make rates append-only with validity windows and source timestamps; implement quote-locking and a server-side conversion ledger with explicit source and destination amounts; add stale-rate fallback policy and user-visible quote expiry. A multi-currency wallet is a product/schema decision, not just a UI toggle.

### 7. Merchant platform and developer API

**Present:** Merchant accounts, plans/subscriptions, limits, payment intents, sandbox/live modes, API keys, payment links/QR prompts, transaction and settlement views, bank account and payout records, disputes/refunds, team members, and signed webhook delivery are represented across the API and models. See [merchant_urls.py](../wallet/merchant_urls.py), [merchant_views.py](../wallet/merchant_views.py), [payment_intents.py](../wallet/services/payment_intents.py), [webhooks.py](../wallet/services/webhooks.py), and [merchant_integration_guide.md](../merchant_integration_guide.md).

**Critical assessment:**

- The developer-facing surface is broad, but an integration is only production-ready when the full payment-to-settlement lifecycle, idempotency contract, error semantics, webhook retries, and reconciliation are stable and documented.
- Merchant limit enforcement calculates current usage and then payment-intent creation proceeds separately. Concurrent requests can both observe remaining capacity and exceed a daily/monthly limit unless the check and reservation are made concurrency-safe.
- Webhook delivery has attempt/status records and a retry endpoint, but merchants need delivery history, next retry time, payload version, replay safety guidance, delivery health, and an actionable dead-letter state.
- Payout schedules and bank models should be paired with provider execution and reconciliation before describing payout as complete.
- Existing merchant documentation has outdated endpoint/feature guidance relative to current code. This makes onboarding harder and can lead integrators to rely on an incorrect contract.

**Meaningful improvements:** Add published API versioning and changelog, language-specific quickstarts/SDKs, copyable sandbox fixtures, scoped/rotatable keys, idempotency examples, webhook endpoint test/send tools, and merchant settlement reports. Make quota reservation atomic and provide clear “authorized/paid/settled/refunded/disputed” status distinctions.

### 8. KYC, disputes, limits, and fraud operations

**Present:** KYC submission and review, user KYC tiers, adjustable send limits, usage-based limit increases, transfer-attempt records, transaction flags, alert rules, dispute creation/review, and admin notes/actions exist. See [models.py](../wallet/models.py), [limits.py](../wallet/services/limits.py), [admin_views.py](../wallet/admin_views.py), and [views.py](../wallet/views.py).

**Critical assessment:**

- Tier-based limit changes and manually set limits are useful controls, but need transparent user-facing explanations and a clear appeal/escalation route.
- KYC appears oriented around uploaded documents and a single review outcome. A mature workflow needs document expiry/re-review, reason codes, reviewer history, consent, retention, and secure access controls for files.
- Disputes have reason and notes fields, but an operational case should also have evidence attachments, category, SLA, assigned owner, communication timeline, decision rationale, linked reversal/refund, and customer-visible status.
- Transfer-attempt logs and rule models are monitoring foundations, not a complete fraud decisioning program. Risk controls should be measurable and explainable; avoid opaque automated restrictions without review and appeal.

**Meaningful improvements:** Build a case-management queue that combines KYC, disputes, suspicious transfers, and account/device alerts; add rule outcomes and false-positive review; add sanctions/PEP screening and jurisdiction-specific controls only with a defined compliance owner and provider/legal basis.

### 9. Notifications and communication

**Present:** Notification records, localized push messages, FCM device registration, OTP delivery, and administrative communications exist. The app supports notification reads and push-driven workflows. See [notifications.py](../wallet/services/notifications.py), [security.py](../wallet/services/security.py), and [tasks.py](../wallet/tasks.py).

**Critical assessment:**

- A database notification and an FCM delivery are different states. Users and support staff need delivery outcome, invalid-token cleanup, retry status, and an in-app inbox that remains the source of truth.
- Sensitive actions should not rely solely on push delivery; the product needs fallback and recovery behavior when push is disabled or delayed.
- Preferences, consent, quiet hours, language selection, and notification category controls are natural next steps. Marketing communication should be separated from transactional/security messages.

**Meaningful improvements:** Add notification preferences and delivery diagnostics, explicit in-app status timelines, and fallback channels for high-value operation state changes. Measure delivery success and time-to-notice for transaction alerts.

### 10. Operations portal and administrative APIs

**Present:** The portal has dashboard, user, wallet, transaction, KYC, support, merchant, device, dispute, fee, FX, webhook, scheduled-task, and audit surfaces. Many pages use a shared resource/detail pattern. Backend admin operations include analytics, reconciliation, reports, system health, communications, and CRUD-style endpoints. See [routes.ts](../operations-portal/config/routes.ts), [admin modules](../operations-portal/src/pages/admin/modules.tsx), [admin service](../operations-portal/src/services/admin.ts), [admin_views.py](../wallet/admin_views.py), and [admin_api.py](../wallet/admin_api.py).

**Critical assessment:**

- A reusable records table is a good starting point, but money operations need workflows, not just generic record inspection: before/after state, reason capture, approval, evidence, and a durable audit reference.
- Several portal action handlers convert every request failure into a generic message. That avoids exposing internals, but gives staff no actionable correlation ID or next step. Add safe, structured error details and server-side correlation IDs.
- The portal exposes sensitive operational data and actions, including device tokens and manual wallet operations. Mask secrets, scope staff access by role, log reads of sensitive material, and require stronger confirmation or dual control for high-risk actions.
- The current reports/analytics should be tied to agreed definitions (gross vs net volume, fees, successful vs attempted payments, provider settlement date vs transaction date) before being used for business decisions.

**Meaningful improvements:** Add role-based permissions, four-eyes approval for manual credits/reversals/limit overrides, operator action previews, case assignment/SLA queues, searchable correlated timelines, export controls, and clear “sandbox/live” indicators on every money-related screen.

### 11. Flutter user experience and localization

**Present:** The authenticated app has dynamic wallet and transaction loading, refresh, transaction history and PDF export, transfer/payment request flows, merchant QR/payment screens, utilities, KYC, schedules, disputes, notifications, parental controls, approvals, device security, app-update policy, and English/French localization. The active app entry point and much of the product UI reside in [main.dart](<../wallert app/lib/main.dart>); there are also focused pages under [the Flutter pages directory](<../wallert app/lib/src/pages>).

**Critical assessment:**

- `main.dart` has become a very large application file containing many unrelated flows. This makes payment lifecycle changes, review, and regression testing harder. Split by feature and introduce typed models/repositories before adding more screens.
- API responses are handled dynamically in many places. Typed request/response models and explicit loading, empty, retry, and stale-data states would reduce client/server drift.
- Several important capabilities are spread across home, services, and feature-specific pages. Improve discoverability and show clear status for pending/retrying/failed operations.
- A static older home-page widget remains in the source tree alongside the current authenticated home implementation. Confirm which screens are live and remove or clearly mark dead/legacy UI to avoid maintaining misleading code.
- Existing widget coverage is a small smoke/formatting set relative to the number of money-moving screens.

**Meaningful improvements:** Add integration tests for real API contracts and critical flows, accessibility and large-text review, offline-safe read-only history, predictable currency/locale formatting, and explicit confirmation/receipt pages. Prefer more evidence and reliability in core workflows over extra dashboard decoration.

### 12. Background processing, deployment, and documentation

**Present:** Celery tasks support scheduled transfers, notification delivery, OTP, webhook processing, exchange-rate refresh, expiry, cleanup, and reconciliation. Django exposes OpenAPI documentation and deployment operations documentation. See [tasks.py](../wallet/tasks.py), [walletmvp/celery.py](../walletmvp/celery.py), [DEPLOYMENT_OPERATIONS.md](../DEPLOYMENT_OPERATIONS.md), and [walletmvp/urls.py](../walletmvp/urls.py).

**Critical assessment:**

- A queued task is not proof of completed work. Every important async operation should have a durable state, retry policy, terminal failure path, alert, and safe manual replay.
- Health checks should distinguish API availability from database, cache/broker, worker, provider, and scheduled-task health. A basic HTTP “ok” response is not an end-to-end readiness signal.
- Documentation is materially out of sync with current features: the README lists some already implemented items as future work and describes multi-wallet support that conflicts with the one-to-one wallet model. The merchant integration guide also lags implemented routes. The mobile-money “simulation” implementation needs equally prominent sandbox labeling.
- Backend tests include meaningful transfer, concurrency, limits, exchange-rate, merchant, security, and support coverage; the Flutter test file is comparatively small, and portal tests focus largely on authentication/app behavior. Provider callbacks, complete consumer journeys, and cross-surface contract tests deserve more coverage.

**Meaningful improvements:** Add queue-age/dead-letter monitoring, provider and worker readiness checks, task replay tooling with idempotency guards, structured correlation IDs, and contract tests generated from the OpenAPI schema. Reconcile README, integration docs, API schema, and the actual feature flags/modes in one documentation pass.

## Additional product opportunities, ranked by user value

These should follow the P0/P1 reliability work rather than compete with it:

1. **Trustworthy activity and statements (high value, low external dependency):** searchable transaction history, downloadable statements by date range, transaction receipts, fee breakdown, and repeat-payment flow.
2. **Recipient convenience (high value):** favorites, recent contacts, saved payment requests, and recipient verification before sending.
3. **Bill and recurring-payment reliability (high value):** validated biller account lookup, scheduled utility payments, reminders, retry policy, and proof-of-payment receipts, after real provider connectivity exists.
4. **Merchant self-service (high value for adoption):** onboarding checklist, sandbox simulator, credential rotation, webhook diagnostics/replay, settlement reports, and dispute evidence submission.
5. **Cross-border payments (high potential, high complexity):** only after multi-currency wallet/ledger design, retained rates, quote expiry, compliance review, and provider settlement are in place.
6. **Savings goals and spending insights (medium value):** labeled sub-balances, budgets, and merchant/category summaries. Do not implement mutable “pockets” as a second balance system; represent them as ledger-backed allocations.
7. **Agent cash network / referral program (conditional):** potentially valuable in target markets, but only after agent vetting, float management, cash reconciliation, fraud controls, and unit economics have owners.

## Suggested delivery sequence

### Phase 0 — Establish financial truth

- Repair reconciliation so it actually verifies ledger invariants and produces a tested report.
- Tie every withdrawal hold to its operation; make release/settlement idempotent and scoped.
- Make provider simulation impossible to mistake for live processing; disable simulated success outside explicit sandbox configuration.
- Make webhook receipt durable across broker outages and distinguish received, queued, processing, and processed.
- Preserve FX history and prevent deletion from nulling historical transaction references.
- Add regression tests for repeated, delayed, out-of-order, and concurrent callbacks/operations.

**Exit criteria:** tests demonstrate that duplicate or failed callbacks cannot create/delete another transaction's ledger movement; reconciliation finds an intentionally introduced variance; no live operation reports success from a simulated provider response.

### Phase 1 — Complete existing payment journeys

- Implement calendar-correct schedules and visible retry/missed-payment behavior.
- Make merchant limits concurrency-safe through reservation/locking.
- Complete one live provider integration end-to-end, including callback, refund/failure, operational visibility, and daily reconciliation.
- Expand disputes and KYC into case workflows with audit, SLA, and evidence.
- Validate user/merchant receipts, activity filters, and explicit status semantics.

**Exit criteria:** an operator can trace a payment from user action through provider response, ledger posting, notification, settlement, and any reversal without manually editing data.

### Phase 2 — Grow usage and developer adoption

- Improve merchant sandbox, SDKs, webhook diagnostics, and settlement reporting.
- Add favorites, recurring templates, reminders, and transaction search/export.
- Decide whether to migrate the wallet schema to support multiple currencies; only then ship FX sending.
- Pilot agent/referral or savings features after compliance and economics sign-off.

**Exit criteria:** improved successful payment completion, lower support contacts per transaction, healthy webhook delivery, and measurable repeat usage—not simply more endpoints.

## Metrics to instrument before judging success

- Successful, failed, reversed, and unknown-outcome transfers by rail and provider.
- Ledger reconciliation coverage and variance count/value; unresolved variance age.
- Provider callback acceptance, queue delay, duplicate rate, processing failures, and settlement mismatch.
- Scheduled transfer on-time completion, retry recovery, and user-notified failure rate.
- Merchant payment-intent conversion, settlement delay, webhook success/retry/dead-letter rate, and dispute rate.
- KYC review time and rejection/appeal rate; support first-response and resolution time.
- Mobile crash-free sessions, API error rate by endpoint, statement export completion, and repeat transfer use.

## Bottom line

The system has already accumulated a large and promising feature set. Its next meaningful release should focus on **accurate status, safe money movement, durable reconciliation, real integrations, and clear operational ownership**. Once users and operators can trust that every “completed” payment is actually settled and every failure is recoverable, convenience features and cross-border expansion become much more valuable and much less risky.
