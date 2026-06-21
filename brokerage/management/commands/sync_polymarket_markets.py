from django.core.management.base import BaseCommand
from brokerage.services.polymarket.adapter import PolymarketAdapter
from brokerage.models import Market
from brokerage.utils.category import extract_category, extract_subcategory


class Command(BaseCommand):
    help = 'Sync markets from Polymarket into local Market model'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100, help='Max markets to fetch')

    def handle(self, *args, **options):
        adapter = PolymarketAdapter()
        limit = options.get('limit')
        
        self.stdout.write(f'Fetching markets from Polymarket (limit: {limit})...')
        
        # Fetch markets with pagination (API batches at 100)
        all_markets = []
        offset = 0
        batch_size = 100
        
        while len(all_markets) < limit:
            remaining = limit - len(all_markets)
            fetch_size = min(batch_size, remaining)
            
            params = {
                'limit': fetch_size, 
                'offset': offset,
                'active': True,
                'closed': False,
                'order': 'volume',
                'ascending': False,
            }
            self.stdout.write(f'  Fetching batch: offset={offset}, limit={fetch_size}...')
            
            try:
                batch = adapter.get_markets(params=params)
                if not batch:
                    self.stdout.write(f'  No more markets available after {len(all_markets)} total')
                    break
                
                all_markets.extend(batch)
                offset += fetch_size
                self.stdout.write(f'  Got {len(batch)} markets (total: {len(all_markets)})')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error fetching batch at offset {offset}: {e}'))
                break
        
        count = 0
        for m in all_markets:
            external_id = m.get('id') or m.get('market_id') or m.get('token')
            if not external_id:
                continue
            
            category = extract_category(m)
            subcategory = extract_subcategory(m, category)
            
            obj, created = Market.objects.update_or_create(
                external_id=str(external_id),
                defaults={
                    'title': m.get('title') or m.get('name') or external_id,
                    'question': m.get('question') or m.get('title') or m.get('name') or '',
                    'description': m.get('description') or '',
                    'category': category,
                    'subcategory': subcategory,
                    'metadata': m,
                }
            )
            count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Synced {count} markets'))
