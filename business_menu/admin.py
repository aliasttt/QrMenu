import hashlib
import json
import logging
import uuid
from datetime import datetime, time

from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from accounts.models import Profile
from .models import (
    BusinessAdmin,
    ProviderEvent,
    ProviderSubscription,
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
    Courier,
    Order,
    Payment,
)
from .subscription_services import (
    SubscriptionConfigurationError,
    SubscriptionVerificationError,
    apply_apple_transaction_to_admin,
    apply_manual_subscription,
    cancel_manual_subscription,
    resolve_subscription_entitlement,
    verify_apple_transaction_id,
)


logger = logging.getLogger(__name__)


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


@admin.register(ProviderSubscription)
class ProviderSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "account",
        "provider",
        "environment",
        "status",
        "current_period_end",
        "will_renew",
        "verification_source",
        "needs_reconciliation",
    )
    list_filter = ("provider", "environment", "status", "verification_source", "needs_reconciliation")
    search_fields = ("account__email", "account__phone", "external_id", "latest_transaction_id")
    exclude = ("provider_customer_id",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)


@admin.register(ProviderEvent)
class ProviderEventAdmin(admin.ModelAdmin):
    list_display = ("subscription", "event_type", "occurred_at", "processed_at", "state_applied")
    list_filter = ("provider", "environment", "event_type", "state_applied")
    search_fields = ("external_event_id", "subscription__external_id")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)


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


class SubscriptionManagementForm(forms.Form):
    action_id = forms.UUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Reason",
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Required. Stored in the Django admin audit log.",
    )
    custom_end = forms.DateField(
        label="Custom end date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    apple_transaction_id = forms.CharField(
        label="Apple transaction ID",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    apple_environment = forms.ChoiceField(
        label="Apple environment",
        choices=(("Production", "Production"), ("Sandbox", "Sandbox")),
        required=False,
        initial="Production",
    )
    apple_evidence_reference = forms.CharField(
        label="Independent ownership evidence reference",
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=(
            "Required for legacy recovery. Reference evidence that predates this approval and links "
            "the purchase to this account; login, the JWS, or an invoice alone is insufficient."
        ),
    )
    confirm_apple_recovery = forms.BooleanField(
        label="I verified the independent ownership evidence and approve this binding",
        required=False,
    )


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    """مدیریت رستوران‌ها"""
    form = RestaurantForm
    list_display = (
        'name', 'admin', 'effective_subscription_status', 'subscription_source',
        'subscription_plan', 'subscription_expires', 'manage_subscription_link',
        'timezone', 'is_active', 'created_at',
    )
    list_filter = ('is_active', 'admin', 'created_at')
    search_fields = ('name', 'description', 'address', 'admin__name', 'admin__phone', 'admin__email')
    readonly_fields = (
        'subscription_owner', 'subscription_effective_details',
        'subscription_provider_details', 'manage_subscription_link',
        'created_at', 'updated_at',
    )
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
            'fields': ('admin', 'name', 'description', 'restaurant_type', 'public_slug')
        }),
        ('اطلاعات تماس و مکان', {
            'fields': (
                'address', 'city', 'country', 'timezone', 'postal_code',
                'phone', 'email', 'whatsapp', 'website',
            )
        }),
        ('گالری و ساعات', {
            'fields': ('logo', 'gallery', 'cover_image_index', 'working_hours', 'closed_today'),
        }),
        ('نقشه', {
            'fields': ('latitude', 'longitude', 'google_place_id'),
        }),
        ('وضعیت', {
            'fields': ('is_active',)
        }),
        ('Subscription', {
            'fields': (
                'subscription_owner', 'subscription_effective_details',
                'subscription_provider_details', 'manage_subscription_link',
            ),
            'description': (
                'Service access is owned by the BusinessAdmin. Blocking access here does not cancel '
                'automatic renewal at Apple, Google Play, or Stripe.'
            ),
        }),
        ('اطلاعات سیستم', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("admin").prefetch_related("admin__provider_subscriptions")
        # Ensure settings exist for all restaurants (legacy data)
        try:
            for r in qs.only("id"):
                RestaurantSettings.objects.get_or_create(restaurant=r)
        except Exception:
            pass
        return qs

    def get_urls(self):
        return [
            path(
                '<path:object_id>/subscription/',
                self.admin_site.admin_view(self.subscription_management_view),
                name='business_menu_restaurant_subscription',
            ),
        ] + super().get_urls()

    def _entitlement(self, obj):
        if not hasattr(obj, '_admin_entitlement'):
            obj._admin_entitlement = resolve_subscription_entitlement(obj.admin)
        return obj._admin_entitlement

    @admin.display(description="Effective subscription")
    def effective_subscription_status(self, obj):
        entitlement = self._entitlement(obj)
        return entitlement['state'] if entitlement['is_entitled'] else f"{entitlement['state']} (no access)"

    @admin.display(description="Source")
    def subscription_source(self, obj):
        entitlement = self._entitlement(obj)
        return entitlement.get('entitlement_source') or entitlement.get('provider') or '-'

    @admin.display(description="Plan")
    def subscription_plan(self, obj):
        return self._entitlement(obj).get('plan') or '-'

    @admin.display(description="Expires")
    def subscription_expires(self, obj):
        return self._entitlement(obj).get('current_period_end') or '-'

    @admin.display(description="Subscription owner")
    def subscription_owner(self, obj):
        affected = Restaurant.objects.filter(admin=obj.admin).values_list('name', flat=True)
        return format_html(
            '<strong>{}</strong><br>Owner ID: {}<br>Affected restaurants: {}',
            obj.admin,
            obj.admin_id,
            ', '.join(affected) or '-',
        )

    @admin.display(description="Effective access")
    def subscription_effective_details(self, obj):
        entitlement = self._entitlement(obj)
        return format_html(
            'Access: <strong>{}</strong><br>Status: {}<br>Reason: {}<br>'
            'Source: {} / {}<br>Plan: {}<br>End: {}<br>Auto-renew: {}',
            'enabled' if entitlement['is_entitled'] else 'disabled',
            entitlement['state'],
            entitlement.get('decision_reason') or '-',
            entitlement.get('entitlement_source') or '-',
            entitlement.get('provider') or '-',
            entitlement.get('plan') or '-',
            entitlement.get('current_period_end') or '-',
            entitlement.get('will_renew') if entitlement.get('will_renew') is not None else 'unknown',
        )

    @admin.display(description="Provider records (read only)")
    def subscription_provider_details(self, obj):
        rows = obj.admin.provider_subscriptions.all().order_by('provider', '-current_period_end')
        if not rows:
            return 'No provider records.'
        return format_html_join(
            format_html('<br>'),
            '{} / {} — {} — plan {} — start {} — end {} — auto-renew {}',
            (
                (
                    row.get_provider_display(), row.environment, row.get_status_display(),
                    row.product_id or '-', row.created_at, row.current_period_end or '-',
                    row.will_renew if row.will_renew is not None else 'unknown',
                )
                for row in rows
            ),
        )

    @admin.display(description="Manage subscription")
    def manage_subscription_link(self, obj):
        if not obj or not obj.pk:
            return '-'
        url = reverse('admin:business_menu_restaurant_subscription', args=[obj.pk])
        return format_html('<a class="button" href="{}">Manage subscription</a>', url)

    def _audit_snapshot(self, account):
        entitlement = resolve_subscription_entitlement(account)
        return {
            'is_entitled': entitlement['is_entitled'],
            'state': entitlement['state'],
            'provider': entitlement.get('provider'),
            'plan': entitlement.get('plan'),
            'current_period_end': entitlement.get('current_period_end'),
            'access_blocked': account.subscription_access_blocked,
            'block_reason': account.subscription_access_block_reason,
        }

    def _apply_subscription_action(self, request, restaurant, form, action):
        allowed = {
            'grant_month', 'grant_year', 'extend_month', 'extend_year',
            'grant_custom', 'cancel_manual', 'block', 'unblock',
        }
        if action not in allowed:
            raise ValidationError('Unknown subscription action.')
        action_id = form.cleaned_data['action_id']
        reason = form.cleaned_data['reason'].strip()
        now = timezone.now()

        with transaction.atomic():
            account = BusinessAdmin.objects.select_for_update().get(pk=restaurant.admin_id)
            if account.subscription_last_admin_action_id == action_id:
                return False
            before = self._audit_snapshot(account)

            if action in {'grant_month', 'grant_year', 'extend_month', 'extend_year'}:
                months = 12 if action.endswith('year') else 1
                plan = 'manual_yearly' if months == 12 else 'manual_monthly'
                apply_manual_subscription(
                    account,
                    event_id=f'admin:{action_id}',
                    plan=plan,
                    months=months,
                    extend=action.startswith('extend_'),
                    now=now,
                )
            elif action == 'grant_custom':
                custom_end = form.cleaned_data['custom_end']
                if not custom_end:
                    raise ValidationError('Custom end date is required.')
                expires_at = timezone.make_aware(
                    datetime.combine(custom_end, time.max), timezone.get_current_timezone()
                )
                if expires_at <= now:
                    raise ValidationError('Custom end date must be in the future.')
                apply_manual_subscription(
                    account,
                    event_id=f'admin:{action_id}',
                    plan='manual_custom',
                    expires_at=expires_at,
                    now=now,
                )
            elif action == 'cancel_manual':
                cancel_manual_subscription(account, event_id=f'admin:{action_id}', now=now)
            elif action == 'block':
                account.subscription_access_blocked = True
                account.subscription_access_blocked_at = now
                account.subscription_access_blocked_by = request.user
                account.subscription_access_block_reason = reason
            elif action == 'unblock':
                account.subscription_access_blocked = False
                account.subscription_access_blocked_at = None
                account.subscription_access_blocked_by = None
                account.subscription_access_block_reason = ''

            account.subscription_last_admin_action_id = action_id
            account.save(update_fields=[
                'subscription_access_blocked', 'subscription_access_blocked_at',
                'subscription_access_blocked_by', 'subscription_access_block_reason',
                'subscription_last_admin_action_id', 'updated_at',
            ])
            account.refresh_from_db()
            after = self._audit_snapshot(account)

        self.log_change(
            request,
            restaurant,
            f"Subscription action={action}; reason={reason}; "
            f"before={json.dumps(before, sort_keys=True)}; after={json.dumps(after, sort_keys=True)}",
        )
        return True

    def _recover_apple_purchase(self, request, restaurant, form):
        transaction_id = form.cleaned_data["apple_transaction_id"].strip()
        environment = form.cleaned_data["apple_environment"]
        evidence_reference = form.cleaned_data["apple_evidence_reference"].strip()
        if not transaction_id:
            raise ValidationError("Apple transaction ID is required.")
        if not evidence_reference:
            raise ValidationError("Independent ownership evidence reference is required.")
        if not form.cleaned_data["confirm_apple_recovery"]:
            raise ValidationError("Confirm that the independent ownership evidence was verified.")

        action_id = form.cleaned_data["action_id"]
        if BusinessAdmin.objects.filter(
            pk=restaurant.admin_id,
            subscription_last_admin_action_id=action_id,
        ).exists():
            return False

        result = verify_apple_transaction_id(transaction_id, environment=environment)
        verified_transaction_id = str(result.payload.get("transactionId") or "")
        original_transaction_id = str(result.payload.get("originalTransactionId") or "")

        with transaction.atomic():
            account = BusinessAdmin.objects.select_for_update().get(pk=restaurant.admin_id)
            if account.subscription_last_admin_action_id == action_id:
                return False
            before = self._audit_snapshot(account)
            apply_apple_transaction_to_admin(
                account,
                result,
                recovery_approved_by=request.user,
            )
            account.subscription_last_admin_action_id = action_id
            account.save(update_fields=["subscription_last_admin_action_id", "updated_at"])
            account.refresh_from_db()
            after = self._audit_snapshot(account)

        transaction_hash = hashlib.sha256(verified_transaction_id.encode()).hexdigest()[:16]
        original_hash = hashlib.sha256(original_transaction_id.encode()).hexdigest()[:16]
        self.log_change(
            request,
            restaurant,
            f"Subscription action=recover_apple; reason={form.cleaned_data['reason'].strip()}; "
            f"evidence={evidence_reference}; transaction_sha256={transaction_hash}; "
            f"original_sha256={original_hash}; before={json.dumps(before, sort_keys=True)}; "
            f"after={json.dumps(after, sort_keys=True)}",
        )
        return True

    def subscription_management_view(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        try:
            restaurant = self.get_queryset(request).get(pk=object_id)
        except Restaurant.DoesNotExist as exc:
            raise Http404 from exc

        form = SubscriptionManagementForm(request.POST or None, initial={'action_id': uuid.uuid4()})
        if request.method == 'POST' and form.is_valid():
            try:
                action = request.POST.get('action', '')
                if action == 'recover_apple':
                    changed = self._recover_apple_purchase(request, restaurant, form)
                else:
                    changed = self._apply_subscription_action(request, restaurant, form, action)
            except ValidationError as exc:
                form.add_error(None, exc)
            except SubscriptionConfigurationError:
                logger.exception("Apple recovery configuration error")
                form.add_error(None, "Apple verification is temporarily unavailable.")
            except SubscriptionVerificationError as exc:
                form.add_error(None, str(exc))
            else:
                self.message_user(
                    request,
                    'Subscription updated.' if changed else 'This action was already applied.',
                    level=messages.SUCCESS if changed else messages.INFO,
                )
                return redirect(reverse('admin:business_menu_restaurant_subscription', args=[restaurant.pk]))

        account = BusinessAdmin.objects.prefetch_related('provider_subscriptions').get(pk=restaurant.admin_id)
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': f'Subscription — {restaurant.name}',
            'restaurant': restaurant,
            'owner': account,
            'affected_restaurants': Restaurant.objects.filter(admin=account),
            'entitlement': resolve_subscription_entitlement(account),
            'provider_subscriptions': account.provider_subscriptions.all().order_by('provider', '-current_period_end'),
            'form': form,
            'change_url': reverse('admin:business_menu_restaurant_change', args=[restaurant.pk]),
        }
        return TemplateResponse(
            request,
            'admin/business_menu/restaurant/subscription_management.html',
            context,
        )

    def admin_phone(self, obj):
        return getattr(obj.admin, "phone", "") or "-"
    admin_phone.short_description = "Admin phone"

    def admin_email(self, obj):
        email = getattr(obj.admin, "email", "") or ""
        return email.strip() or "-"
    admin_email.short_description = "Admin email"

    def delete_model(self, request, obj):
        """
        Use an explicit transaction for single deletes so admin can show
        a clear error instead of surfacing raw DB integrity exceptions.
        """
        try:
            with transaction.atomic():
                obj.delete()
        except IntegrityError:
            self.message_user(
                request,
                (
                    f'حذف رستوران "{obj}" انجام نشد. '
                    "ابتدا رکوردهای وابسته (مثل سفارش/پرداخت/رزرو) را حذف کنید و دوباره تلاش کنید."
                ),
                level=messages.ERROR,
            )

    def delete_queryset(self, request, queryset):
        """
        Avoid bulk fast-delete edge-cases by deleting row-by-row.
        This keeps behavior predictable when there are many related rows.
        """
        failed = []
        deleted_count = 0
        for obj in queryset:
            try:
                with transaction.atomic():
                    obj.delete()
                    deleted_count += 1
            except IntegrityError:
                failed.append(str(obj))

        if deleted_count:
            self.message_user(
                request,
                f"{deleted_count} رستوران با موفقیت حذف شد.",
                level=messages.SUCCESS,
            )
        if failed:
            self.message_user(
                request,
                (
                    "حذف بعضی رستوران‌ها انجام نشد به‌خاطر داده‌های وابسته: "
                    + ", ".join(failed[:5])
                    + (" ..." if len(failed) > 5 else "")
                ),
                level=messages.ERROR,
            )


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
@admin.register(Courier)
class CourierAdmin(admin.ModelAdmin):
    list_display = ("id", "restaurant", "name", "phone", "is_active", "created_at")
    list_filter = ("is_active", "restaurant", "created_at")
    search_fields = ("name", "phone", "restaurant__name")
    readonly_fields = ("created_at",)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("stripe_payment_intent_id", "stripe_charge_id", "amount", "currency", "status", "created_at")
    can_delete = True
    show_change_link = True


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """سفارشات هر رستوران"""
    list_display = (
        "id", "restaurant", "customer_short", "service_type", "table_number",
        "payment_method", "status", "courier", "total_amount", "currency", "created_at",
    )
    list_filter = ("status", "service_type", "payment_method", "restaurant", "created_at")
    search_fields = ("restaurant__name", "customer__email", "customer__phone", "customer__name", "stripe_order_id")
    readonly_fields = ("created_at", "updated_at")
    list_editable = ("status",)
    inlines = [PaymentInline]
    raw_id_fields = ("customer", "courier")

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
    list_display = (
        "name",
        "phone",
        "restaurant",
        "business_admin",
        "orders_count",
        "total_spent",
        "last_order_at",
        "created_at",
    )
    list_filter = ("restaurant", "business_admin", "source", "created_at")
    search_fields = (
        "name",
        "first_name",
        "last_name",
        "email",
        "phone",
        "address",
        "restaurant__name",
        "business_admin__name",
        "stripe_customer_id",
    )
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("restaurant", "business_admin", "last_order")


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
