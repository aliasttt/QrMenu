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

## Not implemented in this phase

- Stripe renewal, failure, cancellation, refund, and Customer Portal lifecycle
- Global subscription permission enforcement
