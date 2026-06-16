"""
Management command to sync resolved markets from Polymarket and trigger settlement
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from brokerage.models import Market
from brokerage.services.polymarket.adapter import PolymarketAdapter
from brokerage.tasks import settle_polymarket_market
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Sync resolved markets from Polymarket and settle user positions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Max number of markets to check (default: 100)'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Process all Polymarket markets (instead of just unresolved ones)'
        )
        parser.add_argument(
            '--auto-settle',
            action='store_true',
            help='Automatically trigger settlement task for resolved markets'
        )

    def handle(self, *args, **options):
        limit = options.get('limit', 100)
        check_all = options.get('all', False)
        auto_settle = options.get('auto_settle', True)
        
        self.stdout.write(
            f'Syncing Polymarket resolutions (limit: {limit}, all: {check_all}, auto_settle: {auto_settle})...'
        )
        
        adapter = PolymarketAdapter()
        
        # Get list of Polymarket markets to check
        if check_all:
            # Check all local markets from Polymarket
            try:
                polymarket_markets = adapter.get_markets(params={'limit': limit})
                self.stdout.write(f'Fetched {len(polymarket_markets)} markets from Polymarket')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to fetch markets from Polymarket: {e}'))
                return
        else:
            # Check only unresolved markets
            unresolved = Market.objects.filter(
                source='polymarket',
                polymarket_status__in=['OPEN', 'CLOSED']
            ).values_list('external_id', flat=True)[:limit]
            
            if not unresolved:
                self.stdout.write('No unresolved Polymarket markets found')
                return
            
            self.stdout.write(f'Checking {len(unresolved)} unresolved markets for resolution...')
            polymarket_markets = []
        
        resolved_count = 0
        settlement_count = 0
        error_count = 0
        
        # Process each market
        for market_data in polymarket_markets:
            try:
                external_id = market_data.get('id') or market_data.get('market_id')
                if not external_id:
                    continue
                
                # Check if market exists locally
                try:
                    local_market = Market.objects.get(external_id=str(external_id), source='polymarket')
                except Market.DoesNotExist:
                    # Market not in our system, skip
                    continue
                
                # Check if already settled
                if local_market.polymarket_status == 'RESOLVED' and local_market.settlement_status == 'COMPLETED':
                    continue
                
                # Extract market status and resolution
                status = market_data.get('status') or market_data.get('market_status')
                resolution = market_data.get('resolution') or market_data.get('resolved_outcome')
                
                # Check if market is now resolved
                if status == 'RESOLVED' or resolution:
                    self.stdout.write(
                        f'Market {external_id} resolved to {resolution}'
                    )
                    
                    # Update local market record
                    local_market.polymarket_status = 'RESOLVED'
                    local_market.resolution_outcome = resolution
                    
                    # Extract resolution price if available
                    if 'resolution_price' in market_data:
                        local_market.resolution_price = market_data['resolution_price']
                    
                    # Use metadata resolved_at if available
                    if 'resolved_at' in market_data:
                        from dateutil.parser import parse
                        try:
                            local_market.resolved_at = parse(market_data['resolved_at'])
                        except:
                            local_market.resolved_at = timezone.now()
                    else:
                        local_market.resolved_at = timezone.now()
                    
                    local_market.save()
                    resolved_count += 1
                    
                    # Trigger settlement if not already settled
                    if local_market.settlement_status != 'COMPLETED':
                        if auto_settle:
                            self.stdout.write(
                                f'  Queueing settlement for market {local_market.id}'
                            )
                            settle_polymarket_market.delay(local_market.id)
                            settlement_count += 1
                        else:
                            self.stdout.write(
                                f'  Market ready for settlement (use --auto-settle to trigger)'
                            )
                    else:
                        self.stdout.write(f'  Market already settled')
                
            except Exception as e:
                logger.error(f'Error processing market {external_id}: {e}')
                self.stdout.write(
                    self.style.ERROR(f'  Error processing market: {e}')
                )
                error_count += 1
        
        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f'\nSync complete: {resolved_count} resolved, '
                f'{settlement_count} settlements queued, {error_count} errors'
            )
        )
