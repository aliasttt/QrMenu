from urllib.parse import urlsplit

from django.utils.translation import gettext

from .models import Category


def _public_image_url(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith("/"):
        return value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def get_restaurant_public_media(restaurant):
    logo_url = ""
    logo = getattr(restaurant, "logo", None)
    if logo:
        try:
            logo_url = _public_image_url(logo.url)
        except Exception:
            logo_url = ""

    raw_gallery = (
        restaurant.gallery if isinstance(restaurant.gallery, (list, tuple)) else []
    )
    valid_gallery = [
        (index, url)
        for index, raw_url in enumerate(raw_gallery)
        if (url := _public_image_url(raw_url))
    ]

    try:
        cover_index = (
            -1
            if isinstance(restaurant.cover_image_index, bool)
            else int(restaurant.cover_image_index)
        )
    except (TypeError, ValueError):
        cover_index = -1

    cover = next((entry for entry in valid_gallery if entry[0] == cover_index), None)
    if cover is None and valid_gallery:
        cover = valid_gallery[0]

    cover_url = cover[1] if cover else ""
    gallery_urls = []
    if cover:
        gallery_urls.append(cover_url)
        gallery_urls.extend(url for index, url in valid_gallery if index != cover[0])

    return {
        "logo_url": logo_url,
        "gallery_urls": gallery_urls,
        "cover_url": cover_url,
        "card_image_url": cover_url or logo_url,
    }


def build_public_menu_collections(
    request, restaurant, menu_items, show_images=True, stock_fallback=""
):
    active_categories = list(
        Category.objects.filter(restaurant=restaurant, is_active=True).order_by(
            "order", "name"
        )
    )
    sections = {
        category.id: {"id": str(category.id), "name": category.name, "items": []}
        for category in active_categories
    }
    other_items = []
    menu_cards = []

    for item in menu_items:
        category = item.category
        if category is not None:
            if category.restaurant_id != restaurant.id or category.id not in sections:
                continue

        image_url = ""
        if show_images:
            first_image = item.images.first()
            if first_image:
                image_url = first_image.get_image_url(request=request) or ""

        card = {
            "id": item.id,
            "name": item.name,
            "description": item.description or "",
            "price": item.price,
            "image_url": image_url,
            "category_id": str(category.id) if category else "other",
            "category_name": category.name if category else gettext("Other"),
            "serial": item.serial or "",
            "stock": (item.stock or "").strip() or stock_fallback,
        }
        menu_cards.append(card)
        if category:
            sections[category.id]["items"].append(card)
        else:
            other_items.append(card)

    menu_sections = [section for section in sections.values() if section["items"]]
    if other_items:
        menu_sections.append({"id": "other", "name": gettext("Other"), "items": other_items})

    category_list = [
        {"id": section["id"], "name": section["name"], "count": len(section["items"])}
        for section in menu_sections
    ]
    return menu_cards, menu_sections, category_list
