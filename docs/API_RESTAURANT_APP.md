# API اپ رستوران (فقط اندپوینت‌های اپ)

Base URL: **`/api/business-menu`**

اپ رستوران **سبد خرید را مدیریت نمی‌کند**. مشتری از **وب** سفارش می‌دهد و پرداخت می‌کند؛ سفارش در دیتابیس ذخیره می‌شود. اپ فقط:

1. **لیست سفارشات** را می‌خواند (مثلاً هر ۵ ثانیه)
2. وقتی سفارش جدید آمد → **New Order** نشان می‌دهد
3. رستوران **Accept / Reject / Prepare / Complete** می‌زند → با API وضعیت را به سرور می‌فرستد

---

## احراز هویت اپ

همهٔ درخواست‌های اپ باید با **JWT** (توکن بعد از لاگین ادمین با OTP) ارسال شوند:

```
Authorization: Bearer <access_token>
```

رستوران از روی توکن ادمین تشخیص داده می‌شود؛ نیازی به `restaurant_id` یا `token` منو نیست.

**زبان پاسخ‌ها:** همهٔ مقادیر در پاسخ API به **انگلیسی** هستند (مثلاً `status`: `"pending"`, `"preparing"`, `"cancelled"`).

---

## ۱. لیست سفارشات جدید (New Order)

برای بخش **New Order** در اپ — فقط سفارشاتی که هنوز قبول/رد نشده‌اند (`status = pending`).

| متد | مسیر |
|-----|------|
| **GET** | **`/api/business-menu/admin/orders/new/`** |

**Headers:** `Authorization: Bearer <access_token>`

**پاسخ موفق (200 OK):** همان ساختار لیست سفارشات، ولی فقط سفارشات با وضعیت **pending** (جدید).

```json
{
  "restaurant_id": 2,
  "restaurant_name": "نام رستوران",
  "orders": [
    {
      "id": 101,
      "status": "pending",
      "service_type": "delivery",
      "payment_method": "cash",
      "table_number": "",
      "notes": "",
      "total_amount": "240.00",
      "currency": "EUR",
      "created_at": "2026-03-09T12:30:00",
      "items": [{"menu_item_id": 5, "name": "Pizza", "price": "12.00", "quantity": 2}]
    }
  ]
}
```

اپ می‌تواند این را مثلاً هر ۵ ثانیه صدا بزند؛ اگر `orders.length > 0` → **New Order** نشان بده.

---

## ۲. لیست همه سفارشات

برای لیست کامل سفارشات (همه وضعیت‌ها).

| متد | مسیر |
|-----|------|
| **GET** | **`/api/business-menu/admin/orders/`** |

**Headers:**

```
Authorization: Bearer <access_token>
```

**بدن درخواست:** ندارد (بدون Query و Body).

**پاسخ موفق (200 OK):**

```json
{
  "restaurant_id": 2,
  "restaurant_name": "نام رستوران",
  "orders": [
    {
      "id": 101,
      "status": "pending",
      "service_type": "delivery",
      "payment_method": "cash",
      "table_number": "",
      "notes": "بدون پیاز",
      "total_amount": "240.00",
      "currency": "EUR",
      "created_at": "2026-03-09T12:30:00",
      "items": [
        {
          "menu_item_id": 5,
          "name": "Pizza",
          "price": "12.00",
          "quantity": 2
        }
      ]
    }
  ]
}
```

برای نمایش در اپ می‌توانی از هر سفارش استفاده کنی:
- `id` — شناسه سفارش
- `service_type` — `dine_in` | `pickup` | `delivery`
- `payment_method` — `cash` | `online`
- `status` — English key: `pending` | `paid` | `preparing` | `completed` | `cancelled` | `refunded`
- `items` — آرایه با `name`, `quantity`, `price`, `menu_item_id`
- `total_amount` — مبلغ کل (رشته)
- `created_at` — زمان ثبت
- `table_number` — فقط برای Dine In
- `notes` — یادداشت مشتری

**پاسخ خطا:**
- `401` — توکن نامعتبر یا منقضی
- `403` — `{"detail": "Business admin not found."}`
- `404` — `{"detail": "Restaurant not found for this admin."}`

---

## ۳. تنظیمات سفارش (از اپ → وب)

این تنظیمات را **اپ** می‌خواند و از **اپ** ست می‌کند؛ **وب** (صفحه منو) همان مقادیر را می‌خواند و به مشتری نشان می‌دهد (دلیوری داره یا نه، پرداخت نقد/آنلاین).

### ۳.۱ خواندن تنظیمات — GET `/admin/settings/`

| متد | مسیر |
|-----|------|
| **GET** | **`/api/business-menu/admin/settings/`** |

**Headers:** `Authorization: Bearer <access_token>`

**پاسخ موفق (200 OK):**

```json
{
  "restaurant_id": 2,
  "restaurant_name": "نام رستوران",
  "has_delivery": false,
  "allow_payment_cash": true,
  "allow_payment_online": true
}
```

| فیلد | توضیح |
|------|--------|
| **has_delivery** | آیا سفارش با دلیوری فعال است؟ اگر `false` باشد در وب گزینه دلیوری نشان داده نمی‌شود. |
| **allow_payment_cash** | پرداخت نقد (کش) فعال است؟ |
| **allow_payment_online** | پرداخت آنلاین (کارت) فعال است؟ |

### ۳.۲ ست کردن تنظیمات از اپ — PATCH `/admin/settings/`

| متد | مسیر |
|-----|------|
| **PATCH** | **`/api/business-menu/admin/settings/`** |

**Headers:** `Authorization: Bearer <access_token>` و `Content-Type: application/json`

**Body (JSON)** — هر فیلد اختیاری است، فقط همان‌هایی را بفرست که می‌خواهی عوض شوند:

```json
{
  "has_delivery": true,
  "allow_payment_cash": true,
  "allow_payment_online": true
}
```

**پاسخ موفق (200 OK):** همان ساختار GET با مقادیر به‌روز.

---

## ۴. به‌روزرسانی وضعیت سفارش (Accept / Reject / Prepare / Complete)

وقتی رستوران روی یک سفارش **Accept** یا **Reject** یا **Prepare** یا **Complete** زد، اپ این API را صدا بزند.

| متد | مسیر |
|-----|------|
| **PATCH** | **`/api/business-menu/admin/orders/<order_id>/`** |

**Headers:**

```
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Body (JSON):**

| فیلد | نوع | مقادیر مجاز |
|------|-----|-------------|
| **status** | string | `preparing` \| `cancelled` \| `completed` \| `paid` |

**نقش هر مقدار:**
- **Accept / شروع آماده‌سازی:** `"status": "preparing"`
- **Reject (لغو):** `"status": "cancelled"`
- **آماده تحویل / تکمیل:** `"status": "completed"`
- **پرداخت شده (مثلاً بعد از دریافت نقد):** `"status": "paid"`

**مثال:**

```http
PATCH /api/business-menu/admin/orders/101/
Content-Type: application/json
Authorization: Bearer <access_token>

{"status": "preparing"}
```

**پاسخ موفق (200 OK):**

```json
{
  "id": 101,
  "status": "preparing"
}
```

**پاسخ خطا:**
- `400` — `{"detail": "Invalid status. Use one of: preparing, cancelled, completed, paid"}`
- `401` — توکن نامعتبر
- `403` — ادمین پیدا نشد
- `404` — `{"detail": "Order not found."}` (سفارش مال این رستوران نیست یا وجود ندارد)

---

## خلاصه برای اپ

| کار اپ | متد | مسیر |
|--------|-----|------|
| **بخش New Order** — لیست سفارشات جدید (pending) | GET | `/api/business-menu/admin/orders/new/` |
| لیست همه سفارشات | GET | `/api/business-menu/admin/orders/` |
| **تنظیمات** — خواندن (دلیوری، کش، آنلاین) | GET | `/api/business-menu/admin/settings/` |
| **تنظیمات** — ست کردن از اپ | PATCH | `/api/business-menu/admin/settings/` با `{ "has_delivery", "allow_payment_cash", "allow_payment_online" }` |
| Accept / شروع آماده‌سازی | PATCH | `/api/business-menu/admin/orders/<order_id>/` با `{"status": "preparing"}` |
| Reject (لغو) | PATCH | با `{"status": "cancelled"}` |
| تکمیل / آماده تحویل | PATCH | با `{"status": "completed"}` |
| پرداخت شده (نقد) | PATCH | با `{"status": "paid"}` |

---

## نکته مهم: تفاوت با اندپوینت وب

| اندپوینت | برای چه کسی | توضیح |
|----------|-------------|--------|
| **GET /api/business-menu/orders/list/?restaurant_id=1** | **وب (مشتری)** | فقط سفارشات **همان Session** مشتری را برمی‌گرداند (لیست «سفارشات من» در سایت). اپ با این لیست **همه** سفارشات رستوران را نمی‌بیند. |
| **GET /api/business-menu/admin/orders/** | **اپ رستوران** | با **JWT ادمین** همه سفارشات رستوران را برمی‌گرداند. اپ باید فقط این را استفاده کند. |

اپ نباید `orders/list` با `restaurant_id` یا `token` صدا بزند؛ برای اپ فقط **admin/orders** با JWT درست است.
