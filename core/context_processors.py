def navigation_context(request):
    return {
        "public_nav_links": [
            {"label": "Features", "href": "/features/", "path_prefix": "/features"},
            {"label": "How it works", "href": "/how-it-works/", "path_prefix": "/how-it-works"},
            {"label": "Pricing", "href": "/pricing/", "path_prefix": "/pricing"},
            {"label": "Contact", "href": "/contact/", "path_prefix": "/contact"},
        ],
        "panel_nav_links": [
            {"label": "Dashboard", "url_name": "panel_dashboard"},
            {"label": "Menu Items", "url_name": "panel_menu_items"},
            {"label": "Categories", "url_name": "panel_categories"},
            {"label": "Campaigns", "url_name": "panel_campaigns"},
            {"label": "Settings", "url_name": "panel_settings"},
        ],
    }


def theme(request):
    return {
        "theme": {
            "brand_name": "QRMenu Pro",
        }
    }

