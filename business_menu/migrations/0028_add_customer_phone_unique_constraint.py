from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_menu", "0027_unique_customer_phone_per_restaurant"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(
                fields=("restaurant", "phone"),
                condition=~models.Q(phone=""),
                name="uniq_customer_phone_per_restaurant",
            ),
        ),
    ]