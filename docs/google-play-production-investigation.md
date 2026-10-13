# Google Play Production investigation — 2026-10-14

The live Google catalog and backend agree. They differ from the reported Android product IDs. A backend configuration change alone cannot fix a client querying products that do not exist in this Play app.

## Verified production evidence

Read-only Scalingo probes against `qrmenu`, release `fdc114d6f245b09321c25d9480d81d8cb13ef785`, matched fetched `origin/main`. The web container was running. No purchase, acknowledgement, account update, or Console change was performed.

| Setting / catalog | Observed value |
| --- | --- |
| Google package | `com.menupanelcli` |
| Google backend allowlist | `de.mybonusberlin.monthly` → `monthly`; `de.mybonusberlin.yearly` → `yearly` |
| Google subscription catalog | HTTP 200; exactly the same two products; no next page |
| Google base plans | Both `ACTIVE`; new-subscriber regional availability only `DE` |
| Apple bundle | `com.qrmenu.new` |
| Apple configured products | `de.preismenu.monthly,de.preismenu.yearly` |
| Test entitlements | Disabled |
| Google provider records / events | 0 / 0 |

`check_google_play_subscription_config --check-credentials` passed mapping structure, encryption-key structure, credential loading, OAuth refresh, and RTDN configuration structure. Catalog read additionally proves the credential can read subscriptions for this package. It does **not** prove purchase verification/acknowledgement permissions or RTDN delivery. Service-account keys and all tokens were kept out of output.

Reported incident: 2026-10-14 01:41 Tehran = 2026-10-13 22:11 UTC. A recent 1000-line log sample contained 12 subscription-status GET 200 and 6 GET 401, and no matched POST to Google verify or restore. The sample is not a complete incident audit. No successful persisted Google purchases exist; failed or unreceived requests cannot be inferred from that count. Existing expected Google API failures had no structured server log.

## Code and response contract

- `business_menu/urls.py`: authenticated status, Google verify, restore, and RTDN routes under `/api/business-menu/`.
- `business_menu/views.py::AdminSubscriptionView`: GET (compatibility POST) serializes entitlement; HTTP 200 alone says nothing about product lookup.
- `business_menu/serializers.py::BusinessMenuSubscriptionSerializer` and `subscription_services.py::resolve_subscription_entitlement`: `state`, `is_entitled`, `plan`, `provider`, expiry, renewal, trial, `purchasable_in_app`, `manage_url`, message, provider history, source, ownership UUID, decision and access-block fields. There is no purchasable product catalog, Android package, base-plan allowlist, Play credentials, or store price. Nested `providers[].product_id` describes recorded purchases. `app_account_token` is an ownership binding, not a login credential.
- `config/settings.py`: dotenv loads without overriding existing environment; Android values come from `GOOGLE_PLAY_*`, Apple from separate `APPLE_*`. There is no default copying Apple products to Android.
- `subscription_services.py::_google_product_allowlist`: maps exact product IDs to allowed base-plan IDs. `plan_from_product_id` recognizes the monthly/yearly suffix of both observed Android IDs.
- `verify_google_play_subscription`: uses server package and purchase token in Android Publisher `purchases.subscriptionsv2.get`, validates product/base plan/state/expiry, then binds ownership and persists. The app's claimed product is not authoritative.
- `_google_authorized_session`, token encryption, account binding, acknowledgement, and Pub/Sub settings operate after purchase or on notifications. They are not used by this backend to supply `queryProductDetailsAsync` inputs. Status fields can affect app UI branching; that requires inspection of the real response and app code.

No Android/iOS app source, Gradle configuration, or purchase-library dependency was found in the tracked workspace. The root package.json builds Tailwind; tracked APKs are not app source. The old Debug responseCode=-1 is not evidence for this Production failure.

## Changes

Dedicated `business_menu.google_play` logging records verify/restore receipt, expected verify error code/HTTP status, and Google API operation, HTTP status and duration or configuration/transport failure. It never logs provider URL (contains purchase token), headers, body, exception text, credentials, email or account identifiers. Unexpected verify errors no longer print a potentially sensitive exception traceback. Payment decisions, allowlists and Apple settings are unchanged.

## Handoff to the app / Play Console team

1. For the installed Production build, provide applicationId, versionName/versionCode, installer source, purchase wrapper version and resolved native Billing Library version. Confirm this is the Play-installed `com.menupanelcli` build.
2. Log requested product IDs and type (`SUBS`), and where those IDs came from. If they are `de.preismenu.*`, they do not match the live Android catalog. Either use the existing Android IDs in an app release, or deliberately create/configure the intended products in Play Console and update the backend allowlist to verified base-plan IDs. Do not rename or change Apple products to solve Android.
3. Log Billing `startConnection`, `onBillingSetupFinished` responseCode/debugMessage, isReady, disconnect/reconnect/retry, then query start/end and duration. Query only after a successful connection. Preserve the Production build identity and timestamps on each diagnostic run.
4. Log query responseCode/debugMessage, requested and returned product IDs, returned count, offer/base-plan IDs, price-phase count, formatted prices/currency and eligibility. On versions supporting `UnfetchedProduct`, log its product ID and status code. Do not log offer tokens, purchase tokens, auth headers or account identifiers.
5. Check Play account country (not merely device locale/IP): the inspected plans enable new subscribers only in DE. Check app country distribution, active base plans/prices, offer eligibility and current Play Store/services. Product presence alone is not proof this user can buy it.
6. After a successful purchase, pass the API's ownership UUID as `obfuscatedAccountId`, then POST purchaseToken securely to `/api/business-menu/admin/subscription/google/verify/`. Log only endpoint, timestamp, HTTP status, response code and correlation ID if available. Do not acknowledge twice or grant access before server verification.

Official integration reference: https://developer.android.com/google/play/billing/integrate

## Missing real account response and versionCode

No authorized session for the affected account was available. No token was fabricated and no user was impersonated. To capture the real response, the app team should instrument its existing authenticated status request, inspect JSON locally and export only `state`, `is_entitled`, `plan`, `provider`, `purchasable_in_app`, `decision_reason`, `access_blocked` and sanitized provider fields. Remove `app_account_token`, all emails/account IDs, headers and cookies; never paste JWTs. Include HTTP status, UTC timestamp and Cache-Control. A tester may obtain versionName/versionCode locally using `adb shell dumpsys package com.menupanelcli` and share only those fields, or read the matching Production artifact in Play Console.

The exact Production query inputs and Billing error remain unverified. If IDs or Billing logic are compiled incorrectly, a new app release is required. If only Console region/plan availability is wrong, a Console correction may suffice. The logging deployment helps diagnosis but does not fix catalog lookup by itself.

## Validation before release

52 Google, shared subscription and admin-subscription tests passed on isolated SQLite test storage; Django system checks passed. Diagnostic tests cover Google HTTP 200/403/429/503 and transport/configuration exceptions, checking that URLs, purchase tokens and exception secrets are absent from logs. `git diff --check` passed. No schema or production-data changes are part of this release.
