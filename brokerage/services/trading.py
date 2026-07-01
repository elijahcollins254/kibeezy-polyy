from decimal import Decimal
from typing import Optional, Dict, Any
from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone

from brokerage.services.ledger import reserve_user_funds, release_user_funds, create_transaction_with_entries, LedgerError
from brokerage.services.fee_service import FeeService
from brokerage.publish import publish_market_event
from brokerage.services.polymarket.adapter import PolymarketAdapter
from brokerage.models import Order, Market, Fill, Position


class TradingService:
    def __init__(self, adapter: Optional[PolymarketAdapter] = None):
        self.adapter = adapter or PolymarketAdapter()

    def validate_balance(self, user, required_amount: Decimal) -> bool:
        # Uses Account-based balances via user's wallet liability account
        wallet = getattr(user, 'wallet', None)
        if wallet is None:
            return False
        available = Decimal(wallet.available_balance() or 0)
        return available >= required_amount

    def create_position_from_fill(self, user, market_external_id: str, side: str, fill_data: Dict[str, Any]) -> Position:
        """Create a brokerage.Position record from a Polymarket fill."""
        f_size = Decimal(str(fill_data.get('size')))
        f_price = Decimal(str(fill_data.get('price')))
        outcome = 'Yes' if side.upper() == 'BUY' else 'No'
        amount = f_size * f_price
        
        market, _ = Market.objects.get_or_create(
            external_id=market_external_id,
            defaults={
                'title': market_external_id,
                'question': market_external_id,
                'category': 'Crypto',
                'description': f'Polymarket {market_external_id}',
                'source': 'polymarket',
                'is_approved': True,
            }
        )

        position, _ = Position.objects.get_or_create(
            user=user,
            market=market,
            defaults={'quantity': f_size, 'average_price': f_price},
        )
        position.quantity += f_size
        position.average_price = ((position.average_price * (position.quantity - f_size)) + (f_price * f_size)) / position.quantity if position.quantity else f_price
        position.save()

        return position

    def place_user_order(self, user, market_external_id: str, side: str, size: Decimal, price: Decimal) -> Order:
        # Calculate cost (simple cost = size * price) — adapt for market conventions
        cost = (size * price).quantize(Decimal('0.00000001'))

        if not self.validate_balance(user, cost):
            raise LedgerError('Insufficient funds')

        # Reserve funds
        reserve_tx = reserve_user_funds(user, cost)

        # Create local order record
        market, _ = Market.objects.get_or_create(external_id=market_external_id, defaults={'title': market_external_id})
        order = Order.objects.create(
            user=user,
            market=market,
            side=side,
            size=size,
            price=price,
            status='PENDING'
        )

        # Enqueue/perform the external order placement synchronously here for simplicity — prefer Celery task in production
        try:
            external = self.adapter.place_order(market_id=market_external_id, side=side, size=float(size), price=float(price), metadata={'internal_order_id': order.id})
        except Exception as e:
            # Release reserved funds on failure
            release_user_funds(user, cost)
            order.status = 'REJECTED'
            order.save()
            raise

        # Update order with external id and status
        order.external_order_id = external.get('id') or external.get('order_id') or None
        # Polymarket may return immediate fill info; interpret conservatively
        order.status = 'OPEN'
        order.save()

        # If external response contains fills, create Fill records and ledger settlement
        fills = external.get('fills') or []
        total_filled = Decimal('0')
        for f in fills:
            f_size = Decimal(str(f.get('size')))
            f_price = Decimal(str(f.get('price')))
            fill_amount = (f_size * f_price).quantize(Decimal('0.00000001'))
            
            # Create brokerage.Fill record (order execution record)
            Fill.objects.create(order=order, external_fill_id=f.get('id'), size=f_size, price=f_price)
            
            # Create brokerage.Position record (user position record)
            try:
                position = self.create_position_from_fill(user, market_external_id, side, f)
                # Store bet ID in metadata for traceability
                fill_metadata = {
                    'external_fill_id': f.get('id'),
                    'position_id': position.id,
                    'fill_amount': str(fill_amount),
                }
            except Exception as e:
                # Log Bet creation failure but continue with ledger
                fill_metadata = {
                    'external_fill_id': f.get('id'),
                    'position_creation_error': str(e),
                    'fill_amount': str(fill_amount),
                }
                raise
            
            total_filled += f_size
            
            # Create ledger entries for each fill: move reserved -> market escrow
            # Debit: LIABILITY_RESERVED_{user.id}
            # Credit: MARKET_ESCROW_{market.external_id}
            entries = [
                {
                    'debit': f'LIABILITY_RESERVED_{user.id}',
                    'credit': f'MARKET_ESCROW_{market_external_id}',
                    'amount': str(fill_amount),
                    'description': f'Fill of {side} {f_size} @ {f_price} for market {market_external_id}'
                },
            ]
            create_transaction_with_entries(
                user,
                'TRADE',
                entries,
                reference=f'fill:{order.id}:{f.get("id")}',
                metadata=fill_metadata
            )

            # publish fill to WebSocket subscribers
            try:
                publish_market_event(market_external_id, {
                    'type': 'fill',
                    'order_id': order.id,
                    'external_fill_id': f.get('id'),
                    'size': str(f_size),
                    'price': str(f_price),
                    'position_id': fill_metadata.get('position_id'),
                })
            except Exception:
                # best-effort, don't fail the flow on publish errors
                pass

        # If fully filled, mark FILLED and update position
        # Note: We maintain dual position records:
        # - brokerage.Position: Tracks reserved funds and balance impact (internal ledger)
        if total_filled >= order.size:
            order.status = 'FILLED'
            order.save()
            # Update or create brokerage position (for balance management)
            pos, _ = Position.objects.get_or_create(user=user, market=market, defaults={'quantity': total_filled, 'average_price': price})
            if pos.quantity and pos.average_price:
                # Weighted average update
                prev_qty = pos.quantity
                prev_avg = pos.average_price
                new_qty = prev_qty + total_filled
                new_avg = ((prev_qty * prev_avg) + (total_filled * price)) / new_qty
                pos.quantity = new_qty
                pos.average_price = new_avg
            else:
                pos.quantity = total_filled
                pos.average_price = price
            pos.save()

        return order

    def place_polymarket_order(
        self,
        user,
        market_id: str,
        token_id: str,
        side: str,
        size: float,
        price: float,
        order_type: str = 'market',
    ) -> Dict[str, Any]:
        """
        Place an order on Polymarket using py-clob-client-v2.
        Creates local Order and Fill records to sync with local Position model.
        
        Args:
            user: Django user object
            market_id: Local market ID to associate with this order
            token_id: Polymarket token ID (from market.clobTokenIds)
            side: 'BUY' or 'SELL'
            size: Number of shares (or USD for market orders)
            price: Price (0-1 for probability, ignored for market orders)
            order_type: 'market' or 'limit'
        
        Returns:
            Dict with order result including local order data
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Get or create local market
            market, _ = Market.objects.get_or_create(external_id=market_id, defaults={'title': market_id})
            
            # Calculate trading fee on the order size
            size_decimal = Decimal(str(size))
            fee, total_cost = FeeService.get_total_cost(size_decimal)
            
            # Check user balance includes fee
            user_balance = Decimal(str(user.wallet.available_balance())) if hasattr(user, 'wallet') else Decimal(str(user.balance))
            if total_cost > user_balance:
                raise ValueError(f"Insufficient balance. Need {total_cost}, have {user_balance}")
            
            # Create local Order record in PENDING state
            price_decimal = Decimal(str(price))
            order = Order.objects.create(
                user=user,
                market=market,
                side=side,
                size=size_decimal,
                price=price_decimal,
                status='PENDING'
            )
            logger.info(f"Created local Order record: {order.id} for user {user.id}")
            
            # Place order on Polymarket
            if order_type == 'market':
                # Market order: amount is in USD
                response = self.adapter.place_market_order(
                    token_id=token_id,
                    amount=size,
                    side=side,
                )
            else:
                # Limit order: size is shares, price is 0-1
                response = self.adapter.place_limit_order(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=side,
                )
            
            # Extract order ID from response
            polymarket_order_id = response.get('id') or response.get('order_id')
            order.external_order_id = polymarket_order_id
            
            # Process fills from response (market orders typically fill immediately or partially)
            fills_data = response.get('fills', []) or response.get('result', {}).get('fills', [])
            
            if fills_data:
                # Order was filled (market order or immediate fill)
                total_filled = Decimal('0')
                for fill_data in fills_data:
                    fill_size = Decimal(str(fill_data.get('size', 0)))
                    fill_price = Decimal(str(fill_data.get('price', price)))
                    
                    # Create Fill record
                    fill = Fill.objects.create(
                        order=order,
                        external_fill_id=fill_data.get('id') or fill_data.get('fill_id'),
                        size=fill_size,
                        price=fill_price
                    )
                    total_filled += fill_size
                    logger.info(f"Created Fill record: {fill.id} for Order {order.id} ({fill_size}@{fill_price})")
                
                # Update order status to FILLED if fully filled
                if total_filled >= size_decimal:
                    order.status = 'FILLED'
                elif total_filled > 0:
                    order.status = 'OPEN'  # Partially filled
                
                order.save()
                
                # Update Position with weighted average (only if there are fills)
                self._update_position_from_fills(user, market, order)
            else:
                # No fills in response - order is pending (limit orders typically)
                order.status = 'OPEN'
                order.save()
            
            logger.info(f"Polymarket {order_type} order placed: {side} {size} token={token_id} polymarket_id={polymarket_order_id} (Fee: {fee})")
            
            # Return success response with local order data
            return {
                'success': True,
                'order_id': order.id,  # Local order ID
                'polymarket_order_id': polymarket_order_id,
                'type': order_type,
                'side': side,
                'size': float(size),
                'price': float(price),
                'token_id': token_id,
                'status': order.status,
                'fee': float(fee),
                'total_cost': float(total_cost),
                'fills_count': len(fills_data) if fills_data else 0,
            }
            
        except Exception as e:
            logger.error(f"Failed to place Polymarket order: {e}", exc_info=True)
            raise
    
    def _update_position_from_fills(self, user, market: Market, order: Order):
        """
        Update Position model based on fills from an order.
        Uses weighted average price calculation.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Get all fills for this order
        fills = order.fills.all()
        if not fills.exists():
            return
        
        # Get or create position
        position, created = Position.objects.get_or_create(
            user=user,
            market=market,
            defaults={'quantity': Decimal('0'), 'average_price': Decimal('0')}
        )
        
        # Calculate total fill size and cost
        total_fill_size = Decimal('0')
        total_fill_cost = Decimal('0')
        
        for fill in fills:
            total_fill_size += fill.size
            total_fill_cost += fill.size * fill.price
        
        if total_fill_size == 0:
            return
        
        # Update position based on order side
        if order.side.upper() == 'BUY':
            prev_qty = position.quantity
            prev_avg = position.average_price
            
            new_qty = prev_qty + total_fill_size
            if new_qty > 0:
                new_avg = ((prev_qty * prev_avg) + total_fill_cost) / new_qty
            else:
                new_avg = Decimal('0')
            
            position.quantity = new_qty
            position.average_price = new_avg
        else:  # SELL
            position.quantity -= total_fill_size
            # For sells, we could calculate realized P&L
        
        position.save()
        logger.info(f"Updated Position for user {user.id} market {market.id}: qty={position.quantity}, avg={position.average_price}")

