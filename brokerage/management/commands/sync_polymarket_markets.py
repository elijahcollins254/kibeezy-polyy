from django.core.management.base import BaseCommand
from brokerage.services.polymarket.adapter import PolymarketAdapter
from brokerage.models import Market
from brokerage.utils.category import extract_category, extract_subcategory


def _is_sports_market(market_data):
    category = market_data.get('category')
    if category and str(category).strip().lower() == 'sports':
        return True
    inferred = extract_category(market_data)
    return inferred == 'Sports'


class Command(BaseCommand):
    help = 'Sync markets from Polymarket into local Market model'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100, help='Max markets to fetch')
        parser.add_argument('--only-sports', action='store_true', help='Sync only sports markets from Polymarket')

    def handle(self, *args, **options):
        adapter = PolymarketAdapter()
        limit = options.get('limit')
        only_sports = options.get('only_sports', False)
        
        self.stdout.write(f'Fetching markets from Polymarket (limit: {limit}, only_sports: {only_sports})...')
        
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
                
                if only_sports:
                    sports_batch = [market for market in batch if _is_sports_market(market)]
                    all_markets.extend(sports_batch)
                    self.stdout.write(f'  Got {len(batch)} markets, {len(sports_batch)} sports markets (total sports: {len(all_markets)})')
                else:
                    all_markets.extend(batch)
                    self.stdout.write(f'  Got {len(batch)} markets (total: {len(all_markets)})')

                offset += fetch_size
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error fetching batch at offset {offset}: {e}'))
                break
        
        if only_sports:
            all_markets = all_markets[:limit]

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
                    'source': 'polymarket',
                    'metadata': m,
                }
            )
            count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Synced {count} markets'))
