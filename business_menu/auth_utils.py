from __future__ import annotations

from django.contrib.auth.models import User


def business_admin_base_username(phone_e164: str) -> str:
    """
    Deterministic username for BusinessMenu admins derived from phone number.
    Example: +491590123456 -> business_admin_491590123456
    """
    digits = "".join(ch for ch in (phone_e164 or "") if ch.isdigit())
    return f"business_admin_{digits}"


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def get_or_create_user_for_business_admin(*, admin_phone: str, admin_name: str = "", admin_email: str = "") -> User:
    """Create a new auth user; only an explicit BusinessAdmin relation can reuse one."""
    base_username = business_admin_base_username(admin_phone)
    normalized_email = normalize_email(admin_email)

    from .models import BusinessAdmin
    linked_admin = BusinessAdmin.objects.filter(phone=admin_phone, auth_user__isnull=False).select_related("auth_user").first()
    if linked_admin:
        return linked_admin.auth_user

    username = base_username
    if User.objects.filter(username=username).exists():
        counter = 1
        while User.objects.filter(username=f"{base_username}_{counter}").exists():
            counter += 1
        username = f"{base_username}_{counter}"

    user = User.objects.create(
        username=username,
        email=normalized_email,
        first_name=admin_name or "",
        is_active=True,
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])
    return user


def sync_user_from_business_admin(*, user: User, admin_phone: str, admin_name: str = "", admin_email: str = "") -> User:
    """
    Keep the auth User consistent with BusinessAdmin data.
    - Email: always normalized
    - Username: prefer deterministic base username (if no conflict)
    """
    normalized_email = normalize_email(admin_email)
    desired_username = business_admin_base_username(admin_phone)

    update_fields: list[str] = []

    if (user.email or "") != normalized_email:
        user.email = normalized_email
        update_fields.append("email")

    if admin_name and (user.first_name or "") != admin_name:
        user.first_name = admin_name
        update_fields.append("first_name")

    # Only move username if it's not already desired and doesn't collide with someone else.
    if user.username != desired_username:
        if not User.objects.filter(username=desired_username).exclude(pk=user.pk).exists():
            user.username = desired_username
            update_fields.append("username")

    if update_fields:
        user.save(update_fields=update_fields)

    return user

