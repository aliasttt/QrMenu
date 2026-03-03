"""
Management command to set user role by phone number
Usage: python manage.py set_user_role --phone +905540225177 --role business_owner
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import Profile


class Command(BaseCommand):
    help = 'Set user role by phone number'

    def add_arguments(self, parser):
        parser.add_argument(
            '--phone',
            type=str,
            required=True,
            help='Phone number of the user (e.g., +905540225177)'
        )
        parser.add_argument(
            '--role',
            type=str,
            required=True,
            choices=[role[0] for role in Profile.Role.choices],
            help='Role to set (superuser, admin, operator, business_owner, customer)'
        )

    def handle(self, *args, **options):
        phone = options['phone'].strip()
        role = options['role']
        
        # Try multiple phone formats
        phone_variants = [phone]
        
        # Remove spaces and try
        phone_no_spaces = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if phone_no_spaces != phone:
            phone_variants.append(phone_no_spaces)
        
        # Try normalized versions
        try:
            from accounts.twilio_utils import format_phone_number
            formatted = format_phone_number(phone)
            phone_variants.append(formatted)
            if formatted.startswith('+'):
                phone_variants.append(formatted[1:])
            # Also try formatting the no-spaces version
            if phone_no_spaces != phone:
                formatted_no_spaces = format_phone_number(phone_no_spaces)
                phone_variants.append(formatted_no_spaces)
                if formatted_no_spaces.startswith('+'):
                    phone_variants.append(formatted_no_spaces[1:])
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Could not format phone: {e}'))
        
        # Try without leading zero
        if phone.startswith('0'):
            phone_variants.append(phone[1:])
        if phone_no_spaces.startswith('0'):
            phone_variants.append(phone_no_spaces[1:])
        
        # Try with + prefix
        if not phone.startswith('+'):
            phone_variants.append('+' + phone)
        if not phone_no_spaces.startswith('+'):
            phone_variants.append('+' + phone_no_spaces)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_variants = []
        for variant in phone_variants:
            if variant not in seen:
                seen.add(variant)
                unique_variants.append(variant)
        
        self.stdout.write(f'Trying phone number variants: {unique_variants}')
        
        user = None
        found_phone = None
        
        # Try to find user with any of these variants
        for phone_variant in unique_variants:
            try:
                profile = Profile.objects.get(phone=phone_variant)
                user = profile.user
                found_phone = phone_variant
                self.stdout.write(self.style.SUCCESS(f'Found user with phone: {found_phone}'))
                break
            except Profile.DoesNotExist:
                continue
        
        if not user:
            self.stdout.write(self.style.ERROR(f'User not found with any phone variant: {unique_variants}'))
            return
        
        self.stdout.write(f'User ID: {user.id}')
        self.stdout.write(f'Username: {user.username}')
        self.stdout.write(f'Email: {user.email}')
        
        profile = user.profile
        old_role = profile.role
        self.stdout.write(f'Current Role: {old_role}')
        
        if old_role == role:
            self.stdout.write(self.style.WARNING(f'User already has role: {role}'))
            return
        
        # Set new role
        profile.role = role
        profile.save(update_fields=['role'])
        
        self.stdout.write(self.style.SUCCESS(f'✓ Role changed from {old_role} to {role}'))
        
        # Verify the role was set
        profile.refresh_from_db()
        if profile.role == role:
            self.stdout.write(self.style.SUCCESS('✓ Role verification successful!'))
        else:
            self.stdout.write(self.style.ERROR('✗ Role verification failed!'))
