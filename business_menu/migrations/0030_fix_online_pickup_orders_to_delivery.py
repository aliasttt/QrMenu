from django.db import migrations


def forwards(apps, schema_editor):
    Order = apps.get_model("business_menu", "Order")
    Order.objects.filter(payment_method="online", service_type="pickup").update(service_type="delivery")


class Migration(migrations.Migration):
    dependencies = [
        ("business_menu", "0029_courier_order_delivery_support"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
