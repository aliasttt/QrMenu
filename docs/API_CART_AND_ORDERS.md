# API سبد خرید و سفارش (Cart & Orders)

Base URL: **`/api/business-menu`**  
(مثال: `https://preismenu.de/api/business-menu`)

همهٔ اندپوینت‌های زیر **بدون احراز هویت** (AllowAny) هستند و با **Session** کار می‌کنند. برای شناسایی رستوران در هر درخواست باید یکی از دو پارامتر را بفرستی:

| پارامتر | نوع | توضیح |
|---------|-----|--------|
| **token** | string | توکن یکتای QR منو (از اپ/لینک منو) |
| **restaurant_id** | integer | شناسهٔ رستوران |

---

## 1. سبد خرید (Cart)

### 1.1 دریافت سبد — GET `/cart/`

لیست آیتم‌های سبد و جمع کل را برمی‌گرداند.

**درخواست**

- **Method:** `GET`
- **URL:** `/api/business-menu/cart/`
- **Query (یا Body در صورت استفاده از POST-style):**
  - `token` (string) **یا** `restaurant_id` (integer) — **اجباری**

**مثال درخواست (Query)**

```
GET /api/business-menu/cart/?restaurant_id=2
GET /api/business-menu/cart/?token=abc123def456
```

**پاسخ موفق (200 OK)**

```json
{
  "restaurant_id": 2,
  "items": [
    {
      "menu_item_id": 5,
      "name": "Beyti kebap",
      "price": "18.50",
      "quantity": 1
    }
  ],
  "subtotal": 18.50,
  "total": 18.50
}
```

**پاسخ خطا**

- `400` — `{"detail": "Provide 'token' or 'restaurant_id'."}`
- `404` — `{"detail": "Invalid menu token."}` یا `{"detail": "Restaurant not found."}`

---

### 1.2 افزودن به سبد — POST `/cart/`

یک آیتم منو را با تعداد مشخص به سبد اضافه می‌کند (یا به تعداد همان آیتم اضافه می‌کند).

**درخواست**

- **Method:** `POST`
- **URL:** `/api/business-menu/cart/`
- **Headers:** `Content-Type: application/json`
- **Body (JSON):**

| فیلد | نوع | اجباری | توضیح |
|------|-----|--------|--------|
| token | string | خیر* | توکن QR منو |
| restaurant_id | integer | خیر* | شناسه رستوران |
| menu_item_id | integer | **بله** | شناسه آیتم منو |
| quantity | integer | خیر | تعداد (پیش‌فرض: 1)، حداقل 1 |

\* یکی از `token` یا `restaurant_id` حتماً لازم است.

**مثال Body**

```json
{
  "restaurant_id": 2,
  "menu_item_id": 5,
  "quantity": 1
}
```

**پاسخ موفق (200 OK)**  
همان ساختار GET سبد (لیست آیتم‌ها + subtotal + total).

**پاسخ خطا**

- `400` — `{"detail": "menu_item_id is required."}` یا عدم ارسال token/restaurant_id
- `404` — `{"detail": "Menu item not found or not available."}`

---

### 1.3 تغییر تعداد آیتم — PATCH `/cart/`

تعداد یک آیتم در سبد را عوض می‌کند. اگر `quantity` برابر 0 باشد، آیتم از سبد حذف می‌شود.

**درخواست**

- **Method:** `PATCH`
- **URL:** `/api/business-menu/cart/`
- **Headers:** `Content-Type: application/json`
- **Body (JSON):**

| فیلد | نوع | اجباری | توضیح |
|------|-----|--------|--------|
| token | string | خیر* | توکن QR منو |
| restaurant_id | integer | خیر* | شناسه رستوران |
| menu_item_id | integer | **بله** | شناسه آیتم منو |
| quantity | integer | **بله** | تعداد جدید (عدد صحیح ≥ 0) |

**مثال Body**

```json
{
  "restaurant_id": 2,
  "menu_item_id": 5,
  "quantity": 3
}
```

**پاسخ موفق (200 OK)**  
همان ساختار GET سبد.

**پاسخ خطا**

- `400` — `{"detail": "menu_item_id is required."}` یا `{"detail": "quantity must be a non-negative integer."}`
- `404` — `{"detail": "Item not in cart."}`

---

### 1.4 حذف آیتم از سبد — DELETE `/cart/`

یک آیتم را کاملاً از سبد حذف می‌کند.

**درخواست**

- **Method:** `DELETE`
- **URL:** `/api/business-menu/cart/`
- **Headers:** `Content-Type: application/json` (اختیاری برای Body)
- **Body (JSON) یا Query:**

| فیلد | نوع | اجباری | توضیح |
|------|-----|--------|--------|
| token | string | خیر* | توکن QR منو |
| restaurant_id | integer | خیر* | شناسه رستوران |
| menu_item_id | integer | **بله** | شناسه آیتم منو |

**مثال Body**

```json
{
  "restaurant_id": 2,
  "menu_item_id": 5
}
```

**مثال Query**

```
DELETE /api/business-menu/cart/?restaurant_id=2&menu_item_id=5
```

**پاسخ موفق (200 OK)**  
همان ساختار GET سبد (بدون آن آیتم).

**پاسخ خطا**

- `400` — `{"detail": "menu_item_id is required."}` یا `{"detail": "Invalid menu_item_id."}`
- `404` — `{"detail": "Item not in cart."}`

---

## 2. گزینه‌های سفارش رستوران (Order Options)

### 2.1 دریافت گزینه‌ها — GET `/order-options/`

برای نمایش/مخفی کردن گزینه‌های «دلیوری»، «پرداخت نقد» و «پرداخت آنلاین» در فرانت/اپ استفاده می‌شود.

**درخواست**

- **Method:** `GET`
- **URL:** `/api/business-menu/order-options/`
- **Query:**
  - `token` (string) **یا** `restaurant_id` (integer) — **اجباری**

**مثال**

```
GET /api/business-menu/order-options/?restaurant_id=2
GET /api/business-menu/order-options/?token=abc123
```

**پاسخ موفق (200 OK)**

```json
{
  "restaurant_id": 2,
  "has_delivery": false,
  "allow_payment_cash": true,
  "allow_payment_online": true
}
```

- **has_delivery:** اگر `false` باشد، گزینه «سفارش با دلیوری» را نشان نده.
- **allow_payment_cash** / **allow_payment_online:** فقط روش‌های پرداختی که `true` هستند را فعال کن.

**پاسخ خطا:** همان 400/404 با `detail` مناسب.

---

## 3. ثبت سفارش (Create Order)

### 3.1 ثبت سفارش — POST `/orders/`

سبد فعلی (Session) را به عنوان یک سفارش ثبت می‌کند. بعد از ثبت موفق، سبد خالی می‌شود.

**درخواست**

- **Method:** `POST`
- **URL:** `/api/business-menu/orders/`
- **Headers:** `Content-Type: application/json`
- **Body (JSON):**

| فیلد | نوع | اجباری | توضیح |
|------|-----|--------|--------|
| token | string | خیر* | توکن QR منو |
| restaurant_id | integer | خیر* | شناسه رستوران |
| service_type | string | خیر | `dine_in` \| `pickup` \| `delivery` (پیش‌فرض: `dine_in`) |
| payment_method | string | خیر | `cash` \| `online` (پیش‌فرض: `cash`) |
| table_number | string | شرطی | برای **Dine In** اجباری؛ برای بقیه اختیاری |
| notes | string | خیر | یادداشت سفارش |

\* یکی از `token` یا `restaurant_id` حتماً لازم است.

**قوانین اعتبارسنجی**

- اگر `service_type === "delivery"` و رستوران `has_delivery: false` داشته باشد → خطا.
- اگر `payment_method === "cash"` و رستوران `allow_payment_cash: false` → خطا.
- اگر `payment_method === "online"` و رستوران `allow_payment_online: false` → خطا.
- اگر `service_type === "dine_in"` و `table_number` خالی باشد → خطا.

**مثال Body**

```json
{
  "restaurant_id": 2,
  "service_type": "dine_in",
  "payment_method": "online",
  "table_number": "22",
  "notes": "بدون پیاز"
}
```

**پاسخ موفق (201 Created)**

```json
{
  "order_id": 42,
  "status": "pending",
  "total_amount": "18.50",
  "currency": "EUR",
  "service_type": "dine_in",
  "payment_method": "online",
  "table_number": "22"
}
```

**پاسخ خطا**

- `400` — مثلاً:
  - `{"detail": "Cart is empty."}`
  - `{"detail": "Invalid service_type. Use dine_in, pickup, or delivery."}`
  - `{"detail": "Delivery is not available for this restaurant."}`
  - `{"detail": "table_number is required for dine-in."}`
  - `{"detail": "Cash payment is not allowed."}` / `{"detail": "Online payment is not allowed."}`
- `404` — رستوران یا token نامعتبر

---

## 4. لیست سفارشات (Order List)

### 4.1 لیست سفارشات همین Session — GET `/orders/list/`

سفارشاتی که با همان Session مرورگر/کاربر برای این رستوران ثبت شده‌اند را برمی‌گرداند (حداکثر 50 مورد).

**درخواست**

- **Method:** `GET`
- **URL:** `/api/business-menu/orders/list/`
- **Query:**
  - `token` (string) **یا** `restaurant_id` (integer) — **اجباری**

**مثال**

```
GET /api/business-menu/orders/list/?restaurant_id=2
GET /api/business-menu/orders/list/?token=abc123
```

**پاسخ موفق (200 OK)**

```json
{
  "orders": [
    {
      "id": 42,
      "status": "در انتظار",
      "status_key": "pending",
      "total_amount": "18.50",
      "currency": "EUR",
      "service_type": "dine_in",
      "payment_method": "online",
      "table_number": "22",
      "created_at": "2026-03-09T12:00:00",
      "items": [
        {
          "menu_item_id": 5,
          "name": "Beyti kebap",
          "price": "18.50",
          "quantity": 1
        }
      ]
    }
  ]
}
```

**پاسخ خطا:** همان 400/404 با `detail` مناسب.

---

## خلاصهٔ اندپوینت‌ها

| متد | مسیر | توضیح |
|-----|------|--------|
| GET | `/api/business-menu/cart/` | دریافت سبد (با `token` یا `restaurant_id`) |
| POST | `/api/business-menu/cart/` | افزودن به سبد (`menu_item_id`, `quantity`, و یکی از token/restaurant_id) |
| PATCH | `/api/business-menu/cart/` | تغییر تعداد (`menu_item_id`, `quantity`) |
| DELETE | `/api/business-menu/cart/` | حذف آیتم (`menu_item_id`) |
| GET | `/api/business-menu/order-options/` | گزینه‌های دلیوری و پرداخت (با `token` یا `restaurant_id`) |
| POST | `/api/business-menu/orders/` | ثبت سفارش (service_type, payment_method, table_number در صورت Dine In, notes) |
| GET | `/api/business-menu/orders/list/` | لیست سفارشات همین Session |

**نکته:** اگر از دامنهٔ همان سایت (مثلاً preismenu.de) درخواست بزنی، Session از طریق Cookie ارسال می‌شود. برای اپ موبایل یا دامنهٔ دیگر باید Session/Cookie را طبق معماری بکند مدیریت کنی یا بعداً با توکن کاربر جایگزین شود.
