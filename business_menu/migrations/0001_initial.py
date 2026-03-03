# Generated manually
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='BusinessAdmin',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone', models.CharField(db_index=True, help_text='Admin phone number', max_length=32, unique=True)),
                ('name', models.CharField(help_text='Admin name', max_length=200)),
                ('email', models.EmailField(blank=True, help_text='Admin email (optional)', max_length=254)),
                ('is_active', models.BooleanField(default=True, help_text='Active/Inactive status')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, help_text='Super admin user who created this admin', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_business_admins', to='auth.user')),
            ],
            options={
                'verbose_name': 'Business Admin',
                'verbose_name_plural': 'Business Admins',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Restaurant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Restaurant/cafe name', max_length=200)),
                ('description', models.TextField(blank=True, help_text='Restaurant description')),
                ('address', models.TextField(blank=True, help_text='Restaurant address')),
                ('phone', models.CharField(blank=True, help_text='Restaurant phone number', max_length=32)),
                ('is_active', models.BooleanField(default=True, help_text='Active/Inactive status')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('admin', models.ForeignKey(help_text='Admin of this restaurant', on_delete=django.db.models.deletion.CASCADE, related_name='restaurants', to='business_menu.businessadmin')),
            ],
            options={
                'verbose_name': 'Restaurant',
                'verbose_name_plural': 'Restaurants',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='MenuItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Menu item name', max_length=200)),
                ('description', models.TextField(blank=True, help_text='Item description')),
                ('price', models.DecimalField(decimal_places=2, help_text='Price in currency unit (e.g., EUR)', max_digits=10)),
                ('stock', models.CharField(blank=True, help_text="Stock status (e.g., 'Available', 'Out of stock', or quantity)", max_length=50)),
                ('is_available', models.BooleanField(default=True, help_text='Is this item available?')),
                ('order', models.PositiveIntegerField(default=0, help_text='Display order in menu')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('restaurant', models.ForeignKey(help_text='Related restaurant', on_delete=django.db.models.deletion.CASCADE, related_name='menu_items', to='business_menu.restaurant')),
            ],
            options={
                'verbose_name': 'Menu Item',
                'verbose_name_plural': 'Menu Items',
                'ordering': ['order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='MenuItemImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(help_text='Menu item image', upload_to='business_menu/items/')),
                ('order', models.PositiveIntegerField(default=0, help_text='Image display order')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('menu_item', models.ForeignKey(help_text='Related menu item', on_delete=django.db.models.deletion.CASCADE, related_name='images', to='business_menu.menuitem')),
            ],
            options={
                'verbose_name': 'Menu Item Image',
                'verbose_name_plural': 'Menu Item Images',
                'ordering': ['order', 'created_at'],
            },
        ),
        migrations.CreateModel(
            name='MenuQRCode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, help_text='Unique token for QR code', max_length=64, unique=True)),
                ('menu_url', models.URLField(blank=True, help_text='Menu URL stored in database', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('restaurant', models.OneToOneField(help_text='Related restaurant', on_delete=django.db.models.deletion.CASCADE, related_name='menu_qrcode', to='business_menu.restaurant')),
            ],
            options={
                'verbose_name': 'Menu QR Code',
                'verbose_name_plural': 'Menu QR Codes',
            },
        ),
        migrations.AddIndex(
            model_name='menuitem',
            index=models.Index(fields=['restaurant', 'is_available'], name='business_me_restaur_idx'),
        ),
    ]
