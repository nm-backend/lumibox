from django.core.management.base import BaseCommand

from apps.catalog.models import Title
from apps.catalog.video_service_sync import sync_title


class Command(BaseCommand):
    help = "Fix corrupted player_id values (HTML instead of numeric IDs)"

    def handle(self, *args, **options):
        # Find titles with corrupted player_id (contains HTML)
        corrupted = Title.objects.filter(
            player_id__isnull=False
        ).exclude(
            player_id=""
        ).filter(
            player_id__contains="<ins"
        )

        count = corrupted.count()
        self.stdout.write(f"Found {count} titles with corrupted player_id")

        for title in corrupted:
            self.stdout.write(f"Fixing: {title.name} (current: {title.player_id[:50]}...)")

            # Clear corrupted player_id
            title.player_id = ""
            title.player_type = ""
            title.save()

            # Re-sync with Vibix API to get correct values
            try:
                result = sync_title(title)
                self.stdout.write(f"  Sync result: {result}")
                title.refresh_from_db()
                self.stdout.write(f"  New player_id: {title.player_id}, player_type: {title.player_type}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Sync failed: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Fixed {count} titles"))
