from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("business_menu", "0033_reservation_timezone_capacity"),
    ]

    operations = [
        migrations.AddField(
            model_name="reservation",
            name="table",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Validated snapshot of the selected table from ReservationSettings.tables.",
            ),
        ),
    ]
