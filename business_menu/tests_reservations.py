from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    BusinessAdmin,
    MenuQRCode,
    Order,
    Reservation,
    ReservationSettings,
    Restaurant,
    RestaurantSettings,
)
from .reservation_services import (
    DAY_NAMES,
    create_reservation_with_capacity,
    get_reservation_policy,
    reservation_count,
    reservation_slots,
)


def make_restaurant(index=1, *, enabled=True, schedule=None, tables=None, timezone_name="Europe/Berlin"):
    admin = BusinessAdmin.objects.create(
        phone=f"+491580000{index:04d}",
        name=f"Reservation Admin {index}",
        email=f"reservation{index}@example.com",
    )
    restaurant = Restaurant.objects.create(
        admin=admin,
        name=f"Restaurant {index}",
        public_slug=f"restaurant-{index}",
        timezone=timezone_name,
    )
    RestaurantSettings.objects.update_or_create(
        restaurant=restaurant,
        defaults={
            "reservation_enabled": False,
            "total_tables": 2,
            "max_guests_per_reservation": 10,
        },
    )
    ReservationSettings.objects.update_or_create(
        restaurant=restaurant,
        defaults={
            "enabled": enabled,
            "max_guests_per_reservation": 6,
            "advance_booking_days": 14,
            "reservation_duration": 60,
            "buffer_minutes": 15,
            "schedule": schedule or {},
            "tables": tables or [],
        },
    )
    return restaurant


def schedule_for(target_date, start="09:00", end="22:00"):
    return {
        DAY_NAMES[target_date.weekday()]: {
            "enabled": True,
            "start": start,
            "end": end,
        }
    }


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STRIPE_SECRET_KEY="",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class ReservationWebIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.target_date = timezone.now().astimezone(ZoneInfo("Europe/Berlin")).date() + timedelta(days=1)
        self.restaurant = make_restaurant(schedule=schedule_for(self.target_date))

    def test_app_settings_are_the_source_for_numeric_slug_and_qr_menus(self):
        qr = MenuQRCode.objects.get(restaurant=self.restaurant)
        numeric = self.client.get(reverse("restaurant_menu", args=[self.restaurant.id]))
        slug = self.client.get(reverse("public_menu", args=[self.restaurant.public_slug]))
        qr_page = self.client.get(f"/business-menu/qr/{qr.token}/")

        for response in (numeric, slug, qr_page):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Table reservation")
        self.assertContains(
            slug,
            reverse("restaurant_reservation_slug", args=[self.restaurant.public_slug]),
        )

    def test_disabled_app_setting_hides_button_and_blocks_public_endpoints(self):
        self.restaurant.reservation_settings.enabled = False
        self.restaurant.reservation_settings.save(update_fields=["enabled"])

        menu = self.client.get(reverse("restaurant_menu", args=[self.restaurant.id]))
        page = self.client.get(reverse("restaurant_reservation", args=[self.restaurant.id]))
        create = self.client.post(
            "/api/business-menu/reservation/create/",
            {"restaurant_id": self.restaurant.id},
            content_type="application/json",
        )

        self.assertNotContains(menu, "Table reservation")
        self.assertEqual(page.status_code, 404)
        self.assertEqual(create.status_code, 400)

    def test_incomplete_or_blocked_schedule_returns_no_invented_slots(self):
        settings_obj = self.restaurant.reservation_settings
        settings_obj.schedule = {}
        settings_obj.save(update_fields=["schedule"])
        empty = self.client.get(
            "/api/business-menu/reservation/slots/",
            {"restaurant_id": self.restaurant.id, "date": self.target_date.isoformat()},
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.data["time_slots"], [])
        self.assertTrue(empty.data["detail"])

        settings_obj.schedule = schedule_for(self.target_date)
        settings_obj.blocked_dates = [self.target_date.isoformat()]
        settings_obj.save(update_fields=["schedule", "blocked_dates"])
        blocked = self.client.get(
            "/api/business-menu/reservation/slots/",
            {"restaurant_id": self.restaurant.id, "date": self.target_date.isoformat()},
        )
        self.assertEqual(blocked.data["time_slots"], [])

    def test_missing_timezone_is_reported_without_fabricated_slots(self):
        self.restaurant.timezone = ""
        self.restaurant.save(update_fields=["timezone"])
        response = self.client.get(
            "/api/business-menu/reservation/slots/",
            {"restaurant_id": self.restaurant.id, "date": self.target_date.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["time_slots"], [])
        self.assertFalse(response.data["configuration_complete"])

    def test_restaurant_timezone_requires_an_iana_name(self):
        self.restaurant.timezone = "Berlin"
        with self.assertRaises(ValidationError):
            self.restaurant.full_clean()

    def test_closed_today_and_booking_horizon_are_enforced_in_restaurant_timezone(self):
        local_today = timezone.now().astimezone(ZoneInfo("Europe/Berlin")).date()
        settings_obj = self.restaurant.reservation_settings
        settings_obj.closed_today = True
        settings_obj.schedule = schedule_for(local_today)
        settings_obj.save(update_fields=["closed_today", "schedule"])
        policy = get_reservation_policy(self.restaurant)
        self.assertEqual(reservation_slots(policy, local_today), [])

        settings_obj.closed_today = False
        settings_obj.save(update_fields=["closed_today"])
        beyond_horizon = local_today + timedelta(days=policy.advance_days + 1)
        settings_obj.schedule = schedule_for(beyond_horizon)
        settings_obj.save(update_fields=["schedule"])
        self.assertEqual(reservation_slots(get_reservation_policy(self.restaurant), beyond_horizon), [])

    @patch("stripe.PaymentIntent.create")
    @patch("business_menu.reservation_emails.send_reservation_new_request_email")
    def test_web_create_uses_existing_pending_model_and_server_validates_slot(self, send_email, payment_intent):
        slots = self.client.get(
            "/api/business-menu/reservation/slots/",
            {"restaurant_id": self.restaurant.id, "date": self.target_date.isoformat()},
        ).data["time_slots"]
        response = self.client.post(
            "/api/business-menu/reservation/create/",
            {
                "restaurant_id": self.restaurant.id,
                "requested_date": self.target_date.isoformat(),
                "requested_time": slots[0],
                "guests_count": 2,
                "customer_name": "Local Test",
                "payment_method": "cash",
            },
            content_type="application/json",
        )
        invalid = self.client.post(
            "/api/business-menu/reservation/create/",
            {
                "restaurant_id": self.restaurant.id,
                "requested_date": self.target_date.isoformat(),
                "requested_time": "03:17",
                "guests_count": 2,
                "customer_name": "Invalid Slot",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Reservation.objects.get().status, Reservation.Status.PENDING)
        self.assertIsNotNone(Reservation.objects.get().requested_at)
        self.assertEqual(invalid.status_code, 400)
        send_email.assert_called_once()
        payment_intent.assert_not_called()

    def test_capacity_is_scoped_and_rechecked_under_database_lock(self):
        settings_obj = self.restaurant.reservation_settings
        settings_obj.tables = [{"id": "one", "enabled": True}]
        settings_obj.save(update_fields=["tables"])
        policy = get_reservation_policy(self.restaurant)
        slot = reservation_slots(policy, self.target_date)[0]
        values = {
            "guests_count": 2,
            "customer_name": "First",
            "status": Reservation.Status.PENDING,
        }
        create_reservation_with_capacity(
            restaurant=self.restaurant,
            policy=policy,
            requested_date=self.target_date,
            requested_time=slot,
            **values,
        )
        with self.assertRaisesMessage(ValueError, "capacity_full"):
            create_reservation_with_capacity(
                restaurant=self.restaurant,
                policy=policy,
                requested_date=self.target_date,
                requested_time=slot,
                **{**values, "customer_name": "Second"},
            )

        other = make_restaurant(2, schedule=schedule_for(self.target_date), tables=[{"id": "one"}])
        create_reservation_with_capacity(
            restaurant=other,
            policy=get_reservation_policy(other),
            requested_date=self.target_date,
            requested_time=slot,
            **{**values, "customer_name": "Other restaurant"},
        )
        self.assertEqual(Reservation.objects.filter(restaurant=other).count(), 1)

    def test_pending_overlap_uses_duration_and_buffer_and_cancel_releases_capacity(self):
        settings_obj = self.restaurant.reservation_settings
        settings_obj.tables = [{"id": "one", "enabled": True}]
        settings_obj.schedule = schedule_for(self.target_date, "09:00", "13:00")
        settings_obj.save(update_fields=["tables", "schedule"])
        zone = ZoneInfo("Europe/Berlin")
        start = datetime.combine(self.target_date, datetime.strptime("09:30", "%H:%M").time(), zone)
        existing = Reservation.objects.create(
            restaurant=self.restaurant,
            requested_date=self.target_date,
            requested_time="09:30",
            requested_at=start.astimezone(UTC),
            occupies_until=(start + timedelta(minutes=75)).astimezone(UTC),
            guests_count=2,
            customer_name="Pending",
            status=Reservation.Status.PENDING,
        )
        policy = get_reservation_policy(self.restaurant)
        self.assertEqual(reservation_count(self.restaurant, policy, self.target_date, "10:15"), 1)
        with self.assertRaisesMessage(ValueError, "capacity_full"):
            create_reservation_with_capacity(
                restaurant=self.restaurant,
                policy=policy,
                requested_date=self.target_date,
                requested_time="10:15",
                guests_count=2,
                customer_name="Blocked overlap",
            )
        existing.status = Reservation.Status.CANCELLED
        existing.save(update_fields=["status"])
        create_reservation_with_capacity(
            restaurant=self.restaurant,
            policy=policy,
            requested_date=self.target_date,
            requested_time="10:15",
            guests_count=2,
            customer_name="Released capacity",
        )

    def test_legacy_null_instants_are_counted_conservatively_until_backfill(self):
        settings_obj = self.restaurant.reservation_settings
        settings_obj.tables = [{"id": "one", "enabled": True}]
        settings_obj.schedule = schedule_for(self.target_date, "09:00", "13:00")
        settings_obj.save(update_fields=["tables", "schedule"])
        Reservation.objects.create(
            restaurant=self.restaurant,
            requested_date=self.target_date,
            requested_time="09:30",
            guests_count=2,
            customer_name="Legacy pending",
            status=Reservation.Status.PENDING,
        )
        policy = get_reservation_policy(self.restaurant)
        self.assertEqual(reservation_count(self.restaurant, policy, self.target_date, "10:15"), 1)

    @override_settings(STRIPE_SECRET_KEY="sk_test_reservation")
    @patch("business_menu.reservation_emails.send_reservation_new_request_email")
    @patch("stripe.PaymentIntent.create")
    def test_online_retry_reuses_reservation_order_and_payment_intent_key(self, create_intent, send_email):
        self.restaurant.admin.stripe_account_id = "acct_reservation_test"
        self.restaurant.admin.save(update_fields=["stripe_account_id"])
        request_id = "87be4db8-b5db-41c9-8fc7-cef4e8cfc9bc"
        slot = reservation_slots(get_reservation_policy(self.restaurant), self.target_date)[0]
        payload = {
            "restaurant_id": self.restaurant.id,
            "request_id": request_id,
            "requested_date": self.target_date.isoformat(),
            "requested_time": slot,
            "guests_count": 2,
            "customer_name": "Online retry",
            "payment_method": "online",
            "order_details": [{"name": "Soup", "price": "9.50", "quantity": 1}],
        }
        create_intent.side_effect = [RuntimeError("temporary Stripe failure"), SimpleNamespace(id="pi_retry_safe")]

        failed = self.client.post(
            "/api/business-menu/reservation/create/", payload, content_type="application/json"
        )
        self.assertEqual(failed.status_code, 502)
        failed_reservation = Reservation.objects.get()
        self.assertEqual(failed_reservation.status, Reservation.Status.CANCELLED)
        self.assertTrue(failed_reservation.payment_setup_failed)
        self.assertIn(
            slot,
            self.client.get(
                "/api/business-menu/reservation/slots/",
                {"restaurant_id": self.restaurant.id, "date": self.target_date.isoformat()},
            ).data["time_slots"],
        )

        retried = self.client.post(
            "/api/business-menu/reservation/create/", payload, content_type="application/json"
        )
        replay = self.client.post(
            "/api/business-menu/reservation/create/", payload, content_type="application/json"
        )

        self.assertEqual(retried.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(Order.objects.count(), 1)
        reservation = Reservation.objects.select_related("order").get()
        self.assertEqual(reservation.status, Reservation.Status.PENDING)
        self.assertEqual(reservation.stripe_payment_intent_id, "pi_retry_safe")
        self.assertEqual(reservation.order.stripe_payment_intent_id, "pi_retry_safe")
        self.assertEqual(retried.data["reservation_id"], replay.data["reservation_id"])
        self.assertEqual(create_intent.call_count, 2)
        self.assertEqual(
            create_intent.call_args_list[0].kwargs["idempotency_key"],
            create_intent.call_args_list[1].kwargs["idempotency_key"],
        )
        self.assertEqual(
            create_intent.call_args_list[1].kwargs["transfer_data"],
            {"destination": "acct_reservation_test"},
        )
        create_intent.reset_mock()
        with patch(
            "stripe.PaymentIntent.retrieve",
            return_value=SimpleNamespace(client_secret="secret_retry_safe"),
        ) as retrieve_intent:
            payment_page_intent = self.client.post(
                "/api/business-menu/api/create-order-payment-intent/",
                {"restaurant_id": self.restaurant.id, "order_id": reservation.order_id},
                content_type="application/json",
            )
        self.assertEqual(payment_page_intent.status_code, 200)
        self.assertEqual(payment_page_intent.data["client_secret"], "secret_retry_safe")
        retrieve_intent.assert_called_once_with("pi_retry_safe")
        create_intent.assert_not_called()
        send_email.assert_called_once_with(reservation)

    def test_page_reports_no_dates_when_schedule_is_incomplete(self):
        self.restaurant.reservation_settings.schedule = {}
        self.restaurant.reservation_settings.save(update_fields=["schedule"])
        response = self.client.get(reverse("restaurant_reservation", args=[self.restaurant.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "None available")

    def test_dst_gaps_and_folds_are_not_offered(self):
        spring = datetime(2027, 3, 28).date()
        autumn = datetime(2027, 10, 31).date()
        now = datetime(2027, 1, 1, tzinfo=UTC)
        self.restaurant.reservation_settings.reservation_duration = 30
        self.restaurant.reservation_settings.buffer_minutes = 0
        self.restaurant.reservation_settings.advance_booking_days = 365
        self.restaurant.reservation_settings.schedule = schedule_for(spring, "01:00", "04:00")
        self.restaurant.reservation_settings.save()
        policy = get_reservation_policy(self.restaurant)
        spring_slots = reservation_slots(policy, spring, now=now)
        self.assertNotIn("02:00", spring_slots)
        self.assertNotIn("02:30", spring_slots)

        self.restaurant.reservation_settings.schedule = schedule_for(autumn, "01:00", "04:00")
        self.restaurant.reservation_settings.save(update_fields=["schedule"])
        autumn_slots = reservation_slots(get_reservation_policy(self.restaurant), autumn, now=now)
        self.assertNotIn("02:00", autumn_slots)
        self.assertNotIn("02:30", autumn_slots)

    def test_overnight_slot_is_stored_as_next_local_day(self):
        self.restaurant.reservation_settings.schedule = schedule_for(self.target_date, "22:00", "02:00")
        self.restaurant.reservation_settings.save(update_fields=["schedule"])
        policy = get_reservation_policy(self.restaurant)
        slot = "00:30"
        self.assertIn(slot, reservation_slots(policy, self.target_date))
        reservation = create_reservation_with_capacity(
            restaurant=self.restaurant,
            policy=policy,
            requested_date=self.target_date,
            requested_time=slot,
            guests_count=2,
            customer_name="Overnight",
            status=Reservation.Status.PENDING,
        )
        self.assertEqual(
            reservation.requested_at.astimezone(ZoneInfo("Europe/Berlin")).date(),
            self.target_date + timedelta(days=1),
        )
