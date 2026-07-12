from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("business_menu", "0030_fix_online_pickup_orders_to_delivery"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="stripe_refund_id",
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="refund_status",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="payment",
            name="refund_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
    ]
