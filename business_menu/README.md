# Business Menu Management API

این اپلیکیشن برای مدیریت منوی رستوران‌ها و کافه‌ها طراحی شده است. ادمین‌ها می‌توانند منو و عکس‌های خود را اضافه کنند و QR کد برای نمایش منو دریافت کنند.

## ویژگی‌ها

- ✅ ثبت ادمین‌ها توسط Super Admin در Django Admin
- ✅ ورود ادمین‌ها با شماره تلفن و OTP
- ✅ مدیریت رستوران‌ها توسط ادمین‌ها
- ✅ افزودن آیتم‌های منو با عکس‌های متعدد
- ✅ تولید QR کد برای هر رستوران
- ✅ نمایش منو هنگام اسکن QR کد

## مدل‌ها

### BusinessAdmin
ادمین‌های رستوران که توسط Super Admin به صورت دستی ثبت می‌شوند.

### Restaurant
رستوران یا کافه که توسط ادمین مدیریت می‌شود.

### MenuItem
آیتم‌های منو شامل نام، توضیحات، قیمت، موجودی و عکس‌ها.

### MenuItemImage
عکس‌های هر آیتم منو (هر آیتم می‌تواند چندین عکس داشته باشد).

### MenuQRCode
QR کد یکتا برای هر رستوران که به صفحه نمایش منو لینک می‌شود.

## API Endpoints

### 1. ارسال OTP
```
POST /api/business-menu/send-otp/
Body: {"phone": "+491234567890"}
```

### 2. ورود با OTP
```
POST /api/business-menu/login/
Body: {"phone": "+491234567890", "code": "123456"}
Response: {
    "success": true,
    "access": "JWT_TOKEN",
    "refresh": "REFRESH_TOKEN",
    "admin": {...}
}
```

### 3. لیست رستوران‌های ادمین
```
GET /api/business-menu/restaurants/
Headers: Authorization: Bearer {access_token}
```

### 4. ایجاد رستوران جدید
```
POST /api/business-menu/restaurants/
Headers: Authorization: Bearer {access_token}
Body: {
    "name": "رستوران تست",
    "description": "توضیحات",
    "address": "آدرس",
    "phone": "+491234567890"
}
```

### 5. لیست آیتم‌های منو
```
GET /api/business-menu/menu-items/?restaurant_id=1
Headers: Authorization: Bearer {access_token}
```

### 6. افزودن آیتم منو
```
POST /api/business-menu/menu-items/
Headers: Authorization: Bearer {access_token}
Content-Type: multipart/form-data
Body: {
    "restaurant": 1,
    "name": "پیتزا مارگاریتا",
    "description": "توضیحات",
    "price": "12.50",
    "stock": "موجود",
    "is_available": true,
    "order": 0,
    "images": [file1, file2, ...]
}
```

### 7. دریافت منو (برای اپلیکیشن)
```
GET /api/business-menu/get-menu/?restaurant_id=1
Response: {
    "success": true,
    "restaurant": {...},
    "menu_items": [
        {
            "id": 1,
            "name": "پیتزا",
            "description": "...",
            "price": "12.50",
            "stock": "موجود",
            "present": true,
            "images": ["url1", "url2"],
            "details": "..."
        }
    ]
}
```

### 8. تولید QR کد
```
POST /api/business-menu/generate-qr/
Headers: Authorization: Bearer {access_token}
Body: {"restaurant_id": 1}
Response: {
    "success": true,
    "qr_code": {
        "token": "...",
        "menu_url": "https://domain.com/business-menu/qr/{token}/",
        "qr_image_url": "https://domain.com/business-menu/qr/{token}.png"
    }
}
```

## نمایش منو

هنگام اسکن QR کد، کاربر به آدرس زیر هدایت می‌شود:
```
GET /business-menu/qr/{token}/
```

این صفحه منو رستوران را به صورت زیبا نمایش می‌دهد.

## استفاده در Django Admin

1. وارد Django Admin شوید
2. به بخش "Business Menu" بروید
3. یک "Business Admin" جدید اضافه کنید:
   - نام
   - شماره تلفن (فرمت E.164: +491234567890)
   - ایمیل (اختیاری)
4. ادمین می‌تواند با این شماره تلفن وارد شود

## نکات مهم

- شماره تلفن باید در فرمت E.164 باشد (مثلاً +491234567890)
- هر ادمین می‌تواند چندین رستوران داشته باشد
- هر رستوران یک QR کد یکتا دارد
- هر آیتم منو می‌تواند چندین عکس داشته باشد
- عکس‌ها در `media/business_menu/items/` ذخیره می‌شوند
