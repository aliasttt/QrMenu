from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from business_menu.models import (
    BusinessAdmin,
    Category,
    CloudinaryImage,
    MenuItem,
    MenuItemImage,
    MenuQRCode,
    MenuTheme,
    Restaurant,
    RestaurantSettings,
)


class Command(BaseCommand):
    help = "Seed a demo restaurant 'mohsen club' with categories, items, images and QR URL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--phone",
            type=str,
            default="+495540225177",
            help="Business admin phone (default: +495540225177)",
        )

    def handle(self, *args, **options):
        phone = str(options["phone"]).strip()

        admin, _ = BusinessAdmin.objects.get_or_create(
            phone=phone,
            defaults={
                "name": "TestUser",
                "is_active": True,
                "payment_status": "paid",
            },
        )
        admin.name = "TestUser"
        admin.is_active = True
        admin.payment_status = "paid"
        admin.save(update_fields=["name", "is_active", "payment_status"])

        restaurant, _ = Restaurant.objects.get_or_create(
            admin=admin,
            defaults={
                "name": "mohsen club",
                "description": "Modern cafe menu for all-day dining.",
                "address": "Reichsstrasse 36, Berlin",
                "phone": phone,
                "is_active": True,
            },
        )
        restaurant.name = "mohsen club"
        if not (restaurant.description or "").strip():
            restaurant.description = "Modern cafe menu for all-day dining."
        if not (restaurant.address or "").strip():
            restaurant.address = "Reichsstrasse 36, Berlin"
        restaurant.phone = phone
        restaurant.is_active = True
        restaurant.save(update_fields=["name", "description", "address", "phone", "is_active"])

        settings_obj, _ = RestaurantSettings.objects.get_or_create(restaurant=restaurant)
        theme = MenuTheme.objects.filter(is_active=True).order_by("id").first()
        settings_obj.show_prices = True
        settings_obj.show_images = True
        settings_obj.show_descriptions = True
        settings_obj.show_serial = True
        settings_obj.menu_theme = theme
        settings_obj.save()

        menu_qr, _ = MenuQRCode.objects.get_or_create(restaurant=restaurant)
        menu_qr.menu_url = f"/business-menu/qr/{menu_qr.token}/"
        menu_qr.save(update_fields=["menu_url"])

        categories = [("Starters", 1), ("Main Dishes", 2), ("Drinks", 3), ("Desserts", 4)]
        category_map = {}
        for cat_name, order in categories:
            cat, _ = Category.objects.get_or_create(
                restaurant=restaurant,
                name=cat_name,
                defaults={"order": order, "is_active": True},
            )
            cat.order = order
            cat.is_active = True
            cat.save(update_fields=["order", "is_active"])
            category_map[cat_name] = cat

        items = [
            ("01", "Caesar Salad", "Starters", 8.90, "Romaine, parmesan, croutons, house dressing"),
            ("02", "Tomato Soup", "Starters", 6.50, "Creamy tomato soup with basil"),
            ("03", "Grilled Chicken Plate", "Main Dishes", 15.90, "Grilled chicken with seasonal vegetables"),
            ("04", "Beef Burger", "Main Dishes", 13.50, "Beef patty, cheddar, pickles, fries"),
            ("05", "Iced Latte", "Drinks", 4.80, "Cold espresso with milk and ice"),
            ("06", "Fresh Orange Juice", "Drinks", 4.20, "Freshly squeezed orange juice"),
            ("07", "Chocolate Brownie", "Desserts", 5.90, "Warm brownie with chocolate sauce"),
            ("08", "Cheesecake", "Desserts", 6.20, "Classic cheesecake with berry topping"),
        ]

        for index, (serial, name, cat_name, price, desc) in enumerate(items, 1):
            item, _ = MenuItem.objects.get_or_create(
                restaurant=restaurant,
                name=name,
                defaults={
                    "category": category_map[cat_name],
                    "description": desc,
                    "price": price,
                    "stock": "Available",
                    "is_available": True,
                    "order": index,
                    "serial": serial,
                },
            )
            item.category = category_map[cat_name]
            item.description = desc
            item.price = price
            item.stock = "Available"
            item.is_available = True
            item.order = index
            item.serial = serial
            item.save(
                update_fields=[
                    "category",
                    "description",
                    "price",
                    "stock",
                    "is_available",
                    "order",
                    "serial",
                ]
            )

            seed = f"{slugify(name)}-{item.id}"
            img_url = f"https://picsum.photos/seed/{seed}/900/700"
            public_id = f"mohsen-club/{seed}"
            cloud_img, _ = CloudinaryImage.objects.get_or_create(
                cloudinary_public_id=public_id,
                defaults={
                    "cloudinary_url": img_url,
                    "secure_url": img_url,
                    "format": "jpg",
                },
            )
            cloud_img.cloudinary_url = img_url
            cloud_img.secure_url = img_url
            cloud_img.format = "jpg"
            cloud_img.save(update_fields=["cloudinary_url", "secure_url", "format"])

            MenuItemImage.objects.get_or_create(
                menu_item=item,
                cloudinary_image=cloud_img,
                defaults={"order": 0},
            )

        self.stdout.write(self.style.SUCCESS("Seed completed for mohsen club"))
        self.stdout.write(self.style.SUCCESS(f"Restaurant ID: {restaurant.id}"))
        self.stdout.write(self.style.SUCCESS(f"Menu URL: https://preismenu.de/business-menu/qr/{menu_qr.token}/"))
