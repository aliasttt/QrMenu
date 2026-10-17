# Business account deletion

`DELETE /api/business-menu/admin/account/` accepts a Bearer access token and
JSON `{"password": "current password"}`. Missing/empty/non-string passwords
return `400 password_required`; a wrong password returns `403 invalid_password`.
Invalid, expired, missing, or refresh tokens return DRF `401`. Successful deletion
returns an empty `204`. A valid signed access token for an already removed User
can repeat this endpoint and receive `204`; it cannot use other account APIs.
An authenticated User without a BusinessAdmin receives `403 business_account_required`.

Deletion runs in one database transaction. It blacklists all recorded refresh
tokens, erases their stored token bodies, removes database sessions, pending
business signup verifications, the BusinessAdmin, Restaurant and cascaded
operational data, and the User and its related profiles/reset codes/activity.
Every refresh route also checks that its User still exists and is active under
a row lock. This closes the legacy/untracked and rotated-token gap in SimpleJWT
5.3.1. Passwords, access tokens and refresh tokens are never logged by deletion.

ProviderSubscription and ProviderEvent records survive with a NULL account.
Their purchase identifiers remain reserved, so another account cannot claim a
deleted account's purchase. Removing BusinessAdmin also removes its
subscription_account_token and Stripe Connect link. No Stripe account deletion
or subscription cancellation API is called. Store renewal remains the customer's
responsibility. Notifications cannot recreate a removed account.

Before operational deletion, RetainedFinancialRecord copies only order status,
amount, currency, payment/service type, date, and payment/refund provider references.
It has no account/restaurant/customer relation. Free text, names, contact details,
session keys, locations, item JSON and reservation/customer records are erased.
Provider references remain restricted accounting identifiers for refunds, not
public profile data. No new public endpoint exposes retained records.

This is a technical retention boundary, not certification that a reduced record
replaces every statutory accounting document. The repository has no invoice model.
The business must retain any separately issued invoices in its accounting system
and set its applicable retention/hold policy there. German AO section 147 uses
different periods by document class and permits extensions for unresolved tax
matters: https://www.gesetze-im-internet.de/ao_1977/__147.html . This endpoint does
not delete documents in external accounting or payment-provider systems.

Media cleanup uses a durable AccountMediaDeletion queue created in the same
transaction. After commit it immediately removes stored logos, gallery uploads,
dish/package images, floor plans and linked/owned Cloudinary images; Cloudinary
deletion requests CDN invalidation. Failed jobs are retried hourly by
`python manage.py purge_account_media` through cron.json. Only job IDs are logged.
Shared Cloudinary images referenced by another restaurant are preserved.
Cloudinary uploads now record the authenticated owner even before attachment.
Historical anonymous uploads that were never attached have no recoverable account
ownership and cannot safely be attributed or deleted by this endpoint. Cached
copies and external image hosts remain subject to their own expiry/deletion rules.

## Release

Take and verify a fresh database backup before applying migrations. Before the
new application starts, enable the blacklist app for the migration one-off and
apply token_blacklist migrations and business_menu 0038/0039. These are additive
schema changes; subscription.account becomes nullable. Then deploy main and
verify the running commit, migration markers, scheduled cleanup and web health.
Do not roll back the nullable-account migration after any account has been deleted.

Validation must use disposable accounts only. Never send a deletion request for
a real restaurant as a deployment smoke test.
