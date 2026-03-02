import json

from django.shortcuts import render


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
