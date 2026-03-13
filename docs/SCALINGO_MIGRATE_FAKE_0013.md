# Fix: DuplicateTable when running migrate on Scalingo

## خطا: `relation "business_menu_customer" already exists`

یعنی جدول‌های مایگریشن 0013 از قبل روی دیتابیس ساخته شده‌اند ولی خود مایگریشن در جدول `django_migrations` ثبت نشده است. باید 0013 را **fake** کنیم (بدون اجرا فقط ثبت کنیم) بعد بقیهٔ مایگریشن‌ها را اجرا کنیم.

### دستورات روی Scalingo (به همین ترتیب):

```bash
# ۱) ثبت مایگریشن 0013 به‌صورت fake + درست کردن sequence
scalingo --app qrmenu run "python manage.py fix_migrations_sequence --fake business_menu 0013_add_customer_order_payment"

# ۲) اجرای بقیهٔ مایگریشن‌ها (0014 تا 0017)
scalingo --app qrmenu run "python manage.py migrate"
```

بعد از این دو دستور، مایگریشن‌ها باید بدون خطا اعمال شوند.

---

## اگر خطای sequence دیدید

اگر بعد از `--fake` این خطا را دیدید:
`IntegrityError: duplicate key value violates unique constraint "django_migrations_pkey"`

یعنی sequence جدول `django_migrations` خراب است. اول فقط sequence را درست کنید بعد دوباره migrate:

```bash
scalingo --app qrmenu run "python manage.py fix_migrations_sequence"
scalingo --app qrmenu run "python manage.py migrate"
```

---

## اگر 0014 هم خطا داد: `column "payment_method" already exists`

یعنی تغییرات 0014 هم از قبل روی دیتابیس اعمال شده‌اند. 0014 را هم fake کنید:

```bash
scalingo --app qrmenu run "python manage.py fix_migrations_sequence --fake business_menu 0014_order_service_and_restaurant_delivery"
scalingo --app qrmenu run "python manage.py migrate"
```

اگر باز هم مایگریشن بعدی (0015 یا 0016) خطای «already exists» داد، همان را هم fake کنید. می‌توانید چند تا را در یک دستور fake کنید:

```bash
scalingo --app qrmenu run "python manage.py fix_migrations_sequence --fake business_menu 0014_order_service_and_restaurant_delivery --fake business_menu 0015_add_opening_hours_and_reservations --fake business_menu 0016_add_order_scheduled_for"
scalingo --app qrmenu run "python manage.py migrate"
```

هدف این است که فقط **0017** (trial و Stripe) واقعاً اجرا شود؛ بقیه روی سرور از قبل اعمال شده‌اند.

---

## اگر بعد از migrate خطای `django_content_type_pkey` دیدید

یعنی sequence جدول `django_content_type` خراب است و موقع سیگنال post_migrate خطا می‌دهد. دستور `fix_migrations_sequence` الان این sequence را هم درست می‌کند. یک بار **بدون** `--fake` اجرا کنید بعد دوباره migrate:

```bash
scalingo --app qrmenu run "python manage.py fix_migrations_sequence"
scalingo --app qrmenu run "python manage.py migrate"
```

اگر باز هم همان خطا آمد، احتمالاً Django دارد ContentTypeهای جدید می‌سازد و با id تکراری برخورد می‌کند. در آن صورت می‌توان با `--run-syncdb` یا با یک دستور SQL جدا sequence را به‌روز کرد (در دستور بالا الان خودکار انجام می‌شود).
