# مراحل Deploy - Business Menu

## مشکل فعلی
1. Migration فایل در Scalingo نیست (باید commit و push شود)
2. Warning درباره URL namespace

## مراحل Deploy

### 1. Commit و Push فایل‌ها

```bash
git add business_menu/
git add config/settings.py
git add config/urls.py
git commit -m "Add business_menu app with migrations"
git push
```

### 2. بعد از Push، در Scalingo:

```bash
# بررسی migration
scalingo --app mywebsite run python manage.py showmigrations business_menu

# اجرای migration
scalingo --app mywebsite run python manage.py migrate business_menu
```

## خطای `column ...auth_user_id does not exist`

این خطا یعنی **کد جدید deploy شده ولی migration جدید اجرا نشده**.

برای رفع سریع:

```bash
scalingo --app mywebsite run python manage.py showmigrations business_menu
scalingo --app mywebsite run python manage.py migrate business_menu
```

## اگر هنوز مشکل دارد:

```bash
# بررسی وضعیت
scalingo --app mywebsite run python manage.py showmigrations

# اگر migration موجود نیست، ایجاد کنید:
scalingo --app mywebsite run python manage.py makemigrations business_menu

# سپس اجرا کنید:
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

## نکته مهم

فایل `business_menu/migrations/0001_initial.py` باید در repository باشد تا در Scalingo در دسترس باشد.
