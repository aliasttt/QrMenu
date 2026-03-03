"""
Django management command to create a BusinessAdmin and set up OTP code
Usage: python manage.py create_admin_with_otp --phone +905540225177 --code 123456 --name "Admin Name"
"""
from django.core.management.base import BaseCommand
from django.core.cache import cache
from django.conf import settings
from business_menu.models import BusinessAdmin, Restaurant
from accounts.twilio_utils import format_phone_number, UNLIMITED_OTP_PHONES


class Command(BaseCommand):
    help = 'Create a BusinessAdmin and set up OTP code for testing'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--phone',
            type=str,
            required=True,
            help='Phone number (e.g., +905540225177)',
        )
        parser.add_argument(
            '--code',
            type=str,
            required=True,
            help='OTP code to set (e.g., 123456)',
        )
        parser.add_argument(
            '--name',
            type=str,
            default='Admin',
            help='Admin name (default: Admin)',
        )
        parser.add_argument(
            '--email',
            type=str,
            default='',
            help='Admin email (optional)',
        )
    
    def handle(self, *args, **options):
        phone = options['phone']
        code = options['code']
        name = options['name']
        email = options['email']
        
        # Format phone number
        try:
            formatted_phone = format_phone_number(phone)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error formatting phone number: {str(e)}'))
            return
        
        # Determine payment status - set to 'paid' for test numbers in UNLIMITED_OTP_PHONES
        is_test_number = formatted_phone in UNLIMITED_OTP_PHONES
        payment_status = 'paid' if is_test_number else 'unpaid'
        
        # Create or get BusinessAdmin
        admin, created = BusinessAdmin.objects.get_or_create(
            phone=formatted_phone,
            defaults={
                'name': name,
                'email': email if email else '',
                'is_active': True,
                'payment_status': payment_status,
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'BusinessAdmin created: {admin.name} ({admin.phone})'))
            if is_test_number:
                self.stdout.write(self.style.SUCCESS(f'Payment status set to PAID (test number)'))
        else:
            # Update existing admin
            admin.name = name
            if email:
                admin.email = email
            admin.is_active = True
            # Update payment status for test numbers
            if is_test_number:
                admin.payment_status = 'paid'
            admin.save()
            self.stdout.write(self.style.SUCCESS(f'BusinessAdmin updated: {admin.name} ({admin.phone})'))
            if is_test_number:
                self.stdout.write(self.style.SUCCESS(f'Payment status set to PAID (test number)'))
        
        # ایجاد رستوران پیش‌فرض اگر وجود نداشته باشد
        try:
            restaurant = admin.restaurant
            if restaurant and restaurant.is_active:
                self.stdout.write(self.style.SUCCESS(f'Restaurant already exists for this admin: {restaurant.name}'))
            else:
                # Restaurant exists but is inactive - activate it
                restaurant.is_active = True
                restaurant.save()
                self.stdout.write(self.style.SUCCESS(f'Restaurant activated: {restaurant.name}'))
        except Restaurant.DoesNotExist:
            restaurant = Restaurant.objects.create(
                admin=admin,
                name='Restaurant',
                description='Default restaurant',
                is_active=True
            )
            self.stdout.write(self.style.SUCCESS(f'Default Restaurant created: {restaurant.name}'))
        
        # Set up OTP code in cache (for DEBUG mode)
        cache_key = f'otp_mock_{formatted_phone}'
        
        # Set cache - unlimited time for phones in UNLIMITED_OTP_PHONES list
        if formatted_phone in UNLIMITED_OTP_PHONES:
            # Set with None timeout (unlimited) - 10 years as fallback
            cache.set(cache_key, code, 315360000)  # 10 years in seconds
            self.stdout.write(self.style.SUCCESS(f'OTP code set (UNLIMITED): {code}'))
        else:
            # Set cache for 24 hours (86400 seconds)
            cache.set(cache_key, code, 86400)
            self.stdout.write(self.style.SUCCESS(f'OTP code set (24h): {code}'))
        
        self.stdout.write(self.style.SUCCESS(f'Cache key: {cache_key}'))
        self.stdout.write(self.style.SUCCESS(f'\nYou can now login with phone: {formatted_phone} and code: {code}'))

