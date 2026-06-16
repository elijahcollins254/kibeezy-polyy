"""
Settlement service for Polymarket orders
Handles P&L calculation, position settlement, and payout transactions
"""
import logging
from decimal import Decimal
from django.db import transaction as db_transaction, models
from django.utils import timezone
from brokerage.models import Market, Order, Fill, Position
from brokerage.services.ledger import create_transaction_with_entries
from brokerage.services.fee_service import FeeService

logger = logging.getLogger(__name__)


class PolymarketSettlementService:
    """Service to settle user positions when a Polymarket market resolves"""
    
    @staticmethod
    def calculate_payout(order: Order, resolution_outcome: str, resolution_price: Decimal) -> Decimal:
        """
        Calculate payout for an order based on market resolution.
        
        Args:
            order: The Order object (BUY or SELL side)
            resolution_outcome: "Yes" or "No"
            resolution_price: Final price at resolution (0-1)
        
        Returns:
            Decimal payout amount in KES
        
        Logic:
        - For BUY orders: If you bought YES and market resolved YES, you win
        - For SELL orders: If you sold YES and market resolved NO, you win
        - Payout = shares × resolution_price × 100 KES (converts 0-1 price to value)
        """
        if not order.status == 'FILLED':
            logger.warning(f"Order {order.id} not filled, skipping settlement")
            return Decimal('0')
        
        filled_size = Fill.objects.filter(order=order).aggregate(
            total=models.Sum('size')
        )['total'] or Decimal('0')
        
        if filled_size == 0:
            return Decimal('0')
        
        # Determine if this order was a winner or loser
        is_winner = False
        
        if order.side.upper() == 'BUY':
            # User bought shares - winner if market resolved YES
            is_winner = (resolution_outcome == 'Yes')
        else:  # SELL
            # User sold shares - winner if market resolved NO
            is_winner = (resolution_outcome == 'No')
        
        # Calculate payout
        if is_winner:
            # Winner gets: shares × resolution_price × 100 KES
            # This converts the 0-1 price to a 0-100 KES range per share
            payout = filled_size * resolution_price * Decimal('100')
        else:
            # Loser gets nothing (complete loss of stake)
            payout = Decimal('0')
        
        logger.info(
            f"Order {order.id} settlement: side={order.side}, filled={filled_size}, "
            f"outcome={resolution_outcome}, is_winner={is_winner}, payout={payout}"
        )
        
        return payout
    
    @staticmethod
    def settle_market(market: Market) -> dict:
        """
        Settle all user orders in a resolved Polymarket market.
        
        Flow:
        1. Validate market is resolved with outcome
        2. For each FILLED order in the market:
           - Calculate payout based on win/loss
           - Update order settlement fields
           - Create ledger transactions for winners
           - Create payout transactions for M-Pesa
        
        Args:
            market: Market that has been resolved
        
        Returns:
            dict with settlement summary
        """
        if market.polymarket_status != 'RESOLVED':
            return {
                'status': 'error',
                'error': f'Market not resolved, status={market.polymarket_status}'
            }
        
        if not market.resolution_outcome:
            return {
                'status': 'error',
                'error': 'Market resolved but no outcome set'
            }
        
        if market.settlement_status == 'COMPLETED':
            logger.info(f"Market {market.id} already settled, skipping")
            return {'status': 'already_settled'}
        
        try:
            with db_transaction.atomic():
                # Lock market to prevent concurrent settlement
                market = Market.objects.select_for_update().get(pk=market.id)
                
                # Mark settlement as processing
                market.settlement_status = 'PROCESSING'
                market.settlement_started_at = timezone.now()
                market.save()
                
                # Get all filled orders for this market
                filled_orders = Order.objects.filter(
                    market=market,
                    status='FILLED'
                )
                
                settlement_summary = {
                    'market_id': market.id,
                    'total_orders': filled_orders.count(),
                    'winners': 0,
                    'losers': 0,
                    'total_payout': Decimal('0'),
                    'payout_transactions': []
                }
                
                # Process each order
                for order in filled_orders:
                    # Skip if already settled
                    if order.settlement_result != 'PENDING':
                        logger.info(f"Order {order.id} already settled, skipping")
                        continue
                    
                    # Calculate payout
                    payout = PolymarketSettlementService.calculate_payout(
                        order,
                        market.resolution_outcome,
                        market.resolution_price or Decimal('0')
                    )
                    
                    # Update order
                    if payout > 0:
                        order.settlement_result = 'WON'
                        settlement_summary['winners'] += 1
                    else:
                        order.settlement_result = 'LOST'
                        settlement_summary['losers'] += 1
                    
                    order.payout = payout
                    order.settled_at = timezone.now()
                    order.save()
                    
                    # Create ledger transaction for winners (payout)
                    if payout > 0:
                        PolymarketSettlementService._create_payout_transaction(
                            order, payout, market
                        )
                        settlement_summary['total_payout'] += payout
                        settlement_summary['payout_transactions'].append({
                            'user_id': order.user.id,
                            'order_id': order.id,
                            'payout': float(payout)
                        })
                
                # Mark settlement as completed
                market.settlement_status = 'COMPLETED'
                market.settlement_completed_at = timezone.now()
                market.save()
                
                logger.info(f"Market {market.id} settlement completed: {settlement_summary}")
                return {
                    'status': 'settled',
                    **settlement_summary
                }
        
        except Exception as e:
            logger.error(f"Settlement error for market {market.id}: {e}", exc_info=True)
            # Mark as failed
            market.settlement_status = 'FAILED'
            market.save()
            return {
                'status': 'error',
                'error': str(e)
            }
    
    @staticmethod
    def _create_payout_transaction(order: Order, payout: Decimal, market: Market):
        """
        Create a ledger transaction for a winning order payout.
        
        This credits the user's liability account with the payout amount.
        Later, M-Pesa B2C will be called to actually transfer funds.
        """
        try:
            from brokerage.models import Account, Transaction, LedgerEntry
            
            # Get or create settlement account
            settlement_account, _ = Account.objects.get_or_create(
                code='SETTLEMENT_POLYMARKET',
                defaults={'name': 'Polymarket Settlement Account'}
            )
            
            # Get user's liability account
            liability_code = f"LIABILITY_USER_{order.user.id}"
            user_liability, _ = Account.objects.get_or_create(
                code=liability_code,
                defaults={'name': f'User Liability - {order.user.phone_number}'}
            )
            
            # Create transaction
            tx = Transaction.objects.create(
                user=order.user,
                type='SETTLEMENT',
                reference=f"PM-SETTLEMENT-{market.id}-{order.id}",
                metadata={
                    'market_id': market.id,
                    'order_id': order.id,
                    'polymarket_id': market.external_id,
                    'amount': str(payout)
                }
            )
            
            # Create ledger entries
            # Debit settlement account, credit user liability
            LedgerEntry.objects.create(
                transaction=tx,
                debit_account=settlement_account,
                credit_account=user_liability,
                amount=payout,
                description=f"Payout for {market.question} resolution to {order.user.phone_number}"
            )
            
            logger.info(f"Created settlement transaction {tx.id} for order {order.id}: {payout} KES")
            
            return tx
        
        except Exception as e:
            logger.error(f"Failed to create payout transaction for order {order.id}: {e}")
            raise
