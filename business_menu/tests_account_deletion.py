import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from .account_deletion import purge_account_media
from .models import (
    AccountMediaDeletion, BusinessAdmin, Category, CloudinaryImage, Courier,
    Customer, MenuItem, MenuItemImage, MenuSet, Order, Package, PackageItem,
    Payment, ProviderSubscription, Reservation, ReservationSettings,
    Restaurant, RestaurantSettings, RetainedFinancialRecord,
)
from .subscription_services import apply_provider_event, SubscriptionOwnershipError


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AccountDeletionTests(APITestCase):
    url = "/api/business-menu/admin/account/"

    def setUp(self):
        self.user = User.objects.create_user("deleting", "owner@example.com", "CurrentPass123!")
        self.admin = BusinessAdmin.objects.create(
            auth_user=self.user, name="Owner", email=self.user.email, phone="+493012345678",
        )
        self.restaurant = Restaurant.objects.create(admin=self.admin, name="Restaurant")
        self.refresh = RefreshToken.for_user(self.user)
        self.second_refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.refresh.access_token}")

    def delete(self, data=None):
        return self.client.delete(self.url, data or {"password": "CurrentPass123!"}, format="json")

    def test_password_required_and_wrong_password_do_not_mutate(self):
        for data in ({}, {"password": ""}, {"password": None}, {"password": 42}):
            response = self.client.delete(self.url, data, format="json")
            self.assertEqual((response.status_code, response.json()), (400, {"detail": "password_required"}))
        response = self.delete({"password": "wrong"})
        self.assertEqual((response.status_code, response.json()), (403, {"detail": "invalid_password"}))
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(BlacklistedToken.objects.exists())

    def test_invalid_missing_expired_and_refresh_tokens_are_401(self):
        expired = self.refresh.access_token
        expired.set_exp(lifetime=timedelta(seconds=-1))
        for token in (None, "broken", str(expired), str(self.refresh)):
            self.client.credentials(**({"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}))
            self.assertEqual(self.delete().status_code, 401)

    def test_delete_revokes_sessions_and_retries_are_204(self):
        self.client.force_login(self.user)
        self.assertTrue(Session.objects.exists())
        with self.captureOnCommitCallbacks(execute=True):
            response = self.delete()
        self.assertEqual(response.status_code, 204, response.content)
        self.assertEqual(response.content, b"")
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(BusinessAdmin.objects.filter(pk=self.admin.pk).exists())
        self.assertFalse(Restaurant.objects.filter(pk=self.restaurant.pk).exists())
        self.assertFalse(Session.objects.exists())
        self.assertEqual(BlacklistedToken.objects.count(), 2)
        self.assertEqual(self.delete().status_code, 204)
        for token in (self.refresh, self.second_refresh):
            for path in ("/api/business-menu/token/refresh/", "/api/accounts/token/refresh/"):
                self.assertEqual(self.client.post(path, {"refresh": str(token)}, format="json").status_code, 401)
        self.assertEqual(self.client.get("/api/business-menu/admin/subscription/").status_code, 401)

    def test_untracked_legacy_refresh_cannot_refresh_deleted_user(self):
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

        OutstandingToken.objects.all().delete()
        self.assertEqual(self.delete().status_code, 204)
        self.assertEqual(self.client.post("/api/business-menu/refresh/", {"refresh": str(self.refresh)}, format="json").status_code, 401)

    def test_other_account_and_non_business_user_are_preserved(self):
        other = User.objects.create_user("other", password="OtherPass123!")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(other).access_token}")
        self.assertEqual(self.delete({"password": "OtherPass123!"}).status_code, 403)
        self.assertTrue(User.objects.filter(pk=other.pk).exists())
        self.assertTrue(Restaurant.objects.filter(pk=self.restaurant.pk).exists())

    def test_active_refresh_still_works_on_all_aliases(self):
        for path in ("/api/business-menu/token/refresh/", "/api/business-menu/refresh/",
                     "/api/v1/token/refresh/", "/api/accounts/token/refresh/",
                     "/api/v1/accounts/token/refresh/"):
            response = self.client.post(path, {"refresh": str(self.refresh)}, format="json")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertIn("access", response.data)

    def test_admin_history_cannot_retain_erased_personal_details(self):
        operator = User.objects.create_user("operator", password="OperatorPass123!")
        courier = Courier.objects.create(restaurant=self.restaurant, name="Private Courier", phone="private")
        for target in (self.user, self.admin, self.restaurant, courier):
            LogEntry.objects.create(user=operator, content_type=ContentType.objects.get_for_model(target), object_id=str(target.pk), object_repr="Private email and phone", action_flag=ADDITION, change_message="Private history")
        unrelated = LogEntry.objects.create(user=operator, content_type=ContentType.objects.get_for_model(operator), object_id=str(operator.pk), object_repr="Preserve unrelated history", action_flag=ADDITION)
        self.assertEqual(self.delete().status_code, 204)
        self.assertEqual(list(LogEntry.objects.values_list("pk", flat=True)), [unrelated.pk])

    def test_cloudinary_ownership_cleanup_preserves_other_restaurant(self):
        other_user = User.objects.create_user("other_owner", password="OtherPass123!")
        other = BusinessAdmin.objects.create(auth_user=other_user, name="Other", email="other@example.com", phone="+493012345679")
        other_restaurant = Restaurant.objects.create(admin=other, name="Other Restaurant")
        own_item = MenuItem.objects.create(restaurant=self.restaurant, name="Own", price=1)
        other_item = MenuItem.objects.create(restaurant=other_restaurant, name="Other", price=1)
        orphan = CloudinaryImage.objects.create(owner=self.admin, cloudinary_public_id="owned-unattached", cloudinary_url="https://example.com/own")
        linked = CloudinaryImage.objects.create(cloudinary_public_id="linked-legacy", cloudinary_url="https://example.com/legacy")
        shared = CloudinaryImage.objects.create(owner=self.admin, cloudinary_public_id="shared", cloudinary_url="https://example.com/shared")
        for item, image in ((own_item, linked), (own_item, shared), (other_item, shared)):
            MenuItemImage.objects.create(menu_item=item, cloudinary_image=image)
        with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}) as destroy:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.delete().status_code, 204)
        self.assertEqual({call.args[0] for call in destroy.call_args_list}, {"owned-unattached", "linked-legacy"})
        self.assertTrue(CloudinaryImage.objects.filter(pk=shared.pk).exists())
        self.assertTrue(MenuItemImage.objects.filter(menu_item=other_item, cloudinary_image=shared).exists())
        self.assertTrue(User.objects.filter(pk=other_user.pk).exists())
        self.assertTrue(Restaurant.objects.filter(pk=other_restaurant.pk).exists())

    def test_operations_deleted_financials_detached_and_purchase_cannot_be_reclaimed(self):
        category = Category.objects.create(restaurant=self.restaurant, name="Food")
        item = MenuItem.objects.create(restaurant=self.restaurant, category=category, name="Dish", price=12)
        MenuSet.objects.create(restaurant=self.restaurant, name="Set")
        package = Package.objects.create(restaurant=self.restaurant, name="Deal", package_price=10)
        PackageItem.objects.create(package=package, menu_item=item)
        Customer.objects.create(restaurant=self.restaurant, business_admin=self.admin, email="private@example.com")
        Reservation.objects.create(restaurant=self.restaurant, requested_date=timezone.localdate(), customer_name="Private guest")
        ReservationSettings.objects.create(restaurant=self.restaurant, tables=[{"name": "Private table"}])
        Courier.objects.create(restaurant=self.restaurant, name="Private courier", phone="private")
        order = Order.objects.create(restaurant=self.restaurant, total_amount=12, notes="Private address", items_json={"email": "private"})
        Payment.objects.create(restaurant=self.restaurant, order=order, amount=12, stripe_charge_id="ch_refund_reference")
        sub = ProviderSubscription.objects.create(account=self.admin, provider="apple", environment="production", external_id="purchase")
        self.assertEqual(self.delete().status_code, 204)
        for model in (Category, MenuItem, MenuSet, Package, PackageItem, Customer, Courier,
                      Reservation, ReservationSettings, RestaurantSettings, Order, Payment):
            self.assertFalse(model.objects.exists())
        self.assertEqual(self.client.get(f"/en/restaurants/{self.restaurant.pk}/menu/").status_code, 404)
        self.assertEqual(RetainedFinancialRecord.objects.count(), 2)
        self.assertNotIn("Private", str(list(RetainedFinancialRecord.objects.values_list("data", flat=True))))
        sub.refresh_from_db()
        self.assertIsNone(sub.account_id)
        other = BusinessAdmin.objects.create(name="Other", email="other@example.com", phone="+493012345679")
        with self.assertRaises(SubscriptionOwnershipError):
            apply_provider_event(account=other, provider="apple", environment="Production", external_id="purchase", event_id="new", event_type="renewal", status="active", current_period_end=timezone.now() + timedelta(days=30))

    def test_files_deleted_and_external_failure_has_durable_retry(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            name = default_storage.save("restaurants/logo.png", ContentFile(b"image"))
            gallery = default_storage.save(f"restaurants/{self.restaurant.pk}/gallery/photo.png", ContentFile(b"gallery"))
            self.restaurant.logo = name
            self.restaurant.gallery = [default_storage.url(gallery)]
            self.restaurant.save()
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.delete().status_code, 204)
            self.assertFalse(default_storage.exists(name))
            self.assertFalse(default_storage.exists(gallery))
        job = AccountMediaDeletion.objects.create(backend="cloudinary", name="private/upload")
        with patch("cloudinary.uploader.destroy", side_effect=RuntimeError("offline")):
            self.assertEqual(purge_account_media(), 1)
        self.assertTrue(AccountMediaDeletion.objects.filter(pk=job.pk).exists())
        with patch("cloudinary.uploader.destroy", return_value={"result": "ok"}) as destroy:
            self.assertEqual(purge_account_media(), 0)
            destroy.assert_called_once_with("private/upload", invalidate=True)

    def test_financial_archive_failure_rolls_back_deletion(self):
        with patch("business_menu.account_deletion._retain_financials", side_effect=RuntimeError("db failed")):
            with self.assertRaises(RuntimeError):
                self.delete()
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(Restaurant.objects.filter(pk=self.restaurant.pk).exists())
        self.assertFalse(BlacklistedToken.objects.exists())
