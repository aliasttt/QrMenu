from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Reservation, ReservationSettings, Restaurant, RestaurantSettings


DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass
class ReservationPolicy:
    enabled: bool
    source: str
    schedule: object
    closed_today: bool
    blocked_dates: set[str]
    max_guests: int
    advance_days: int
    duration_minutes: int
    buffer_minutes: int
    capacity: int
    capacity_scope: str
    timezone_name: str


def get_reservation_policy(restaurant) -> ReservationPolicy:
    try:
        legacy = restaurant.settings
    except RestaurantSettings.DoesNotExist:
        legacy = None
    try:
        app_settings = restaurant.reservation_settings
    except ReservationSettings.DoesNotExist:
        app_settings = None

    if app_settings is not None:
        tables = app_settings.tables if isinstance(app_settings.tables, list) else []
        available_tables = [
            table for table in tables
            if isinstance(table, dict) and table.get("enabled", table.get("active", True)) is not False
        ]
        capacity = len(available_tables) if tables else int(getattr(legacy, "total_tables", 0) or 0)
        return ReservationPolicy(
            enabled=bool(app_settings.enabled),
            source="reservation_settings",
            schedule=app_settings.schedule if isinstance(app_settings.schedule, dict) else {},
            closed_today=bool(app_settings.closed_today),
            blocked_dates={str(value) for value in (app_settings.blocked_dates or [])},
            max_guests=max(1, int(app_settings.max_guests_per_reservation or 1)),
            advance_days=max(0, int(app_settings.advance_booking_days or 0)),
            duration_minutes=max(1, int(app_settings.reservation_duration or 1)),
            buffer_minutes=max(0, int(app_settings.buffer_minutes or 0)),
            capacity=max(0, capacity),
            capacity_scope="slot" if tables else "day",
            timezone_name=str(restaurant.timezone or ""),
        )

    return ReservationPolicy(
        enabled=bool(getattr(legacy, "reservation_enabled", False)),
        source="restaurant_settings",
        schedule=getattr(legacy, "opening_hours_json", None) or [],
        closed_today=False,
        blocked_dates=set(),
        max_guests=max(1, int(getattr(legacy, "max_guests_per_reservation", 1) or 1)),
        advance_days=30,
        duration_minutes=30,
        buffer_minutes=0,
        capacity=max(0, int(getattr(legacy, "total_tables", 0) or 0)),
        capacity_scope="day",
        timezone_name=str(restaurant.timezone or ""),
    )


def _parse_clock(value):
    try:
        return datetime.strptime(str(value or "")[:5], "%H:%M").time()
    except (TypeError, ValueError):
        return None


def _schedule_windows(policy: ReservationPolicy, requested_date: date):
    schedule = policy.schedule
    if isinstance(schedule, dict):
        day = schedule.get(DAY_NAMES[requested_date.weekday()]) or {}
        if not isinstance(day, dict) or day.get("enabled") is not True:
            return []
        start = _parse_clock(day.get("start"))
        end = _parse_clock(day.get("end"))
        return [(start, end)] if start and end else []
    if isinstance(schedule, list):
        windows = []
        for item in schedule:
            if not isinstance(item, dict) or item.get("day") != requested_date.weekday():
                continue
            start = _parse_clock(item.get("open"))
            end = _parse_clock(item.get("close"))
            if start and end:
                windows.append((start, end))
        return windows
    return []


def _policy_zone(policy):
    try:
        return ZoneInfo(policy.timezone_name) if policy.timezone_name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def reservation_local_today(policy: ReservationPolicy, *, now=None):
    zone = _policy_zone(policy)
    if zone is None:
        return None
    return (now or timezone.now()).astimezone(zone).date()


def _aware_local(naive, zone):
    """Reject DST gaps and folds because the string-only API cannot disambiguate them."""
    candidates = {}
    for fold in (0, 1):
        value = naive.replace(tzinfo=zone, fold=fold)
        utc_value = value.astimezone(UTC)
        round_trip = utc_value.astimezone(zone)
        if round_trip.replace(tzinfo=None) == naive:
            candidates[utc_value] = value
    if not candidates:
        raise ValueError("nonexistent_local_time")
    if len(candidates) > 1:
        raise ValueError("ambiguous_local_time")
    return next(iter(candidates.values()))


def _slot_naive_datetimes(policy: ReservationPolicy, requested_date: date):
    step = max(1, policy.duration_minutes + policy.buffer_minutes)
    for start, end in _schedule_windows(policy, requested_date):
        current = datetime.combine(requested_date, start)
        end_at = datetime.combine(requested_date, end)
        if end <= start:
            end_at += timedelta(days=1)
        while current + timedelta(minutes=policy.duration_minutes) <= end_at:
            yield current
            current += timedelta(minutes=step)


def reservation_interval(policy: ReservationPolicy, requested_date: date, requested_time: str):
    zone = _policy_zone(policy)
    if zone is None:
        raise ValueError("timezone_not_configured")
    matches = [
        value for value in _slot_naive_datetimes(policy, requested_date)
        if value.strftime("%H:%M") == requested_time
    ]
    if len(matches) != 1:
        raise ValueError("slot_unavailable")
    start = _aware_local(matches[0], zone).astimezone(UTC)
    return start, start + timedelta(minutes=policy.duration_minutes + policy.buffer_minutes)


def reservation_slots(policy: ReservationPolicy, requested_date: date, *, now=None) -> list[str]:
    zone = _policy_zone(policy)
    if zone is None:
        return []
    now = (now or timezone.now()).astimezone(zone)
    today = now.date()
    if not policy.enabled or requested_date < today or requested_date > today + timedelta(days=policy.advance_days):
        return []
    if requested_date.isoformat() in policy.blocked_dates or (requested_date == today and policy.closed_today):
        return []
    values = []
    for current in _slot_naive_datetimes(policy, requested_date):
        try:
            aware = _aware_local(current, zone)
        except ValueError:
            continue
        if aware > now:
            values.append((aware.astimezone(UTC), current.strftime("%H:%M")))
    return [value for _instant, value in sorted(set(values))]


def reservation_count(restaurant, policy: ReservationPolicy, requested_date: date, requested_time="") -> int:
    reservations = Reservation.objects.filter(
        restaurant=restaurant,
        requested_date=requested_date,
    ).exclude(status=Reservation.Status.CANCELLED)
    if policy.capacity_scope == "slot":
        try:
            start, end = reservation_interval(policy, requested_date, requested_time)
        except ValueError:
            return 0
        reservations = reservations.filter(
            Q(requested_at__lt=end, occupies_until__gt=start)
            | Q(requested_at__isnull=True, requested_date=requested_date)
        )
    return reservations.count()


def create_reservation_with_capacity(*, restaurant, policy, requested_date, requested_time, **values):
    """Serialize capacity checks on PostgreSQL by locking the restaurant row."""
    with transaction.atomic():
        locked_restaurant = Restaurant.objects.select_for_update().get(pk=restaurant.pk)
        current_policy = get_reservation_policy(locked_restaurant)
        if not current_policy.enabled or requested_time not in reservation_slots(current_policy, requested_date):
            raise ValueError("slot_unavailable")
        if current_policy.capacity <= 0 or reservation_count(
            locked_restaurant, current_policy, requested_date, requested_time
        ) >= current_policy.capacity:
            raise ValueError("capacity_full")
        requested_at, occupies_until = reservation_interval(
            current_policy, requested_date, requested_time
        )
        return Reservation.objects.create(
            restaurant=locked_restaurant,
            requested_date=requested_date,
            requested_time=requested_time,
            requested_at=requested_at,
            occupies_until=occupies_until,
            **values,
        )


def retry_failed_payment_reservation(reservation):
    """Reacquire capacity for the same idempotent request after Stripe setup failed."""
    with transaction.atomic():
        locked_restaurant = Restaurant.objects.select_for_update().get(pk=reservation.restaurant_id)
        locked = Reservation.objects.select_for_update().get(pk=reservation.pk)
        if not locked.payment_setup_failed or locked.status != Reservation.Status.CANCELLED:
            return locked
        policy = get_reservation_policy(locked_restaurant)
        if not policy.enabled or locked.requested_time not in reservation_slots(policy, locked.requested_date):
            raise ValueError("slot_unavailable")
        if policy.capacity <= 0 or reservation_count(
            locked_restaurant, policy, locked.requested_date, locked.requested_time
        ) >= policy.capacity:
            raise ValueError("capacity_full")
        locked.requested_at, locked.occupies_until = reservation_interval(
            policy, locked.requested_date, locked.requested_time
        )
        locked.status = Reservation.Status.PENDING
        locked.payment_setup_failed = False
        locked.save(update_fields=["requested_at", "occupies_until", "status", "payment_setup_failed", "updated_at"])
        return locked
