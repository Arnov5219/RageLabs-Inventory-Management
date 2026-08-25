import os
import shutil
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = 'Restores the database from a backup file.'

    def add_arguments(self, parser):
        parser.add_argument('backup_file', type=str, help='Path to the backup file to restore.')

    def handle(self, *args, **options):
        backup_file = options['backup_file']
        if not os.path.exists(backup_file):
            self.stderr.write(f"Backup file {backup_file} does not exist.")
            return

        db_path = settings.DATABASES['default']['NAME']
        
        self.stdout.write(self.style.WARNING(f"WARNING: This will overwrite the current database at {db_path}!"))
        
        shutil.copy2(backup_file, db_path)
        self.stdout.write(self.style.SUCCESS(f"Successfully restored database from {backup_file}"))
