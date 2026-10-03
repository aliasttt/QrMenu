from types import SimpleNamespace

from django.test import RequestFactory, TestCase, override_settings

from .models import (
    BusinessAdmin,
    Category,
    MenuItem,
    MenuItemImage,
    MenuQRCode,
    Restaurant,
    RestaurantSettings,
)
from .public_menu import get_restaurant_public_media
from .serializers import CategorySerializer, RestaurantProfileSerializer


class _Logo:
    def __init__(self, url):
        self.url = url

    def __bool__(self):
        return True


class _BrokenLogo:
    @property
    def url(self):
        raise ValueError("legacy file without a usable URL")

    def __bool__(self):
        return True


class RestaurantPublicMediaTests(TestCase):
    def test_cover_uses_original_gallery_index_and_moves_only_the_cover_first(self):
        restaurant = SimpleNamespace(
            logo=_Logo("https://cdn.example/logo.png"),
            gallery=[
                "https://cdn.example/first.jpg",
                "",
                "https://cdn.example/cover.jpg",
                "https://cdn.example/last.jpg",
            ],
            cover_image_index=2,
        )

        media = get_restaurant_public_media(restaurant)

        self.assertEqual(media["logo_url"], "https://cdn.example/logo.png")
        self.assertEqual(media["cover_url"], "https://cdn.example/cover.jpg")
        self.assertEqual(
            media["gallery_urls"],
            [
                "https://cdn.example/cover.jpg",
                "https://cdn.example/first.jpg",
                "https://cdn.example/last.jpg",
            ],
        )

        restaurant.cover_image_index = 0
        zero_cover = get_restaurant_public_media(restaurant)
        self.assertEqual(zero_cover["cover_url"], "https://cdn.example/first.jpg")
        self.assertEqual(
            zero_cover["gallery_urls"],
            [
                "https://cdn.example/first.jpg",
                "https://cdn.example/cover.jpg",
                "https://cdn.example/last.jpg",
            ],
        )

    def test_invalid_cover_falls_back_without_shifting_over_invalid_entries(self):
        for cover_index in (1, 99, "bad", True):
            with self.subTest(cover_index=cover_index):
                restaurant = SimpleNamespace(
                    logo=None,
                    gallery=["https://cdn.example/first.jpg", None, "https://cdn.example/last.jpg"],
                    cover_image_index=cover_index,
                )
                media = get_restaurant_public_media(restaurant)
                self.assertEqual(media["cover_url"], "https://cdn.example/first.jpg")
                self.assertEqual(
                    media["gallery_urls"],
                    ["https://cdn.example/first.jpg", "https://cdn.example/last.jpg"],
                )

    def test_empty_or_legacy_media_is_safe_and_logo_is_independent(self):
        logo_only = get_restaurant_public_media(
            SimpleNamespace(
                logo=_Logo("/media/logo.png"), gallery=[], cover_image_index=0
            )
        )
        invalid = get_restaurant_public_media(
            SimpleNamespace(
                logo=_BrokenLogo(), gallery={"not": "a list"}, cover_image_index=None
            )
        )

        self.assertEqual(logo_only["card_image_url"], "/media/logo.png")
        self.assertEqual(logo_only["gallery_urls"], [])
        self.assertEqual(invalid["logo_url"], "")
        self.assertEqual(invalid["cover_url"], "")


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STRIPE_SECRET_KEY="",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class PublicMenuRouteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = BusinessAdmin.objects.create(phone="+493012345601", name="Owner one", email="owner-one@example.test")
        cls.restaurant = Restaurant.objects.create(
            admin=cls.admin,
            name="Same restaurant",
            public_slug="fixture-menu",
            logo="restaurants/logos/real-logo.png",
            gallery=[
                "https://cdn.example/gallery-one.jpg",
                "https://cdn.example/selected-cover.jpg",
                "https://cdn.example/gallery-three.jpg",
            ],
            cover_image_index=1,
        )
        RestaurantSettings.objects.filter(restaurant=cls.restaurant).update(show_images=True)
        cls.qr = MenuQRCode.objects.get(restaurant=cls.restaurant)
        cls.qr.token = "fixture-token"
        cls.qr.save(update_fields=["token"])

        cls.early = Category.objects.create(
            restaurant=cls.restaurant, name="Early category", order=1
        )
        cls.late = Category.objects.create(
            restaurant=cls.restaurant, name="Late category", order=5
        )
        Category.objects.create(
            restaurant=cls.restaurant, name="Empty category", order=0
        )
        cls.inactive = Category.objects.create(
            restaurant=cls.restaurant, name="Inactive category", order=2, is_active=False
        )

        cls.second_admin = BusinessAdmin.objects.create(phone="+493012345602", name="Owner two", email="owner-two@example.test")
        cls.second_restaurant = Restaurant.objects.create(
            admin=cls.second_admin,
            name="Same restaurant",
            logo="restaurants/logos/second-logo.png",
        )
        cls.foreign_category = Category.objects.create(
            restaurant=cls.second_restaurant, name="Foreign category", order=0
        )

        cls.late_item = MenuItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.late,
            name="Late item",
            price="10.00",
            order=0,
        )
        cls.early_item = MenuItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.early,
            name="Early item",
            price="11.00",
            order=5,
        )
        MenuItemImage.objects.create(
            menu_item=cls.early_item,
            image="business_menu/items/food-only.jpg",
        )
        MenuItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.inactive,
            name="Inactive item",
            price="12.00",
            order=2,
        )
        MenuItem.objects.create(
            restaurant=cls.restaurant,
            category=cls.foreign_category,
            name="Cross restaurant item",
            price="13.00",
            order=3,
        )
        cls.other_item = MenuItem.objects.create(
            restaurant=cls.restaurant,
            category=None,
            name="Uncategorized item",
            price="14.00",
            order=4,
        )

    def test_numeric_slug_and_qr_routes_share_media_and_safe_category_rules(self):
        urls = (
            f"/restaurants/{self.restaurant.id}/menu/",
            "/m/fixture-menu/",
            "/business-menu/qr/fixture-token/",
        )

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["logo_url"], "/media/restaurants/logos/real-logo.png")
                self.assertEqual(
                    response.context["gallery_urls"],
                    [
                        "https://cdn.example/selected-cover.jpg",
                        "https://cdn.example/gallery-one.jpg",
                        "https://cdn.example/gallery-three.jpg",
                    ],
                )
                self.assertEqual(
                    [category["name"] for category in response.context["category_list"]],
                    ["Early category", "Late category", "Other"],
                )
                self.assertTrue(
                    all("thumb" not in category for category in response.context["category_list"])
                )
                visible_names = [item["name"] for item in response.context["menu_cards"]]
                self.assertNotIn("Inactive item", visible_names)
                self.assertNotIn("Cross restaurant item", visible_names)
                self.assertIn("Uncategorized item", visible_names)
                self.assertNotIn(
                    "/media/business_menu/items/food-only.jpg",
                    response.context["gallery_urls"],
                )

    def test_restaurant_list_uses_cover_then_logo_then_local_placeholder(self):
        no_media_admin = BusinessAdmin.objects.create(phone="+493012345603", name="Owner three", email="owner-three@example.test")
        no_media = Restaurant.objects.create(admin=no_media_admin, name="No media")

        response = self.client.get("/restaurants/")

        self.assertEqual(response.status_code, 200)
        by_id = {restaurant.id: restaurant for restaurant in response.context["restaurants"]}
        self.assertEqual(
            by_id[self.restaurant.id].public_media["card_image_url"],
            "https://cdn.example/selected-cover.jpg",
        )
        self.assertEqual(
            by_id[self.second_restaurant.id].public_media["card_image_url"],
            "/media/restaurants/logos/second-logo.png",
        )
        self.assertEqual(by_id[no_media.id].public_media["card_image_url"], "")
        self.assertNotContains(response, "loremflickr.com")
        self.assertNotContains(response, "picsum.photos")
        self.assertContains(response, "onerror=")

    def test_show_images_only_controls_food_images(self):
        settings_obj = self.restaurant.settings
        settings_obj.show_images = False
        settings_obj.save(update_fields=["show_images"])

        response = self.client.get(f"/restaurants/{self.restaurant.id}/menu/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["logo_url"])
        self.assertTrue(response.context["gallery_urls"])
        self.assertTrue(all(not item["image_url"] for item in response.context["menu_cards"]))

    def test_existing_profile_and_category_serializer_contracts_are_unchanged(self):
        request = RequestFactory().get("/")
        profile = RestaurantProfileSerializer(
            self.restaurant, context={"request": request}
        ).data
        category = CategorySerializer(self.early).data

        self.assertEqual(
            set(profile),
            {
                "name", "logo", "description", "restaurant_type", "email", "phone",
                "whatsapp", "website", "address", "city", "country", "postal_code",
                "latitude", "longitude", "google_place_id", "google_maps_url", "gallery",
                "cover_image_index", "working_hours", "closed_today", "timezone",
            },
        )
        self.assertEqual(set(category), {"id", "restaurant", "name", "order"})

    def test_navbar_relies_on_alpine_automatic_init_only(self):
        response = self.client.get("/restaurants/")
        self.assertNotContains(response, 'x-init="init()"')
