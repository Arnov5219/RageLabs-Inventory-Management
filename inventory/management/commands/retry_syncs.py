from django.core.management.base import BaseCommand
from inventory.models import SheetSyncLog
from inventory.helpers import trigger_google_sheets_sync

class Command(BaseCommand):
    help = 'Retries failed Google Sheets synchronizations.'

    def handle(self, *args, **options):
        failed_logs = SheetSyncLog.objects.filter(status__in=['FAILED', 'PENDING'])
        self.stdout.write(f"Found {failed_logs.count()} failed/pending sync logs to retry.")
        
        success_count = 0
        for log in failed_logs:
            self.stdout.write(f"Retrying sync log #{log.id} for branch {log.branch.branch_code}...")
            trigger_google_sheets_sync(log.history_record)
            # Refresh from DB to see if status updated to SUCCESS
            log.refresh_from_db()
            if log.status == 'SUCCESS':
                success_count += 1
                self.stdout.write(self.style.SUCCESS(f"Sync log #{log.id} succeeded."))
            else:
                self.stderr.write(f"Sync log #{log.id} failed again: {log.error_message}")
                
        self.stdout.write(self.style.SUCCESS(f"Retry run completed. {success_count} logs successfully synced."))
