from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def link_existing_business_admin_users(apps, schema_editor):
    BusinessAdmin = apps.get_model("business_menu", "BusinessAdmin")
    User = apps.get_model("auth", "User")

    for admin in BusinessAdmin.objects.filter(auth_user__isnull=True):
        phone = getattr(admin, "phone", "") or ""
        digits = "".join(ch for ch in phone if ch.isdigit())
        if not digits:
            continue
        base_username = f"business_admin_{digits}"

        user = User.objects.filter(username=base_username).first()
        if not user:
            # Fall back to a suffixed username if present (business_admin_..._1)
            user = User.objects.filter(username__startswith=base_username).order_by("id").first()

        if user:
            BusinessAdmin.objects.filter(pk=admin.pk, auth_user__isnull=True).update(auth_user_id=user.pk)


class Migration(migrations.Migration):

    dependencies = [
        ("business_menu", "0009_add_serial_to_menuitem_and_show_serial_to_restaurantsettings"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="businessadmin",
            name="auth_user",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="business_menu_admin",
                to=settings.AUTH_USER_MODEL,
                help_text="Linked auth user for API authentication (do not edit manually unless needed)",
            ),
        ),
        migrations.RunPython(link_existing_business_admin_users, migrations.RunPython.noop),
    ]

