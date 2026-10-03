import json
import re
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from .admin import BusinessAdminForm
from .identity import normalize_business_email, normalize_business_phone
from .models import BusinessAdmin, Category, Restaurant
from .serializers import BusinessAdminUpdateSerializer, RestaurantOwnerRegistrationSerializer
from .subscription_services import resolve_subscription_entitlement
from .views import _get_business_admin_for_user


class BusinessAdminIdentityTests(TestCase):
    def make_admin(self, *, email="owner@example.com", phone="+493012345678", user=True, restaurant=False):
        auth_user = None
        if user:
            auth_user = User.objects.create_user(
                username=f"manager_{User.objects.count()}", email=email, password="StrongPass123!"
            )
        admin = BusinessAdmin.objects.create(
            auth_user=auth_user, name="Restaurant manager", email=email, phone=phone
        )
        if restaurant:
            Restaurant.objects.create(admin=admin, name="Fixture restaurant")
        return admin, auth_user

    def test_email_normalizes_case_and_whitespace(self):
        self.assertEqual(normalize_business_email("  Owner+tag@Example.COM "), "owner+tag@example.com")

    def test_phone_formats_normalize_and_local_without_country_is_rejected(self):
        self.assertEqual(normalize_business_phone("+49 (30) 1234-5678"), "+493012345678")
        self.assertEqual(normalize_business_phone("0049 30 1234 5678"), "+493012345678")
        with self.assertRaisesMessage(Exception, "Enter an international phone number"):
            normalize_business_phone("030 12345678")

    def test_model_enforces_domain_scoped_normalization_and_database_uniqueness(self):
        first, _ = self.make_admin(email="Owner@Example.com")
        self.assertEqual(first.email, "owner@example.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            BusinessAdmin.objects.create(name="Second", email=" OWNER@example.com ", phone="+493012345679")
        with self.assertRaises(IntegrityError), transaction.atomic():
            BusinessAdmin.objects.create(name="Third", email="third@example.com", phone="0049 (30) 1234-5678")

    def test_profile_serializer_rejects_duplicate_email_and_phone_equivalence(self):
        self.make_admin(email="used@example.com", phone="+493012345678")
        _, owner = self.make_admin(email="owner2@example.com", phone="+493012345679")
        own_admin = owner.business_menu_admin
        serializer = BusinessAdminUpdateSerializer(own_admin, data={"email": " USED@example.com "}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("email", serializer.errors)
        serializer = BusinessAdminUpdateSerializer(own_admin, data={"phone": "0049 30 1234 5678"}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("phone", serializer.errors)

    def test_signup_rejects_local_phone_without_explicit_country_code(self):
        serializer = RestaurantOwnerRegistrationSerializer(data={
            "restaurant_name": "Cafe", "phone": "030 12345678", "email": "new@example.com",
            "password": "StrongPass123!", "accept_terms": True, "b2b_confirmation": True,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn("phone", serializer.errors)

    def test_manual_admin_creation_commits_auth_user_and_profile_together(self):
        form = BusinessAdminForm(data={
            "name": "New manager", "phone": "0049 30 1234 5688", "email": " NEW.Owner@Example.com ",
            "is_active": True, "payment_status": "unpaid", "password": "StrongPass123!",
            "password_confirm": "StrongPass123!",
        })
        self.assertTrue(form.is_valid(), form.errors)
        admin = form.save()
        admin.refresh_from_db()
        self.assertEqual(admin.email, "new.owner@example.com")
        self.assertEqual(admin.phone, "+493012345688")
        self.assertTrue(admin.auth_user.check_password("StrongPass123!"))
        self.assertEqual(admin.auth_user.profile.phone, admin.phone)

    def test_existing_unlinked_admin_is_not_automatically_bound_during_edit(self):
        admin, _ = self.make_admin(user=False)
        form = BusinessAdminForm(instance=admin, data={
            "name": "Edited manager", "phone": admin.phone, "email": admin.email,
            "is_active": True, "payment_status": "unpaid", "password": "", "password_confirm": "",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("verified auth-user link", str(form.errors))
        self.assertEqual(User.objects.count(), 0)

    def test_audit_is_dry_run_and_does_not_print_contact_details(self):
        admin, _ = self.make_admin(email="private.owner@example.com", phone="+493012345678", user=False)
        out = __import__("io").StringIO()
        call_command("audit_business_admin_identity", stdout=out)
        report = json.loads(out.getvalue())
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(report["accounts"][0]["business_admin_id"], admin.id)
        self.assertIn(admin.id, [row["business_admin_id"] for row in report["incomplete_links"]])
        self.assertNotIn("private.owner@example.com", out.getvalue())
        self.assertNotIn("+493012345678", out.getvalue())

    def test_unsubscribed_account_is_not_mislabeled_as_legacy(self):
        admin, _ = self.make_admin(email="none@example.com", phone="+493012345679", user=False)
        entitlement = resolve_subscription_entitlement(admin)
        self.assertEqual(entitlement["state"], "none")
        self.assertFalse(entitlement["is_entitled"])
        self.assertEqual(entitlement["entitlement_source"], "none")


@override_settings(SECURE_SSL_REDIRECT=False)
class BusinessAdminIdentityLoginTests(APITestCase):
    def make_account(self, suffix, *, restaurant_active=True, with_restaurant=True):
        email = f"owner{suffix}@example.com"
        phone = f"+4930123456{suffix:02d}"
        user = User.objects.create_user(username=f"owner{suffix}", email=email, password="StrongPass123!")
        admin = BusinessAdmin.objects.create(auth_user=user, name="Owner", email=email, phone=phone, payment_status="unpaid")
        restaurant = None
        if with_restaurant:
            restaurant = Restaurant.objects.create(admin=admin, name="Restaurant", is_active=restaurant_active)
        return user, admin, restaurant

    def test_unsubscribed_manager_with_active_restaurant_gets_login_and_false_entitlement(self):
        user, admin, _ = self.make_account(1)
        response = self.client.post("/api/business-menu/login/", {
            "email": admin.email.upper(), "password": "StrongPass123!",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["admin"]["id"], admin.id)
        self.assertEqual(response.data["restaurant"]["id"], admin.restaurant.id)
        self.assertFalse(response.data["subscription"]["is_entitled"])
        self.assertTrue(response.data["access"])

    def test_missing_or_inactive_restaurant_does_not_issue_tokens(self):
        _, unassigned, _ = self.make_account(2, with_restaurant=False)
        response = self.client.post("/api/business-menu/login/", {
            "email": unassigned.email, "password": "StrongPass123!",
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "restaurant_not_assigned")
        self.assertNotIn("access", response.data)

    def test_reset_password_returns_complete_login_payload_or_no_token_without_restaurant(self):
        from accounts.models import PasswordResetCode
        from django.utils import timezone
        from datetime import timedelta

        user, admin, _ = self.make_account(9)
        PasswordResetCode.objects.create(
            user=user, email=admin.email, code="123456", expires_at=timezone.now() + timedelta(minutes=5),
        )
        response = self.client.post("/api/business-menu/reset-password/", {
            "email": f" {admin.email.upper()} ", "code": "123456", "password": "NewStrongPass123!",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["admin"]["id"], admin.id)
        self.assertEqual(response.data["restaurant"]["id"], admin.restaurant.id)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

        user2, admin2, _ = self.make_account(10, with_restaurant=False)
        PasswordResetCode.objects.create(
            user=user2, email=admin2.email, code="654321", expires_at=timezone.now() + timedelta(minutes=5),
        )
        no_restaurant = self.client.post("/api/business-menu/reset-password/", {
            "email": admin2.email, "code": "654321", "password": "NewStrongPass123!",
        }, format="json")
        self.assertEqual(no_restaurant.status_code, 403)
        self.assertEqual(no_restaurant.data["code"], "restaurant_not_assigned")
        self.assertNotIn("access", no_restaurant.data)

        _, inactive, _ = self.make_account(3, restaurant_active=False)
        response = self.client.post("/api/business-menu/login/", {
            "email": inactive.email, "password": "StrongPass123!",
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "restaurant_inactive")
        self.assertNotIn("access", response.data)

    def test_identity_resolver_ignores_tampered_business_id_header(self):
        user, admin, _ = self.make_account(4)
        _, other_admin, _ = self.make_account(5)
        self.assertEqual(_get_business_admin_for_user(user, request=SimpleNamespace(
            headers={"X-Business-Id": str(other_admin.id)}, query_params={"business_id": other_admin.id}
        )).id, admin.id)

    def test_profile_edit_updates_the_linked_user_and_profile_only(self):
        user, admin, _ = self.make_account(8)
        self.client.force_authenticate(user=user)
        response = self.client.patch("/api/business-menu/update-profile/", {
            "email": " New.Owner@example.com ", "phone": "+49 30 1234 5677",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        admin.refresh_from_db()
        user.refresh_from_db()
        user.profile.refresh_from_db()
        self.assertEqual(admin.email, "new.owner@example.com")
        self.assertEqual(admin.phone, "+493012345677")
        self.assertEqual(user.email, admin.email)
        self.assertEqual(user.profile.phone, admin.phone)
        self.assertEqual(user.profile.role, user.profile.Role.ADMIN)

    def test_ambiguous_email_stops_without_trying_password_candidates(self):
        candidates = Mock()
        candidates.select_related.return_value = candidates
        candidates.count.return_value = 2
        with patch("business_menu.views.BusinessAdmin.objects.filter", return_value=candidates):
            response = self.client.post("/api/business-menu/login/", {
                "email": "ambiguous@example.com", "password": "StrongPass123!",
            }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["message"], "Invalid email or password.")
        self.assertNotIn("access", response.data)

    def test_category_writes_cannot_create_or_target_another_restaurant_by_id_or_phone(self):
        owner, own_admin, own_restaurant = self.make_account(6)
        _, other_admin, other_restaurant = self.make_account(7)
        foreign_category = Category.objects.create(restaurant=other_restaurant, name="Foreign")
        self.client.force_authenticate(user=owner)

        response = self.client.post("/api/business-menu/categories/", {
            "name": "Injected", "restaurant_id": other_restaurant.id, "phone": "+493012345699",
        }, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Category.objects.filter(name="Injected").count(), 0)
        self.assertEqual(BusinessAdmin.objects.count(), 2)
        self.assertEqual(Restaurant.objects.count(), 2)

        response = self.client.patch(f"/api/business-menu/categories/{foreign_category.id}/", {
            "name": "Taken over",
        }, format="json")
        self.assertEqual(response.status_code, 404)
        foreign_category.refresh_from_db()
        self.assertEqual(foreign_category.name, "Foreign")

        response = self.client.post("/api/business-menu/categories/", {
            "name": "Owned", "restaurant_id": own_restaurant.id,
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Category.objects.get(name="Owned").restaurant_id, own_restaurant.id)


class BusinessAdminIdentityMigrationPreflightTests(TestCase):
    def run_preflight(self, rows):
        from importlib import import_module
        validate_business_admin_identities = import_module(
            "business_menu.migrations.0037_businessadmin_identity_constraints"
        ).validate_business_admin_identities

        class Manager:
            def using(self, alias):
                return self

            def values_list(self, *fields):
                return rows

        class HistoricalModel:
            objects = Manager()

        apps = SimpleNamespace(get_model=lambda *args: HistoricalModel)
        schema_editor = SimpleNamespace(connection=SimpleNamespace(alias="default"))
        validate_business_admin_identities(apps, schema_editor)

    def test_preflight_allows_clean_rows_and_rejects_collisions_and_empty_emails(self):
        self.run_preflight([(1, "one@example.com", "+493012345678")])
        for rows, expected in (
            ([(1, "one@example.com", "+493012345678"), (2, "ONE@example.com", "+493012345679")], "duplicate_email_id_groups=[[1, 2]]"),
            ([(5, "five@example.com", "+493012345678"), (6, "six@example.com", "0049 30 1234 5678")], "duplicate_phone_id_groups=[[5, 6]]"),
            ([(3, "", "+493012345678")], "empty_or_invalid_email_ids=[3]"),
            ([(4, "four@example.com", "03012345678")], "invalid_or_ambiguous_phone_ids=[4]"),
        ):
            with self.assertRaisesRegex(RuntimeError, re.escape(expected)):
                self.run_preflight(rows)

    def test_data_migration_canonicalizes_clean_rows(self):
        from importlib import import_module
        normalize_business_admin_identities = import_module(
            "business_menu.migrations.0037_businessadmin_identity_constraints"
        ).normalize_business_admin_identities
        updates = []

        class Rows(list):
            def iterator(self):
                return iter(self)

        class Manager:
            def using(self, alias):
                return self

            def values_list(self, *fields):
                return Rows([(1, " Owner@Example.com ", "0049 30 1234 5678")])

            def filter(self, **kwargs):
                return self

            def update(self, **values):
                updates.append(values)

        class HistoricalModel:
            objects = Manager()

        apps = SimpleNamespace(get_model=lambda *args: HistoricalModel)
        schema_editor = SimpleNamespace(connection=SimpleNamespace(alias="default"))
        normalize_business_admin_identities(apps, schema_editor)
        self.assertEqual(updates, [{"email": "owner@example.com", "phone": "+493012345678"}])
