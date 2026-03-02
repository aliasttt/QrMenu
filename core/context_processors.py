def navigation_context(request):
    return {
        "public_nav_links": [
            {"label": "Features", "href": "/#features"},
            {"label": "How it works", "href": "/#how-it-works"},
            {"label": "Pricing", "href": "/#pricing"},
        ],
        "panel_nav_links": [
            {"label": "Dashboard", "url_name": "panel_dashboard"},
            {"label": "Menu Items", "url_name": "panel_menu_items"},
            {"label": "Categories", "url_name": "panel_categories"},
            {"label": "Campaigns", "url_name": "panel_campaigns"},
            {"label": "Settings", "url_name": "panel_settings"},
        ],
    }


def theme_tokens(request):
    return {
        "theme": {
            "brand_name": "QRMenu Pro",
            "primary_hex": "#F97316",
            "primary_600_hex": "#EA580C",
            "surface": "#FFFFFF",
        }
    }
