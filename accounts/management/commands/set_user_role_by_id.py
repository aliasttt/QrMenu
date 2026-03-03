"""
Management command to set user role by user ID
Usage: python manage.py set_user_role_by_id --user-id 27 --role business_owner
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import Profile


class Command(BaseCommand):
    help = 'Set user role by user ID'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            required=True,
            help='User ID (e.g., 27)'
        )
        parser.add_argument(
            '--role',
            type=str,
            required=True,
            choices=[role[0] for role in Profile.Role.choices],
            help='Role to set (superuser, admin, operator, business_owner, customer)'
        )

    def handle(self, *args, **options):
        user_id = options['user_id']
        role = options['role']
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User with ID {user_id} not found'))
            return
        
        self.stdout.write(f'User ID: {user.id}')
        self.stdout.write(f'Username: {user.username}')
        self.stdout.write(f'Email: {user.email}')
        
        profile, _ = Profile.objects.get_or_create(user=user)
        self.stdout.write(f'Phone: {profile.phone or "(not set)"}')
        
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
