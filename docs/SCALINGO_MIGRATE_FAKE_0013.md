# Fix: DuplicateTable + django_migrations_pkey when running migrate on Scalingo

If you see:

- `psycopg.errors.DuplicateTable: relation "business_menu_customer" already exists` when applying `0013`
- `IntegrityError: duplicate key value violates unique constraint "django_migrations_pkey"` when running `migrate ... --fake`

the database already has the tables, and the `django_migrations.id` sequence is out of sync (new rows get a duplicate id).

**Fix: run the helper command to fix the sequence and fake 0013, then migrate.**

On Scalingo, run these in order:

```bash
# 1) Fix django_migrations id sequence and record 0013 as applied (without running it)
scalingo --app qrmenu run "python manage.py fix_migrations_sequence --fake business_menu 0013_add_customer_order_payment"

# 2) Apply remaining migrations (0014, 0015, 0016, ...)
scalingo --app qrmenu run "python manage.py migrate"
```

If you only see the **sequence** error and 0013 is already recorded, just fix the sequence then migrate:

```bash
scalingo --app qrmenu run "python manage.py fix_migrations_sequence"
scalingo --app qrmenu run "python manage.py migrate"
```

If a later migration fails with "column already exists", fake that migration too:

```bash
scalingo --app qrmenu run "python manage.py fix_migrations_sequence --fake business_menu 0014_order_service_and_restaurant_delivery"
scalingo --app qrmenu run "python manage.py migrate"
```
