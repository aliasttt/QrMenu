# Generated migration for adding serial field to MenuItem and show_serial to RestaurantSettings

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('business_menu', '0008_add_white_orange_white_red_themes'),
    ]

    operations = [
        migrations.AddField(
            model_name='menuitem',
            name='serial',
            field=models.CharField(blank=True, help_text='Serial number for menu item (optional)', max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='restaurantsettings',
            name='show_serial',
            field=models.BooleanField(default=False, help_text='Show serial numbers in menu display'),
        ),
    ]
