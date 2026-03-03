from __future__ import annotations

import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class BusinessAdmin(models.Model):
    """
    Restaurant/cafe admins registered manually by super admin
    """
    auth_user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_menu_admin",
        help_text="Linked auth user for API authentication (do not edit manually unless needed)",
    )
    phone = models.CharField(max_length=32, unique=True, db_index=True, help_text="Admin phone number")
    name = models.CharField(max_length=200, help_text="Admin name")
    email = models.EmailField(blank=True, help_text="Admin email (optional)")
    is_active = models.BooleanField(default=True, help_text="Active/Inactive status")
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ('unpaid', 'Unpaid'),
            ('paid', 'Paid'),
        ],
        default='unpaid',
        help_text="Payment status - users cannot login until payment is confirmed"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name="created_business_admins",
        help_text="Super admin user who created this admin"
    )
    
    class Meta:
        verbose_name = "Business Menu Admin"
        verbose_name_plural = "Business Menu Admins"
        ordering = ['-created_at']
    
    def __str__(self) -> str:
        email = (self.email or "").strip()
        if email:
            return f"{self.name} ({self.phone}) - {email}"
        return f"{self.name} ({self.phone})"


class Restaurant(models.Model):
    """
    Restaurant or cafe managed by admin
    Each admin can only manage one restaurant (one phone number = one restaurant)
    """
    admin = models.OneToOneField(
        BusinessAdmin, 
        on_delete=models.CASCADE, 
        related_name="restaurant",
        help_text="Admin of this restaurant (one admin = one restaurant)"
    )
    name = models.CharField(max_length=200, help_text="Restaurant/cafe name")
    description = models.TextField(blank=True, help_text="Restaurant description")
    address = models.TextField(blank=True, help_text="Restaurant address")
    phone = models.CharField(max_length=32, blank=True, help_text="Restaurant phone number")
    is_active = models.BooleanField(default=True, help_text="Active/Inactive status")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Restaurant"
        verbose_name_plural = "Restaurants"
        ordering = ['-created_at']
    
    def __str__(self) -> str:
        return f"{self.name} - {self.admin.name}"


class MenuItem(models.Model):
    """
    Restaurant menu items
    """
    restaurant = models.ForeignKey(
        Restaurant, 
        on_delete=models.CASCADE, 
        related_name="menu_items",
        help_text="Related restaurant"
    )
    category = models.ForeignKey(
        'Category',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="menu_items",
        help_text="Menu item category"
    )
    name = models.CharField(max_length=200, help_text="Menu item name")
    description = models.TextField(blank=True, help_text="Item description")
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        help_text="Price in currency unit (e.g., EUR)"
    )
    stock = models.CharField(
        max_length=50, 
        blank=True, 
        help_text="Stock status (e.g., 'Available', 'Out of stock', or quantity)"
    )
    is_available = models.BooleanField(default=True, help_text="Is this item available?")
    order = models.PositiveIntegerField(default=0, help_text="Display order in menu")
    serial = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Serial number for menu item (optional)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Menu Item"
        verbose_name_plural = "Menu Items"
        ordering = ['order', 'name']
        indexes = [
            # Important: keep this name stable to avoid migrations trying to rename it (SQLite deploy issues)
            models.Index(fields=['restaurant', 'is_available'], name='business_me_restaur_idx'),
        ]
    
    def __str__(self) -> str:
        return f"{self.name} - {self.restaurant.name}"


class CloudinaryImage(models.Model):
    """
    مدل برای ذخیره اطلاعات تصاویر در Cloudinary با UUID
    """
    uuid = models.UUIDField(
        unique=True, 
        db_index=True, 
        default=uuid.uuid4,
        editable=False,
        help_text="UUID یکتا برای تصویر"
    )
    cloudinary_public_id = models.CharField(
        max_length=255, 
        unique=True, 
        db_index=True,
        help_text="Public ID در Cloudinary"
    )
    cloudinary_url = models.URLField(
        max_length=500,
        help_text="URL کامل تصویر در Cloudinary"
    )
    secure_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="URL امن تصویر در Cloudinary (HTTPS)"
    )
    format = models.CharField(
        max_length=10,
        blank=True,
        help_text="فرمت تصویر (jpg, png, etc.)"
    )
    width = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="عرض تصویر"
    )
    height = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="ارتفاع تصویر"
    )
    bytes_size = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="حجم فایل به بایت"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Cloudinary Image"
        verbose_name_plural = "Cloudinary Images"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['uuid']),
            models.Index(fields=['cloudinary_public_id']),
        ]
    
    def __str__(self) -> str:
        return f"Image {str(self.uuid)[:8]}"
    
    def get_url(self, secure=True):
        """بازگرداندن URL تصویر"""
        return self.secure_url if secure and self.secure_url else self.cloudinary_url


class MenuItemImage(models.Model):
    """
    Menu item images - اکنون از UUID برای امنیت بیشتر استفاده می‌کند
    """
    menu_item = models.ForeignKey(
        MenuItem, 
        on_delete=models.CASCADE, 
        related_name="images",
        help_text="Related menu item"
    )
    # نگه داشتن image برای سازگاری با کدهای قدیمی
    image = models.ImageField(
        upload_to="business_menu/items/", 
        help_text="Menu item image (legacy)",
        null=True,
        blank=True
    )
    # استفاده از UUID برای امنیت بیشتر
    cloudinary_image = models.ForeignKey(
        CloudinaryImage,
        on_delete=models.CASCADE,
        related_name="menu_item_images",
        null=True,
        blank=True,
        help_text="تصویر در Cloudinary با UUID"
    )
    order = models.PositiveIntegerField(default=0, help_text="Image display order")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Menu Item Image"
        verbose_name_plural = "Menu Item Images"
        ordering = ['order', 'created_at']
    
    def __str__(self) -> str:
        return f"Image {self.menu_item.name}"
    
    def get_image_url(self, request=None, secure=True):
        """بازگرداندن URL تصویر (اولویت با Cloudinary)"""
        if self.cloudinary_image:
            return self.cloudinary_image.get_url(secure=secure)
        elif self.image:
            if request:
                return request.build_absolute_uri(self.image.url)
            return self.image.url
        return None


class Category(models.Model):
    """
    Menu categories for organizing menu items
    """
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="categories",
        help_text="Related restaurant"
    )
    name = models.CharField(max_length=200, help_text="Category name")
    order = models.PositiveIntegerField(default=0, help_text="Display order")
    is_active = models.BooleanField(default=True, help_text="Is this category active?")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ['order', 'name']
        unique_together = ('restaurant', 'name')
    
    def __str__(self) -> str:
        return f"{self.name} - {self.restaurant.name}"


class MenuSet(models.Model):
    """
    Menu sets/groups for organizing menu items
    """
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="menu_sets",
        help_text="Related restaurant"
    )
    name = models.CharField(max_length=200, help_text="Menu set name")
    description = models.TextField(blank=True, help_text="Menu set description")
    order = models.PositiveIntegerField(default=0, help_text="Display order")
    is_active = models.BooleanField(default=True, help_text="Is this menu set active?")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Menu Set"
        verbose_name_plural = "Menu Sets"
        ordering = ['order', 'name']
        unique_together = ('restaurant', 'name')
    
    def __str__(self) -> str:
        return f"{self.name} - {self.restaurant.name}"


class Package(models.Model):
    """
    Package/Deal containing multiple menu items with special pricing
    """
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="packages",
        help_text="Related restaurant"
    )
    name = models.CharField(max_length=200, help_text="Package name")
    description = models.TextField(blank=True, help_text="Package description")
    package_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Package price (discounted price)"
    )
    image = models.ImageField(
        upload_to='packages/',
        blank=True,
        null=True,
        help_text="Package image"
    )
    is_active = models.BooleanField(default=True, help_text="Is this package active?")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Package"
        verbose_name_plural = "Packages"
        ordering = ['-created_at']
    
    def __str__(self) -> str:
        return f"{self.name} - {self.restaurant.name}"
    
    def calculate_original_price(self):
        """محاسبه قیمت اصلی از مجموع قیمت آیتم‌ها"""
        total = 0
        for package_item in self.package_items.all():
            if package_item.menu_item and package_item.menu_item.price:
                total += package_item.menu_item.price * package_item.quantity
        return total
    
    def calculate_discount_percent(self):
        """محاسبه درصد تخفیف"""
        original_price = self.calculate_original_price()
        if original_price > 0:
            discount = original_price - self.package_price
            return round((discount / original_price) * 100, 2)
        return 0
    
    @property
    def original_price(self):
        """قیمت اصلی (property)"""
        return self.calculate_original_price()
    
    @property
    def discount_percent(self):
        """درصد تخفیف (property)"""
        return self.calculate_discount_percent()


class PackageItem(models.Model):
    """
    Menu items included in a package with quantity
    """
    package = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name="package_items",
        help_text="Related package"
    )
    menu_item = models.ForeignKey(
        'MenuItem',
        on_delete=models.CASCADE,
        related_name="package_items",
        help_text="Menu item in package"
    )
    quantity = models.PositiveIntegerField(default=1, help_text="Quantity of this item in package")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Package Item"
        verbose_name_plural = "Package Items"
        unique_together = ('package', 'menu_item')
    
    def __str__(self) -> str:
        return f"{self.package.name} - {self.menu_item.name} x{self.quantity}"


class MenuTheme(models.Model):
    """
    Theme for the public web menu page (selected from the app settings screen)
    """
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, db_index=True)
    # Store static path (served by WhiteNoise / collectstatic)
    preview_static_path = models.CharField(
        max_length=255,
        blank=True,
        help_text="Static path for theme preview image (e.g. business_menu/themes/previews/classic.svg)",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Menu Theme"
        verbose_name_plural = "Menu Themes"
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name


class RestaurantSettings(models.Model):
    """
    Per-restaurant display settings for the public menu page
    """
    restaurant = models.OneToOneField(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="settings",
    )
    menu_theme = models.ForeignKey(
        MenuTheme,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="restaurant_settings",
    )
    show_prices = models.BooleanField(default=True)
    show_images = models.BooleanField(default=True)
    show_descriptions = models.BooleanField(default=True)
    show_serial = models.BooleanField(default=False, help_text="Show serial numbers in menu display")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Restaurant Settings"
        verbose_name_plural = "Restaurant Settings"

    def __str__(self) -> str:
        return f"Settings - {self.restaurant.name}"


class MenuQRCode(models.Model):
    """
    Menu QR code for each restaurant
    """
    restaurant = models.OneToOneField(
        Restaurant, 
        on_delete=models.CASCADE, 
        related_name="menu_qrcode",
        help_text="Related restaurant"
    )
    token = models.CharField(max_length=64, unique=True, db_index=True, help_text="Unique token for QR code")
    menu_url = models.URLField(blank=True, null=True, help_text="Menu URL stored in database")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    @staticmethod
    def generate_token() -> str:
        """Generate unique token for QR code"""
        return uuid.uuid4().hex
    
    def save(self, *args, **kwargs):
        if not self.token:
            self.token = self.generate_token()
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = "Menu QR Code"
        verbose_name_plural = "Menu QR Codes"
    
    def __str__(self) -> str:
        return f"Menu QR {self.restaurant.name} - {self.token[:8]}"
