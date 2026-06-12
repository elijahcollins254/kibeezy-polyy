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
