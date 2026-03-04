"""
Seed sample restaurants/cafes and menu items for the public restaurants list page.
Usage: python manage.py seed_restaurants_and_menus
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction

from business_menu.models import BusinessAdmin, Restaurant, Category, MenuItem


# Sample data: (restaurant/cafe name, description, address)
RESTAURANTS = [
    (
        "Café Moka",
        "A cozy café with specialty coffees and homemade desserts. Quiet space for work and meetups.",
        "123 Main Street, Downtown",
    ),
    (
        "Sabz Garden Restaurant",
        "Iranian restaurant with a green setting and a wide menu of authentic dishes and fresh kebabs.",
        "Jordan, Nahid Street, Alley 2",
    ),
    (
        "Pizza Napoli",
        "Italian pizza and pasta with imported ingredients and a traditional wood-fired oven.",
        "Zaferanieh, Oak Avenue",
    ),
]

# Per-restaurant: list of (category_name, [(item_name, description, price), ...])
MENU_DATA = [
    # Café Moka
    [
        ("Coffee & Drinks", [
            ("Espresso", "Single shot Italian espresso", Decimal("4.50")),
            ("Latte", "Latte with fresh milk and latte art", Decimal("6.00")),
            ("Cappuccino", "Cappuccino with cocoa powder", Decimal("5.50")),
            ("Chai Masala", "Indian tea with spices and milk", Decimal("5.00")),
            ("Iced Latte", "Cold latte over ice", Decimal("6.50")),
        ]),
        ("Desserts & Pastries", [
            ("Cheesecake", "New York cheesecake with strawberry", Decimal("8.00")),
            ("Brownie", "Chocolate brownie with walnuts", Decimal("6.50")),
            ("Carrot Cake", "Carrot cake with cream cheese frosting", Decimal("7.00")),
            ("Blueberry Muffin", "Fresh muffin with blueberries", Decimal("4.50")),
        ]),
        ("Breakfast", [
            ("English Breakfast", "Eggs, bacon, beans, toast", Decimal("12.00")),
            ("Pancakes with Fruit", "Pancakes with honey and seasonal fruit", Decimal("10.00")),
            ("Oatmeal", "Oats with banana and honey", Decimal("7.50")),
        ]),
    ],
    # Sabz Garden Restaurant
    [
        ("Kebabs", [
            ("Koobideh Kebab", "Mixed kebab with rice and tomato", Decimal("18.00")),
            ("Chicken Kebab", "Chicken kebab with saffron rice and butter", Decimal("16.00")),
            ("Bakhtiari", "Half koobideh, half chicken kebab", Decimal("20.00")),
            ("Barg Kebab", "Lamb kebab with rice and sumac", Decimal("22.00")),
        ]),
        ("Stews & Rice", [
            ("Ghormeh Sabzi", "Herb stew with kidney beans and rice", Decimal("14.00")),
            ("Zereshk Polo ba Morgh", "Saffron chicken with barberry rice", Decimal("15.00")),
            ("Fesenjan", "Pomegranate walnut stew with chicken", Decimal("17.00")),
            ("Baghali Polo ba Morgh", "Chicken with fava bean rice", Decimal("15.50")),
        ]),
        ("Starters & Salad", [
            ("Mast-o-Khiar", "Yogurt with cucumber and mint", Decimal("3.50")),
            ("Salad Shirazi", "Cucumber, tomato, onion with lime", Decimal("4.00")),
            ("Tripe", "Seasoned tripe", Decimal("8.00")),
        ]),
    ],
    # Pizza Napoli
    [
        ("Pizza", [
            ("Margherita", "Tomato, mozzarella, fresh basil", Decimal("12.00")),
            ("Pepperoni", "Spicy pepperoni with extra cheese", Decimal("14.00")),
            ("Quattro Formaggi", "Four Italian cheeses", Decimal("15.00")),
            ("Grilled Vegetables", "Pepper, mushroom, olive, tomato", Decimal("13.00")),
            ("Marinara", "Tomato sauce with garlic and basil", Decimal("11.00")),
        ]),
        ("Pasta", [
            ("Spaghetti Carbonara", "Bacon, egg yolk, pecorino", Decimal("13.00")),
            ("Penne Alfredo", "Alfredo sauce with chicken and mushroom", Decimal("14.00")),
            ("Lasagna", "Layers of pasta with ragù and cheese", Decimal("14.50")),
        ]),
        ("Drinks", [
            ("Lemonade", "Fresh lemonade with mint", Decimal("4.00")),
            ("Orange Juice", "Fresh orange juice", Decimal("4.50")),
            ("Italian Soda", "Soda with lemon or orange flavor", Decimal("3.50")),
        ]),
    ],
]


class Command(BaseCommand):
    help = "Create sample restaurants/cafes and menu items for the public list and menu pages."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all restaurants (and their menus) created by this seed before creating new ones.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["clear"]:
            self._clear_seeded()
            return

        base_phone = "+9891234500"
        created_restaurants = 0
        created_items = 0

        for idx, (r_name, r_desc, r_address) in enumerate(RESTAURANTS):
            phone = f"{base_phone}{idx:02d}"
            admin, admin_created = BusinessAdmin.objects.get_or_create(
                phone=phone,
                defaults={
                    "name": f"Admin {r_name[:20]}",
                    "email": f"seed-{idx}@example.com",
                    "is_active": True,
                    "payment_status": "paid",
                },
            )
            if not admin_created:
                restaurant = getattr(admin, "restaurant", None)
                if restaurant:
                    self.stdout.write(
                        self.style.WARNING(f"Restaurant id={restaurant.id} already exists, skip.")
                    )
                    continue

            restaurant = Restaurant.objects.create(
                admin=admin,
                name=r_name,
                description=r_desc,
                address=r_address,
                phone=phone,
                is_active=True,
            )
            created_restaurants += 1
            self.stdout.write(self.style.SUCCESS(f"Created restaurant id={restaurant.id}"))

            menu_data = MENU_DATA[idx] if idx < len(MENU_DATA) else []
            for cat_name, items in menu_data:
                category = Category.objects.create(
                    restaurant=restaurant,
                    name=cat_name,
                    order=len(restaurant.categories.all()),
                    is_active=True,
                )
                for order, (item_name, item_desc, price) in enumerate(items):
                    MenuItem.objects.create(
                        restaurant=restaurant,
                        category=category,
                        name=item_name,
                        description=item_desc,
                        price=price,
                        is_available=True,
                        order=order,
                    )
                    created_items += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Restaurants: {created_restaurants}, Menu items: {created_items}."
            )
        )
        self.stdout.write(
            self.style.SUCCESS("Visit /restaurants/ to see the list and open menus.")
        )

    def _clear_seeded(self):
        base_phone = "+9891234500"
        deleted = 0
        for idx in range(len(RESTAURANTS)):
            phone = f"{base_phone}{idx:02d}"
            try:
                admin = BusinessAdmin.objects.get(phone=phone)
                if hasattr(admin, "restaurant"):
                    admin.restaurant.delete()
                    deleted += 1
                admin.delete()
            except BusinessAdmin.DoesNotExist:
                pass
        self.stdout.write(self.style.SUCCESS(f"Cleared {deleted} seeded restaurants and admins."))
