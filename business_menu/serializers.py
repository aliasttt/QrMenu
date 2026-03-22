from rest_framework import serializers
from decimal import Decimal, InvalidOperation
from .models import (
    BusinessAdmin,
    Restaurant,
    MenuItem,
    MenuItemImage,
    MenuQRCode,
    CloudinaryImage,
    Category,
    MenuSet,
    Package,
    PackageItem,
    MenuTheme,
    RestaurantSettings,
)
from .cloudinary_utils import upload_image_to_cloudinary, get_image_url_by_uuid


def normalize_price_value(value):
    """
    تابع کمکی برای normalize کردن قیمت
    پشتیبانی از هر دو فرمت کاما و نقطه برای اعشار
    مثال: "12,50" -> "12.50", "12.50" -> "12.50", "1,234.56" -> "1234.56"
    """
    if value is None:
        return None
    
    # تبدیل به string
    if isinstance(value, (list, tuple)) and len(value) > 0:
        value = value[0]
    
    if not isinstance(value, str):
        value = str(value)
    
    # حذف فاصله‌ها و کاراکترهای غیرقابل نمایش
    value = value.strip().replace(" ", "").replace("\u200c", "").replace("\u200d", "").replace("\xa0", "")

    # بعضی کیبوردها (خصوصاً فارسی/عربی روی iOS) جداکننده‌ها را با کاراکترهای متفاوت می‌فرستند
    # Arabic decimal separator: "٫" (U+066B)
    # Arabic thousand separator: "٬" (U+066C)
    # Arabic comma: "،" (U+060C)
    value = value.translate(
        str.maketrans(
            {
                "٫": ".",  # decimal separator
                "٬": ",",  # thousand separator -> treat like comma, logic below will handle
                "،": ",",  # comma
            }
        )
    )
    
    # اگر خالی شد
    if not value:
        return None
    
    # اگر فقط نقطه یا کاما است، نادیده بگیر
    if value in ['.', ',', '-', '-.', '-,']:
        return None
    
    # بررسی وجود نقطه و کاما
    has_comma = ',' in value
    has_dot = '.' in value
    
    if has_comma and has_dot:
        # اگر هم نقطه و هم کاما دارد، آخرین جداکننده اعشار را پیدا کن
        last_comma_pos = value.rfind(',')
        last_dot_pos = value.rfind('.')
        
        if last_dot_pos > last_comma_pos:
            # نقطه آخر است، پس کاماها را حذف کن (مثل "1,234.56")
            value = value.replace(',', '')
        else:
            # کاما آخر است، پس نقطه‌ها را حذف کن و کاما را به نقطه تبدیل کن (مثل "1.234,56")
            value = value.replace('.', '').replace(',', '.')
    elif has_comma:
        # اگر فقط کاما دارد، آن را به نقطه تبدیل کن
        value = value.replace(',', '.')
    # اگر فقط نقطه دارد یا هیچکدام ندارد، بدون تغییر نگه دار
    
    # حذف کاراکترهای غیر عددی (به جز نقطه و منفی در ابتدا)
    # فقط اعداد، نقطه و منفی در ابتدا را نگه دار
    cleaned = ''
    has_dot = False
    for i, char in enumerate(value):
        if char.isdigit():
            cleaned += char
        elif char == '.' and not has_dot:
            cleaned += char
            has_dot = True
        elif char == '-' and i == 0:
            cleaned += char
    
    # اگر خالی شد یا فقط منفی است
    if not cleaned or cleaned == '-':
        return None
    
    # اگر با نقطه شروع یا تمام می‌شود، اصلاح کن
    if cleaned.startswith('.'):
        cleaned = '0' + cleaned
    if cleaned.endswith('.'):
        cleaned = cleaned[:-1]
    
    # اگر فقط یک نقطه است
    if cleaned == '.':
        return None
    
    return cleaned


class CommaDecimalField(serializers.DecimalField):
    """DecimalField که ویرگول را به نقطه تبدیل می‌کند برای پشتیبانی از کیبورد iPhone"""
    
    def to_internal_value(self, data):
        """تبدیل ویرگول به نقطه قبل از validation"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"CommaDecimalField.to_internal_value called with data: {data}, type: {type(data)}")
        
        if data is None:
            if self.required:
                self.fail('required')
            return None
        
        # اگر قبلاً normalize شده (string است و فقط نقطه دارد)، مستقیماً استفاده کن
        if isinstance(data, str) and ',' not in data and '.' in data:
            # احتمالاً قبلاً normalize شده
            normalized_data = data
        else:
            # استفاده از تابع normalize
            original_data = data
            normalized_data = normalize_price_value(data)
            logger.info(f"CommaDecimalField normalized: {original_data} -> {normalized_data}")
        
        # اگر خالی شد بعد از normalize
        if normalized_data is None or normalized_data == '':
            if self.required:
                self.fail('required')
            return None
        
        # فراخوانی متد والد با مقدار normalize شده
        try:
            result = super().to_internal_value(normalized_data)
            logger.info(f"CommaDecimalField success: {normalized_data} -> {result}")
            return result
        except Exception as e:
            # اگر خطا داد، خطای بهتری نمایش بده
            logger.error(f"CommaDecimalField error: {str(e)}, original: {data}, normalized: {normalized_data}, type: {type(data)}")
            # اگر خطای validation است، پیام بهتری بده
            if 'valid number' in str(e).lower() or 'invalid' in str(e).lower():
                raise serializers.ValidationError("Invalid price. Please enter a valid number (e.g. 12.50 or 12,50)")
            raise


class BusinessAdminSerializer(serializers.ModelSerializer):
    """Serializer برای ادمین رستوران"""
    email = serializers.EmailField(allow_blank=True, required=False)
    
    class Meta:
        model = BusinessAdmin
        fields = ('id', 'phone', 'name', 'email', 'is_active', 'created_at')
        read_only_fields = ('id', 'created_at')
    
    def to_representation(self, instance):
        """تبدیل empty string به None برای نمایش"""
        data = super().to_representation(instance)
        # اگر email empty string است، آن را None کن برای نمایش بهتر
        if data.get('email') == '':
            data['email'] = None
        return data


class BusinessAdminUpdateSerializer(serializers.ModelSerializer):
    """Serializer برای آپدیت پروفایل ادمین (فقط email و phone)"""
    class Meta:
        model = BusinessAdmin
        fields = ('phone', 'email')
        extra_kwargs = {
            'phone': {'required': False},
            'email': {'required': False, 'allow_blank': True},
        }
    
    def validate_phone(self, value):
        """بررسی فرمت شماره تلفن"""
        if value is not None and value != '':
            # بعضی کلاینت‌ها phone را به صورت عدد/لیست می‌فرستند
            if isinstance(value, (list, tuple)):
                value = value[0] if value else ''
            value = str(value).strip()
            if not value:
                raise serializers.ValidationError("Phone number cannot be empty")
            # استفاده از format_phone_number از accounts.twilio_utils
            try:
                from accounts.twilio_utils import format_phone_number
                return format_phone_number(value)
            except Exception as e:
                raise serializers.ValidationError(f"Invalid phone number format: {str(e)}")
        return value
    
    def validate_email(self, value):
        """بررسی و normalize کردن email"""
        if value:
            # حذف فاصله‌های اضافی
            value = value.strip()
            # اگر email خالی شد، None برگردان (نه empty string)
            if not value:
                return ''
            # بررسی فرمت email
            from django.core.validators import validate_email as django_validate_email
            try:
                django_validate_email(value)
            except Exception:
                raise serializers.ValidationError("Invalid email format")
        return value
    
    def update(self, instance, validated_data):
        """ذخیره داده‌ها و اطمینان از به‌روزرسانی"""
        # به‌روزرسانی فیلدها
        for attr, value in validated_data.items():
            # اگر email خالی است، empty string ذخیره کن (نه None)
            if attr == 'email' and value is None:
                value = ''
            setattr(instance, attr, value)
        
        # ذخیره در دیتابیس با update_fields برای بهینه‌سازی
        update_fields = list(validated_data.keys())
        instance.save(update_fields=update_fields)
        
        # refresh از دیتابیس برای اطمینان از ذخیره شدن
        instance.refresh_from_db()
        
        return instance


class RestaurantSerializer(serializers.ModelSerializer):
    """Serializer برای رستوران"""
    admin_name = serializers.CharField(source='admin.name', read_only=True)
    
    class Meta:
        model = Restaurant
        fields = (
            'id', 'admin', 'admin_name', 'name', 'description', 'address', 'phone',
            'country', 'city', 'is_active', 'created_at',
        )
        read_only_fields = ('id', 'created_at')


_WORKING_HOURS_DAY_KEYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)


def _default_working_hours():
    return {k: {"enabled": False, "open": "", "close": ""} for k in _WORKING_HOURS_DAY_KEYS}


class RestaurantProfileSerializer(serializers.ModelSerializer):
    """
    GET/PATCH پروفایل رستوران — نام فیلدها همان نام ستون‌های مدل است.
    لوگو فقط از طریق upload-logo؛ در خروجی به صورت URL مطلق.
    """
    logo = serializers.SerializerMethodField()
    google_maps_url = serializers.SerializerMethodField()

    class Meta:
        model = Restaurant
        fields = (
            "name",
            "logo",
            "description",
            "restaurant_type",
            "email",
            "phone",
            "whatsapp",
            "website",
            "address",
            "city",
            "country",
            "postal_code",
            "latitude",
            "longitude",
            "google_place_id",
            "google_maps_url",
            "gallery",
            "cover_image_index",
            "working_hours",
            "closed_today",
        )
        extra_kwargs = {
            "gallery": {"required": False},
            "working_hours": {"required": False},
            "email": {"allow_blank": True},
            "website": {"allow_blank": True},
            "whatsapp": {"allow_blank": True},
            "google_place_id": {"allow_blank": True, "required": False},
        }

    def get_google_maps_url(self, obj):
        return obj.google_maps_url or ""

    def get_logo(self, obj):
        if not obj.logo:
            return ""
        request = self.context.get("request")
        url = obj.logo.url
        if request:
            return request.build_absolute_uri(url)
        return url

    def to_representation(self, instance):
        data = super().to_representation(instance)
        merged = _default_working_hours()
        raw = instance.working_hours or {}
        if isinstance(raw, dict):
            for k in _WORKING_HOURS_DAY_KEYS:
                if k in raw and isinstance(raw[k], dict):
                    merged[k] = {
                        "enabled": bool(raw[k].get("enabled", False)),
                        "open": str(raw[k].get("open", "") or ""),
                        "close": str(raw[k].get("close", "") or ""),
                    }
        data["working_hours"] = merged
        data["gallery"] = list(instance.gallery) if isinstance(instance.gallery, list) else []
        if instance.latitude is not None:
            data["latitude"] = str(instance.latitude)
        else:
            data["latitude"] = None
        if instance.longitude is not None:
            data["longitude"] = str(instance.longitude)
        else:
            data["longitude"] = None
        return data

    def validate_latitude(self, value):
        if value is None or value == "":
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise serializers.ValidationError("Invalid latitude.")
        if v < -90 or v > 90:
            raise serializers.ValidationError("Latitude must be between -90 and 90.")
        return value

    def validate_longitude(self, value):
        if value is None or value == "":
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise serializers.ValidationError("Invalid longitude.")
        if v < -180 or v > 180:
            raise serializers.ValidationError("Longitude must be between -180 and 180.")
        return value

    def validate_working_hours(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("working_hours must be an object")
        out = {}
        for k in _WORKING_HOURS_DAY_KEYS:
            if k not in value:
                continue
            block = value[k]
            if not isinstance(block, dict):
                raise serializers.ValidationError(f"Invalid block for {k}")
            out[k] = {
                "enabled": bool(block.get("enabled", False)),
                "open": str(block.get("open", "") or ""),
                "close": str(block.get("close", "") or ""),
            }
        return out

    def validate_gallery(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("gallery must be a list of URL strings")
        return [str(u).strip() for u in value if str(u).strip()]

    def validate(self, attrs):
        inst = self.instance
        gallery = attrs.get("gallery")
        if gallery is None and inst:
            gallery = list(inst.gallery or [])
        else:
            gallery = list(gallery or [])
        idx = attrs.get("cover_image_index")
        if idx is None and inst is not None:
            idx = inst.cover_image_index
        if idx is None:
            idx = 0
        if gallery and idx >= len(gallery):
            raise serializers.ValidationError(
                {"cover_image_index": "cover_image_index must be < len(gallery)"}
            )
        if not gallery:
            attrs["cover_image_index"] = 0

        lat = attrs.get("latitude", serializers.empty)
        lng = attrs.get("longitude", serializers.empty)
        if inst is not None:
            if lat is serializers.empty:
                lat = inst.latitude
            if lng is serializers.empty:
                lng = inst.longitude
        else:
            if lat is serializers.empty:
                lat = None
            if lng is serializers.empty:
                lng = None
        if (lat is None) != (lng is None):
            raise serializers.ValidationError(
                "latitude and longitude must both be set or both cleared."
            )
        return attrs

    def update(self, instance, validated_data):
        if "working_hours" in validated_data:
            wh = validated_data["working_hours"]
            current = instance.working_hours if isinstance(instance.working_hours, dict) else {}
            validated_data["working_hours"] = {**current, **wh}
        return super().update(instance, validated_data)


class CloudinaryImageSerializer(serializers.ModelSerializer):
    """Serializer برای تصاویر Cloudinary"""
    url = serializers.SerializerMethodField()
    
    class Meta:
        model = CloudinaryImage
        fields = ('uuid', 'url', 'format', 'width', 'height', 'bytes_size', 'created_at')
        read_only_fields = ('uuid', 'url', 'format', 'width', 'height', 'bytes_size', 'created_at')
    
    def get_url(self, obj):
        """بازگرداندن URL تصویر"""
        return obj.get_url(secure=True)


class MenuItemImageSerializer(serializers.ModelSerializer):
    """Serializer برای عکس‌های آیتم منو - اکنون از UUID استفاده می‌کند"""
    image_url = serializers.SerializerMethodField()
    image_uuid = serializers.SerializerMethodField()
    
    class Meta:
        model = MenuItemImage
        fields = ('id', 'image', 'image_url', 'image_uuid', 'order')
        read_only_fields = ('id', 'image_url', 'image_uuid')
    
    def get_image_url(self, obj):
        """بازگرداندن URL کامل عکس (اولویت با Cloudinary)"""
        url = obj.get_image_url(request=self.context.get('request'), secure=True)
        return url
    
    def get_image_uuid(self, obj):
        """بازگرداندن UUID تصویر"""
        if obj.cloudinary_image:
            return str(obj.cloudinary_image.uuid)
        return None


class MenuItemSerializer(serializers.ModelSerializer):
    """Serializer برای آیتم منو"""
    restaurant = serializers.IntegerField(source='restaurant.id', read_only=True)
    category = serializers.SerializerMethodField()
    present = serializers.SerializerMethodField()
    details = serializers.CharField(source='description', required=False)
    images = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    # فیلد write-only برای price (برای update)
    price_value = serializers.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        required=False, 
        write_only=True,
        source='price'
    )
    
    class Meta:
        model = MenuItem
        fields = (
            'id', 'restaurant', 'category', 'name', 'price', 'price_value',
            'present', 'stock', 'details', 'images', 'order', 'serial'
        )
        read_only_fields = ('id', 'restaurant', 'category', 'images', 'price')
        extra_kwargs = {
            'name': {'required': False},
            'stock': {'required': False},
            'order': {'required': False},
            'serial': {'required': False, 'allow_blank': True}
        }
    
    def get_category(self, obj):
        """برگرداندن category ID"""
        return obj.category.id if obj.category else None
    
    def get_present(self, obj):
        """تبدیل is_available به string"""
        return "true" if obj.is_available else "false"
    
    def get_price(self, obj):
        """تبدیل price به string"""
        if obj.price:
            return str(obj.price)
        return "0.00"
    
    def to_internal_value(self, data):
        """تبدیل فیلدهای اپ به فیلدهای مدل برای update"""
        # تبدیل present به is_available
        if 'present' in data:
            present_value = data['present']
            if isinstance(present_value, str):
                data['is_available'] = present_value.lower() in ('true', '1', 'yes', 'on')
            else:
                data['is_available'] = bool(present_value)
            data.pop('present', None)
        
        # تبدیل details به description
        if 'details' in data:
            data['description'] = data.pop('details')
        
        # تبدیل price از string به Decimal (اگر price_value نباشد)
        if 'price' in data and 'price_value' not in data:
            try:
                from decimal import Decimal
                price_value = data.pop('price')
                # استفاده از تابع normalize_price_value
                price_value_normalized = normalize_price_value(price_value)
                if price_value_normalized is not None:
                    data['price_value'] = Decimal(price_value_normalized)
            except (ValueError, TypeError, Exception):
                # اگر تبدیل نشد، خطا را به validation بسپار
                pass
        
        # حذف فیلدهای خالی یا نامعتبر
        # اگر name یا stock به صورت list یا مقدار نامعتبر آمده، نادیده بگیر
        if 'name' in data:
            if isinstance(data['name'], list):
                if len(data['name']) > 0:
                    name_value = str(data['name'][0]).strip()
                    if name_value:
                        data['name'] = name_value
                    else:
                        data.pop('name', None)
                else:
                    data.pop('name', None)
            elif isinstance(data['name'], str):
                name_value = data['name'].strip()
                if name_value:
                    data['name'] = name_value
                else:
                    # اگر خالی است، نادیده بگیر (برای partial update)
                    data.pop('name', None)
            else:
                # اگر نوع نامعتبر است، به string تبدیل کن
                try:
                    name_value = str(data['name']).strip()
                    if name_value:
                        data['name'] = name_value
                    else:
                        data.pop('name', None)
                except:
                    data.pop('name', None)
        
        if 'stock' in data:
            if isinstance(data['stock'], list):
                if len(data['stock']) > 0:
                    stock_val = str(data['stock'][0]).strip()
                    data['stock'] = stock_val if stock_val else ''
                else:
                    # اگر لیست خالی است، empty string بگذار (نه None)
                    data['stock'] = ''
            elif data['stock'] is None:
                # اگر None است، empty string بگذار
                data['stock'] = ''
            elif not isinstance(data['stock'], str):
                # اگر نامعتبر است، به string تبدیل کن
                stock_val = str(data['stock']).strip() if data['stock'] is not None else ''
                data['stock'] = stock_val
            else:
                # اگر string است، strip کن
                data['stock'] = data['stock'].strip() if data['stock'] else ''
        
        return super().to_internal_value(data)
    
    def validate_price_value(self, value):
        """Validate price value"""
        if value is not None:
            if value < 0:
                raise serializers.ValidationError("Price cannot be negative")
        return value
    
    def get_images(self, obj):
        """برگرداندن لیست URL تصاویر"""
        images = []
        request = self.context.get('request')
        
        for img in obj.images.all().order_by('order'):
            url = img.get_image_url(request=request, secure=True)
            if url:
                images.append(url)
        
        return images
    
    def get_image_uuids(self, obj):
        """برگرداندن لیست UUID تصاویر (برای امنیت)"""
        image_uuids = []
        
        for img in obj.images.all().order_by('order'):
            # اولویت با Cloudinary UUID
            if img.cloudinary_image:
                image_uuids.append(str(img.cloudinary_image.uuid))
            # اگر cloudinary_image نداره، UUID نداره (legacy image)
        
        return image_uuids


class MenuItemCreateSerializer(serializers.ModelSerializer):
    """Serializer برای ایجاد آیتم منو (با عکس‌ها یا UUID)"""
    # پشتیبانی از آپلود مستقیم فایل
    images = serializers.ListField(
        child=serializers.ImageField(),
        required=False,
        allow_empty=True,
        write_only=True,
        help_text="لیست عکس‌های آیتم منو (فایل‌ها)"
    )
    # پشتیبانی از UUID (برای امنیت بیشتر)
    image_uuids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        write_only=True,
        help_text="لیست UUID تصاویر (از قبل آپلود شده در Cloudinary)"
    )
    # فیلدهای سازگار با اپ دوم
    present = serializers.CharField(required=False, write_only=True, help_text="موجود بودن (معادل is_available) - می‌تواند 'true'/'false' یا true/false باشد")
    details = serializers.CharField(required=False, allow_blank=True, write_only=True, help_text="توضیحات (معادل description)")
    category = serializers.IntegerField(required=False, allow_null=True, write_only=True, help_text="دسته‌بندی ID")
    # استفاده از CommaDecimalField برای پشتیبانی از ویرگول
    # required=False می‌کنیم و در validate بررسی می‌کنیم تا خطای بهتری بدهیم
    price = CommaDecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,  # تغییر به False تا بتوانیم در validate بررسی کنیم
        allow_null=True,
        help_text="قیمت (پشتیبانی از نقطه و ویرگول به عنوان جداکننده اعشار)"
    )
    
    class Meta:
        model = MenuItem
        fields = (
            'restaurant', 'name', 'description', 'price', 'stock', 
            'is_available', 'order', 'serial', 'images', 'image_uuids', 'present', 'details', 'category'
        )
    
    def to_internal_value(self, data):
        """Normalize کردن داده‌ها قبل از validation"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"MenuItemCreateSerializer.to_internal_value called with data: {data}")
        
        # قیمت توسط CommaDecimalField خودش normalize می‌شود، نیازی به normalize کردن اینجا نیست
        # فقط log می‌کنیم برای debugging
        if 'price' in data:
            price_value = data.get('price')
            logger.info(f"Price found in data: {price_value}, type: {type(price_value)}")
        else:
            logger.warning("Price not found in data keys: %s", list(data.keys()) if hasattr(data, 'keys') else data)
        
        result = super().to_internal_value(data)
        logger.info(f"MenuItemCreateSerializer.to_internal_value returning: {result}")
        return result
    
    def validate_present(self, value):
        """تبدیل present از string به boolean"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value)
    
    
    def validate(self, attrs):
        """تبدیل فیلدهای اپ به فیلدهای مدل"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"MenuItemCreateSerializer.validate called with attrs: {attrs}")
        
        # بررسی قیمت - اگر required است اما ارسال نشده
        if 'price' not in attrs or attrs.get('price') is None:
            # بررسی در data اصلی
            initial_data = getattr(self, 'initial_data', {})
            if 'price' not in initial_data or not initial_data.get('price'):
                raise serializers.ValidationError({
                    'price': 'This field is required.'
                })
        
        # تبدیل present به is_available
        if 'present' in attrs:
            attrs['is_available'] = self.validate_present(attrs.pop('present'))
        
        # تبدیل details به description
        if 'details' in attrs:
            attrs['description'] = attrs.pop('details')
        
        # قیمت توسط CommaDecimalField خودش normalize می‌شود، نیازی به تغییر نیست
        
        # category به صورت ID ذخیره می‌شود
        # اگر category_id داده شده، آن را به category تبدیل کن
        if 'category' in attrs:
            category_id = attrs.pop('category')
            if category_id:
                attrs['category_id'] = category_id
        
        logger.info(f"MenuItemCreateSerializer.validate returning attrs: {attrs}")
        return attrs
    
    def create(self, validated_data):
        """ایجاد آیتم منو همراه با عکس‌ها"""
        images_data = validated_data.pop('images', []) or []
        image_uuids = validated_data.pop('image_uuids', []) or []
        
        # ایجاد menu_item
        menu_item = MenuItem.objects.create(**validated_data)
        
        # آپلود و ایجاد عکس‌ها از فایل‌ها
        try:
            for index, image_data in enumerate(images_data):
                try:
                    # آپلود به Cloudinary و دریافت UUID
                    upload_result = upload_image_to_cloudinary(image_data)
                    
                    if upload_result.get('success') and upload_result.get('cloudinary_image'):
                        # استفاده از CloudinaryImage
                        MenuItemImage.objects.create(
                            menu_item=menu_item,
                            cloudinary_image=upload_result['cloudinary_image'],
                            order=index
                        )
                    else:
                        # Fallback به روش قدیمی (اگر Cloudinary فعال نباشد)
                        MenuItemImage.objects.create(
                            menu_item=menu_item,
                            image=image_data,
                            order=index
                        )
                except Exception as e:
                    # اگر خطا در آپلود عکس رخ داد، ادامه بده
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error uploading image {index}: {str(e)}")
                    # Fallback: ذخیره بدون cloudinary
                    try:
                        MenuItemImage.objects.create(
                            menu_item=menu_item,
                            image=image_data,
                            order=index
                        )
                    except Exception:
                        pass  # اگر این هم خطا داد، نادیده بگیر
        
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error processing images: {str(e)}")
        
        # استفاده از UUIDهای موجود
        try:
            for index, image_uuid in enumerate(image_uuids):
                try:
                    from .cloudinary_utils import get_image_by_uuid
                    cloudinary_image = get_image_by_uuid(str(image_uuid))
                    
                    if cloudinary_image:
                        MenuItemImage.objects.create(
                            menu_item=menu_item,
                            cloudinary_image=cloudinary_image,
                            order=len(images_data) + index
                        )
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error processing image UUID {image_uuid}: {str(e)}")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error processing image UUIDs: {str(e)}")
        
        return menu_item


class MenuQRCodeSerializer(serializers.ModelSerializer):
    """Serializer برای QR کد منو"""
    restaurant_name = serializers.CharField(source='restaurant.name', read_only=True)
    menu_url = serializers.SerializerMethodField()
    qr_image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = MenuQRCode
        fields = ('id', 'restaurant', 'restaurant_name', 'token', 'menu_url', 'qr_image_url', 'created_at')
        read_only_fields = ('id', 'token', 'created_at')
    
    def get_menu_url(self, obj):
        """بازگرداندن URL منو"""
        request = self.context.get('request')
        if request:
            base_url = request.build_absolute_uri('/').rstrip('/')
            return f"{base_url}/business-menu/qr/{obj.token}/"
        return None
    
    def get_qr_image_url(self, obj):
        """بازگرداندن URL تصویر QR کد"""
        request = self.context.get('request')
        if request:
            base_url = request.build_absolute_uri('/').rstrip('/')
            return f"{base_url}/business-menu/qr/{obj.token}.png"
        return None


class LoginSerializer(serializers.Serializer):
    """Serializer برای لاگین با شماره تلفن و OTP"""
    # Some clients send `number` instead of `phone` (legacy compatibility).
    phone = serializers.CharField(required=False, allow_blank=True, help_text="شماره تلفن (یا number)")
    number = serializers.CharField(required=False, allow_blank=True, help_text="Legacy phone field (maps to phone)")
    code = serializers.CharField(required=True, help_text="کد OTP")

    def validate(self, attrs):
        phone = (attrs.get("phone") or "").strip()
        number = (attrs.get("number") or "").strip()

        if not phone and number:
            phone = number
            attrs["phone"] = phone

        if not phone:
            raise serializers.ValidationError({"phone": "Phone number is required"})

        # Keep `number` in sync for clients that read it back
        attrs["number"] = phone
        return attrs


class CategorySerializer(serializers.ModelSerializer):
    """Serializer برای دسته‌بندی منو"""
    restaurant = serializers.IntegerField(source='restaurant.id', read_only=True)
    
    class Meta:
        model = Category
        fields = ('id', 'restaurant', 'name', 'order')
        read_only_fields = ('id',)
        extra_kwargs = {
            'restaurant': {'required': False},
            'order': {'required': False}
        }


class MenuSetSerializer(serializers.ModelSerializer):
    """Serializer برای مجموعه منو"""
    restaurant = serializers.IntegerField(source='restaurant.id', read_only=True)
    isActive = serializers.BooleanField(source='is_active', required=False, write_only=True, allow_null=True)
    # فیلدهای write-only برای سازگاری با اپ
    price = serializers.CharField(required=False, write_only=True, allow_blank=True, help_text="Price (optional, not stored in model)")
    items = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
        write_only=True,
        help_text="List of menu item IDs (optional, not stored in model)"
    )
    
    class Meta:
        model = MenuSet
        fields = ('id', 'restaurant', 'name', 'description', 'order', 'is_active', 'isActive', 'price', 'items', 'created_at')
        read_only_fields = ('id', 'restaurant', 'created_at')
        extra_kwargs = {
            'is_active': {'required': False},
            'description': {'required': False, 'allow_blank': True},
            'order': {'required': False}
        }
    
    def validate(self, attrs):
        """تبدیل فیلدهای اپ به فیلدهای مدل"""
        # تبدیل isActive به is_active
        if 'isActive' in attrs:
            attrs['is_active'] = attrs.pop('isActive')
        
        # حذف price و items چون در مدل ذخیره نمی‌شوند
        attrs.pop('price', None)
        attrs.pop('items', None)
        
        return attrs


class PackageItemSerializer(serializers.ModelSerializer):
    """Serializer برای آیتم‌های پکیج"""
    menu_item = serializers.IntegerField(source='menu_item.id', read_only=True)
    
    class Meta:
        model = PackageItem
        fields = ('menu_item', 'quantity')
        read_only_fields = ('menu_item',)


class PackageSerializer(serializers.ModelSerializer):
    """Serializer برای پکیج"""
    restaurant = serializers.IntegerField(source='restaurant.id', read_only=True)
    items = PackageItemSerializer(source='package_items', many=True, read_only=True)
    original_price = serializers.SerializerMethodField()
    discount_percent = serializers.SerializerMethodField()
    # Writable on create/update (multipart upload), rendered as absolute URL in to_representation
    image = serializers.ImageField(required=False, allow_null=True)
    
    class Meta:
        model = Package
        fields = (
            'id', 'restaurant', 'name', 'description', 
            'items', 'original_price', 'package_price', 
            'discount_percent', 'is_active', 'image', 
            'created_at'
        )
        read_only_fields = ('id', 'restaurant', 'original_price', 'discount_percent', 'created_at')
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True},
            'is_active': {'required': False},
            'image': {'required': False, 'allow_null': True},
        }
    
    def get_original_price(self, obj):
        """محاسبه قیمت اصلی"""
        return str(obj.original_price)
    
    def get_discount_percent(self, obj):
        """محاسبه درصد تخفیف"""
        return obj.discount_percent

    def to_representation(self, instance):
        """
        Render image as full URL (backward-compatible with previous API that returned URL string).
        Keep field writable for uploads.
        """
        rep = super().to_representation(instance)
        if not getattr(instance, "image", None):
            rep["image"] = None
            return rep

        request = self.context.get("request")
        try:
            image_url = instance.image.url
        except Exception:
            rep["image"] = None
            return rep

        if request:
            if image_url.startswith("/"):
                rep["image"] = request.build_absolute_uri(image_url)
            elif image_url.startswith("http"):
                rep["image"] = image_url
            else:
                rep["image"] = request.build_absolute_uri("/" + image_url.lstrip("/"))
        else:
            rep["image"] = image_url
        return rep


class PackageCreateSerializer(serializers.ModelSerializer):
    """Serializer برای ایجاد پکیج"""
    restaurant = serializers.IntegerField(required=False, write_only=True)
    items = serializers.ListField(
        child=serializers.DictField(),
        required=True,
        write_only=True,
        help_text="List of items: [{'menu_item': 5, 'quantity': 2}, ...]"
    )
    
    class Meta:
        model = Package
        fields = (
            'restaurant', 'name', 'description', 'items',
            'package_price', 'is_active', 'image'
        )
        extra_kwargs = {
            'description': {'required': False, 'allow_blank': True},
            'is_active': {'required': False},
            'image': {'required': False},
        }
    
    def create(self, validated_data):
        """ایجاد پکیج با آیتم‌ها"""
        items_data = validated_data.pop('items', [])
        restaurant_id = validated_data.pop('restaurant', None)
        
        # دریافت restaurant
        if restaurant_id:
            from .models import Restaurant
            try:
                restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
            except Restaurant.DoesNotExist:
                raise serializers.ValidationError({"restaurant": "Restaurant not found"})
        else:
            raise serializers.ValidationError({"restaurant": "restaurant is required"})
        
        # ایجاد پکیج
        package = Package.objects.create(restaurant=restaurant, **validated_data)
        
        # ایجاد آیتم‌های پکیج
        for item_data in items_data:
            menu_item_id = item_data.get('menu_item')
            quantity = item_data.get('quantity', 1)
            
            if menu_item_id:
                try:
                    menu_item = MenuItem.objects.get(id=menu_item_id, restaurant=restaurant)
                    PackageItem.objects.create(
                        package=package,
                        menu_item=menu_item,
                        quantity=quantity
                    )
                except MenuItem.DoesNotExist:
                    # اگر آیتم پیدا نشد، نادیده بگیر (یا می‌توانید خطا بدهید)
                    pass
        
        return package


class SendOTPSerializer(serializers.Serializer):
    """Serializer برای ارسال OTP"""
    phone = serializers.CharField(required=False, allow_blank=True, help_text="شماره تلفن (یا number)")
    number = serializers.CharField(required=False, allow_blank=True, help_text="Legacy phone field (maps to phone)")

    def validate(self, attrs):
        phone = (attrs.get("phone") or "").strip()
        number = (attrs.get("number") or "").strip()

        if not phone and number:
            phone = number
            attrs["phone"] = phone

        if not phone:
            raise serializers.ValidationError({"phone": "Phone number is required"})

        attrs["number"] = phone
        return attrs


class RestaurantOwnerRegistrationSerializer(serializers.Serializer):
    """Serializer for restaurant owner signup (web). Minimal fields; rest editable in app."""
    restaurant_name = serializers.CharField(required=True, max_length=200, help_text="Restaurant name")
    phone = serializers.CharField(required=True, help_text="Phone number")
    email = serializers.EmailField(required=True, help_text="Email address")
    password = serializers.CharField(required=True, write_only=True, min_length=8, help_text="Password (minimum 8 characters)")
    accept_terms = serializers.BooleanField(required=True, help_text="Accept terms and conditions")
    b2b_confirmation = serializers.BooleanField(required=True, help_text="I confirm that I am acting as a business customer (B2B)")
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    country = serializers.CharField(required=False, allow_blank=True, max_length=100, default="")
    city = serializers.CharField(required=False, allow_blank=True, max_length=100, default="")
    
    def validate_phone(self, value):
        """بررسی فرمت شماره تلفن"""
        try:
            from accounts.twilio_utils import format_phone_number
            return format_phone_number(value)
        except Exception as e:
            raise serializers.ValidationError(f"Invalid phone number format: {str(e)}")
    
    def validate(self, attrs):
        """بررسی قوانین"""
        accept_terms = attrs.get('accept_terms')
        b2b_confirmation = attrs.get('b2b_confirmation', False)
        
        if not accept_terms:
            raise serializers.ValidationError({"accept_terms": "You must accept the terms and conditions"})
        
        if not b2b_confirmation:
            raise serializers.ValidationError({"b2b_confirmation": "You must confirm that you are acting as a business customer (B2B)"})
        
        # بررسی تکراری نبودن شماره تلفن
        phone = attrs.get('phone')
        if BusinessAdmin.objects.filter(phone=phone).exists():
            raise serializers.ValidationError({"phone": "A restaurant owner with this phone number already exists"})
        
        # بررسی تکراری نبودن ایمیل
        email = attrs.get('email')
        if BusinessAdmin.objects.filter(email=email).exists():
            raise serializers.ValidationError({"email": "A restaurant owner with this email already exists"})
        
        return attrs


class MenuThemeSerializer(serializers.ModelSerializer):
    preview_image = serializers.SerializerMethodField()

    class Meta:
        model = MenuTheme
        fields = ("id", "name", "preview_image")

    def get_preview_image(self, obj):
        if not obj.preview_static_path:
            return None
        request = self.context.get("request")
        if not request:
            return obj.preview_static_path
        from django.templatetags.static import static

        return request.build_absolute_uri(static(obj.preview_static_path))


class RestaurantSettingsSerializer(serializers.ModelSerializer):
    menu_theme = serializers.PrimaryKeyRelatedField(
        queryset=MenuTheme.objects.filter(is_active=True),
        allow_null=True,
        required=False,
    )
    email = serializers.SerializerMethodField()

    class Meta:
        model = RestaurantSettings
        fields = (
            "menu_theme", "show_prices", "show_images", "show_descriptions", "show_serial",
            "has_delivery", "allow_payment_cash", "allow_payment_online",
            "reservation_enabled", "total_tables", "max_guests_per_reservation",
            "email",
        )
    
    def get_email(self, obj):
        """برگرداندن ایمیل صاحب بیزینس همان رستوران"""
        if obj.restaurant and obj.restaurant.admin and obj.restaurant.admin.email:
            return obj.restaurant.admin.email
        return None

