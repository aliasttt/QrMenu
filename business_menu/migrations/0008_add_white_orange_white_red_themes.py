# Generated on 2025-12-28

from django.db import migrations


def add_new_themes(apps, schema_editor):
    MenuTheme = apps.get_model("business_menu", "MenuTheme")

    themes = [
        {
            "name": "White Orange",
            "slug": "white-orange",
            "preview_static_path": "business_menu/themes/previews/white-orange.svg",
        },
        {
            "name": "White Red",
            "slug": "white-red",
            "preview_static_path": "business_menu/themes/previews/white-red.svg",
        },
    ]

    for t in themes:
        MenuTheme.objects.update_or_create(
            slug=t["slug"],
            defaults={
                "name": t["name"],
                "preview_static_path": t["preview_static_path"],
                "is_active": True,
            },
        )


def remove_new_themes(apps, schema_editor):
    MenuTheme = apps.get_model("business_menu", "MenuTheme")
    MenuTheme.objects.filter(slug__in=["white-orange", "white-red"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("business_menu", "0007_seed_menu_themes"),
    ]

    operations = [
        migrations.RunPython(add_new_themes, reverse_code=remove_new_themes),
    ]
