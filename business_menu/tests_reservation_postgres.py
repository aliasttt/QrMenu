from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from django.utils import timezone
from zoneinfo import ZoneInfo

from .models import Reservation
from .reservation_services import create_reservation_with_capacity, get_reservation_policy, reservation_slots
from .tests_reservations import make_restaurant, schedule_for


@skipUnless(connection.vendor == "postgresql", "PostgreSQL locking test")
class ReservationPostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.target_date = timezone.now().astimezone(ZoneInfo("Europe/Berlin")).date() + timedelta(days=1)

    def _attempt(self, restaurant_id, slot, barrier, table_key=""):
        close_old_connections()
        from .models import Restaurant

        restaurant = Restaurant.objects.get(pk=restaurant_id)
        barrier.wait()
        try:
            reservation = create_reservation_with_capacity(
                restaurant=restaurant,
                policy=get_reservation_policy(restaurant),
                requested_date=self.target_date,
                requested_time=slot,
                table_key=table_key,
                guests_count=2,
                customer_name="Concurrent",
                status=Reservation.Status.PENDING,
            )
            return reservation.pk
        except ValueError as exc:
            return str(exc)
        finally:
            close_old_connections()

    def test_empty_reservation_table_allows_only_last_capacity(self):
        restaurant = make_restaurant(schedule=schedule_for(self.target_date), tables=[])
        restaurant.settings.total_tables = 1
        restaurant.settings.save(update_fields=["total_tables"])
        slot = reservation_slots(get_reservation_policy(restaurant), self.target_date)[0]
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _i: self._attempt(restaurant.id, slot, barrier), range(2)))
        self.assertEqual(Reservation.objects.filter(restaurant=restaurant).count(), 1)
        self.assertEqual(sum(isinstance(value, int) for value in results), 1)
        self.assertIn("capacity_full", results)

    def test_restaurant_locks_are_independent(self):
        restaurants = [
            make_restaurant(index, schedule=schedule_for(self.target_date), tables=[{"id": "one"}])
            for index in (10, 11)
        ]
        slots = [reservation_slots(get_reservation_policy(item), self.target_date)[0] for item in restaurants]
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self._attempt, restaurant.id, slot, barrier)
                for restaurant, slot in zip(restaurants, slots)
            ]
            results = [future.result() for future in futures]
        self.assertTrue(all(isinstance(value, int) for value in results))

    def test_same_table_cannot_be_double_booked(self):
        restaurant = make_restaurant(
            20,
            schedule=schedule_for(self.target_date),
            tables=[
                {"id": "window", "name": "Window", "capacity": 4},
                {"id": "vip", "name": "VIP", "capacity": 8},
            ],
        )
        slot = reservation_slots(get_reservation_policy(restaurant), self.target_date)[0]
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _i: self._attempt(restaurant.id, slot, barrier, "window"),
                    range(2),
                )
            )
        self.assertEqual(Reservation.objects.filter(restaurant=restaurant).count(), 1)
        self.assertEqual(sum(isinstance(value, int) for value in results), 1)
        self.assertIn("capacity_full", results)
