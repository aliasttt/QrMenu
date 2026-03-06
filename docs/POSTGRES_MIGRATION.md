# انتقال دیتابیس PostgreSQL از mywebsite به qrmenu (Scalingo)

## آدرس‌های دیتابیس (از داشبورد)

- **قدیمی (mywebsite):**  
  `postgres://mywebsite_2040:<password>@mywebsite-2040.postgresql.c.osc-fr1.scalingo-dbs.com:36348/mywebsite_2040?sslmode=prefer`

- **جدید (qrmenu):**  
  `postgres://qrmenu_8822:<password>@qrmenu-8822.postgresql.c.osc-fr1.scalingo-dbs.com:35045/qrmenu_8822?sslmode=prefer`

`<password>` را از Scalingo → App → Databases → PostgreSQL → Connection string عوض کن.

---

## فقط انتقال دیتا (جدول‌ها از قبل ساخته شده‌اند)

### ۱. گرفتن dump از دیتابیس قدیمی

```bash
pg_dump "postgres://mywebsite_2040:YOUR_OLD_PASSWORD@mywebsite-2040.postgresql.c.osc-fr1.scalingo-dbs.com:36348/mywebsite_2040?sslmode=prefer" -Fc -f backup.dump
```

### ۲. ریختن فقط دیتا داخل دیتابیس جدید

```bash
pg_restore --data-only --no-owner --no-acl -d "postgres://qrmenu_8822:YOUR_NEW_PASSWORD@qrmenu-8822.postgresql.c.osc-fr1.scalingo-dbs.com:35045/qrmenu_8822?sslmode=prefer" backup.dump
```

---

## اگر خطای duplicate key گرفتی

اول جدول‌ها را در دیتابیس جدید خالی کن، بعد دوباره `pg_restore` بزن:

```sql
-- در psql متصل به دیتابیس qrmenu:
TRUNCATE table_name RESTART IDENTITY CASCADE;
-- یا برای همه جدول‌ها (با احتیاط):
-- DO $$ DECLARE r RECORD; BEGIN FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP EXECUTE 'TRUNCATE ' || quote_ident(r.tablename) || ' RESTART IDENTITY CASCADE'; END LOOP; END $$;
```

---

## روش مستقیم (بدون فایل موقت)

اگر `pg_dump` و `psql` روی سیستم داری:

```bash
pg_dump "DATABASE_URL_OLD" | psql "DATABASE_URL_NEW"
```

برای فقط دیتا با این روش باید از گزینه‌های مناسب `pg_dump` (مثلاً `--data-only`) استفاده کنی.

---

## پیش‌نیاز

- نصب **PostgreSQL client** (شامل `pg_dump` و `pg_restore`) روی ویندوز  
  یا از [PostgreSQL Downloads](https://www.postgresql.org/download/windows/) یا از طریق Chocolatey: `choco install postgresql`
