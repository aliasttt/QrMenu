# اجرای Migration - دستورات دقیق

## مشکل
Migration ایجاد شده اما اجرا نشده است.

## راه حل

### 1. حذف migration قبلی (اگر مشکل دارد):

```bash
scalingo --app mywebsite run python manage.py migrate business_menu zero
```

### 2. ایجاد مجدد migration:

```bash
scalingo --app mywebsite run python manage.py makemigrations business_menu
```

### 3. اجرای migration:

```bash
scalingo --app mywebsite run python manage.py migrate business_menu
```

یا برای اجرای همه:

```bash
scalingo --app mywebsite run python manage.py migrate
```

## بررسی

بعد از اجرا:

```bash
scalingo --app mywebsite run python manage.py showmigrations business_menu
```

باید ببینید:
```
business_menu
 [X] 0001_initial
```

## اگر هنوز مشکل دارد:

```bash
# بررسی وضعیت migration
scalingo --app mywebsite run python manage.py showmigrations

# اجرای migration با force
scalingo --app mywebsite run python manage.py migrate business_menu --run-syncdb
```
