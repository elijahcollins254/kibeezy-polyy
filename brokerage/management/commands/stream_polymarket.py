"""Management command to run the Polymarket WebSocket streamer."""

import asyncio
import signal
from django.core.management.base import BaseCommand
from django.conf import settings
from brokerage.services.polymarket.websocket_streamer import PolymarketWebSocketStreamer
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Start the Polymarket WebSocket streamer for real-time market data and order updates'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--network',
            type=str,
            default='mainnet',
            choices=['mainnet', 'testnet'],
            help='Network to connect to (default: mainnet)',
        )
        parser.add_argument(
            '--market-ids',
            type=str,
            nargs='+',
            help='Market IDs to subscribe to (optional)',
        )
        parser.add_argument(
            '--account',
            type=str,
            help='Account address to subscribe to for order updates (optional)',
        )
    
    def handle(self, *args, **options):
        network = options.get('network', 'mainnet')
        market_ids = options.get('market_ids', [])
        account = options.get('account')
        
        self.stdout.write(
            self.style.SUCCESS(f'Starting Polymarket WebSocket streamer ({network})...')
        )
        
        # Create streamer instance
        streamer = PolymarketWebSocketStreamer(network=network)
        
        # Handle graceful shutdown
        def signal_handler(sig, frame):
            self.stdout.write(self.style.WARNING('\nShutting down...'))
            asyncio.create_task(streamer.disconnect())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Subscribe to specific markets if provided
        async def setup_subscriptions():
            # Connect first
            await streamer.connect()
            
            # Subscribe to markets
            if market_ids:
                from brokerage.models import Market
                for market_id in market_ids:
                    try:
                        market = Market.objects.get(id=market_id)
                        token_ids = [
                            market.yes_token_id,
                            market.no_token_id,
                        ]
                        token_ids = [t for t in token_ids if t]
                        
                        if token_ids:
                            await streamer.subscribe_to_market(market_id, token_ids)
                            self.stdout.write(
                                self.style.SUCCESS(f'Subscribed to market {market_id}')
                            )
                    except Market.DoesNotExist:
                        self.stdout.write(
                            self.style.WARNING(f'Market {market_id} not found')
                        )
            
            # Subscribe to order updates
            if account:
                await streamer.subscribe_to_orders(account)
                self.stdout.write(
                    self.style.SUCCESS(f'Subscribed to order updates for {account}')
                )
        
        # Run the streamer
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(setup_subscriptions())
            loop.run_until_complete(streamer._listen())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Interrupted'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
            raise
        finally:
            loop.run_until_complete(streamer.disconnect())
