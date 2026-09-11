from django.core.management.base import BaseCommand

from apps.catalog.models import Title


class Command(BaseCommand):
    help = "Fix missing player_type for titles with player_id"

    def handle(self, *args, **options):
        titles_to_fix = Title.objects.filter(
            player_id__isnull=False
        ).exclude(
            player_id=""
        ).filter(
            player_type=""
        )

        count = titles_to_fix.count()
        self.stdout.write(f"Found {count} titles with player_id but no player_type")

        for title in titles_to_fix:
            if title.is_series:
                title.player_type = "series"
            else:
                title.player_type = "movie"

            title.save()
            self.stdout.write(f"Fixed: {title.name} -> player_type={title.player_type}")

        self.stdout.write(self.style.SUCCESS(f"Fixed {count} titles"))
