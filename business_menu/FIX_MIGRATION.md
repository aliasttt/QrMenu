# Fix Migration Error

## مشکل
```
ProgrammingError: relation "business_menu_menuqrcode" does not exist
```

## راه حل

### در Production (Scalingo):

```bash
# 1. ایجاد migration
scalingo --app mywebsite run python manage.py makemigrations business_menu

# 2. اجرای migration
scalingo --app mywebsite run python manage.py migrate business_menu
```

### در Local:

```bash
# 1. ایجاد migration
python manage.py makemigrations business_menu

# 2. اجرای migration
python manage.py migrate business_menu
```

## تغییرات انجام شده

1. ✅ همه متن‌های فارسی در admin panel به انگلیسی تبدیل شدند
2. ✅ verbose_name ها به انگلیسی تبدیل شدند
3. ✅ help_text ها به انگلیسی تبدیل شدند
4. ✅ فیلد `menu_url` به `MenuQRCode` اضافه شد

## بعد از Migration

بعد از اجرای migration، باید بتوانید:
- وارد Django Admin شوید (`/admin/`)
- بخش "Business Menu Management" را ببینید
- جداول زیر را مدیریت کنید:
  - Business Admins
  - Restaurants
  - Menu Items
  - Menu Item Images
  - Menu QR Codes
