import os
import shutil
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = 'Creates a backup of the SQLite database.'

    def handle(self, *args, **options):
        db_path = settings.DATABASES['default']['NAME']
        if not os.path.exists(db_path):
            self.stderr.write(f"Database path {db_path} does not exist.")
            return

        backup_dir = os.path.join(settings.BASE_DIR, 'backups')
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"db_backup_{timestamp}.sqlite3"
        backup_path = os.path.join(backup_dir, backup_filename)

        shutil.copy2(db_path, backup_path)
        self.stdout.write(self.style.SUCCESS(f"Successfully created backup: {backup_path}"))

        # Keep last 7 backups, delete older ones
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith('db_backup_') and f.endswith('.sqlite3')],
            key=lambda x: os.path.getmtime(os.path.join(backup_dir, x))
        )
        if len(backups) > 7:
            for old_backup in backups[:-7]:
                os.remove(os.path.join(backup_dir, old_backup))
                self.stdout.write(f"Removed old backup: {old_backup}")
