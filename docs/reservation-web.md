# Web reservations

`ReservationSettings` is the primary source because it is the model written by the app endpoint `/api/business-menu/reservation-settings/<restaurant_id>/`. The web menu, QR menu, public config, slots, and create endpoints now read that source. `RestaurantSettings` remains a compatibility fallback only when no `ReservationSettings` row exists; its `total_tables` is also used when the app has not supplied any table records.

The server validates enabled/closed state, blocked dates, booking horizon, schedule, duration plus buffer, guest limit, and capacity. Reservations use the existing `Reservation` model and remain `pending`. Pending and confirmed reservations consume capacity; cancelled reservations release it. PostgreSQL serializes the final capacity check by locking the stable restaurant row, including when the reservation table is initially empty.

The web form supplies a UUID `request_id`. A repeated successful request returns the same reservation and order. Stripe receives the same idempotency key on a retry. If initial PaymentIntent setup fails, the reservation and order are marked cancelled so capacity is released; retry reacquires capacity and reuses those rows. Cash reservations never call Stripe. A successfully created but abandoned online payment remains pending and intentionally holds capacity until an administrator cancels it; automatic expiry is not enabled because the existing checkout path can still accept that PaymentIntent and releasing capacity first could overbook.

`Restaurant.timezone` is an optional, validated IANA name managed in Django admin. It does not change the project-wide `TIME_ZONE`. A blank/invalid value produces no slots and an explicit incomplete-configuration response. Existing app payloads remain valid because the field is optional.

`Reservation.requested_at` and `occupies_until` store comparable aware instants while `requested_date` and `requested_time` remain unchanged for API compatibility and restaurant-local display. DST gaps and folds are omitted because the current string-only API cannot disambiguate them. Overnight times are attached to the following local calendar day. Slot capacity uses interval overlap for table-backed schedules and retains the legacy per-day rule when only `total_tables` exists. Existing rows whose instants are still null are counted conservatively against every slot on that restaurant-local date until backfilled.

Before deployment, inspect the conservative backfill; it infers `Europe/Berlin` only for exact Germany country values and reports everything else as ambiguous:

```console
python manage.py backfill_reservation_timezones
python manage.py backfill_reservation_timezones --apply  # reviewed staging/production run only
```

Deployment order: deploy code and migration `0033_reservation_timezone_capacity`, leave restaurants with blank timezone unavailable for web reservation, run the backfill without `--apply`, review ambiguous restaurants, apply the reviewed backfill, then set remaining timezones explicitly before enabling their reservation settings. The migration is additive and does not rewrite existing reservations.

Rollback preserves data: roll application code back first, but keep migration `0033` applied and retain the added columns. Old code ignores them. Do not reverse the migration unless the stored timezone/instant/idempotency data has been exported and data loss is explicitly accepted.

This branch names its migration `0033` because its base ends at `0032`. The subscription WIP independently used `0033`; when the branches are later combined, create a Django merge migration or renumber/rebase one branch after inspecting both graph leaves. Do not change either dependency speculatively now.
