from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def active_link(context, url_name, active_classes="text-primary-600 bg-primary-50", inactive_classes="text-slate-600 hover:text-primary-600"):
    request = context.get("request")
    if not request:
        return inactive_classes
    current = getattr(request.resolver_match, "url_name", "")
    return active_classes if current == url_name else inactive_classes


@register.simple_tag(takes_context=True)
def active_nav_path(context, path_prefix, active_classes="text-primary-600 font-semibold", inactive_classes="text-slate-600 hover:text-primary-600"):
    """Use for public nav: active if request path starts with path_prefix (e.g. '/features')."""
    request = context.get("request")
    if not request:
        return inactive_classes
    path = (request.path or "").rstrip("/")
    prefix = path_prefix.rstrip("/")
    if prefix and path.startswith(prefix) and (path == prefix or path[len(prefix)] == "/"):
        return active_classes
    return inactive_classes

