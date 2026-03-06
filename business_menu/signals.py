from __future__ import annotations

from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver

from .models import Restaurant, RestaurantSettings, MenuQRCode


@receiver(post_save, sender=Restaurant)
def ensure_restaurant_settings(sender, instance: Restaurant, created: bool, **kwargs):
    # Always ensure settings exist (idempotent)
    RestaurantSettings.objects.get_or_create(restaurant=instance)
    # Ensure each restaurant always has a unique QR token/menu URL.
    menu_qr, _ = MenuQRCode.objects.get_or_create(restaurant=instance)
    relative_url = f"/business-menu/qr/{menu_qr.token}/"
    if menu_qr.menu_url != relative_url:
        menu_qr.menu_url = relative_url
        menu_qr.save(update_fields=["menu_url"])


@receiver(post_migrate)
def backfill_restaurant_settings(sender, **kwargs):
    # After migrations, ensure every restaurant has settings + QR URL
    try:
        for r in Restaurant.objects.all().only("id"):
            RestaurantSettings.objects.get_or_create(restaurant=r)
            menu_qr, _ = MenuQRCode.objects.get_or_create(restaurant=r)
            relative_url = f"/business-menu/qr/{menu_qr.token}/"
            if menu_qr.menu_url != relative_url:
                menu_qr.menu_url = relative_url
                menu_qr.save(update_fields=["menu_url"])
    except Exception:
        # Avoid breaking migrations if tables aren't ready
        return

