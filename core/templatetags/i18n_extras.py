from django import template
from django.urls import translate_url as django_translate_url

register = template.Library()


@register.filter(name="translate_url")
def translate_url_filter(path: str, lang_code: str) -> str:
    """Return the given URL path translated to lang_code, or the original path on failure."""
    if not path:
        return "/"
    try:
        return django_translate_url(path, lang_code) or path
    except Exception:
        return path
