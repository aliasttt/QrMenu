from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django import forms
from django.core.exceptions import ValidationError
from accounts.models import Profile
from .models import (
    BusinessAdmin,
    Restaurant,
    Category,
    MenuSet,
    MenuItem,
    MenuItemImage,
    MenuQRCode,
    CloudinaryImage,
    Package,
    PackageItem,
    MenuTheme,
    RestaurantSettings,
    Customer,
    Order,
    Payment,
)


class BusinessAdminForm(forms.ModelForm):
    """Custom form for BusinessAdmin with password field"""
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={'placeholder': 'Enter password'}),
        required=False,
        help_text="Required when creating new admin. Leave empty to keep current password when editing."
    )
    password_confirm = forms.CharField(
        label="Password confirmation",
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm password'}),
        required=False,
        help_text="Enter the same password as before, for verification."
    )
    
    class Meta:
        model = BusinessAdmin
        fields = ['name', 'phone', 'email', 'is_active', 'payment_status']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            # For new admins, password is required
            self.fields['password'].required = True
            self.fields['password_confirm'].required = True
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        
        # For new admins, password is required
        if not self.instance.pk:
            if not password:
                raise ValidationError({'password': 'Password is required when creating a new admin.'})
            if password != password_confirm:
                raise ValidationError({'password_confirm': 'Passwords do not match.'})
        else:
            # For existing admins, if password is provided, it must match confirmation
            if password and password != password_confirm:
                raise ValidationError({'password_confirm': 'Passwords do not match.'})
        
        return cleaned_data
    
    def save(self, commit=True):
        admin_obj = super().save(commit=False)
        
        # Create or update User
        if not admin_obj.auth_user_id:
            # Create new user
            username = admin_obj.phone.replace('+', '').replace('-', '').replace(' ', '')
            username = f"business_menu_admin_{username}"
            # Ensure username is unique
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1
            
            user = User.objects.create_user(
                username=username,
                email=admin_obj.email or f"{username}@business.local",
                first_name=admin_obj.name.split()[0] if admin_obj.name else '',
                last_name=' '.join(admin_obj.name.split()[1:]) if len(admin_obj.name.split()) > 1 else '',
                is_active=admin_obj.is_active
            )
            admin_obj.auth_user = user
            
            # Set password
            password = self.cleaned_data.get('password')
            if password:
                user.set_password(password)
                user.save()
            
            # Create Profile
            profile, created = Profile.objects.get_or_create(user=user)
            profile.role = Profile.Role.ADMIN
            profile.phone = admin_obj.phone
            profile.is_active = admin_obj.is_active
            profile.save()
        else:
            # Update existing user
            user = admin_obj.auth_user
            user.email = admin_obj.email or user.email
            name_parts = admin_obj.name.split()
            if name_parts:
                user.first_name = name_parts[0]
                user.last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
            user.is_active = admin_obj.is_active
            
            # Update password if provided
            password = self.cleaned_data.get('password')
            if password:
                user.set_password(password)
            
            user.save()
            
            # Update Profile
            profile, created = Profile.objects.get_or_create(user=user)
            profile.phone = admin_obj.phone
            profile.is_active = admin_obj.is_active
            profile.save()
        
        if commit:
            admin_obj.save()
        
        return admin_obj


@admin.register(BusinessAdmin)
class BusinessMenuAdminAdmin(admin.ModelAdmin):
    """
    Business Menu Admin management in Django Admin panel (for Menu App)
    Super admin can manually add new admins
    Note: This is separate from Loyalty Business Admin
    """
    form = BusinessAdminForm
    list_display = ('name', 'phone', 'email', 'payment_status', 'is_active', 'created_at', 'created_by')
    list_filter = ('payment_status', 'is_active', 'created_at')
    search_fields = ('name', 'phone', 'email')
    readonly_fields = ('created_at', 'updated_at', 'auth_user')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'phone', 'email')
        }),
        ('Password', {
            'fields': ('password', 'password_confirm'),
            'description': 'Enter a password. Password is required when creating new admin.'
        }),
        ('Status', {
            'fields': ('is_active', 'payment_status')
        }),
        ('System Information', {
            'fields': ('auth_user', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """
        Set current user as created_by when creating new admin
        """
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    # Note: Restaurant is now OneToOneField, so we don't use inline here
    # Restaurant is managed separately in RestaurantAdmin

    def has_add_permission(self, request):
        # Only superuser can register a new restaurant admin
        return bool(request.user and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)


class MenuItemImageInline(admin.TabularInline):
    """Inline for managing menu item images"""
    model = MenuItemImage
    extra = 1
    fields = ('image', 'cloudinary_image', 'image_uuid_display', 'order')
    readonly_fields = ('image_uuid_display',)
    
    def image_uuid_display(self, obj):
        """نمایش UUID تصویر"""
        if obj and obj.cloudinary_image:
            return str(obj.cloudinary_image.uuid)
        return '-'
    image_uuid_display.short_description = 'UUID'


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    """Menu Item management"""
    list_display = ('name', 'restaurant', 'price', 'is_available', 'order', 'created_at')
    list_filter = ('is_available', 'restaurant', 'created_at')
    search_fields = ('name', 'description', 'restaurant__name')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [MenuItemImageInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('restaurant', 'name', 'description')
        }),
        ('Price & Stock', {
            'fields': ('price', 'stock', 'is_available')
        }),
        ('Display', {
            'fields': ('order',)
        }),
        ('System Information', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


class RestaurantForm(forms.ModelForm):
    """Custom form for Restaurant with validation"""
    
    class Meta:
        model = Restaurant
        fields = '__all__'
    
    def clean_admin(self):
        admin = self.cleaned_data.get('admin')
        if admin:
            # Check if this admin is already assigned to another restaurant
            existing_restaurant = Restaurant.objects.filter(admin=admin)
            if self.instance.pk:
                # Exclude current instance when editing
                existing_restaurant = existing_restaurant.exclude(pk=self.instance.pk)
            
            if existing_restaurant.exists():
                existing = existing_restaurant.first()
                raise ValidationError(
                    f'این شماره تلفن ({admin.phone}) قبلاً برای رستوران "{existing.name}" استفاده شده است. '
                    f'هر شماره تلفن فقط می‌تواند به یک رستوران متصل باشد.'
                )
        return admin


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    """مدیریت رستوران‌ها"""
    form = RestaurantForm
    list_display = ('name', 'admin', 'admin_phone', 'admin_email', 'is_active', 'created_at')
    list_filter = ('is_active', 'admin', 'created_at')
    search_fields = ('name', 'description', 'address', 'admin__name', 'admin__phone', 'admin__email')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ("admin",)

    class RestaurantSettingsInline(admin.StackedInline):
        model = RestaurantSettings
        extra = 0
        can_delete = False

    class PackageInline(admin.TabularInline):
        model = Package
        extra = 0
        show_change_link = True
        fields = ("name", "package_price", "is_active", "created_at")
        readonly_fields = ("created_at",)

    inlines = [RestaurantSettingsInline, PackageInline]
    
    fieldsets = (
        ('اطلاعات اصلی', {
            'fields': ('admin', 'name', 'description')
        }),
        ('اطلاعات تماس', {
            'fields': ('address', 'phone')
        }),
        ('وضعیت', {
            'fields': ('is_active',)
        }),
        ('اطلاعات سیستم', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Ensure settings exist for all restaurants (legacy data)
        try:
            for r in qs.only("id"):
                RestaurantSettings.objects.get_or_create(restaurant=r)
        except Exception:
            pass
        return qs

    def admin_phone(self, obj):
        return getattr(obj.admin, "phone", "") or "-"
    admin_phone.short_description = "Admin phone"

    def admin_email(self, obj):
        email = getattr(obj.admin, "email", "") or ""
        return email.strip() or "-"
    admin_email.short_description = "Admin email"


# ——— منوها: دسته‌بندی و مجموعه‌ها ———
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """دسته‌بندی‌های منو"""
    list_display = ("name", "restaurant", "order", "is_active", "created_at")
    list_filter = ("is_active", "restaurant", "created_at")
    search_fields = ("name", "restaurant__name")
    ordering = ("restaurant", "order", "name")
    list_editable = ("order", "is_active")


@admin.register(MenuSet)
class MenuSetAdmin(admin.ModelAdmin):
    """مجموعه‌های منو"""
    list_display = ("name", "restaurant", "order", "is_active", "created_at")
    list_filter = ("is_active", "restaurant", "created_at")
    search_fields = ("name", "description", "restaurant__name")
    ordering = ("restaurant", "order", "name")
    list_editable = ("order", "is_active")


@admin.register(MenuQRCode)
class MenuQRCodeAdmin(admin.ModelAdmin):
    """Menu QR Code management"""
    list_display = ('restaurant', 'token_short', 'created_at', 'menu_url_display')
    list_filter = ('created_at',)
    search_fields = ('restaurant__name', 'token')
    readonly_fields = ('token', 'created_at', 'updated_at', 'menu_url_display')
    
    fieldsets = (
        ('Information', {
            'fields': ('restaurant', 'token')
        }),
        ('Menu Link', {
            'fields': ('menu_url_display',)
        }),
        ('System Information', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def token_short(self, obj):
        """Display short token"""
        return obj.token[:16] + '...' if len(obj.token) > 16 else obj.token
    token_short.short_description = 'Token'
    
    def menu_url_display(self, obj):
        """Display menu link"""
        if obj.pk:
            # Use stored menu_url or construct it
            menu_url = obj.menu_url or f"https://your-domain.com/business-menu/qr/{obj.token}/"
            return format_html('<a href="{}" target="_blank">{}</a>', menu_url, menu_url)
        return '-'
    menu_url_display.short_description = 'Menu URL'


# ——— سفارشات ———
class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("stripe_payment_intent_id", "stripe_charge_id", "amount", "currency", "status", "created_at")
    can_delete = True
    show_change_link = True


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """سفارشات هر رستوران"""
    list_display = ("id", "restaurant", "customer_short", "status", "total_amount", "currency", "created_at")
    list_filter = ("status", "restaurant", "created_at")
    search_fields = ("restaurant__name", "customer__email", "customer__phone", "customer__name", "stripe_order_id")
    readonly_fields = ("created_at", "updated_at")
    list_editable = ("status",)
    inlines = [PaymentInline]
    raw_id_fields = ("customer",)

    def customer_short(self, obj):
        if not obj.customer:
            return "—"
        return obj.customer.name or obj.customer.email or obj.customer.phone or "—"
    customer_short.short_description = "مشتری"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """پرداخت‌ها (وضعیت از Stripe)"""
    list_display = ("id", "restaurant", "order", "amount", "currency", "status", "created_at")
    list_filter = ("status", "restaurant", "created_at")
    search_fields = ("restaurant__name", "stripe_payment_intent_id", "stripe_charge_id")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("order",)


# ——— مشتریان (CRM) ———
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """مشتریان — داده از Stripe/سفارشات"""
    list_display = ("name", "email", "phone", "restaurant", "stripe_customer_id", "created_at")
    list_filter = ("restaurant", "created_at")
    search_fields = ("name", "email", "phone", "restaurant__name", "stripe_customer_id")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("restaurant",)


@admin.register(MenuItemImage)
class MenuItemImageAdmin(admin.ModelAdmin):
    """لیست تصاویر آیتم‌های منو"""
    list_display = ("id", "menu_item", "menu_item_restaurant", "order", "created_at")
    list_filter = ("menu_item__restaurant", "created_at")
    search_fields = ("menu_item__name",)
    raw_id_fields = ("menu_item", "cloudinary_image")
    readonly_fields = ("created_at",)

    def menu_item_restaurant(self, obj):
        return obj.menu_item.restaurant.name if obj.menu_item_id else "—"
    menu_item_restaurant.short_description = "رستوران"


@admin.register(CloudinaryImage)
class CloudinaryImageAdmin(admin.ModelAdmin):
    """مدیریت تصاویر Cloudinary"""
    list_display = ('uuid_short', 'cloudinary_public_id', 'format', 'width', 'height', 'bytes_size_display', 'created_at')
    list_filter = ('format', 'created_at')
    search_fields = ('uuid', 'cloudinary_public_id')
    readonly_fields = ('uuid', 'cloudinary_url', 'secure_url', 'format', 'width', 'height', 'bytes_size', 'created_at', 'updated_at', 'image_preview')
    
    fieldsets = (
        ('اطلاعات UUID', {
            'fields': ('uuid',)
        }),
        ('اطلاعات Cloudinary', {
            'fields': ('cloudinary_public_id', 'cloudinary_url', 'secure_url')
        }),
        ('اطلاعات تصویر', {
            'fields': ('format', 'width', 'height', 'bytes_size')
        }),
        ('پیش‌نمایش', {
            'fields': ('image_preview',)
        }),
        ('اطلاعات سیستم', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def uuid_short(self, obj):
        """نمایش UUID کوتاه"""
        return str(obj.uuid)[:16] + '...' if obj.uuid else '-'
    uuid_short.short_description = 'UUID'
    
    def bytes_size_display(self, obj):
        """نمایش حجم فایل به صورت خوانا"""
        if obj.bytes_size:
            if obj.bytes_size < 1024:
                return f"{obj.bytes_size} B"
            elif obj.bytes_size < 1024 * 1024:
                return f"{obj.bytes_size / 1024:.2f} KB"
            else:
                return f"{obj.bytes_size / (1024 * 1024):.2f} MB"
        return '-'
    bytes_size_display.short_description = 'حجم'
    
    def image_preview(self, obj):
        """پیش‌نمایش تصویر"""
        if obj and obj.secure_url:
            return format_html('<img src="{}" style="max-width: 200px; max-height: 200px;" />', obj.secure_url)
        return '-'
    image_preview.short_description = 'پیش‌نمایش'


class PackageItemInline(admin.TabularInline):
    """Inline for managing package items"""
    model = PackageItem
    extra = 1
    fields = ('menu_item', 'quantity')
    autocomplete_fields = ('menu_item',)


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    """مدیریت پکیج‌ها"""
    list_display = ('name', 'restaurant', 'package_price', 'original_price_display', 'discount_percent_display', 'is_active', 'created_at')
    list_filter = ('is_active', 'restaurant', 'created_at')
    search_fields = ('name', 'description', 'restaurant__name')
    readonly_fields = ('created_at', 'updated_at', 'original_price_display', 'discount_percent_display')
    inlines = [PackageItemInline]
    
    fieldsets = (
        ('اطلاعات اصلی', {
            'fields': ('restaurant', 'name', 'description')
        }),
        ('قیمت', {
            'fields': ('package_price', 'original_price_display', 'discount_percent_display')
        }),
        ('تصویر', {
            'fields': ('image',)
        }),
        ('وضعیت', {
            'fields': ('is_active',)
        }),
        ('اطلاعات سیستم', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def original_price_display(self, obj):
        """نمایش قیمت اصلی"""
        if obj.pk:
            return f"{obj.original_price:.2f}"
        return '-'
    original_price_display.short_description = 'قیمت اصلی'
    
    def discount_percent_display(self, obj):
        """نمایش درصد تخفیف"""
        if obj.pk:
            return f"{obj.discount_percent}%"
        return '-'
    discount_percent_display.short_description = 'تخفیف'


@admin.register(MenuTheme)
class MenuThemeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")


@admin.register(RestaurantSettings)
class RestaurantSettingsAdmin(admin.ModelAdmin):
    """تنظیمات نمایش منو هر رستوران"""
    list_display = ("restaurant", "menu_theme", "show_prices", "show_images", "show_descriptions", "show_serial", "updated_at")
    list_filter = ("menu_theme", "show_prices", "show_images", "show_descriptions", "show_serial")
    search_fields = ("restaurant__name", "restaurant__phone")
