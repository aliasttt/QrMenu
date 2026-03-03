from __future__ import annotations

from dataclasses import dataclass

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
    """
    Resolve the Django auth user for a given BusinessAdmin in a way that is stable even when:
    - An older user exists with a suffixed username (business_admin_..._1)
    - Email casing/whitespace differs

    This prevents OTP email verification codes being created for one user and checked against another.
    """
    base_username = business_admin_base_username(admin_phone)
    normalized_email = normalize_email(admin_email)

    # 1) Prefer exact deterministic username (most stable)
    user = User.objects.filter(username=base_username).first()
    if user:
        return user

    # 2) Fall back: try to find an existing suffixed user created earlier
    candidates = User.objects.filter(username__startswith=base_username).order_by("id")

    if normalized_email:
        by_email = candidates.filter(email__iexact=normalized_email)
        if by_email.count() == 1:
            return by_email.first()

    # If only one candidate exists, use it.
    if candidates.count() == 1:
        return candidates.first()

    # 3) Create a new unique username (base or base_1...)
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

