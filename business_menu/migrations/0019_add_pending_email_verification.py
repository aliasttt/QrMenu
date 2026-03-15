# Generated manually for PendingEmailVerification

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("business_menu", "0018_add_signup_by_ip"),
    ]

    operations = [
        migrations.CreateModel(
            name="PendingEmailVerification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(db_index=True, max_length=254)),
                ("code", models.CharField(max_length=6)),
                ("signup_data", models.JSONField(help_text="Validated signup form data (temporary, deleted after verify)")),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Pending email verification",
                "verbose_name_plural": "Pending email verifications",
                "ordering": ["-created_at"],
            },
        ),
    ]
