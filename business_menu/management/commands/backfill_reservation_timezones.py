from django.core.management.base import BaseCommand

from business_menu.models import Reservation, Restaurant
from business_menu.reservation_services import get_reservation_policy, reservation_interval


GERMANY_COUNTRIES = {"de", "deutschland", "germany"}


class Command(BaseCommand):
    help = "Dry-run or apply conservative restaurant timezone and reservation-instant backfill."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Persist unambiguous changes.")

    def handle(self, *args, **options):
        apply = options["apply"]
        restaurants = list(Restaurant.objects.all().order_by("id"))
        inferred = ambiguous = existing = 0
        backfillable = unresolved = 0

        for restaurant in restaurants:
            if restaurant.timezone:
                existing += 1
            elif restaurant.country.strip().casefold() in GERMANY_COUNTRIES:
                inferred += 1
                restaurant.timezone = "Europe/Berlin"
                if apply:
                    restaurant.save(update_fields=["timezone"])
            else:
                ambiguous += 1

            if not restaurant.timezone:
                unresolved += Reservation.objects.filter(
                    restaurant=restaurant, requested_at__isnull=True
                ).count()
                continue

            policy = get_reservation_policy(restaurant)
            for reservation in Reservation.objects.filter(
                restaurant=restaurant, requested_at__isnull=True
            ).iterator():
                try:
                    start, end = reservation_interval(
                        policy, reservation.requested_date, reservation.requested_time
                    )
                except ValueError:
                    unresolved += 1
                    continue
                backfillable += 1
                if apply:
                    reservation.requested_at = start
                    reservation.occupies_until = end
                    reservation.save(update_fields=["requested_at", "occupies_until"])

        mode = "APPLY" if apply else "DRY RUN"
        self.stdout.write(
            f"{mode}: restaurants existing={existing}, inferred_germany={inferred}, "
            f"ambiguous={ambiguous}; reservations backfillable={backfillable}, unresolved={unresolved}"
        )
