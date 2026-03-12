"""Opening hours check for ordering. Used by menu view and order/cart APIs."""
from datetime import datetime, date, time, timedelta


def is_within_opening_hours(settings_obj, now=None):
    """
    Return True if ordering is allowed: no hours set, or current time within a slot.
    opening_hours_json: [{"day": 0, "open": "09:00", "close": "22:00"}, ...] with day 0=Monday, 6=Sunday.
    """
    if now is None:
        now = datetime.now()
    hours_json = getattr(settings_obj, "opening_hours_json", None) or []
    if not isinstance(hours_json, list) or len(hours_json) == 0:
        return True
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    current_time = now.time()
    for slot in hours_json:
        if slot.get("day") != weekday:
            continue
        try:
            open_str = (slot.get("open") or "").strip() or "00:00"
            close_str = (slot.get("close") or "").strip() or "23:59"
            open_t = datetime.strptime(open_str[:5], "%H:%M").time()
            close_t = datetime.strptime(close_str[:5], "%H:%M").time()
            if open_t <= current_time <= close_t:
                return True
            if close_t < open_t:  # e.g. 22:00 - 02:00
                if current_time >= open_t or current_time <= close_t:
                    return True
        except (ValueError, TypeError):
            continue
    return False


def is_datetime_within_hours(settings_obj, dt):
    """Return True if the given datetime is within opening hours."""
    if dt is None:
        return False
    hours_json = getattr(settings_obj, "opening_hours_json", None) or []
    if not isinstance(hours_json, list) or len(hours_json) == 0:
        return True
    weekday = dt.weekday()
    current_time = dt.time()
    for slot in hours_json:
        if slot.get("day") != weekday:
            continue
        try:
            open_str = (slot.get("open") or "").strip() or "00:00"
            close_str = (slot.get("close") or "").strip() or "23:59"
            open_t = datetime.strptime(open_str[:5], "%H:%M").time()
            close_t = datetime.strptime(close_str[:5], "%H:%M").time()
            if open_t <= current_time <= close_t:
                return True
            if close_t < open_t:
                if current_time >= open_t or current_time <= close_t:
                    return True
        except (ValueError, TypeError):
            continue
    return False


def get_open_days(settings_obj):
    """Return set of weekday integers (0=Mon .. 6=Sun) that have at least one slot."""
    hours_json = getattr(settings_obj, "opening_hours_json", None) or []
    if not isinstance(hours_json, list) or len(hours_json) == 0:
        return set(range(7))
    return {s.get("day") for s in hours_json if s.get("day") is not None}


def get_slots_for_day(settings_obj, day_int):
    """Return list of (open_time, close_time) for a weekday (0=Mon .. 6=Sun). Times are time objects."""
    hours_json = getattr(settings_obj, "opening_hours_json", None) or []
    result = []
    for slot in (hours_json or []):
        if slot.get("day") != day_int:
            continue
        try:
            open_str = (slot.get("open") or "").strip() or "00:00"
            close_str = (slot.get("close") or "").strip() or "23:59"
            open_t = datetime.strptime(open_str[:5], "%H:%M").time()
            close_t = datetime.strptime(close_str[:5], "%H:%M").time()
            result.append((open_t, close_t))
        except (ValueError, TypeError):
            continue
    return result
