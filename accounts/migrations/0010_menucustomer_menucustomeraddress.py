from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_add_business_admin_role"),
    ]

    operations = [
        migrations.CreateModel(
            name="MenuCustomer",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(db_index=True, max_length=254, unique=True)),
                ("phone", models.CharField(db_index=True, max_length=32, unique=True)),
                ("first_name", models.CharField(blank=True, max_length=120)),
                ("last_name", models.CharField(blank=True, max_length=120)),
                ("password", models.CharField(max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_login_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "Menu Customer",
                "verbose_name_plural": "Menu Customers",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="MenuCustomerAddress",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(blank=True, max_length=64)),
                ("address", models.TextField()),
                ("is_default", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="addresses", to="accounts.menucustomer")),
            ],
            options={
                "verbose_name": "Menu Customer Address",
                "verbose_name_plural": "Menu Customer Addresses",
                "ordering": ["-is_default", "-created_at"],
            },
        ),
    ]
