# 📋 خلاصه API های Business Menu - مطابق دیاگرام

## ✅ API های ساخته شده

### 1️⃣ Authentication (احراز هویت)

#### ارسال OTP
```
POST /api/business-menu/send-otp/
Body: {"phone": "+491234567890"}
```

#### ورود با OTP
```
POST /api/business-menu/login/
Body: {
    "phone": "+491234567890",  // یا "number"
    "code": "123456"            // یا "opCode"
}
Response: {
    "access": "JWT_TOKEN",
    "refresh": "REFRESH_TOKEN",
    "admin": {...}
}
```

---

### 2️⃣ افزودن آیتم منو (Add Menu Item)

طبق دیاگرام: `post:{ images[]:string price:string present:string انبار-tank details }`

```
POST /api/business-menu/menu-items/
Authorization: Bearer {access_token}
Content-Type: multipart/form-data

Body:
{
    "restaurant": 1,
    "name": "پیتزا مارگاریتا",
    "price": "12.50",              // ✅ price:string
    "present": "true",              // ✅ present:string
    "stock": "موجود",               // ✅ انبار-tank
    "details": "توضیحات",          // ✅ details
    "images": [file1, file2, ...]  // ✅ images[]:string
}
```

**فیلدهای مطابق دیاگرام:**
- ✅ `images[]:string` → لیست عکس‌ها
- ✅ `price:string` → قیمت
- ✅ `present:string` → موجود بودن ("true" یا "false")
- ✅ `انبار-tank` → `stock` (موجودی)
- ✅ `details` → توضیحات

---

### 3️⃣ دریافت منو (Get Menu)

طبق دیاگرام: `get menu`

```
GET /api/business-menu/get-menu/?restaurant_id=1

Response:
{
    "success": true,
    "restaurant": {...},
    "menu_items": [
        {
            "id": 1,
            "name": "پیتزا",
            "price": "12.50",
            "present": true,
            "stock": "موجود",
            "details": "توضیحات",
            "images": ["url1", "url2"]
        }
    ]
}
```

---

### 4️⃣ تولید QR کد

```
POST /api/business-menu/generate-qr/
Authorization: Bearer {access_token}
Body: {"restaurant_id": 1}

Response: {
    "qr_code": {
        "token": "...",
        "menu_url": "https://domain.com/business-menu/qr/{token}/",
        "qr_image_url": "https://domain.com/business-menu/qr/{token}.png"
    }
}
```

---

### 5️⃣ نمایش منو (هنگام اسکن QR)

```
GET /business-menu/qr/{token}/
```

این صفحه HTML منو رستوران را نمایش می‌دهد.

---

## 🔄 تطابق با دیاگرام

| دیاگرام | API | وضعیت |
|---------|-----|-------|
| `method:Post` با `number` و `opCode` | `POST /api/business-menu/login/` | ✅ |
| `post:{ images[]:string price:string present:string انبار-tank details }` | `POST /api/business-menu/menu-items/` | ✅ |
| `get menu` | `GET /api/business-menu/get-menu/` | ✅ |
| `url:image` | عکس‌ها در `images[]` | ✅ |
| `اپلود /qr` | `POST /api/business-menu/generate-qr/` | ✅ |

---

## 📱 مثال استفاده کامل

### مرحله 1: ارسال OTP
```bash
curl -X POST http://localhost:8000/api/business-menu/send-otp/ \
  -H "Content-Type: application/json" \
  -d '{"phone": "+491234567890"}'
```

### مرحله 2: ورود با OTP
```bash
curl -X POST http://localhost:8000/api/business-menu/login/ \
  -H "Content-Type: application/json" \
  -d '{"phone": "+491234567890", "code": "123456"}'
# دریافت access_token
```

### مرحله 3: ایجاد رستوران
```bash
curl -X POST http://localhost:8000/api/business-menu/restaurants/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "رستوران تست", "description": "...", "address": "...", "phone": "+491234567890"}'
```

### مرحله 4: افزودن آیتم منو (مطابق دیاگرام)
```bash
curl -X POST http://localhost:8000/api/business-menu/menu-items/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "restaurant=1" \
  -F "name=پیتزا مارگاریتا" \
  -F "price=12.50" \
  -F "present=true" \
  -F "stock=موجود" \
  -F "details=پیتزا با پنیر و گوجه" \
  -F "images=@image1.jpg" \
  -F "images=@image2.jpg"
```

### مرحله 5: دریافت منو
```bash
curl http://localhost:8000/api/business-menu/get-menu/?restaurant_id=1
```

### مرحله 6: تولید QR کد
```bash
curl -X POST http://localhost:8000/api/business-menu/generate-qr/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"restaurant_id": 1}'
```

---

## ✅ همه API ها آماده هستند!

تمام API های مورد نیاز طبق دیاگرام ساخته شده‌اند و آماده استفاده هستند.
