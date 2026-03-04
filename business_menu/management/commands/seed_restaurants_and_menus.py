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
        "کافه‌ای دنج با قهوه‌های تخصصی و دسرهای خانگی. فضای آرام برای کار و دورهمی.",
        "خیابان ولیعصر، پلاک ۱۲۳۴",
    ),
    (
        "رستوران باغ سبز",
        "رستوران ایرانی با فضای سبز و منوی گسترده از غذاهای اصیل و کباب‌های تازه.",
        "جردن، خیابان ناهید، کوچه دوم",
    ),
    (
        "Pizza Napoli",
        "پیتزا و پاستای ایتالیایی با مواد اولیه وارداتی و تنور سنتی.",
        "زعفرانیه، خیابان فلان",
    ),
]

# Per-restaurant: list of (category_name, [(item_name, description, price), ...])
MENU_DATA = [
    # Café Moka
    [
        ("قهوه و نوشیدنی‌ها", [
            ("اسپرسو", "اسپرسو تک شات ایتالیایی", Decimal("4.50")),
            ("لاته", "لاته با شیر تازه و آرت لتی", Decimal("6.00")),
            ("کاپوچینو", "کاپوچینو با پودر کاکائو", Decimal("5.50")),
            ("چای ماسالا", "چای هندی با ادویه و شیر", Decimal("5.00")),
            ("آیس لاته", "لاته سرد با یخ", Decimal("6.50")),
        ]),
        ("دسر و شیرینی", [
            ("چیزکیک", "چیزکیک نیویورکی با توت فرنگی", Decimal("8.00")),
            ("براونی", "براونی شکلاتی با گردو", Decimal("6.50")),
            ("کیک هویج", "کیک هویج با خامه پنیر", Decimal("7.00")),
            ("مافین بلوبری", "مافین تازه با بلوبری", Decimal("4.50")),
        ]),
        ("صبحانه", [
            ("صبحانه انگلیسی", "تخم مرغ، بیکن، لوبیا، نان تست", Decimal("12.00")),
            ("پنکیک با میوه", "پنکیک با عسل و میوه‌های فصل", Decimal("10.00")),
            ("اوتمیل", "جو دوسر با موز و عسل", Decimal("7.50")),
        ]),
    ],
    # رستوران باغ سبز
    [
        ("کباب‌ها", [
            ("کباب کوبیده", "کباب کوبیده مخلوط با برنج و گوجه", Decimal("18.00")),
            ("جوجه کباب", "جوجه کباب با برنج زعفرانی و کره", Decimal("16.00")),
            ("بختیاری", "نیم‌روز کوبیده و نیم‌روز جوجه", Decimal("20.00")),
            ("کباب برگ", "گوشت گوسفندی با برنج و سماق", Decimal("22.00")),
        ]),
        ("خوراک‌ها", [
            ("قورمه سبزی", "قورمه سبزی با لوبیا و برنج", Decimal("14.00")),
            ("زرشک پلو با مرغ", "مرغ زعفرانی با زرشک و برنج", Decimal("15.00")),
            ("فسنجان", "فسنجان با مرغ و گردو", Decimal("17.00")),
            ("باقالی پلو با مرغ", "مرغ با باقالی و برنج", Decimal("15.50")),
        ]),
        ("پیش‌غذا و سالاد", [
            ("ماست و خیار", "ماست با خیار و نعناع", Decimal("3.50")),
            ("سالاد شیرازی", "خیار، گوجه، پیاز با آبلیمو", Decimal("4.00")),
            ("سیرابی", "سیرابی با ادویه", Decimal("8.00")),
        ]),
    ],
    # Pizza Napoli
    [
        ("پیتزا", [
            ("مارگاریتا", "گوجه، موتزارلا، ریحان تازه", Decimal("12.00")),
            ("پپرونی", "پپرونی تند با پنیر اضافه", Decimal("14.00")),
            ("کواترو فورماژی", "چهار نوع پنیر ایتالیایی", Decimal("15.00")),
            ("سبزیجات گریل", "فلفل، قارچ، زیتون، گوجه", Decimal("13.00")),
            ("مارینارا", "سس گوجه با سیر و ریحان", Decimal("11.00")),
        ]),
        ("پاستا", [
            ("اسپاگتی کاربونارا", "بیکن، زرده تخم مرغ، پنیر پکورینو", Decimal("13.00")),
            ("پنه آلفردو", "سس آلفردو با مرغ و قارچ", Decimal("14.00")),
            ("لازانیا", "لایه‌های پاستا با رگه و پنیر", Decimal("14.50")),
        ]),
        ("نوشیدنی", [
            ("لیموناد", "لیموناد تازه با نعناع", Decimal("4.00")),
            ("آب پرتقال", "آب پرتقال تازه", Decimal("4.50")),
            ("سودا ایتالیانا", "سودا با طعم لیمو یا پرتقال", Decimal("3.50")),
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
