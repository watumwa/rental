from django.core.management.base import BaseCommand

from rentalapp.services import run_daily_operations


class Command(BaseCommand):
    help = "Update lease lifecycle states and queue arrears reminders. Safe to run daily."

    def handle(self, *args, **options):
        result = run_daily_operations()
        self.stdout.write(
            self.style.SUCCESS(
                f"Daily operations complete: {result['expired']} leases expired, "
                f"{result['reminders']} reminders queued."
            )
        )
