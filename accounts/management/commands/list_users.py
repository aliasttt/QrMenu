"""
Management command to list users with their roles and phone numbers
Usage: python manage.py list_users --search 905540225177
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import Profile


class Command(BaseCommand):
    help = 'List users with their roles and phone numbers'

    def add_arguments(self, parser):
        parser.add_argument(
            '--search',
            type=str,
            help='Search by phone number or username'
        )

    def handle(self, *args, **options):
        search_term = (options.get('search') or '').strip()
        
        if search_term:
            # Search by phone in profile
            profiles = Profile.objects.filter(phone__icontains=search_term)
            users = [p.user for p in profiles]
            # Also search by username
            users_by_username = User.objects.filter(username__icontains=search_term)
            users = list(set(list(users) + list(users_by_username)))
        else:
            users = User.objects.all().order_by('id')
        
        self.stdout.write(f'\nFound {len(users)} user(s):\n')
        self.stdout.write('-' * 80)
        
        for user in users:
            try:
                profile = user.profile
                phone = profile.phone or "(not set)"
                role = profile.role
            except Profile.DoesNotExist:
                phone = "(no profile)"
                role = "(no profile)"
            
            self.stdout.write(f'ID: {user.id}')
            self.stdout.write(f'Username: {user.username}')
            self.stdout.write(f'Email: {user.email or "(not set)"}')
            self.stdout.write(f'Phone: {phone}')
            self.stdout.write(f'Role: {role}')
            self.stdout.write('-' * 80)
