from django.core.management.base import BaseCommand
from brokerage.models import Market


class Command(BaseCommand):
    help = 'Backfill market question field from metadata for existing markets'

    def handle(self, *args, **options):
        updated = 0
        skipped = 0
        
        for market in Market.objects.all():
            # Skip if question is already filled
            if market.question:
                skipped += 1
                continue
            
            # Try to get question from metadata
            question = None
            if market.metadata:
                question = market.metadata.get('question')
            
            # Fall back to title if no question in metadata
            if not question:
                question = market.title
            
            if question:
                market.question = question
                market.save()
                updated += 1
                self.stdout.write(f'Updated: {market.external_id} -> {question[:60]}...')
        
        self.stdout.write(
            self.style.SUCCESS(f'Backfill complete: {updated} updated, {skipped} skipped')
        )
