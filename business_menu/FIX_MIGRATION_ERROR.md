# رفع خطای Migration

## مشکل
Migration `0002` سعی می‌کند نام index را تغییر دهد اما index با نام قبلی وجود ندارد.

## راه حل

### 1. Migration اضافی حذف شد
فایل `0002_rename_business_me_restaur_123abc_idx_business_me_restaur_07242c_idx.py` حذف شد.

### 2. اجرای مجدد Migration

```bash
scalingo --app mywebsite run python manage.py migrate business_menu
```

یا اگر migration قبلی اجرا شده:

```bash
# بررسی وضعیت
scalingo --app mywebsite run python manage.py showmigrations business_menu

# اگر 0001 اجرا شده اما 0002 خطا داده، fake کنید:
scalingo --app mywebsite run python manage.py migrate business_menu 0002 --fake
```

### 3. اگر هنوز مشکل دارد:

```bash
# حذف migration مشکل‌دار از دیتابیس
scalingo --app mywebsite run python manage.py migrate business_menu 0001

# سپس اجرای مجدد
scalingo --app mywebsite run python manage.py migrate business_menu
```

## بررسی نهایی

```bash
scalingo --app mywebsite run python manage.py showmigrations business_menu
```

باید ببینید:
```
business_menu
 [X] 0001_initial
```

بدون هیچ migration دیگری.
