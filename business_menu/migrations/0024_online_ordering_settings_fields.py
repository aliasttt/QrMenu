from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("business_menu", "0023_restaurant_coords_9_6_and_public_slug"),
    ]

    operations = [
        migrations.AddField(
            model_name="restaurantsettings",
            name="enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="min_order_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("15.00"), max_digits=10),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="estimated_delivery_time",
            field=models.CharField(blank=True, default="30-45", max_length=50),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="delivery_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="delivery_fee",
            field=models.DecimalField(decimal_places=2, default=Decimal("3.50"), max_digits=10),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="free_delivery_above",
            field=models.DecimalField(decimal_places=2, default=Decimal("30.00"), max_digits=10),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="delivery_radius_km",
            field=models.DecimalField(decimal_places=2, default=Decimal("5"), max_digits=10),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="delivery_zones",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="delivery_hours_same_as_working",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="delivery_hours_start",
            field=models.CharField(blank=True, default="11:00", max_length=5),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="delivery_hours_end",
            field=models.CharField(blank=True, default="22:00", max_length=5),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="pickup_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="pickup_preparation_time",
            field=models.CharField(blank=True, default="15-20", max_length=50),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="online_payment_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="payment_gateway",
            field=models.CharField(
                choices=[
                    ("stripe", "Only Stripe"),
                    ("paypal", "Only PayPal"),
                    ("both", "Stripe + PayPal"),
                    ("none", "No online payment"),
                ],
                default="stripe",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="stripe_publishable_key",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="stripe_secret_key",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="paypal_client_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="paypal_client_secret",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="card_payment_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="restaurantsettings",
            name="cash_payment_enabled",
            field=models.BooleanField(default=True),
        ),
    ]
