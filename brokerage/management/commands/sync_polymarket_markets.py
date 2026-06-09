from django.core.management.base import BaseCommand
from brokerage.services.polymarket.adapter import PolymarketAdapter
from brokerage.models import Market


class Command(BaseCommand):
    help = 'Sync markets from Polymarket into local Market model'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100, help='Max markets to fetch')

    def handle(self, *args, **options):
        adapter = PolymarketAdapter()
        params = {'limit': options.get('limit')}
        self.stdout.write('Fetching markets from Polymarket...')
        markets = adapter.get_markets(params=params)
        count = 0
        for m in markets:
            external_id = m.get('id') or m.get('market_id') or m.get('token')
            if not external_id:
                continue
            obj, created = Market.objects.update_or_create(
                external_id=str(external_id),
                defaults={
                    'title': m.get('title') or m.get('name') or external_id,
                    'description': m.get('description') or '',
                    'metadata': m,
                }
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f'Synced {count} markets'))
