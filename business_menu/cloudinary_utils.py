"""
Utility functions for Cloudinary image upload and management
"""
import os
from django.conf import settings
from .models import CloudinaryImage


def upload_image_to_cloudinary(image_file, folder="business_menu"):
    """
    آپلود تصویر به Cloudinary و بازگرداندن UUID
    
    Args:
        image_file: فایل تصویر (Django UploadedFile)
        folder: پوشه در Cloudinary (پیش‌فرض: business_menu)
    
    Returns:
        dict: {
            'success': bool,
            'uuid': str (اگر موفق),
            'error': str (اگر خطا),
            'cloudinary_image': CloudinaryImage object (اگر موفق)
        }
    """
    # بررسی اینکه Cloudinary فعال است یا نه
    use_cloudinary = getattr(settings, 'USE_CLOUDINARY', False)
    
    if not use_cloudinary:
        return {
            'success': False,
            'error': 'Cloudinary فعال نیست. لطفاً USE_CLOUDINARY=1 را تنظیم کنید.'
        }
    
    try:
        import cloudinary
        import cloudinary.uploader
        
        # آپلود به Cloudinary
        upload_result = cloudinary.uploader.upload(
            image_file,
            folder=folder,
            resource_type="image",
            use_filename=True,
            unique_filename=True,
            overwrite=False,
            # فعال کردن کش
            eager=[{"quality": "auto", "fetch_format": "auto"}],
        )
        
        # استخراج اطلاعات
        public_id = upload_result.get('public_id')
        secure_url = upload_result.get('secure_url')
        url = upload_result.get('url')
        format_type = upload_result.get('format')
        width = upload_result.get('width')
        height = upload_result.get('height')
        bytes_size = upload_result.get('bytes')
        
        # ایجاد یا دریافت CloudinaryImage
        cloudinary_image, created = CloudinaryImage.objects.get_or_create(
            cloudinary_public_id=public_id,
            defaults={
                'cloudinary_url': url or secure_url,
                'secure_url': secure_url or url,
                'format': format_type or '',
                'width': width,
                'height': height,
                'bytes_size': bytes_size,
            }
        )
        
        # اگر از قبل وجود داشت، اطلاعات را به‌روزرسانی کن
        if not created:
            cloudinary_image.cloudinary_url = url or secure_url
            cloudinary_image.secure_url = secure_url or url
            cloudinary_image.format = format_type or cloudinary_image.format
            cloudinary_image.width = width or cloudinary_image.width
            cloudinary_image.height = height or cloudinary_image.height
            cloudinary_image.bytes_size = bytes_size or cloudinary_image.bytes_size
            cloudinary_image.save()
        
        return {
            'success': True,
            'uuid': str(cloudinary_image.uuid),
            'cloudinary_image': cloudinary_image,
            'public_id': public_id,
            'url': secure_url or url,
        }
        
    except ImportError:
        return {
            'success': False,
            'error': 'کتابخانه Cloudinary نصب نشده است.'
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'خطا در آپلود به Cloudinary: {str(e)}'
        }


def get_image_by_uuid(uuid_str):
    """
    دریافت تصویر از روی UUID
    
    Args:
        uuid_str: UUID تصویر (string)
    
    Returns:
        CloudinaryImage object یا None
    """
    try:
        return CloudinaryImage.objects.get(uuid=uuid_str)
    except CloudinaryImage.DoesNotExist:
        return None
    except ValueError:
        # UUID نامعتبر
        return None


def get_image_url_by_uuid(uuid_str, secure=True):
    """
    دریافت URL تصویر از روی UUID
    
    Args:
        uuid_str: UUID تصویر (string)
        secure: استفاده از HTTPS
    
    Returns:
        str: URL تصویر یا None
    """
    cloudinary_image = get_image_by_uuid(uuid_str)
    if cloudinary_image:
        return cloudinary_image.get_url(secure=secure)
    return None


def delete_image_from_cloudinary(uuid_str):
    """
    حذف تصویر از Cloudinary و دیتابیس
    
    Args:
        uuid_str: UUID تصویر
    
    Returns:
        dict: {
            'success': bool,
            'message': str
        }
    """
    cloudinary_image = get_image_by_uuid(uuid_str)
    
    if not cloudinary_image:
        return {
            'success': False,
            'message': 'تصویر یافت نشد'
        }
    
    try:
        import cloudinary
        import cloudinary.uploader
        
        # حذف از Cloudinary
        cloudinary.uploader.destroy(
            cloudinary_image.cloudinary_public_id,
            resource_type="image"
        )
        
        # حذف از دیتابیس
        cloudinary_image.delete()
        
        return {
            'success': True,
            'message': 'تصویر با موفقیت حذف شد'
        }
        
    except ImportError:
        return {
            'success': False,
            'message': 'کتابخانه Cloudinary نصب نشده است.'
        }
    except Exception as e:
        return {
            'success': False,
            'message': f'خطا در حذف تصویر: {str(e)}'
        }


def check_cloudinary_status():
    """
    بررسی وضعیت Cloudinary و کش
    
    Returns:
        dict: اطلاعات وضعیت Cloudinary
    """
    use_cloudinary = getattr(settings, 'USE_CLOUDINARY', False)
    cloud_name = getattr(settings, 'CLOUDINARY_CLOUD_NAME', '')
    api_key = getattr(settings, 'CLOUDINARY_API_KEY', '')
    api_secret = getattr(settings, 'CLOUDINARY_API_SECRET', '')
    
    status_info = {
        'enabled': use_cloudinary,
        'cloud_name': cloud_name if cloud_name else 'NOT SET',
        'api_key': 'SET' if api_key else 'NOT SET',
        'api_secret': 'SET' if api_secret else 'NOT SET',
        'configured': use_cloudinary and cloud_name and api_key and api_secret,
    }
    
    # تست اتصال
    if status_info['configured']:
        try:
            import cloudinary
            import cloudinary.api
            
            # تست ping
            ping_result = cloudinary.api.ping()
            status_info['connection'] = 'SUCCESS' if ping_result.get('status') == 'ok' else 'FAILED'
            status_info['cloud_name'] = cloudinary.config().cloud_name
        except Exception as e:
            status_info['connection'] = f'ERROR: {str(e)}'
    else:
        status_info['connection'] = 'NOT CONFIGURED'
    
    # تعداد تصاویر در دیتابیس
    try:
        status_info['total_images'] = CloudinaryImage.objects.count()
    except:
        status_info['total_images'] = 0
    
    return status_info

