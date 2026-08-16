from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("business_menu", "0031_payment_refund_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="businessadmin",
            name="subscription_environment",
            field=models.CharField(blank=True, help_text="Provider environment for the current subscription (Sandbox, Production, etc.)", max_length=32),
        ),
        migrations.AddField(
            model_name="businessadmin",
            name="subscription_original_transaction_id",
            field=models.CharField(blank=True, db_index=True, help_text="Original store transaction ID for receipt/notification reconciliation", max_length=255),
        ),
        migrations.AddField(
            model_name="businessadmin",
            name="subscription_product_id",
            field=models.CharField(blank=True, help_text="Store product or Stripe price ID for the current subscription", max_length=255),
        ),
        migrations.AddField(
            model_name="businessadmin",
            name="subscription_provider",
            field=models.CharField(blank=True, db_index=True, help_text="Provider for the active subscription entitlement (stripe, apple, google, manual)", max_length=32),
        ),
        migrations.AddField(
            model_name="businessadmin",
            name="subscription_transaction_id",
            field=models.CharField(blank=True, db_index=True, help_text="Latest verified store transaction ID", max_length=255),
        ),
    ]
