# Subscription records and release prerequisites

`ProviderSubscription` is the provider-specific source of truth. `BusinessAdmin` billing fields remain a temporary projection for older app versions. `ProviderEvent` contains identifiers and processing metadata only; raw receipts, purchase tokens, JWS payloads, and webhook bodies must not be stored or logged.

## Entitlement policy

- Production Apple, live Stripe, production Google, and explicit manual grants may entitle an account.
- Sandbox/test records entitle only when `ALLOW_TEST_SUBSCRIPTION_ENTITLEMENTS=True`; production must set it to `False`.
- `canceled` means renewal is disabled and remains entitled until `current_period_end`.
- Missing renewal information remains `null`.
- Internal 12-day trials remain on `BusinessAdmin.trial_ends_at` and are reported separately from store trials.
- `LEGACY_SUBSCRIPTION_FALLBACK_ENABLED=True` preserves the old API while an account has no provider-verified row. Disable it only after the dry-run, backfill, and reconciliation queues are clear.

## Apple release gate

Set all existing Apple Server API variables and provide current Apple root certificates in `APPLE_ROOT_CERTIFICATES_PEM`. A missing or untrusted chain rejects transaction verification and returns a retryable 503 for notifications without changing subscription state.

The app must use the additive `app_account_token` returned by the subscription API as StoreKit's `appAccountToken`. New purchases without that token are not claimed by the first requester. Existing purchases without a token are accepted only when their original transaction ID is already bound to the same account by legacy data or a provider row.

## Legacy backfill

Inspect only:

```console
python manage.py backfill_provider_subscriptions
```

Apply locally/staging after reviewing counts:

```console
python manage.py backfill_provider_subscriptions --apply
```

The command is idempotent. It marks inferred rows as `legacy` and `needs_reconciliation`; it never labels them store-verified and does not replace an already verified row.

## Google Play release gate

Google verification uses `purchases.subscriptionsv2.get`. The client sends only `purchaseToken`; package name and the product/base-plan allowlist are server configuration. The client must set BillingClient's `obfuscatedAccountId` to the existing additive `app_account_token` value. A token without that identifier is accepted only when the same purchase, or its `linkedPurchaseToken`, is already bound to that account.

| Environment variable | Purpose | Source / setup |
| --- | --- | --- |
| `GOOGLE_PLAY_PACKAGE_NAME` | Exact Android application ID | Existing app entry in Play Console |
| `GOOGLE_PLAY_SUBSCRIPTION_PRODUCTS_JSON` | JSON map of product IDs to allowed base-plan IDs | Existing subscriptions in Play Console; no guessed defaults |
| `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_B64` | Base64-encoded service-account JSON for Scalingo | Existing Google Cloud service account with Android Publisher access; set directly in Scalingo, never paste into chat or Git. Leave empty when ADC is available |
| `GOOGLE_APPLICATION_CREDENTIALS` | Optional ADC file path instead of the base64 variable | Workloads with an existing mounted credential file |
| `GOOGLE_PLAY_TOKEN_ENCRYPTION_KEY` | Fernet key for recoverable encrypted purchase tokens | Generate once in a trusted shell and store in Scalingo. Back it up securely; rotation requires re-encryption |
| `GOOGLE_PUBSUB_AUDIENCE` | Exact OIDC audience checked on RTDN pushes | Must equal the audience configured on the Pub/Sub push subscription |
| `GOOGLE_PUBSUB_SERVICE_ACCOUNT_EMAIL` | Allowed Pub/Sub push identity | The user-managed push-auth service account configured on the subscription |

For Scalingo, use the base64 credential variable because ADC is not normally attached to a container. Grant the existing service account access to the app in Play Console, enable the Android Publisher API, configure Play RTDN to publish to a Pub/Sub topic, and configure an authenticated push subscription for `/api/business-menu/admin/subscriptions/google/notifications/`. The push identity, audience, issuer, signature, package name, message size, and message ID are verified.

The exact public push URL and recommended audience are both `https://preismenu.de/api/business-menu/admin/subscriptions/google/notifications/`. The Android Publisher service account verifies purchases; the separate Pub/Sub push-auth service account signs push requests. Do not reuse or confuse their permissions. Base64 is only encoding: keep the JSON in Scalingo environment storage and outside Git/chat.

Non-secret Play Console inputs still required are the Android application ID, each subscription product ID, each allowed base-plan ID, the Cloud project/topic name, and the push-auth service-account email. Enable Google Play Android Developer API, link the Cloud project/service account in Play Console, and grant only the subscription/order viewing and management access needed by verification and acknowledgement.

Validate structure without printing secrets:

```console
python manage.py check_google_play_subscription_config
python manage.py check_google_play_subscription_config --check-credentials
```

The second command only refreshes an OAuth access token. It does not prove a real purchase, RTDN delivery, or acknowledgement.

Purchase tokens are stored only as a SHA-256 ownership identifier plus a Fernet-encrypted recoverable value. They are excluded from admin screens, API responses, and logs. Acknowledgement is server-owned and idempotent. Failed acknowledgements remain `needs_reconciliation=True`; inspect and retry with:

```console
python manage.py retry_google_play_acknowledgements
python manage.py retry_google_play_acknowledgements --apply
```

`cron.json` runs the `--apply` command hourly through Scalingo Scheduler. A PostgreSQL advisory lock prevents overlapping runs from doing the same work, and any provider failure exits non-zero while leaving `needs_reconciliation=True` for the next retry. Monitor non-zero task exits and rows that remain queued.

## Client compatibility

- Existing Apple purchases whose original transaction is already bound continue to verify/restore without `appAccountToken`.
- New or previously unbound Apple purchases require the app to pass `app_account_token` to StoreKit.
- New Google purchases require the same value as BillingClient `obfuscatedAccountId`. Existing or linked Google purchases can restore only after a secure server binding exists.
- A pending, test, invalid, or unrelated Google row does not erase an independent legacy Apple/Stripe entitlement. A verified row for that same legacy provider purchase supersedes the fallback, so a confirmed revoke is not undone.

The authenticated app obtains the stable UUID from `GET` (or compatibility `POST`) `/api/business-menu/admin/subscription/`, field `app_account_token`. For a new Apple purchase pass it as StoreKit `appAccountToken`; for a new Google purchase pass it as BillingClient `obfuscatedAccountId`. Verify with `/admin/subscription/apple/verify/` or `/admin/subscription/google/verify/`; restore uses `/admin/subscription/restore/` with `provider` and the provider purchase token/JWS. Previously bound purchases may restore without adding a new ownership claim; previously unbound purchases require an app update and the account token.

Call StoreKit `finish()`/`finishTransaction` only after `/api/business-menu/admin/subscription/apple/verify/` returns `200` and the verified subscription has been persisted. Keep the transaction pending for a retryable `503`; do not start another purchase to work around verification failure.

## Service block and mobile subscription state

`Block all service access` sets `BusinessAdmin.subscription_access_blocked`, its timestamp, actor, reason, and last admin-action UUID. It leaves `User.is_active`, `BusinessAdmin.is_active`, `Restaurant.is_active`, JWT validity, and financial/provider records unchanged. Unblock recalculates access from the remaining valid subscription/trial; it does not create or extend one.

`GET /api/business-menu/admin/subscription/` (and compatibility POST) requires valid authentication but does not require an entitlement. It returns `Cache-Control: private, no-store` so HTTP caches cannot reuse a previous Active response. A service-blocked active account receives `200` with these fields, even while a paid provider/manual record still exists:

```json
{
  "state": "blocked",
  "is_entitled": false,
  "access_blocked": true,
  "entitlement_source": "admin_block",
  "decision_reason": "administratively_blocked",
  "access_block_reason": "Account review",
  "message": "Access is blocked by an administrator."
}
```

This is an excerpt; the response retains provider, expiry and provider-history fields. Every nested `providers[].is_entitled` is false while blocked. A future expiry or a provider row with `status=active` must not override top-level `is_entitled=false`. APIs with subscription enforcement keep returning `402 subscription_required` while access is blocked.

No mobile application source is present in this web repository. The following handler/store changes and device acceptance test must be implemented in the app; backend tests do not verify the mobile UI.

| Response from subscription status | Required handler/store behavior |
| --- | --- |
| `200`, `state=blocked`, `is_entitled=false` | Atomically replace the entire cached subscription for the current account; immediately replace Active with Blocked and show the supplied message/reason. Keep service features disabled. |
| `200`, `is_entitled=false`, `state=none/expired` | Replace cached Active with the new state; keep service features disabled. |
| `200`, entitled active/trial | Replace the account's cached state and mark it freshly verified. |
| `401 not_authenticated` or `401 token_not_valid` | Use the existing refresh flow below, once, then retry status with the new Bearer access token. Never turn a 401 into a subscription result. |
| `401 user_inactive` or `401 user_not_found` | Clear the session and private subscription cache; show sign-in/account-unavailable. |
| `403 account_inactive` or `403 restaurant_inactive` | Clear cached Active and disable features; show the inactive-account/restaurant message. Do not retry refresh for these codes. |
| Transport failure, timeout or `5xx` (including `503 subscription_status_unavailable`) | Set freshness to unverified and show "Current subscription status could not be verified". Cached history must not be displayed as confirmed Active or enable features. |

Refresh uses `POST /api/business-menu/token/refresh/` with JSON `{"refresh":"<stored-refresh-token>"}`. `/api/business-menu/refresh/` is its existing alias. Send the stored access token as `Authorization: Bearer <access>` on status requests. Persist both `access` and the rotated `refresh` from a successful refresh response. Share one in-flight refresh across concurrent 401s; exclude the refresh request from its own retry interceptor. If refresh fails or the single status retry still returns 401, clear tokens and all private subscription state and show sign-in. Auth failures retain 401 on status and project refresh routes; other legacy API routes retain their existing mapping.

The store should keep freshness separately from the cached payload. Only a successful status response for the current account may set freshness to verified. Discard late responses after logout/account change and clear private state on either action. Display Active and enable features only from a verified response with `is_entitled=true` and `access_blocked=false`.

Device acceptance: start with an active manual subscription, fetch status, perform Block all in the admin panel, and refresh status with the same valid JWT. Expect 200/blocked, no Active display and protected APIs still denied. Unblock with a valid entitlement should restore access; unblock after expiry should return 200/expired with `is_entitled=false`. Also test expired JWT -> successful refresh -> fresh blocked status, failed refresh -> sign-in with no private cache, both inactive 403 codes, and network/503 -> unverified display. This flow needs no Apple purchase.

## Not implemented in this phase

- Stripe renewal, failure, cancellation, refund, and Customer Portal lifecycle
- Global subscription permission enforcement
