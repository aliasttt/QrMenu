from __future__ import annotations

from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver

from .models import Restaurant, RestaurantSettings


@receiver(post_save, sender=Restaurant)
def ensure_restaurant_settings(sender, instance: Restaurant, created: bool, **kwargs):
    # Always ensure settings exist (idempotent)
    RestaurantSettings.objects.get_or_create(restaurant=instance)


@receiver(post_migrate)
def backfill_restaurant_settings(sender, **kwargs):
    # After migrations, ensure every restaurant has a settings row
    try:
        for r in Restaurant.objects.all().only("id"):
            RestaurantSettings.objects.get_or_create(restaurant=r)
    except Exception:
        # Avoid breaking migrations if tables aren't ready
        return

