# Fix: DuplicateTable when running migrate on Scalingo

If you see:

```
psycopg.errors.DuplicateTable: relation "business_menu_customer" already exists
Applying business_menu.0013_add_customer_order_payment...
```

the database already has the Customer/Order/Payment tables (e.g. from an earlier deploy or manual create), but Django’s migration history doesn’t have `0013` applied.

**Fix: mark 0013 as applied without running it, then run the rest of the migrations.**

On Scalingo, run:

```bash
# 1) Mark 0013 as applied without touching the database
scalingo --app qrmenu run "python manage.py migrate business_menu 0013 --fake"

# 2) Apply remaining migrations (0014, 0015, 0016, ...)
scalingo --app qrmenu run "python manage.py migrate"
```

If any later migration fails with “column already exists” or “table already exists”, you can fake that one too, then run `migrate` again. For example:

```bash
scalingo --app qrmenu run "python manage.py migrate business_menu 0014_order_service_and_restaurant_delivery --fake"
scalingo --app qrmenu run "python manage.py migrate"
```
