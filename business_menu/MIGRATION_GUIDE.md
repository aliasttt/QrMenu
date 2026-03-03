# Migration Guide - Business Menu

## مشکل: جدول `business_menu_menuqrcode` وجود ندارد

این خطا به این دلیل است که migration ها هنوز اجرا نشده‌اند.

## راه حل

### 1. ایجاد Migration

```bash
python manage.py makemigrations business_menu
```

این دستور migration های لازم را ایجاد می‌کند.

### 2. اجرای Migration

```bash
python manage.py migrate business_menu
```

یا برای اجرای همه migration ها:

```bash
python manage.py migrate
```

### 3. در Production (Scalingo)

```bash
scalingo --app mywebsite run python manage.py makemigrations business_menu
scalingo --app mywebsite run python manage.py migrate business_menu
```

## Migration های ایجاد شده

بعد از اجرای `makemigrations`، فایل‌های زیر ایجاد می‌شوند:

- `business_menu/migrations/0001_initial.py` - ایجاد جداول اولیه
- `business_menu/migrations/0002_menuqrcode_menu_url.py` - اضافه کردن فیلد `menu_url`

## بررسی Migration ها

برای بررسی migration های موجود:

```bash
python manage.py showmigrations business_menu
```

باید همه migration ها با `[X]` علامت خورده باشند.

## در صورت خطا

اگر migration با خطا مواجه شد:

1. بررسی کنید که دیتابیس در دسترس است
2. بررسی کنید که `business_menu` در `INSTALLED_APPS` است
3. لاگ‌های خطا را بررسی کنید
