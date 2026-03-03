# Business Menu API Endpoints - مطابق دیاگرام

## 🔐 Authentication APIs

### 1. ارسال OTP (Send OTP)
```
POST /api/business-menu/send-otp/
Content-Type: application/json

Body:
{
    "phone": "+491234567890"  // یا "number" برای سازگاری با دیاگرام
}

Response:
{
    "success": true,
    "message": "کد OTP ارسال شد"
}
```

### 2. ورود با OTP (Login)
```
POST /api/business-menu/login/
Content-Type: application/json

Body:
{
    "phone": "+491234567890",  // یا "number"
    "code": "123456"            // یا "opCode"
}

Response:
{
    "success": true,
    "message": "ورود موفقیت‌آمیز بود",
    "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "admin": {
        "id": 1,
        "phone": "+491234567890",
        "name": "علی احمدی",
        "email": "ali@example.com"
    }
}
```

## 🍽️ Menu Management APIs

### 3. افزودن آیتم منو (Add Menu Item)
```
POST /api/business-menu/menu-items/
Authorization: Bearer {access_token}
Content-Type: multipart/form-data

Body (مطابق دیاگرام):
{
    "restaurant": 1,                    // ID رستوران
    "name": "پیتزا مارگاریتا",           // نام آیتم
    "price": "12.50",                    // قیمت (string)
    "present": "true",                   // موجود بودن (string: "true" یا "false")
    "stock": "موجود",                    // موجودی/انبار (string)
    "details": "پیتزا با پنیر و گوجه",   // توضیحات (details)
    "images": [file1, file2, ...]       // لیست عکس‌ها (images[]:string)
}

Response:
{
    "success": true,
    "message": "آیتم منو با موفقیت ایجاد شد",
    "menu_item": {
        "id": 1,
        "restaurant": 1,
        "name": "پیتزا مارگاریتا",
        "description": "پیتزا با پنیر و گوجه",
        "price": "12.50",
        "stock": "موجود",
        "is_available": true,
        "images": [
            {
                "id": 1,
                "image_url": "http://domain.com/media/business_menu/items/image1.jpg",
                "order": 0
            },
            {
                "id": 2,
                "image_url": "http://domain.com/media/business_menu/items/image2.jpg",
                "order": 1
            }
        ]
    }
}
```

**نکته:** در دیاگرام فیلدها به این صورت هستند:
- `images[]:string` → لیست عکس‌ها
- `price:string` → قیمت
- `present:string` → موجود بودن
- `انبار-tank` → موجودی/stock
- `details` → توضیحات

### 4. دریافت منو (Get Menu)
```
GET /api/business-menu/get-menu/?restaurant_id=1

Response:
{
    "success": true,
    "restaurant": {
        "id": 1,
        "name": "رستوران تست",
        "description": "توضیحات رستوران",
        "address": "آدرس رستوران",
        "phone": "+491234567890"
    },
    "menu_items": [
        {
            "id": 1,
            "name": "پیتزا مارگاریتا",
            "description": "پیتزا با پنیر و گوجه",
            "price": "12.50",
            "stock": "موجود",
            "present": true,              // موجود بودن
            "images": [                   // لیست URL عکس‌ها
                "http://domain.com/media/business_menu/items/image1.jpg",
                "http://domain.com/media/business_menu/items/image2.jpg"
            ],
            "details": "پیتزا با پنیر و گوجه"  // توضیحات
        }
    ]
}
```

### 5. لیست آیتم‌های منو (برای مدیریت)
```
GET /api/business-menu/menu-items/?restaurant_id=1
Authorization: Bearer {access_token}

Response:
{
    "success": true,
    "menu_items": [
        {
            "id": 1,
            "restaurant": 1,
            "restaurant_name": "رستوران تست",
            "name": "پیتزا مارگاریتا",
            "description": "پیتزا با پنیر و گوجه",
            "price": "12.50",
            "stock": "موجود",
            "is_available": true,
            "order": 0,
            "images": [...],
            "created_at": "2025-01-01T12:00:00Z"
        }
    ]
}
```

## 🏢 Restaurant Management APIs

### 6. لیست رستوران‌های ادمین
```
GET /api/business-menu/restaurants/
Authorization: Bearer {access_token}

Response:
{
    "success": true,
    "restaurants": [
        {
            "id": 1,
            "admin": 1,
            "admin_name": "علی احمدی",
            "name": "رستوران تست",
            "description": "توضیحات",
            "address": "آدرس",
            "phone": "+491234567890",
            "is_active": true,
            "created_at": "2025-01-01T12:00:00Z"
        }
    ]
}
```

### 7. ایجاد رستوران جدید
```
POST /api/business-menu/restaurants/
Authorization: Bearer {access_token}
Content-Type: application/json

Body:
{
    "name": "رستوران تست",
    "description": "توضیحات رستوران",
    "address": "آدرس رستوران",
    "phone": "+491234567890"
}

Response:
{
    "success": true,
    "message": "رستوران با موفقیت ایجاد شد",
    "restaurant": {...}
}
```

## 📱 QR Code APIs

### 8. تولید QR کد
```
POST /api/business-menu/generate-qr/
Authorization: Bearer {access_token}
Content-Type: application/json

Body:
{
    "restaurant_id": 1
}

Response:
{
    "success": true,
    "message": "QR کد با موفقیت ایجاد شد",
    "qr_code": {
        "id": 1,
        "restaurant": 1,
        "restaurant_name": "رستوران تست",
        "token": "abc123def456...",
        "menu_url": "https://domain.com/business-menu/qr/abc123def456.../",
        "qr_image_url": "https://domain.com/business-menu/qr/abc123def456....png",
        "created_at": "2025-01-01T12:00:00Z"
    }
}
```

## 🌐 Public Display

### 9. نمایش منو (هنگام اسکن QR کد)
```
GET /business-menu/qr/{token}/

این یک صفحه HTML است که منو رستوران را نمایش می‌دهد.
```

### 10. تصویر QR کد
```
GET /business-menu/qr/{token}.png

این یک تصویر PNG از QR کد است.
```

## 📋 خلاصه فیلدها مطابق دیاگرام

| دیاگرام | API فعلی | توضیحات |
|---------|----------|---------|
| `number` | `phone` | شماره تلفن |
| `opCode` | `code` | کد OTP |
| `images[]:string` | `images` | لیست عکس‌ها |
| `price:string` | `price` | قیمت |
| `present:string` | `is_available` | موجود بودن (در response به صورت boolean برمی‌گردد) |
| `انبار-tank` | `stock` | موجودی/انبار |
| `details` | `description` | توضیحات |

## 🔄 سازگاری با دیاگرام

APIها طبق دیاگرام ساخته شده‌اند و از فیلدهای زیر پشتیبانی می‌کنند:
- ✅ `number` / `phone` برای شماره تلفن
- ✅ `opCode` / `code` برای OTP
- ✅ `images[]` برای لیست عکس‌ها
- ✅ `price` به صورت string
- ✅ `present` برای موجود بودن
- ✅ `stock` برای موجودی
- ✅ `details` برای توضیحات
