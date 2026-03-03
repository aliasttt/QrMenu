"""
Django management command to create 20 test BusinessAdmin accounts with sequential phone numbers
Usage: python manage.py create_test_business_admins
"""
from django.core.management.base import BaseCommand
from django.core.cache import cache
from django.db import transaction
from business_menu.models import BusinessAdmin, Restaurant
from business_menu.auth_utils import get_or_create_user_for_business_admin, sync_user_from_business_admin
from accounts.twilio_utils import format_phone_number
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Create 20 test BusinessAdmin accounts with sequential phone numbers and OTP 123456'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--base-phone',
            type=str,
            default='+905540225181',
            help='Base phone number to start from (default: +905540225181)',
        )
        parser.add_argument(
            '--count',
            type=int,
            default=20,
            help='Number of test accounts to create (default: 20)',
        )
        parser.add_argument(
            '--code',
            type=str,
            default='123456',
            help='OTP code to set for all accounts (default: 123456)',
        )
    
    @transaction.atomic
    def handle(self, *args, **options):
        base_phone = options['base_phone']
        count = options['count']
        code = options['code']
        
        # Format base phone number
        try:
            formatted_base = format_phone_number(base_phone)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error formatting base phone number: {str(e)}'))
            return
        
        # Extract the numeric part (without +)
        base_digits = formatted_base.replace('+', '')
        
        # Extract the last digits to increment
        # For Turkish numbers: +905540225181 -> base is 905540225181, last 3 digits are 181
        # We'll increment the last 3 digits: 181, 182, 183, ...
        if len(base_digits) >= 3:
            prefix = base_digits[:-3]  # All digits except last 3
            last_three = int(base_digits[-3:])  # Last 3 digits as integer
        else:
            self.stdout.write(self.style.ERROR(f'Phone number too short: {formatted_base}'))
            return
        
        created_count = 0
        updated_count = 0
        phone_numbers = []
        
        self.stdout.write(self.style.SUCCESS(f'Creating {count} test BusinessAdmin accounts...'))
        self.stdout.write(self.style.SUCCESS(f'Base phone: {formatted_base}'))
        self.stdout.write(self.style.SUCCESS(f'OTP code: {code}\n'))
        
        for i in range(count):
            # Calculate new last 3 digits
            new_last_three = last_three + i
            # Format as 3 digits with leading zeros if needed
            new_last_three_str = f"{new_last_three:03d}"
            # Construct full phone number
            new_phone_digits = prefix + new_last_three_str
            new_phone = '+' + new_phone_digits
            
            try:
                # Format phone number to ensure consistency
                formatted_phone = format_phone_number(new_phone)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'Error formatting phone {new_phone}: {str(e)}'))
                continue
            
            phone_numbers.append(formatted_phone)
            
            # Create or get BusinessAdmin
            admin, created = BusinessAdmin.objects.get_or_create(
                phone=formatted_phone,
                defaults={
                    'name': f'Test Admin {i+1}',
                    'email': f'testadmin{i+1}@test.local',
                    'is_active': True,
                    'payment_status': 'paid',  # Set to paid for test accounts
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'✓ Created: {admin.name} ({admin.phone})'))
            else:
                updated_count += 1
                # Update existing admin
                admin.name = f'Test Admin {i+1}'
                admin.email = f'testadmin{i+1}@test.local'
                admin.is_active = True
                admin.payment_status = 'paid'
                admin.save()
                self.stdout.write(self.style.WARNING(f'↻ Updated: {admin.name} ({admin.phone})'))
            
            # Create or get User account
            user = get_or_create_user_for_business_admin(
                admin_phone=admin.phone,
                admin_name=admin.name,
                admin_email=admin.email,
            )
            sync_user_from_business_admin(
                user=user,
                admin_phone=admin.phone,
                admin_name=admin.name,
                admin_email=admin.email,
            )
            
            # Link user to BusinessAdmin
            if admin.auth_user_id != user.id:
                admin.auth_user = user
                admin.save(update_fields=['auth_user'])
            
            # Create default Restaurant if it doesn't exist
            try:
                restaurant = admin.restaurant
                if not restaurant.is_active:
                    restaurant.is_active = True
                    restaurant.save()
            except Restaurant.DoesNotExist:
                restaurant = Restaurant.objects.create(
                    admin=admin,
                    name=f'Test Restaurant {i+1}',
                    description=f'Test restaurant for {admin.name}',
                    is_active=True
                )
            
            # Set up OTP code in cache (unlimited for test accounts)
            cache_key = f'otp_mock_{formatted_phone}'
            cache.set(cache_key, code, 315360000)  # 10 years in seconds
        
        self.stdout.write(self.style.SUCCESS(f'\n{"="*60}'))
        self.stdout.write(self.style.SUCCESS(f'Summary:'))
        self.stdout.write(self.style.SUCCESS(f'  Created: {created_count} accounts'))
        self.stdout.write(self.style.SUCCESS(f'  Updated: {updated_count} accounts'))
        self.stdout.write(self.style.SUCCESS(f'  Total: {created_count + updated_count} accounts'))
        self.stdout.write(self.style.SUCCESS(f'\nPhone numbers created:'))
        for phone in phone_numbers:
            self.stdout.write(self.style.SUCCESS(f'  {phone}'))
        
        self.stdout.write(self.style.WARNING(f'\n⚠ IMPORTANT: You need to update accounts/twilio_utils.py'))
        self.stdout.write(self.style.WARNING(f'Add these phone numbers to UNLIMITED_OTP_PHONES and UNLIMITED_OTP_CODES'))
        self.stdout.write(self.style.WARNING(f'\nUNLIMITED_OTP_PHONES = ['))
        for phone in phone_numbers:
            self.stdout.write(self.style.WARNING(f"    '{phone}',"))
        self.stdout.write(self.style.WARNING(f']'))
        self.stdout.write(self.style.WARNING(f'\nUNLIMITED_OTP_CODES = {{'))
        for phone in phone_numbers:
            self.stdout.write(self.style.WARNING(f"    '{phone}': '{code}',"))
        self.stdout.write(self.style.WARNING(f'}}'))
