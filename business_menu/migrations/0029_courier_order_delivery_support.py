from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("business_menu", "0028_add_customer_phone_unique_constraint"),
    ]

    operations = [
        migrations.CreateModel(
            name="Courier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("phone", models.CharField(max_length=32)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "restaurant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="couriers",
                        to="business_menu.restaurant",
                    ),
                ),
            ],
            options={
                "verbose_name": "Courier",
                "verbose_name_plural": "Couriers",
                "ordering": ["name", "id"],
            },
        ),
        migrations.AddField(
            model_name="order",
            name="cancellation_reason",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="courier",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="orders",
                to="business_menu.courier",
            ),
        ),
        migrations.AlterField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "در انتظار"),
                    ("paid", "پرداخت شده"),
                    ("preparing", "در حال آماده‌سازی"),
                    ("out_for_delivery", "Out for delivery"),
                    ("completed", "تکمیل شده"),
                    ("cancelled", "لغو شده"),
                    ("refunded", "مسترد شده"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
    ]
