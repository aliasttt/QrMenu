# Mobile Admin Orders API

Base URL:

```text
https://preismenu.de/api/business-menu
```

All admin order endpoints require JWT:

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

## 1. Login

```http
POST /api/business-menu/login/
```

Body:

```json
{
  "email": "admin@example.com",
  "password": "password"
}
```

Use `access` from the response as the Bearer token.

## 2. Get All Orders

```http
GET /api/business-menu/admin/orders/
```

Optional filter:

```http
GET /api/business-menu/admin/orders/?status=paid
```

Returns the latest 200 finalized orders for the logged-in admin restaurant.
Online orders are returned only after customer details are completed.

Response:

```json
{
  "restaurant_id": 2,
  "restaurant_name": "serdal doner",
  "count": 1,
  "orders": [
    {
      "id": 20,
      "status": "paid",
      "total_amount": "25.00",
      "currency": "EUR",
      "service_type": "pickup",
      "payment_method": "online",
      "table_number": "",
      "notes": "Customer: Ali Asadi\nPhone: +905340382335\nAddress: Berlin ...",
      "scheduled_for": null,
      "created_at": "2026-07-06T18:22:10.123456+00:00",
      "updated_at": "2026-07-06T18:25:11.123456+00:00",
      "items": [
        {
          "menu_item_id": 123,
          "name": "Iskender kebab ve Adana",
          "price": "25.00",
          "quantity": 1
        }
      ],
      "customer": {
        "id": 45,
        "name": "Ali Asadi",
        "phone": "+905340382335",
        "email": "",
        "notes": "Address: Berlin ..."
      },
      "payment": {
        "stripe_payment_intent_id": "pi_...",
        "stripe_order_id": ""
      },
      "actions": {
        "can_mark_preparing": true,
        "can_mark_completed": false,
        "can_cancel": true
      }
    }
  ]
}
```

## 3. Get New Orders

```http
GET /api/business-menu/admin/orders/new/
```

Use this for the "New Orders" screen.

Includes:

- cash orders with `status=pending`
- online orders with `status=paid`

Response shape is the same as `GET /admin/orders/`.

## 4. Get One Order

```http
GET /api/business-menu/admin/orders/<order_id>/
```

Response is one order object:

```json
{
  "id": 20,
  "status": "paid",
  "total_amount": "25.00",
  "currency": "EUR",
  "service_type": "pickup",
  "payment_method": "online",
  "table_number": "",
  "notes": "Customer: Ali Asadi\nPhone: +905340382335\nAddress: Berlin ...",
  "scheduled_for": null,
  "created_at": "2026-07-06T18:22:10.123456+00:00",
  "updated_at": "2026-07-06T18:25:11.123456+00:00",
  "items": [],
  "customer": {
    "id": 45,
    "name": "Ali Asadi",
    "phone": "+905340382335",
    "email": "",
    "notes": "Address: Berlin ..."
  },
  "payment": {
    "stripe_payment_intent_id": "pi_...",
    "stripe_order_id": ""
  },
  "actions": {
    "can_mark_preparing": true,
    "can_mark_completed": false,
    "can_cancel": true
  }
}
```

## 5. Update Order Status

```http
PATCH /api/business-menu/admin/orders/<order_id>/
```

Body:

```json
{
  "status": "preparing"
}
```

Allowed statuses:

```text
preparing
completed
cancelled
paid
```

Response returns the full updated order object.

## Recommended Mobile Flow

1. Login and store `access`.
2. Call `GET /admin/orders/new/` for the main active/new orders screen.
3. Call `GET /admin/orders/` for full order history.
4. Call `GET /admin/orders/<id>/` when opening an order detail page.
5. Call `PATCH /admin/orders/<id>/` to move the order through statuses.

