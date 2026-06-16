from celery import shared_task
from decimal import Decimal
from brokerage.services.polymarket.adapter import PolymarketAdapter
from brokerage.services.ledger import release_user_funds, create_transaction_with_entries
from brokerage.models import Order, Fill, Position, Market
from django.core.cache import cache
from brokerage.publish import publish_market_event


@shared_task(bind=True, max_retries=3)
def execute_order_task(self, order_id: int):
    """Celery task to execute an order on the external exchange and process fills."""
    try:
        order = Order.objects.select_related('user', 'market').get(pk=order_id)
    except Order.DoesNotExist:
        return {'status': 'missing'}

    adapter = PolymarketAdapter()
    try:
        resp = adapter.place_order(market_id=order.market.external_id, side=order.side, size=float(order.size), price=float(order.price), metadata={'internal_order_id': order.id})
    except Exception as exc:
        # Optionally retry
        raise self.retry(exc=exc)

    # Update order with external id
    order.external_order_id = resp.get('id') or resp.get('order_id')
    order.status = 'OPEN'
    order.save()

    total_filled = Decimal('0')
    fills = resp.get('fills') or []
    for f in fills:
        f_size = Decimal(str(f.get('size')))
        f_price = Decimal(str(f.get('price')))
        Fill.objects.create(order=order, external_fill_id=f.get('id'), size=f_size, price=f_price)
        total_filled += f_size
        # Ledger: reserved -> market escrow
        create_transaction_with_entries(order.user, 'TRADE', [
            {'debit': f'LIABILITY_RESERVED_{order.user.id}', 'credit': f'MARKET_ESCROW_{order.market.external_id}', 'amount': str((f_size * f_price).quantize(Decimal('0.00000001'))), 'description': f'Fill for order {order.id}'}
        ], reference=f'celery_fill:{order.id}:{f.get("id")}')
        try:
            from brokerage.publish import publish_market_event
            publish_market_event(order.market.external_id, {
                'type': 'fill',
                'order_id': order.id,
                'external_fill_id': f.get('id'),
                'size': str(f_size),
                'price': str(f_price),
            })
        except Exception:
            pass

    if total_filled >= order.size:
        order.status = 'FILLED'
        order.save()
        # Update position
        pos, _ = Position.objects.get_or_create(user=order.user, market=order.market)
        prev_qty = pos.quantity or Decimal('0')
        prev_avg = pos.average_price or Decimal('0')
        new_qty = prev_qty + total_filled
        if new_qty > 0:
            new_avg = ((prev_qty * prev_avg) + (total_filled * order.price)) / new_qty if prev_qty > 0 else order.price
            pos.quantity = new_qty
            pos.average_price = new_avg
        pos.save()

    return {'status': 'ok', 'order': order.id, 'filled': float(total_filled)}


@shared_task(bind=True)
def poll_and_publish_orderbooks(self, limit: int = 100):
    """Poll top `limit` markets' orderbooks from Polymarket, cache them briefly and publish changes via Channels."""
    adapter = PolymarketAdapter()
    markets = Market.objects.all().order_by('-created_at')[:limit]
    for m in markets:
        market_id = m.external_id
        cache_key = f"orderbook:{market_id}"
        try:
            ob = adapter.get_orderbook(market_id)
        except Exception:
            continue

        # Compare to cached snapshot
        prev = cache.get(cache_key)
        if prev != ob:
            # Update cache (short TTL)
            try:
                cache.set(cache_key, ob, timeout=5)
            except Exception:
                pass

            # Publish delta / snapshot to subscribers
            try:
                publish_market_event(market_id, {'type': 'orderbook_update', 'orderbook': ob})
            except Exception:
                pass

    return {'status': 'ok', 'processed': len(markets)}


@shared_task(bind=True)
def sync_polymarket_markets_task(self, limit: int = 500):
    """Wrapper task to run the management command that syncs Polymarket markets.

    This allows scheduling the sync via Celery Beat.
    Args:
        limit: Max number of markets to fetch (default 500)
    """
    try:
        from django.core.management import call_command
        call_command('sync_polymarket_markets', '--limit', str(limit))
        return {'status': 'ok', 'limit': limit}
    except Exception as e:
        raise e


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def settle_polymarket_market(self, market_id: int):
    """
    Settle all user positions in a resolved Polymarket market.
    
    This task:
    1. Validates market is resolved with outcome
    2. Calculates P&L for each user order (win/loss)
    3. Creates payout transactions for winners
    4. Updates order settlement status
    
    Args:
        market_id: ID of the resolved market
    
    Returns:
        dict with settlement summary
    """
    try:
        from brokerage.models import Market
        from brokerage.services.settlement import PolymarketSettlementService
        import logging
        
        logger = logging.getLogger(__name__)
        
        market = Market.objects.get(id=market_id)
        logger.info(f"Starting settlement for market {market_id}: {market.question}")
        
        result = PolymarketSettlementService.settle_market(market)
        
        logger.info(f"Market {market_id} settlement result: {result}")
        return result
    
    except Market.DoesNotExist:
        logger.error(f"Market {market_id} not found")
        return {'status': 'error', 'error': 'market_not_found'}
    except Exception as e:
        logger.error(f"Settlement error for market {market_id}: {e}", exc_info=True)
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True)
def start_polymarket_websocket_stream(self, network: str = 'mainnet', market_ids: list = None):
    """
    Start the Polymarket WebSocket streamer in an asyncio event loop.
    
    This task should be run as a persistent worker that streams real-time
    market data and order updates from Polymarket.
    
    Args:
        network: 'mainnet' or 'testnet'
        market_ids: Optional list of market IDs to subscribe to
    
    Returns:
        dict with streamer status
    """
    import asyncio
    import logging
    from brokerage.services.polymarket.websocket_streamer import PolymarketWebSocketStreamer
    
    logger = logging.getLogger(__name__)
    logger.info(f"Starting WebSocket stream on {network}")
    
    try:
        # Create streamer
        streamer = PolymarketWebSocketStreamer(network=network)
        
        # Subscribe to markets if provided
        async def setup_and_stream():
            await streamer.connect()
            
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
                            logger.info(f"Subscribed to market {market_id}")
                    except Market.DoesNotExist:
                        logger.warning(f"Market {market_id} not found")
            
            # Listen for messages (blocking)
            await streamer._listen()
        
        # Run async event loop
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(setup_and_stream())
        except KeyboardInterrupt:
            logger.info("WebSocket stream interrupted")
        finally:
            asyncio.run_coroutine_threadsafe(streamer.disconnect(), loop)
            loop.close()
        
        return {'status': 'ok', 'network': network}
    
    except Exception as e:
        logger.error(f"WebSocket stream error: {e}", exc_info=True)
        return {'status': 'error', 'error': str(e)}

