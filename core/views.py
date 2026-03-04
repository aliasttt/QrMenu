import json

from django.shortcuts import render, get_object_or_404
from django.http import Http404

from business_menu.models import Restaurant, MenuItem


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
    plans = [
        {
            "name": "Starter",
            "price": "228",
            "summary": "For small venues",
            "badge": None,
            "highlight": False,
            "features": [
                "Up to 50 menu items",
                "1 QR code",
                "Basic analytics",
                "Email support",
            ],
        },
        {
            "name": "Growth",
            "price": "588",
            "summary": "Most popular",
            "badge": "Popular",
            "highlight": True,
            "features": [
                "Unlimited menu items",
                "Unlimited QR codes",
                "Campaigns & discounts",
                "Priority support",
                "Custom domain",
            ],
        },
        {
            "name": "Scale",
            "price": "1,188",
            "summary": "For chains",
            "badge": None,
            "highlight": False,
            "features": [
                "Unlimited menu items",
                "Unlimited QR codes",
                "Campaigns & discounts",
                "Priority support",
                "Custom domain",
                "Multi-location",
                "API & webhooks",
                "Dedicated success manager",
            ],
        },
    ]
    comparison = [
        {"name": "Menu items", "starter": "50", "growth": "Unlimited", "scale": "Unlimited"},
        {"name": "QR codes", "starter": "1", "growth": "Unlimited", "scale": "Unlimited"},
        {"name": "Campaigns", "starter": "—", "growth": "✓", "scale": "✓"},
        {"name": "Custom domain", "starter": "—", "growth": "✓", "scale": "✓"},
        {"name": "Multi-location", "starter": "—", "growth": "—", "scale": "✓"},
        {"name": "API / Webhooks", "starter": "—", "growth": "—", "scale": "✓"},
        {"name": "Dedicated success manager", "starter": "—", "growth": "—", "scale": "✓"},
    ]
    faqs = [
        {"q": "Can I change plans later?", "a": "Yes. Upgrade or downgrade anytime. We prorate the difference."},
        {"q": "Is there a free trial?", "a": "Yes. Start with a 14-day free trial on any plan. No card required."},
        {"q": "What does 'plus 19% VAT' mean?", "a": "Prices are quoted excluding VAT. If you are in the EU and liable for VAT, 19% will be added at checkout as required by law."},
    ]
    return render(request, "pages/pricing.html", {"plans": plans, "comparison": comparison, "faqs": faqs})


def contact(request):
    return render(request, "pages/contact.html")


def restaurants_list(request):
    """صفحهٔ لیست رستوران‌ها / کافه‌ها به صورت کارت."""
    restaurants = Restaurant.objects.filter(is_active=True).order_by("name")
    return render(request, "pages/restaurants_list.html", {"restaurants": restaurants})


def restaurant_menu(request, restaurant_id):
    """صفحهٔ منوی یک رستوران: آیتم‌های منو به صورت کارت (عکس، نام، توضیح، قیمت)."""
    restaurant = get_object_or_404(Restaurant, pk=restaurant_id, is_active=True)
    items = (
        MenuItem.objects.filter(restaurant=restaurant, is_available=True)
        .select_related("category")
        .prefetch_related("images", "images__cloudinary_image")
        .order_by("order", "name")
    )
    menu_cards = []
    for item in items:
        img_url = None
        first_img = item.images.first()
        if first_img:
            img_url = first_img.get_image_url(request=request)
        if not img_url:
            img_url = f"https://picsum.photos/seed/menu-{item.id}/640/400"
        menu_cards.append({
            "id": item.id,
            "name": item.name,
            "description": item.description or "",
            "price": item.price,
            "image_url": img_url,
        })
    return render(
        request,
        "pages/restaurant_menu.html",
        {"restaurant": restaurant, "menu_cards": menu_cards},
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
    return render(request, "pages/auth/login.html")


def register_view(request):
    return render(request, "pages/auth/register.html")


def panel_dashboard(request):
    stats = [
        {"label": "Today Orders", "value": "128", "delta": "+12%"},
        {"label": "Revenue", "value": "$2,430", "delta": "+8.4%"},
        {"label": "Menu Items", "value": "64", "delta": "+3"},
        {"label": "Active Campaigns", "value": "3", "delta": "Live"},
    ]
    recent_orders = [
        {"id": "#1023", "customer": "John S.", "amount": "$34.00", "status": "Completed"},
        {"id": "#1022", "customer": "Nadia K.", "amount": "$19.50", "status": "Preparing"},
        {"id": "#1021", "customer": "Alex R.", "amount": "$42.20", "status": "Completed"},
    ]
    return render(
        request,
        "pages/panel/dashboard.html",
        {
            "stats": stats,
            "recent_orders": recent_orders,
            "dashboard_crumbs": [{"label": "Panel", "url": "/panel/"}, {"label": "Dashboard", "url": ""}],
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


def error_404(request, exception):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    return render(request, "errors/500.html", status=500)
