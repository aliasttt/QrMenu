from django.apps import AppConfig


class BusinessMenuConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'business_menu'
    verbose_name = 'Business Menu Management'

    def ready(self):  # pragma: no cover
        # Register signals (auto-create RestaurantSettings, etc.)
        from . import signals  # noqa: F401
