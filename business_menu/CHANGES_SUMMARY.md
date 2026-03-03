# خلاصه تغییرات - Business Menu Management

## ✅ تغییرات انجام شده

### 1. جداول کاملاً جدا از اپ بونوس
- ✅ همه مدل‌ها در اپ `business_menu` هستند
- ✅ هیچ ارتباطی با مدل‌های `loyalty` یا `accounts` ندارند
- ✅ جداول مستقل در دیتابیس مشترک

### 2. Admin Panel جدا
- ✅ Django Admin برای `business_menu` کاملاً جدا است
- ✅ در بخش "Business Menu" در Django Admin نمایش داده می‌شود
- ✅ هیچ ارتباطی با admin panel اپ بونوس ندارد

### 3. Dashboard Admin وبسایت
- ✅ در `admin/views.py` و `admin/dashboard.html` هیچ اطلاعاتی از `business_menu` نمایش داده نمی‌شود
- ✅ فقط اطلاعات مربوط به `loyalty.Business` نمایش داده می‌شود
- ✅ کاملاً جدا از business_menu

### 4. API های جدید

#### الف) ذخیره منو از اپ
```
POST /api/business-menu/save-menu-from-app/
Authorization: Bearer {access_token}
Body: {
    "restaurant_id": 1,
    "menu_items": [
        {
            "name": "پیتزا",
            "price": "12.50",
            "present": "true",
            "stock": "موجود",
            "details": "توضیحات",
            "images": ["url1", "url2"]
        }
    ]
}
```

#### ب) دریافت URL منو
```
GET /api/business-menu/get-menu-url/?restaurant_id=1
Authorization: Bearer {access_token}

Response: {
    "success": true,
    "menu_url": "https://domain.com/business-menu/qr/{token}/",
    "token": "..."
}
```

### 5. ذخیره URL در دیتابیس
- ✅ فیلد `menu_url` به مدل `MenuQRCode` اضافه شد
- ✅ هنگام تولید QR کد، URL در دیتابیس ذخیره می‌شود
- ✅ URL در admin panel نمایش داده می‌شود

### 6. نمایش منو با استایل وبسایت
- ✅ Template `menu_display.html` با استایل مطابق با وبسایت
- ✅ استفاده از `base.html` برای استایل یکسان
- ✅ نمایش زیبای منوها با عکس‌ها

### 7. ارسال URL به اپ
- ✅ در template `menu_display.html`، URL منو در متغیر `menu_url` موجود است
- ✅ می‌تواند از طریق JavaScript به اپ ارسال شود
- ✅ یا از طریق API `get-menu-url` دریافت شود

## 📋 فلو کامل

1. **اپ منو را اضافه می‌کند:**
   ```
   POST /api/business-menu/menu-items/
   ```

2. **اپ منو را برای ذخیره می‌فرستد:**
   ```
   POST /api/business-menu/save-menu-from-app/
   ```

3. **اپ QR کد را درخواست می‌کند:**
   ```
   POST /api/business-menu/generate-qr/
   Response: {
       "qr_code": {...},
       "menu_url": "https://domain.com/business-menu/qr/{token}/"
   }
   ```

4. **اپ URL منو را دریافت می‌کند:**
   ```
   GET /api/business-menu/get-menu-url/?restaurant_id=1
   Response: {
       "menu_url": "https://domain.com/business-menu/qr/{token}/"
   }
   ```

5. **کاربر QR کد را اسکن می‌کند:**
   - به `https://domain.com/business-menu/qr/{token}/` هدایت می‌شود
   - منو با استایل زیبا نمایش داده می‌شود
   - URL در template موجود است و می‌تواند به اپ ارسال شود

## 🔄 Migration لازم

بعد از تغییرات، باید migration ایجاد کنید:

```bash
python manage.py makemigrations business_menu
python manage.py migrate business_menu
```

این migration فیلد `menu_url` را به `MenuQRCode` اضافه می‌کند.
