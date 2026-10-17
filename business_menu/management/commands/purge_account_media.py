from django.core.management.base import BaseCommand, CommandError

from business_menu.account_deletion import purge_account_media


class Command(BaseCommand):
    help = "Retry pending media deletion for erased business accounts."

    def handle(self, *args, **options):
        if purge_account_media():
            raise CommandError("Some account media deletions remain pending; retry required.")
        self.stdout.write("Account media cleanup complete.")
