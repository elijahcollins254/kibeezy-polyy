from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from django.db import models
from django.utils import timezone

from brokerage.api.serializers import PlaceOrderSerializer, OrderSerializer
from brokerage.services.trading import TradingService
from brokerage.tasks import execute_order_task
from brokerage.utils.signature import verify_signature
import time
import logging

logger = logging.getLogger(__name__)


class PlaceOrderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PlaceOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        svc = TradingService()
        data = serializer.validated_data
        user = request.user
        
        # Optional signature verification for non-custodial flows.
        sig = data.get('signature')
        signer = data.get('signer_address')
        if sig:
            # Build canonical payload that the client should have signed
            payload = {
                'market_id': data['market_id'],
                'side': data['side'],
                'size': str(data['size']),
                'price': str(data['price']),
            }
            # include optional nonce/timestamp if present
            if data.get('nonce'):
                payload['nonce'] = data.get('nonce')
            if data.get('timestamp'):
                payload['timestamp'] = data.get('timestamp')

            # If timestamp present, reject if too old to mitigate replay (2 minutes)
            ts = data.get('timestamp')
            if ts and abs(int(time.time()) - int(ts)) > 120:
                return Response({'error': 'signature timestamp out of window'}, status=status.HTTP_400_BAD_REQUEST)

            # Determine expected address: prefer explicit signer_address, else attempt user profile
            expected_addr = signer or getattr(user, 'eth_address', None) or getattr(user, 'wallet_address', None)
            if not expected_addr:
                return Response({'error': 'no expected signer address available; register an address or omit signature'}, status=status.HTTP_400_BAD_REQUEST)

            try:
                ok = verify_signature(payload, sig, expected_addr)
            except ValueError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

            if not ok:
                return Response({'error': 'invalid signature'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Determine if this is a Polymarket order (token_id in request indicates Polymarket)
            token_id = data.get('token_id')
            order_type = data.get('order_type', 'market')  # 'market' or 'limit'
            
            if token_id:
                # ============================================
                # POLYMARKET ORDER
                # ============================================
                logger.info(f"Placing Polymarket {order_type} order: {data['side']} {data['size']}@{data['price']} token={token_id}")
                
                result = svc.place_polymarket_order(
                    user=user,
                    market_id=data['market_id'],
                    token_id=token_id,
                    side=data['side'],
                    size=float(data['size']),
                    price=float(data['price']),
                    order_type=order_type,
                )
                
                return Response(result, status=status.HTTP_201_CREATED)
            else:
                # ============================================
                # LOCAL MARKET ORDER (backward compatibility)
                # ============================================
                order = svc.place_user_order(
                    user,
                    data['market_id'],
                    data['side'],
                    data['size'],
                    data['price']
                )
                
                # Enqueue background task for extra processing (idempotent)
                try:
                    execute_order_task.delay(order.id)
                except Exception:
                    # Don't block user flow if Celery unavailable; it's best-effort
                    pass

                out = OrderSerializer(order)
                return Response(out.data, status=status.HTTP_201_CREATED)
                
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PolymarketFillWebhookView(APIView):
    """
    Webhook endpoint to receive Polymarket fill notifications.
    
    Polymarket sends fill events when orders are executed.
    This endpoint:
    1. Receives fill notifications from Polymarket
    2. Finds the corresponding local Order
    3. Creates Fill records
    4. Updates Position model to reflect fills
    
    Webhook should be configured in Polymarket CLOB settings to POST to:
    /api/brokerage/webhooks/polymarket-fills/
    """
    permission_classes = [permissions.AllowAny]  # Webhooks are typically unauthenticated
    
    def post(self, request):
        """
        Handle incoming fill notification from Polymarket.
        
        Expected payload:
        {
            "event_type": "ORDER_FILLED" or "FILL",
            "order_id": "polymarket-order-id",
            "fills": [
                {
                    "id": "fill-id",
                    "size": 10.5,
                    "price": 0.65,
                    "timestamp": 1234567890
                }
            ],
            "market_id": "market-id",
            "token_id": "token-id",
            "user_address": "0x...",  # Optional: user's Polymarket address
        }
        """
        try:
            webhook_data = request.data
            polymarket_order_id = webhook_data.get('order_id')
            fills_list = webhook_data.get('fills', [])
            event_type = webhook_data.get('event_type', 'FILL')
            
            if not polymarket_order_id or not fills_list:
                logger.warning(f"Invalid webhook payload: missing order_id or fills")
                return Response({'error': 'Missing order_id or fills'}, status=status.HTTP_400_BAD_REQUEST)
            
            logger.info(f"Received Polymarket {event_type} webhook for order {polymarket_order_id} with {len(fills_list)} fills")
            
            # Find the local Order by external_order_id (Polymarket order ID)
            from brokerage.models import Order, Fill
            from decimal import Decimal
            
            try:
                order = Order.objects.get(external_order_id=polymarket_order_id)
            except Order.DoesNotExist:
                logger.error(f"No local Order found for Polymarket order_id {polymarket_order_id}")
                return Response({'error': f'Order {polymarket_order_id} not found'}, status=status.HTTP_404_NOT_FOUND)
            
            # Process each fill
            for fill_data in fills_list:
                fill_id = fill_data.get('id') or fill_data.get('fill_id')
                fill_size = Decimal(str(fill_data.get('size', 0)))
                fill_price = Decimal(str(fill_data.get('price', 0)))
                
                # Check if fill already exists (idempotent)
                fill_exists = Fill.objects.filter(
                    order=order,
                    external_fill_id=fill_id
                ).exists()
                
                if not fill_exists:
                    # Create new Fill record
                    fill = Fill.objects.create(
                        order=order,
                        external_fill_id=fill_id,
                        size=fill_size,
                        price=fill_price
                    )
                    logger.info(f"Created Fill {fill.id} for Order {order.id}: {fill_size}@{fill_price}")
                else:
                    logger.info(f"Fill {fill_id} already exists for Order {order.id}, skipping")
            
            # Update order status to FILLED if all shares filled
            total_filled = Fill.objects.filter(order=order).aggregate(
                total=models.Sum('size')
            )['total'] or Decimal('0')
            
            if total_filled >= order.size:
                order.status = 'FILLED'
            elif total_filled > 0:
                order.status = 'OPEN'  # Partial fill
            
            order.save()
            logger.info(f"Updated Order {order.id} status to {order.status} (filled: {total_filled}/{order.size})")
            
            # Update Position from all fills
            svc = TradingService()
            svc._update_position_from_fills(order.user, order.market, order)
            
            return Response({
                'success': True,
                'order_id': order.id,
                'status': order.status,
                'fills_processed': len(fills_list),
                'total_filled': float(total_filled),
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Webhook processing failed: {e}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PolymarketResolutionWebhookView(APIView):
    """
    Webhook endpoint to receive Polymarket market resolution notifications.
    
    When a Polymarket market resolves (outcome determined), Polymarket can send
    a webhook to this endpoint. We then:
    1. Update the local market record with resolution outcome
    2. Trigger settlement task to calculate and process payouts
    
    Webhook should be configured in Polymarket CLOB settings to POST to:
    /api/brokerage/webhooks/polymarket-resolution/
    """
    permission_classes = [permissions.AllowAny]  # Webhooks are typically unauthenticated
    
    def post(self, request):
        """
        Handle incoming resolution notification from Polymarket.
        
        Expected payload:
        {
            "event": "market_resolved",
            "market_id": "0xmkt123...",
            "token_ids": ["61919"],
            "outcome": "Yes",
            "resolved_at": 1686234567,
            "resolution_price": 0.75
        }
        """
        try:
            webhook_data = request.data
            market_id = webhook_data.get('market_id')
            outcome = webhook_data.get('outcome')
            event_type = webhook_data.get('event', 'market_resolved')
            
            if not market_id or not outcome:
                logger.warning(f"Invalid resolution webhook: missing market_id or outcome")
                return Response(
                    {'error': 'Missing market_id or outcome'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            logger.info(f"Received Polymarket resolution webhook for market {market_id}: {outcome}")
            
            # Find the local Market by external_id
            from brokerage.models import Market
            from decimal import Decimal
            
            try:
                market = Market.objects.get(external_id=str(market_id), source='polymarket')
            except Market.DoesNotExist:
                logger.error(f"No local Market found for Polymarket market_id {market_id}")
                return Response(
                    {'error': f'Market {market_id} not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Update market with resolution data
            market.polymarket_status = 'RESOLVED'
            market.resolution_outcome = outcome
            
            # Extract resolution price if available
            if 'resolution_price' in webhook_data:
                market.resolution_price = Decimal(str(webhook_data['resolution_price']))
            
            # Set resolution timestamp
            if 'resolved_at' in webhook_data:
                from datetime import datetime
                ts = webhook_data['resolved_at']
                market.resolved_at = datetime.fromtimestamp(ts)
            else:
                market.resolved_at = timezone.now()
            
            market.save()
            logger.info(f"Updated Market {market.id} with resolution: {outcome}")
            
            # Trigger settlement task
            from brokerage.tasks import settle_polymarket_market
            task = settle_polymarket_market.delay(market.id)
            
            return Response({
                'success': True,
                'market_id': market.id,
                'polymarket_id': market_id,
                'outcome': outcome,
                'settlement_task_id': task.id
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Resolution webhook processing failed: {e}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

