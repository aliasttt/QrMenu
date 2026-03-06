# -*- coding: utf-8 -*-
"""
Template tag to group business_menu admin models into sections for the admin index.
"""
from django import template
from django.contrib import admin

register = template.Library()

# سکشن‌های پنل Business Menu (ترتیب نمایش)
BUSINESS_MENU_SECTIONS = [
    ("کاربران و رستوران‌ها", ["businessadmin", "restaurant"]),
    ("منوها (دسته‌بندی، مجموعه، آیتم، پکیج)", ["category", "menuset", "menuitem", "package"]),
    ("سفارشات و پرداخت", ["order", "payment"]),
    ("مشتریان (CRM)", ["customer"]),
    ("تصاویر و فایل‌های استاتیک", ["cloudinaryimage", "menuitemimage"]),
    ("QR کد و تنظیمات", ["menuqrcode", "restaurantsettings", "menutheme"]),
]


@register.inclusion_tag("admin/business_menu_section.html", takes_context=True)
def business_menu_sectioned(context):
    """
    Build sectioned app list for business_menu and pass to template.
    Context must have 'app_list' (from admin index view).
    """
    app_list = context.get("app_list") or []
    business_app = None
    other_apps = []
    for app in app_list:
        if app.get("app_label") == "business_menu":
            business_app = app
        else:
            other_apps.append(app)

    sections = []
    if business_app:
        models_by_name = {m.get("object_name", "").lower(): m for m in business_app.get("models", [])}
        for section_title, model_names in BUSINESS_MENU_SECTIONS:
            models = []
            for name in model_names:
                if name in models_by_name:
                    models.append(models_by_name[name])
            if models:
                sections.append({"title": section_title, "models": models})

    return {
        "request": context.get("request"),
        "sections": sections,
        "other_apps": other_apps,
        "show_changelinks": True,
    }
