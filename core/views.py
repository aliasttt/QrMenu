import json

from django.shortcuts import render, get_object_or_404, redirect
from django.http import Http404
from django.contrib.auth import authenticate, login as auth_login

from django.utils import timezone
from business_menu.models import Restaurant, MenuItem, RestaurantSettings, MenuTheme, Order, BusinessAdmin
from business_menu.hours_utils import (
    is_within_opening_hours,
    is_datetime_within_hours,
    get_open_days,
    get_slots_for_day,
)


def _restaurant_payload(restaurant_slug="orange-bistro"):
    restaurant = {
        "id": 101,
        "name": "Orange Bistro",
        "slug": restaurant_slug,
        "address": "123 Main St, Midtown",
        "phone": "+1 (555) 128-9981",
        "hours": "09:00 - 23:00",
        "rating": 4.8,
    }

    categories = [
        {"id": 1, "name": "Starters", "slug": "starters"},
        {"id": 2, "name": "Main Dishes", "slug": "main-dishes"},
        {"id": 3, "name": "Desserts", "slug": "desserts"},
        {"id": 4, "name": "Drinks", "slug": "drinks"},
    ]

    menu_items = [
        {
            "id": 1,
            "name": "Truffle Fries",
            "price": 8.50,
            "category_slug": "starters",
            "image_url": "https://picsum.photos/seed/fries/640/480",
            "tags": ["Popular", "Vegetarian"],
        },
        {
            "id": 2,
            "name": "Bruschetta",
            "price": 7.00,
            "category_slug": "starters",
            "image_url": "https://picsum.photos/seed/bruschetta/640/480",
            "tags": ["Vegan"],
        },
        {
            "id": 3,
            "name": "Grilled Salmon",
            "price": 18.90,
            "category_slug": "main-dishes",
            "image_url": "https://picsum.photos/seed/salmon/640/480",
            "tags": ["Chef Choice"],
        },
        {
            "id": 4,
            "name": "Steak Frites",
            "price": 24.00,
            "category_slug": "main-dishes",
            "image_url": "https://picsum.photos/seed/steak/640/480",
            "tags": ["High Protein"],
        },
        {
            "id": 5,
            "name": "Chocolate Lava Cake",
            "price": 9.00,
            "category_slug": "desserts",
            "image_url": "https://picsum.photos/seed/lava/640/480",
            "tags": ["Sweet"],
        },
        {
            "id": 6,
            "name": "Iced Latte",
            "price": 5.50,
            "category_slug": "drinks",
            "image_url": "https://picsum.photos/seed/latte/640/480",
            "tags": ["Cold Brew"],
        },
    ]

    cart_items = [
        {"id": 1, "name": "Truffle Fries", "qty": 1, "price": 8.50},
        {"id": 6, "name": "Iced Latte", "qty": 2, "price": 5.50},
    ]
    cart_subtotal = round(sum(item["qty"] * item["price"] for item in cart_items), 2)

    return {
        "restaurant": restaurant,
        "categories": categories,
        "menu_items": menu_items,
        "cart_items": cart_items,
        "cart_subtotal": cart_subtotal,
    }


def landing(request):
    testimonials = [
        {"name": "Nina Park", "role": "Owner, Basil House", "quote": "We increased table turnover with faster ordering."},
        {"name": "Armin Cole", "role": "Manager, South Fork", "quote": "Campaigns helped us fill off-peak hours."},
        {"name": "Lara Kim", "role": "Founder, Luna Cafe", "quote": "Our staff now spends less time taking manual orders."},
    ]
    features = [
        "AI menu import",
        "Multilingual menus",
        "QR code generation",
        "Order management",
        "Campaign engine",
        "Daily analytics",
        "Category controls",
        "Live availability",
        "POS-ready payloads",
        "Mobile-first pages",
        "Role-ready panel",
        "Conversion focused UI",
    ]
    return render(
        request,
        "pages/landing.html",
        {"testimonials": testimonials, "features": features},
    )


def features(request):
    feature_list = [
        {"title": "AI menu import", "desc": "Upload a PDF or photo and we extract your dishes and prices automatically.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z\"/></svg>"},
        {"title": "Multilingual menus", "desc": "Serve your menu in multiple languages and switch by customer preference.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18m8.129-8.5A18.022 18.022 0 0119.588 9\"/></svg>"},
        {"title": "QR code generation", "desc": "Generate and download QR codes for tables, takeaway, and delivery.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M12 4v1m6 11h2m-6 0h-2v4m0-11v3m0 0h.01M12 12h4.01M16 20h4M4 12h4m12 0h.01M5 8h2a1 1 0 001-1V5a1 1 0 00-1-1H5a1 1 0 00-1 1v2a1 1 0 001 1zm12 0h2a1 1 0 001-1V5a1 1 0 00-1-1h-2a1 1 0 00-1 1v2a1 1 0 001 1zM5 20h2a1 1 0 001-1v-2a1 1 0 00-1-1H5a1 1 0 00-1 1v2a1 1 0 001 1z\"/></svg>"},
        {"title": "Order management", "desc": "Receive, track, and fulfill orders from one dashboard with status updates.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01\"/></svg>"},
        {"title": "Campaign engine", "desc": "Create time-based discounts, happy hours, and target specific categories.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M15 5v2m0 4v2m0 4v2M5 5a2 2 0 00-2 2v3a2 2 0 110 4v3a2 2 0 002 2h14a2 2 0 002-2v-3a2 2 0 110-4V7a2 2 0 00-2-2H5z\"/></svg>"},
        {"title": "Daily analytics", "desc": "View orders, revenue, and top items with simple charts and exports.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z\"/></svg>"},
        {"title": "Category controls", "desc": "Organize items into categories and reorder with drag-and-drop.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M4 6h16M4 10h16M4 14h16M4 18h16\"/></svg>"},
        {"title": "Live availability", "desc": "Mark items as out of stock and hide or show sections by schedule.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z\"/></svg>"},
        {"title": "POS-ready payloads", "desc": "Send orders to your POS or kitchen display via webhooks or API.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z\"/><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M15 12a3 3 0 11-6 0 3 3 0 016 0z\"/></svg>"},
        {"title": "Mobile-first pages", "desc": "Menus and checkout are optimized for phones and tablets.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z\"/></svg>"},
        {"title": "Role-ready panel", "desc": "Invite staff with roles: admin, manager, or view-only.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z\"/></svg>"},
        {"title": "Conversion focused UI", "desc": "Clean design and clear CTAs to maximize add-to-cart and checkout.", "icon": "<svg class=\"h-6 w-6\" fill=\"none\" stroke=\"currentColor\" viewBox=\"0 0 24 24\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"2\" d=\"M13 10V3L4 14h7v7l9-11h-7z\"/></svg>"},
    ]
    faqs = [
        {"q": "Can I use my own domain?", "a": "Yes. You can connect a custom domain (e.g. menu.yourrestaurant.com) from the settings panel."},
        {"q": "Is there a mobile app for staff?", "a": "The panel is fully responsive; you can use it from any browser. Native apps are on our roadmap."},
        {"q": "How do I print QR codes?", "a": "Generate QR codes from the dashboard and download as PNG or SVG. Print on table tents or stickers."},
        {"q": "Do you integrate with POS?", "a": "We support webhooks and an API so you can push orders to your POS or kitchen display system."},
    ]
    return render(request, "pages/features.html", {"feature_list": feature_list, "faqs": faqs})


def how_it_works(request):
    steps = [
        {"num": 1, "title": "Set up your menu", "desc": "Create categories, add dishes with prices and photos, and set availability.", "detail": "Drag-and-drop reorder, bulk edit, or import from spreadsheet."},
        {"num": 2, "title": "Generate your QR", "desc": "Print QR codes for each table or area. Customers scan to open your menu.", "detail": "Download PNG or SVG, print on table tents or stickers."},
        {"num": 3, "title": "Get online orders", "desc": "Customers browse, add to cart, and checkout. You receive and fulfill orders.", "detail": "Optional: connect to POS or kitchen display."},
    ]
    return render(request, "pages/how_it_works.html", {"steps": steps})


def pricing(request):
    """Single annual plan: €200 + 19% VAT = €238 total. Motivating benefits for restaurant owners."""
    plan = {
        "price_eur": "200",
        "price_with_vat_eur": "238",
        "features": [
            "QR menu — customers scan and browse your menu on their phone",
            "Unlimited menu items and categories",
            "Unlimited QR codes for tables and takeaway",
            "Online ordering — guests order and pay from the same link",
            "Customizable themes to match your brand",
            "Campaigns & discounts (happy hour, daily specials)",
            "Multilingual menu support",
            "Real-time updates — change prices and availability instantly",
            "Basic analytics — see what sells",
            "Email & WhatsApp support",
        ],
    }
    benefits = [
        {"title": "Win more orders", "text": "Guests order directly from the QR menu. No waiting for staff—faster turnover and higher revenue."},
        {"title": "Look professional", "text": "A clean digital menu and your own domain build trust. Stand out from competitors still using paper."},
        {"title": "One subscription, everything included", "text": "No per-order fees or hidden costs. One annual fee covers menu, ordering, and support."},
        {"title": "Launch in minutes", "text": "Add your dishes, print a QR code, and go live. No IT or design skills needed."},
    ]
    faqs = [
        {"q": "What is included in the price?", "a": "Everything: QR menu, online ordering, unlimited items and QR codes, campaigns, custom domain option, themes, and support. One annual subscription, no per-order fees."},
        {"q": "Is there a free trial?", "a": "Yes. Start with a free trial to build your menu and test ordering. No card required until you go live."},
        {"q": "Why 19% VAT?", "a": "We are VAT-registered in the EU. If you are in the EU and liable for VAT, 19% is added at checkout (total €238/year). If you are outside the EU or VAT-exempt, the amount may differ."},
    ]
    return render(request, "pages/pricing.html", {"plan": plan, "benefits": benefits, "faqs": faqs})


def contact(request):
    return render(request, "pages/contact.html")


SERVICE_PAGES = [
    {
        "slug": "ai-menu-import",
        "title": "AI Menu Import",
        "tagline": "Turn paper menus into digital menus in minutes.",
        "summary": "Upload a photo or PDF and let AI extract dish names, descriptions, and prices automatically.",
        "hero_image": "https://images.unsplash.com/photo-1489515217757-5fd1be406fef?w=1400&q=80",
        "benefits": [
            "Save hours of manual typing",
            "Launch your QR menu faster",
            "Reduce human data-entry errors",
        ],
    },
    {
        "slug": "customizable-themes",
        "title": "Customizable Themes",
        "tagline": "Match your menu design to your restaurant brand.",
        "summary": "Choose from modern themes and customize colors, typography, and layout in a few clicks.",
        "hero_image": "https://images.unsplash.com/photo-1558655146-9f40138edfeb?w=1400&q=80",
        "benefits": [
            "Consistent brand identity",
            "Better visual experience for guests",
            "Faster edits with pre-built styles",
        ],
    },
    {
        "slug": "dedicated-support",
        "title": "Dedicated Support",
        "tagline": "Real help when you need it most.",
        "summary": "Our team helps with setup, menu updates, and optimization so your staff can focus on service.",
        "hero_image": "https://images.unsplash.com/photo-1521737604893-d14cc237f11d?w=1400&q=80",
        "benefits": [
            "Priority support for urgent issues",
            "Faster onboarding for new branches",
            "Better uptime and smoother operations",
        ],
    },
    {
        "slug": "menu-creation",
        "title": "Menu Creation",
        "tagline": "Build clean, organized menus your guests love.",
        "summary": "Create categories, add dish photos, set prices, and reorder items with a simple dashboard.",
        "hero_image": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=1400&q=80",
        "benefits": [
            "Unlimited menu items",
            "Quick editing for daily changes",
            "Clear structure for better ordering",
        ],
    },
    {
        "slug": "multi-service-management",
        "title": "Multi-Service Management",
        "tagline": "Run dine-in, takeaway, and delivery from one panel.",
        "summary": "Manage service types, availability, and order flow in one place without switching tools.",
        "hero_image": "https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?w=1400&q=80",
        "benefits": [
            "One dashboard for all channels",
            "Less staff confusion",
            "Higher operational speed",
        ],
    },
    {
        "slug": "multilingual-support",
        "title": "Multilingual Support",
        "tagline": "Serve local and international guests better.",
        "summary": "Offer your menu in multiple languages and let customers switch language instantly.",
        "hero_image": "https://images.unsplash.com/photo-1455390582262-044cdead277a?w=1400&q=80",
        "benefits": [
            "Better guest experience for tourists",
            "Fewer ordering mistakes",
            "Higher conversion on the menu page",
        ],
    },
    {
        "slug": "online-ordering",
        "title": "Online Ordering",
        "tagline": "Take orders directly from the QR menu.",
        "summary": "Guests browse, add to cart, and checkout from their phone with a smooth mobile-first flow.",
        "hero_image": "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=1400&q=80",
        "benefits": [
            "Increase average order value",
            "Reduce table waiting time",
            "Capture more takeaway orders",
        ],
    },
    {
        "slug": "pdf-export",
        "title": "PDF Export",
        "tagline": "Keep digital and printed menus in sync.",
        "summary": "Export your latest menu as PDF for table cards, flyers, and offline sharing.",
        "hero_image": "https://images.unsplash.com/photo-1517842645767-c639042777db?w=1400&q=80",
        "benefits": [
            "Ready-to-print output",
            "Consistent branding across channels",
            "Simple backup of menu data",
        ],
    },
    {
        "slug": "real-time-updates",
        "title": "Real-Time Updates",
        "tagline": "Update prices and stock instantly.",
        "summary": "Publish menu changes live in seconds so guests always see accurate information.",
        "hero_image": "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=1400&q=80",
        "benefits": [
            "No stale menu data",
            "Fewer customer complaints",
            "Faster reaction to peak-hour demand",
        ],
    },
    {
        "slug": "secure-payment-processing",
        "title": "Secure Payment Processing",
        "tagline": "Accept payments safely and confidently.",
        "summary": "Support secure online checkout with trusted gateways and encrypted transaction flow.",
        "hero_image": "https://images.unsplash.com/photo-1563013544-824ae1b704d3?w=1400&q=80",
        "benefits": [
            "Safer transactions",
            "More trust from customers",
            "Higher checkout completion",
        ],
    },
    {
        "slug": "smart-order-management",
        "title": "Smart Order Management",
        "tagline": "Track every order in one clean queue.",
        "summary": "Filter by status, prioritize prep, and keep front-of-house and kitchen fully synchronized.",
        "hero_image": "https://images.unsplash.com/photo-1461344577544-4e5dc9487184?w=1400&q=80",
        "benefits": [
            "Clear workflow for staff",
            "Faster fulfillment",
            "Improved customer satisfaction",
        ],
    },
]


def services(request):
    """Services hub page with cards linking to each dedicated service page."""
    return render(request, "pages/services.html", {"service_pages": SERVICE_PAGES})


def service_detail(request, service_slug):
    """Dedicated marketing page for a single service."""
    service = next((item for item in SERVICE_PAGES if item["slug"] == service_slug), None)
    if not service:
        raise Http404("Service not found")
    return render(
        request,
        "pages/service_detail.html",
        {"service": service, "service_pages": SERVICE_PAGES},
    )


def restaurants_list(request):
    """صفحهٔ لیست رستوران‌ها / کافه‌ها به صورت کارت."""
    restaurants = Restaurant.objects.filter(is_active=True).order_by("name")
    return render(request, "pages/restaurants_list.html", {"restaurants": restaurants})


def _ensure_restaurant_settings_columns():
    """اگر ستون‌های has_delivery و ... در جدول نباشند (مایگریشن روی سرور اجرا نشده)، با raw SQL اضافه می‌کند."""
    from django.db import connection
    vendor = connection.vendor
    if vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'business_menu_restaurantsettings' AND column_name = 'has_delivery';
        """)
        if cursor.fetchone():
            return
        for col, default in [
            ("has_delivery", "false"),
            ("allow_payment_cash", "true"),
            ("allow_payment_online", "true"),
        ]:
            cursor.execute(
                f"ALTER TABLE business_menu_restaurantsettings ADD COLUMN IF NOT EXISTS {col} boolean DEFAULT {default} NOT NULL;"
            )


def restaurant_menu(request, restaurant_id):
    """صفحهٔ منوی یک رستوران — تنظیمات و تم از اپ اعمال می‌شود."""
    # اگر مایگریشن روی سرور اجرا نشده باشد، ستون‌های جدید را با raw SQL اضافه کن (فقط PostgreSQL)
    try:
        _ensure_restaurant_settings_columns()
    except Exception:
        pass
    restaurant = get_object_or_404(
        Restaurant.objects.select_related("admin", "settings", "settings__menu_theme"),
        pk=restaurant_id,
        is_active=True,
    )
    settings_obj, _ = RestaurantSettings.objects.get_or_create(
        restaurant=restaurant,
        defaults={
            "show_prices": True,
            "show_images": True,
            "show_descriptions": True,
            "show_serial": False,
            "has_delivery": False,
            "allow_payment_cash": True,
            "allow_payment_online": True,
        },
    )
    if settings_obj.menu_theme_id is None:
        classic = MenuTheme.objects.filter(slug="classic", is_active=True).first()
        if classic:
            settings_obj.menu_theme = classic
            settings_obj.save(update_fields=["menu_theme"])
    theme_slug = "theme--classic"
    if settings_obj.menu_theme and getattr(settings_obj.menu_theme, "slug", None):
        theme_slug = f"theme--{settings_obj.menu_theme.slug}"

    items = (
        MenuItem.objects.filter(restaurant=restaurant, is_available=True)
        .select_related("category")
        .prefetch_related("images", "images__cloudinary_image")
    )
    if getattr(settings_obj, "show_serial", False):
        if items.exclude(serial__isnull=True).exclude(serial="").exists():
            items = items.order_by("serial", "order", "name")
        else:
            items = items.order_by("order", "name")
    else:
        items = items.order_by("order", "name")
    menu_cards = []
    sections_map = {}
    show_images = getattr(settings_obj, "show_images", True)
    for item in items:
        img_url = None
        if show_images:
            first_img = item.images.first()
            if first_img:
                img_url = first_img.get_image_url(request=request)
        if not img_url:
            img_url = f"https://picsum.photos/seed/menu-{item.id}/640/400"
        category_key = str(item.category.id) if item.category else "other"
        category_name = item.category.name if item.category else "Other"
        menu_cards.append({
            "id": item.id,
            "name": item.name,
            "description": item.description or "",
            "price": item.price,
            "image_url": img_url,
            "category_id": category_key,
            "category_name": category_name,
            "serial": getattr(item, "serial", None) or "",
            "stock": getattr(item, "stock", None) or "",
        })

        if category_key not in sections_map:
            sections_map[category_key] = {
                "id": category_key,
                "name": category_name,
                "items": [],
            }
        sections_map[category_key]["items"].append(menu_cards[-1])

    menu_sections = list(sections_map.values())
    category_list = []
    for sec in menu_sections:
        thumb = sec["items"][0]["image_url"] if sec["items"] else ""
        category_list.append({
            "id": sec["id"],
            "name": sec["name"],
            "count": len(sec["items"]),
            "thumb": thumb,
        })

    # Use first menu images as top banner gallery (if available).
    banner_images = []
    for card in menu_cards:
        img = card.get("image_url")
        if img and img not in banner_images:
            banner_images.append(img)
        if len(banner_images) >= 3:
            break

    restaurant_hours = getattr(settings_obj, "opening_hours", None) or getattr(restaurant, "hours", None) or ""
    is_within_hours = is_within_opening_hours(settings_obj)
    scheduled_for = (request.GET.get("scheduled_for") or "").strip()
    # If customer chose a future time from schedule page, allow ordering even when "now" is closed
    if scheduled_for:
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00").split("+")[0].split(".")[0])
            if dt > datetime.now() and is_datetime_within_hours(settings_obj, dt):
                is_within_hours = True
            else:
                scheduled_for = ""
        except (ValueError, TypeError):
            scheduled_for = ""
    # سبد و گزینه‌های سفارش برای پنل Orders (همان کلید سشن business_menu)
    cart_key = f"cart_restaurant_{restaurant.id}"
    cart_items = list(request.session.get(cart_key, []))
    order_options = {
        "has_delivery": getattr(settings_obj, "has_delivery", False),
        "allow_payment_cash": getattr(settings_obj, "allow_payment_cash", True),
        "allow_payment_online": getattr(settings_obj, "allow_payment_online", True),
    }
    return render(
        request,
        "pages/restaurant_menu.html",
        {
            "restaurant": restaurant,
            "restaurant_hours": restaurant_hours,
            "is_within_hours": is_within_hours,
            "scheduled_for": scheduled_for,
            "schedule_url": f"/restaurants/{restaurant_id}/schedule/",
            "menu_cards": menu_cards,
            "menu_sections": menu_sections,
            "category_list": category_list,
            "banner_images": banner_images,
            "theme_slug": theme_slug,
            "settings": settings_obj,
            "packages": [],
            "cart_items": cart_items,
            "order_options": order_options,
        },
    )


def public_menu(request, restaurant_slug):
    payload = _restaurant_payload(restaurant_slug)
    payload["checkout_url"] = f"/m/{restaurant_slug}/checkout/"
    payload["cart_items_json"] = json.dumps(payload["cart_items"])
    return render(request, "pages/public_menu.html", payload)


def checkout(request, restaurant_slug):
    payload = _restaurant_payload(restaurant_slug)
    payload["cart_items_json"] = json.dumps(payload["cart_items"])
    return render(request, "pages/checkout.html", payload)


def login_view(request):
    """GET: show login form. POST: email + password → authenticate restaurant owner, session login, redirect to panel."""
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        password = request.POST.get("password") or ""
        if not email or not password:
            return render(
                request,
                "pages/auth/login.html",
                {"error": "Email and password are required.", "email": email},
            )
        # Find BusinessAdmin by email, then get linked User
        admin = BusinessAdmin.objects.filter(email__iexact=email).first()
        if not admin:
            from django.contrib.auth.models import User
            user_by_email = User.objects.filter(email__iexact=email).first()
            if user_by_email:
                try:
                    admin = user_by_email.business_menu_admin
                except BusinessAdmin.DoesNotExist:
                    admin = None
        if not admin:
            return render(
                request,
                "pages/auth/login.html",
                {"error": "No restaurant account found with this email.", "email": email},
            )
        user = admin.auth_user
        if not user:
            return render(
                request,
                "pages/auth/login.html",
                {"error": "Account not set up. Please contact support.", "email": email},
            )
        auth_user = authenticate(request, username=user.username, password=password)
        if auth_user is not None:
            auth_login(request, auth_user)
            admin_id = admin.id
            return redirect(f"/panel/?admin_id={admin_id}")
        return render(
            request,
            "pages/auth/login.html",
            {"error": "Invalid password.", "email": email},
        )
    return render(request, "pages/auth/login.html", {})


def register_view(request):
    return render(request, "pages/auth/register.html")


def panel_dashboard(request):
    """Simple panel: plan status, payment/Stripe, app download links. Use ?admin_id=X to identify owner."""
    admin_id = request.GET.get("admin_id")
    if admin_id:
        try:
            admin = BusinessAdmin.objects.get(id=int(admin_id))
        except (ValueError, BusinessAdmin.DoesNotExist):
            admin = None
        if admin:
            now = timezone.now()
            payment_status = admin.payment_status
            is_trial = payment_status == "trial"
            trial_active = is_trial and admin.trial_ends_at and now < admin.trial_ends_at
            is_paid = payment_status == "paid"
            subscription_active = is_paid and (not admin.subscription_ends_at or admin.subscription_ends_at > now)
            plan_active = trial_active or subscription_active
            expires_at = None
            if is_trial and admin.trial_ends_at:
                expires_at = admin.trial_ends_at
            elif is_paid and admin.subscription_ends_at:
                expires_at = admin.subscription_ends_at
            from django.conf import settings
            return render(
                request,
                "pages/panel/dashboard_simple.html",
                {
                    "admin": admin,
                    "admin_id": admin.id,
                    "restaurant_name": getattr(admin.restaurant, "name", "") if hasattr(admin, "restaurant") and admin.restaurant else "",
                    "plan_active": plan_active,
                    "payment_status": payment_status,
                    "trial_active": trial_active,
                    "subscription_active": subscription_active,
                    "expires_at": expires_at,
                    "stripe_connected": bool(admin.stripe_account_id),
                    "subscribe_url": f"/business-menu/subscribe/?admin_id={admin.id}",
                    "connect_stripe_url": f"/business-menu/connect/?admin_id={admin.id}",
                    "app_android_url": getattr(settings, "APP_ANDROID_URL", "") or getattr(settings, "QR_MENU_APK_DEFAULT_URL", "https://example.com/app.apk"),
                    "app_ios_url": getattr(settings, "APP_IOS_URL", "https://apps.apple.com/app/id000000000"),
                },
            )
    # Fallback: show minimal dashboard without admin (e.g. link to login/register)
    from django.conf import settings
    return render(
        request,
        "pages/panel/dashboard_simple.html",
        {
            "admin": None,
            "admin_id": None,
            "restaurant_name": "",
            "plan_active": False,
            "payment_status": "",
            "trial_active": False,
            "subscription_active": False,
            "expires_at": None,
            "stripe_connected": False,
            "subscribe_url": "",
            "connect_stripe_url": "",
            "app_android_url": getattr(settings, "APP_ANDROID_URL", "") or getattr(settings, "QR_MENU_APK_DEFAULT_URL", ""),
            "app_ios_url": getattr(settings, "APP_IOS_URL", "https://apps.apple.com/app/id000000000"),
        },
    )


def panel_settings(request):
    payload = _restaurant_payload()
    payload["settings_crumbs"] = [{"label": "Panel", "url": "/panel/"}, {"label": "Settings", "url": ""}]
    return render(request, "pages/panel/settings.html", payload)


def panel_categories(request):
    payload = _restaurant_payload()
    payload["categories_crumbs"] = [{"label": "Panel", "url": "/panel/"}, {"label": "Categories", "url": ""}]
    return render(request, "pages/panel/categories.html", payload)


def panel_menu_items(request):
    payload = _restaurant_payload()
    payload["menu_items_crumbs"] = [{"label": "Panel", "url": "/panel/"}, {"label": "Menu Items", "url": ""}]
    return render(request, "pages/panel/menu_items_list.html", payload)


def panel_menu_item_form(request, item_id=None):
    payload = _restaurant_payload()
    selected_item = None
    if item_id is not None:
        selected_item = next((item for item in payload["menu_items"] if item["id"] == item_id), None)
    payload["item"] = selected_item
    payload["menu_item_form_crumbs"] = [
        {"label": "Panel", "url": "/panel/"},
        {"label": "Menu Items", "url": "/panel/menu-items/"},
        {"label": "Edit Item" if selected_item else "New Item", "url": ""},
    ]
    return render(request, "pages/panel/menu_item_form.html", payload)


def panel_campaigns(request):
    campaigns = [
        {"name": "Lunch Combo 20% Off", "status": "Active", "dates": "Mar 1 - Mar 20", "discount": "20%", "target": "Main Dishes"},
        {"name": "Happy Hour Drinks", "status": "Scheduled", "dates": "Mar 10 - Mar 30", "discount": "15%", "target": "Drinks"},
        {"name": "Dessert Friday", "status": "Expired", "dates": "Feb 1 - Feb 28", "discount": "10%", "target": "Desserts"},
    ]
    return render(
        request,
        "pages/panel/campaigns.html",
        {
            "campaigns": campaigns,
            "campaigns_crumbs": [{"label": "Panel", "url": "/panel/"}, {"label": "Campaigns", "url": ""}],
        },
    )


def restaurant_schedule(request, restaurant_id):
    """Schedule page: pick a future date/time when restaurant is open (for ordering when currently closed)."""
    restaurant = get_object_or_404(Restaurant, pk=restaurant_id, is_active=True)
    settings_obj, _ = RestaurantSettings.objects.get_or_create(
        restaurant=restaurant,
        defaults={
            "show_prices": True,
            "show_images": True,
            "show_descriptions": True,
            "show_serial": False,
            "has_delivery": False,
            "allow_payment_cash": True,
            "allow_payment_online": True,
        },
    )
    restaurant_hours = getattr(settings_obj, "opening_hours", None) or ""
    hours_json = getattr(settings_obj, "opening_hours_json", None) or []
    open_days = get_open_days(settings_obj) if hours_json else set(range(7))
    from datetime import datetime, date, timedelta, time as dt_time

    # Build next 14 days with their slots (simplified: one slot per day = first open/close)
    days_with_slots = []
    today = date.today()
    for i in range(14):
        d = today + timedelta(days=i)
        wd = d.weekday()
        if wd not in open_days:
            continue
        slots = get_slots_for_day(settings_obj, wd)
        if not slots:
            continue
        options = []
        for open_t, close_t in slots[:2]:
            start_dt = datetime.combine(d, open_t)
            end_dt = datetime.combine(d, close_t)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
            t = start_dt
            while t < end_dt and len(options) < 12:
                if t > datetime.now():
                    options.append((t.isoformat(), t.strftime("%H:%M")))
                t += timedelta(minutes=60)
        if options:
            days_with_slots.append({"date": d, "date_label": d.strftime("%A, %b %d"), "options": options})
    return render(
        request,
        "pages/restaurant_schedule.html",
        {
            "restaurant": restaurant,
            "restaurant_hours": restaurant_hours,
            "days_with_slots": days_with_slots,
            "menu_url": f"/restaurants/{restaurant_id}/menu/",
        },
    )


def order_payment(request, restaurant_id, order_id):
    """Stripe payment page for an order (online payment). Placeholder until Stripe secret key is set."""
    restaurant = get_object_or_404(Restaurant, pk=restaurant_id, is_active=True)
    order = get_object_or_404(Order, pk=order_id, restaurant=restaurant)
    if order.payment_method != "online":
        return render(
            request,
            "pages/order_payment.html",
            {"restaurant": restaurant, "order": order, "error": "This order is not for online payment."},
            status=400,
        )
    if str(order.status) not in ("pending", "paid"):
        return render(
            request,
            "pages/order_payment.html",
            {"restaurant": restaurant, "order": order, "error": "This order is already completed or cancelled."},
            status=400,
        )
    return render(
        request,
        "pages/order_payment.html",
        {
            "restaurant": restaurant,
            "order": order,
            "order_items": order.items_json if getattr(order, "items_json", None) else [],
            "total_amount": order.total_amount,
            "currency": order.currency or "EUR",
        },
    )


def error_404(request, exception):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    return render(request, "errors/500.html", status=500)
