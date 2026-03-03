# راه حل سریع - اجرای Migration

## مشکل
Migration ایجاد شده اما اجرا نشده است.

## دستورات

### در Scalingo:

```bash
# اجرای migration برای business_menu
scalingo --app mywebsite run python manage.py migrate business_menu

# یا اجرای همه migration ها
scalingo --app mywebsite run python manage.py migrate
```

## اگر migration اجرا نشد:

```bash
# بررسی وضعیت
scalingo --app mywebsite run python manage.py showmigrations business_menu

# اگر migration موجود است اما اجرا نشده، force کنید:
scalingo --app mywebsite run python manage.py migrate business_menu --fake-initial
```

## بررسی

```bash
scalingo --app mywebsite run python manage.py showmigrations business_menu
```

باید ببینید:
```
business_menu
 [X] 0001_initial
```

## تغییرات انجام شده

1. ✅ فایل migration ایجاد شد (`0001_initial.py`)
2. ✅ مشکل URL namespace حل شد (`app_name` حذف شد)
3. ✅ همه متن‌ها به انگلیسی تبدیل شدند

## بعد از Migration

بعد از اجرای migration:
- ✅ جداول ایجاد می‌شوند
- ✅ می‌توانید وارد Django Admin شوید
- ✅ می‌توانید Business Admin اضافه کنید
