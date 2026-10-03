from collections import defaultdict

import django.db.models.functions.text
from django.core.exceptions import ValidationError
from django.db import migrations, models


def validate_business_admin_identities(apps, schema_editor):
    from business_menu.identity import normalize_business_email, normalize_business_phone

    BusinessAdmin = apps.get_model("business_menu", "BusinessAdmin")
    email_groups = defaultdict(list)
    phone_groups = defaultdict(list)
    invalid_emails = []
    invalid_phones = []
    for admin_id, email, phone in BusinessAdmin.objects.using(schema_editor.connection.alias).values_list("id", "email", "phone"):
        try:
            email_groups[normalize_business_email(email)].append(admin_id)
        except (ValidationError, ValueError, TypeError):
            invalid_emails.append(admin_id)
        try:
            phone_groups[normalize_business_phone(phone)].append(admin_id)
        except (ValidationError, ValueError, TypeError):
            invalid_phones.append(admin_id)

    duplicate_emails = [ids for ids in email_groups.values() if len(ids) > 1]
    duplicate_phones = [ids for ids in phone_groups.values() if len(ids) > 1]
    if invalid_emails or invalid_phones or duplicate_emails or duplicate_phones:
        raise RuntimeError(
            "BusinessAdmin identity migration stopped without changing data. "
            f"empty_or_invalid_email_ids={invalid_emails}; "
            f"duplicate_email_id_groups={duplicate_emails}; "
            f"invalid_or_ambiguous_phone_ids={invalid_phones}; "
            f"duplicate_phone_id_groups={duplicate_phones}. "
            "Run audit_business_admin_identity and resolve each account explicitly before retrying."
        )


def normalize_business_admin_identities(apps, schema_editor):
    from business_menu.identity import normalize_business_email, normalize_business_phone

    BusinessAdmin = apps.get_model("business_menu", "BusinessAdmin")
    manager = BusinessAdmin.objects.using(schema_editor.connection.alias)
    for admin_id, email, phone in manager.values_list("id", "email", "phone").iterator():
        manager.filter(pk=admin_id).update(
            email=normalize_business_email(email),
            phone=normalize_business_phone(phone),
        )


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("business_menu", "0036_subscription_admin_override"),
    ]

    operations = [
        migrations.RunPython(validate_business_admin_identities, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="businessadmin",
            name="phone",
            field=models.CharField(db_index=True, help_text="Admin phone number", max_length=32),
        ),
        migrations.RunPython(normalize_business_admin_identities, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="businessadmin",
            name="phone",
            field=models.CharField(db_index=True, help_text="Admin phone number", max_length=32, unique=True),
        ),
        migrations.AlterField(
            model_name="businessadmin",
            name="email",
            field=models.EmailField(help_text="Unique account email", max_length=254),
        ),
        migrations.AddConstraint(
            model_name="businessadmin",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("email"),
                name="uniq_businessadmin_email_ci",
            ),
        ),
        migrations.AddConstraint(
            model_name="businessadmin",
            constraint=models.CheckConstraint(
                condition=models.Q(email=django.db.models.functions.text.Lower(django.db.models.functions.text.Trim("email")))
                & ~models.Q(email=""),
                name="businessadmin_email_canonical_nonempty",
            ),
        ),
    ]
