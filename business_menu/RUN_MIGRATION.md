# اجرای Migration - Business Menu

## مشکل
خطای `relation "business_menu_businessadmin" does not exist` به این دلیل است که migration ها هنوز اجرا نشده‌اند.

## راه حل

### در Production (Scalingo):

```bash
# 1. بررسی migration های موجود
scalingo --app mywebsite run python manage.py showmigrations business_menu

# 2. اجرای migration
scalingo --app mywebsite run python manage.py migrate business_menu

# یا اجرای همه migration ها
scalingo --app mywebsite run python manage.py migrate
```

### در Local:

```bash
# 1. بررسی migration های موجود
python manage.py showmigrations business_menu

# 2. اجرای migration
python manage.py migrate business_menu

# یا اجرای همه migration ها
python manage.py migrate
```

## اگر migration ایجاد نشده بود:

```bash
# در Scalingo
scalingo --app mywebsite run python manage.py makemigrations business_menu
scalingo --app mywebsite run python manage.py migrate business_menu

# در Local
python manage.py makemigrations business_menu
python manage.py migrate business_menu
```

## بررسی

بعد از اجرای migration، بررسی کنید:

```bash
scalingo --app mywebsite run python manage.py showmigrations business_menu
```

باید همه migration ها با `[X]` علامت خورده باشند:
```
business_menu
 [X] 0001_initial
```

## نکته مهم

اگر فایل `0001_initial.py` را به صورت دستی ایجاد کردید، باید آن را commit و push کنید تا در Scalingo در دسترس باشد.
