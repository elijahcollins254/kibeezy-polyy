from django.core.management.base import BaseCommand
from brokerage.services.polymarket.adapter import PolymarketAdapter
from brokerage.models import Market


class Command(BaseCommand):
    help = 'Sync markets from Polymarket into local Market model'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100, help='Max markets to fetch')

    def extract_category(self, market_data):
        """Extract or infer category from Polymarket market data."""
        # Priority: category field → tags → infer from keywords
        if market_data.get('category'):
            return market_data.get('category')
        
        # Check tags
        if market_data.get('tags'):
            tags = market_data.get('tags', [])
            if isinstance(tags, list) and len(tags) > 0:
                tag_mapping = {
                    'sports': 'Sports',
                    'politics': 'Politics',
                    'election': 'Politics',
                    'economy': 'Economy',
                    'crypto': 'Crypto',
                    'bitcoin': 'Crypto',
                    'ethereum': 'Crypto',
                    'tech': 'Technology',
                    'technology': 'Technology',
                    'ai': 'Technology',
                    'environment': 'Environment',
                    'climate': 'Environment',
                    'geo': 'Geopolitics',
                    'geopolitics': 'Geopolitics',
                    'war': 'Geopolitics',
                }
                for tag in tags:
                    tag_lower = str(tag).lower()
                    for key, category in tag_mapping.items():
                        if key in tag_lower:
                            return category
        
        # Infer from title/question
        text = (market_data.get('title') or market_data.get('question') or '').lower()
        infer_mapping = {
            'sports': 'Sports',
            'game': 'Sports',
            'match': 'Sports',
            'election': 'Politics',
            'political': 'Politics',
            'vote': 'Politics',
            'government': 'Politics',
            'economy': 'Economy',
            'stock': 'Economy',
            'gdp': 'Economy',
            'inflation': 'Economy',
            'bitcoin': 'Crypto',
            'ethereum': 'Crypto',
            'crypto': 'Crypto',
            'blockchain': 'Crypto',
            'ai': 'Technology',
            'tech': 'Technology',
            'software': 'Technology',
            'climate': 'Environment',
            'environment': 'Environment',
            'war': 'Geopolitics',
            'russia': 'Geopolitics',
            'ukraine': 'Geopolitics',
            'israel': 'Geopolitics',
        }
        for keyword, category in infer_mapping.items():
            if keyword in text:
                return category
        
        return 'Other'

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
            
            params = {'limit': fetch_size, 'offset': offset}
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
            
            category = self.extract_category(m)
            
            obj, created = Market.objects.update_or_create(
                external_id=str(external_id),
                defaults={
                    'title': m.get('title') or m.get('name') or external_id,
                    'question': m.get('question') or m.get('title') or m.get('name') or '',
                    'description': m.get('description') or '',
                    'category': category,
                    'metadata': m,
                }
            )
            count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Synced {count} markets'))
