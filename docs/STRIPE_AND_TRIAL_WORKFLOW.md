# Stripe & Trial Workflow

## 1. Environment variables

Copy your keys into `.env` (do **not** commit `.env`):

```env
# Stripe (use your test/live keys)
STRIPE_PUBLISHABLE_KEY=pk_test_51TA6qLIR2dUpjRYD...
STRIPE_SECRET_KEY=sk_test_51TA6qLIR2dUpjRYD...
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_PRICE_ID_ANNUAL=price_xxx
```

- **STRIPE_PUBLISHABLE_KEY** / **STRIPE_SECRET_KEY**: from Stripe Dashboard → Developers → API keys.
- **STRIPE_WEBHOOK_SECRET**: after creating a webhook endpoint (see below).
- **STRIPE_PRICE_ID_ANNUAL**: create a one-time Product and Price in Stripe Dashboard (e.g. “Annual subscription”) and paste the **Price ID** (starts with `price_`).

## 2. Webhook (Stripe Dashboard)

1. Developers → Webhooks → Add endpoint.
2. URL: `https://your-domain.com/api/business-menu/api/stripe-webhook/`
3. Events: `checkout.session.completed`, `account.updated` (for Connect).
4. Copy the **Signing secret** into `STRIPE_WEBHOOK_SECRET`.

## 3. Platform workflow (summary)

| Step | Where | What happens |
|------|--------|---------------|
| 1. Signup | Web `/auth/register/` | Restaurant name, owner name, email, phone, password, country, city. Creates User + BusinessAdmin + Restaurant. **12-day trial** starts; no payment. |
| 2. Trial | App | User can use app (orders, menu, settings). **Stripe Connect is not active** during trial. |
| 3. Trial end | Cron | Run daily: `python manage.py send_trial_ended_emails`. Sets `payment_status=unpaid` and sends email with subscribe link. |
| 4. Subscribe | Web `/business-menu/subscribe/?admin_id=X` | User clicks “Subscribe” → Stripe Checkout (card, Apple Pay, Google Pay). |
| 5. After payment | Webhook | `checkout.session.completed` → set `payment_status=paid`, `subscription_ends_at=now+1 year`. |
| 6. Connect | After subscribe | User can click “Connect Stripe to receive payments” → Stripe Connect onboarding (IBAN, KYC). `stripe_account_id` saved. |
| 7. Customer payments | (Future) | When implementing order payment, create PaymentIntent with restaurant’s `stripe_account_id` so money goes to restaurant. |

## 4. API endpoints

- **POST** `/api/business-menu/signup/` — Restaurant owner signup (starts trial).
- **POST** `/api/business-menu/api/create-checkout-session/` — Body: `{"admin_id": 123}`. Returns `{ "url": "https://checkout.stripe.com/..." }`.
- **POST** `/api/business-menu/api/create-connect-link/` — Body: `{"admin_id": 123}`. For paid admins only. Returns `{ "url": "https://connect.stripe.com/..." }`.
- **POST** `/api/business-menu/api/stripe-webhook/` — Stripe webhooks (no auth; verified by signature).

## 5. Login rules

- **paid**: always allowed.
- **trial** and `trial_ends_at` in the future: allowed.
- **trial** expired or **unpaid**: 403, message “Your trial has ended. Please subscribe.” and `subscribe_url` in response.

## 6. Trial-end emails (cron)

```bash
# Daily
python manage.py send_trial_ended_emails
```

Optional: `SITE_URL` in `.env` (e.g. `https://preismenu.de`) so the email link uses the correct domain.

---

## 7. خطای دیتابیس / sequence

### `column "trial_ends_at" does not exist`

اگر این خطا را می‌بینید یعنی مایگریشن مربوط به trial و Stripe روی دیتابیس اجرا نشده است. حتماً مایگریشن را اجرا کنید:

```bash
python manage.py migrate business_menu
```

اگر روی سرور (مثلاً Scalingo) هستید، معمولاً مایگریشن در مرحلهٔ deploy اجرا می‌شود؛ اگر دستی اجرا می‌کنید یک بار همین دستور را روی دیتابیس production بزنید.

### `duplicate key value violates unique constraint "auth_user_pkey"` (در signup)

اگر دیتابیس را قبلاً import کرده‌اید، sequence جدول `auth_user` ممکن است خراب باشد. دو راه‌حل:

1. **خودکار:** در هر درخواست signup، قبل از ساخت User تابع `fix_auth_and_signup_sequences()` اجرا می‌شود (در `config.sequence_utils`) و sequenceهای لازم را درست می‌کند.
2. **دستی:** یک بار روی سرور اجرا کنید:  
   `scalingo --app qrmenu run "python manage.py fix_migrations_sequence"`
