# Generated manually to add BUSINESS_ADMIN role choice

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_migrate_business_owner_to_admin'),
    ]

    operations = [
        migrations.AlterField(
            model_name='profile',
            name='role',
            field=models.CharField(
                choices=[
                    ('superuser', 'Super User'),
                    ('admin', 'Admin'),
                    ('operator', 'Operator'),
                    ('business_admin', 'Business Admin'),
                    ('customer', 'Customer'),
                    ('business_owner', 'Business Owner'),  # Legacy - deprecated
                ],
                default='customer',
                max_length=32
            ),
        ),
    ]
