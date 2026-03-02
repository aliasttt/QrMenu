from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def active_link(context, url_name, active_classes="text-primary-600 bg-primary-50", inactive_classes="text-slate-600 hover:text-primary-600"):
    request = context.get("request")
    if not request:
        return inactive_classes
    current = getattr(request.resolver_match, "url_name", "")
    return active_classes if current == url_name else inactive_classes
