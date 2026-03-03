from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import Profile


class Command(BaseCommand):
    help = (
        "Migrate all Profile.role from BUSINESS_OWNER to BUSINESS_ADMIN.\n"
        "This command converts all legacy business_owner roles to business_admin.\n"
        "Safe to run multiple times - it only updates profiles with business_owner role."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without actually changing anything",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed output for each profile updated",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        verbose = options["verbose"]

        # Find all profiles with BUSINESS_OWNER role
        profiles = Profile.objects.filter(role=Profile.Role.BUSINESS_OWNER)
        count = profiles.count()

        if count == 0:
            self.stdout.write(
                self.style.SUCCESS("✓ No profiles with BUSINESS_OWNER role found. Nothing to migrate.")
            )
            return

        self.stdout.write(
            self.style.WARNING(f"Found {count} profile(s) with BUSINESS_OWNER role.")
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made.")
            )
            self.stdout.write("\nProfiles that would be updated:")
            for profile in profiles:
                self.stdout.write(
                    f"  - User ID {profile.user_id} ({profile.user.username}): "
                    f"role={profile.role} → BUSINESS_ADMIN"
                )
            return

        # Update all profiles
        updated_count = 0
        for profile in profiles:
            old_role = profile.role
            profile.role = Profile.Role.BUSINESS_ADMIN
            profile.save(update_fields=["role"])
            updated_count += 1

            if verbose:
                self.stdout.write(
                    f"  ✓ Updated User ID {profile.user_id} ({profile.user.username}): "
                    f"{old_role} → BUSINESS_ADMIN"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Successfully migrated {updated_count} profile(s) from BUSINESS_OWNER to BUSINESS_ADMIN."
            )
        )

        # Verify migration
        remaining = Profile.objects.filter(role=Profile.Role.BUSINESS_OWNER).count()
        if remaining > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠ Warning: {remaining} profile(s) still have BUSINESS_OWNER role."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("✓ All BUSINESS_OWNER roles have been migrated.")
            )
