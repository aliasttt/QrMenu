# Generated manually to migrate BUSINESS_OWNER role to BUSINESS_ADMIN

from django.db import migrations


def migrate_business_owner_to_admin(apps, schema_editor):
    """
    Migrate all Profile.role from BUSINESS_OWNER to BUSINESS_ADMIN.
    This is a data migration to convert legacy business_owner roles.
    """
    Profile = apps.get_model('accounts', 'Profile')
    
    # Update all profiles with BUSINESS_OWNER role to BUSINESS_ADMIN
    updated_count = Profile.objects.filter(role='business_owner').update(role='business_admin')
    
    if updated_count > 0:
        print(f"Migrated {updated_count} profile(s) from BUSINESS_OWNER to BUSINESS_ADMIN")


def reverse_migrate(apps, schema_editor):
    """
    Reverse migration: convert BUSINESS_ADMIN back to BUSINESS_OWNER.
    Note: This may not be accurate if new BUSINESS_ADMIN profiles were created.
    """
    Profile = apps.get_model('accounts', 'Profile')
    
    # Convert back (but this is not perfect since new BUSINESS_ADMIN might exist)
    Profile.objects.filter(role='business_admin').update(role='business_owner')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_alter_profile_role'),
    ]

    operations = [
        migrations.RunPython(
            migrate_business_owner_to_admin,
            reverse_migrate,
        ),
    ]
