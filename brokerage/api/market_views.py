from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from django.shortcuts import get_object_or_404
from django.db import models
import logging

from brokerage.models import Market
from brokerage.api.market_serializers import MarketSerializer
from brokerage.services.polymarket.adapter import PolymarketAdapter
from django.core.cache import cache
from brokerage.publish import publish_market_event

logger = logging.getLogger(__name__)


class MarketListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        # Support search via query param `q` which will proxy to Polymarket Data/Gamma
        q = request.query_params.get('q')
        adapter = PolymarketAdapter()
        
        # If search query provided, fetch from our database first, then fallback to Polymarket API
        if q:
            try:
                # First try searching in our database for approved markets
                qs = Market.objects.filter(
                    is_approved=True,
                    source='polymarket'
                ).filter(
                    models.Q(title__icontains=q) | 
                    models.Q(question__icontains=q) | 
                    models.Q(category__icontains=q)
                ).order_by('-created_at')[:100]
                
                if qs.exists():
                    out = MarketSerializer(qs, many=True)
                    response = Response(out.data)
                else:
                    # Fallback to Polymarket API if not in database
                    params = {'q': q, 'limit': 100}
                    markets = adapter.get_markets(params=params)
                    response = Response(markets)
            except Exception as e:
                logger.warning(f"Failed to search markets: {str(e)}")
                response = Response([], status=status.HTTP_200_OK)
        else:
            # By default, fetch approved Polymarket markets from our database (which have categories)
            try:
                qs = Market.objects.filter(
                    is_approved=True,
                    source='polymarket'
                ).order_by('-created_at')[:500]
                
                if qs.exists():
                    out = MarketSerializer(qs, many=True)
                    response = Response(out.data)
                else:
                    # Fallback to Polymarket API if no approved markets in database
                    polymarkets = adapter.get_markets(params={'limit': 100})
                    logger.info(f"Successfully fetched {len(polymarkets) if isinstance(polymarkets, list) else 1} Polymarket markets from API")
                    response = Response(polymarkets)
            except Exception as e:
                logger.error(f"Failed to fetch Polymarket markets: {str(e)}", exc_info=True)
                response = Response([], status=status.HTTP_200_OK)
        
        # Disable caching for live market data
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response


class MarketDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, external_id):
        # Determine which data the caller wants via query path
        # - default: return market metadata + orderbook (CLOB)
        # - if path ends with /trades/ -> return trade history (Data API)
        # - if path ends with /positions/ -> return user positions (Data API, auth required)

        adapter = PolymarketAdapter()

        # If market exists locally, use it; otherwise still allow fetching remote metadata
        try:
            market = Market.objects.get(external_id=external_id)
            local_market = True
        except Market.DoesNotExist:
            market = None
            local_market = False

        # Trades endpoint
        if request.path.endswith('/trades/'):
            try:
                trades = adapter.get_trade_history(external_id, limit=int(request.query_params.get('limit', 100)))
                response = Response(trades, status=status.HTTP_200_OK)
                # Disable caching for live trade data
                response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                response['Pragma'] = 'no-cache'
                response['Expires'] = '0'
                return response
            except Exception as e:
                logger.error(f"Failed to fetch trade history for {external_id}: {str(e)}", exc_info=True)
                # Return empty trades list as fallback instead of error
                response = Response([], status=status.HTTP_200_OK)
                response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                return response

        # Positions endpoint (requires authentication)
        if request.path.endswith('/positions/'):
            if not request.user or not request.user.is_authenticated:
                return Response({'error': 'authentication_required'}, status=status.HTTP_401_UNAUTHORIZED)
            try:
                # account_id mapping may vary; use user's address or internal account id
                account_id = getattr(request.user, 'eth_address', None) or getattr(request.user, 'wallet_address', None) or str(request.user.id)
                positions = adapter.get_positions(account_id)
                return Response(positions)
            except Exception:
                return Response({'error': 'failed_fetch_positions'}, status=status.HTTP_502_BAD_GATEWAY)

        # Default: market metadata + orderbook
        cache_key = f"orderbook:{external_id}"
        orderbook = cache.get(cache_key)
        if orderbook is None:
            try:
                orderbook = adapter.get_orderbook(external_id)
            except Exception:
                orderbook = {}
            try:
                cache.set(cache_key, orderbook, timeout=5)
            except Exception:
                pass

        try:
            publish_market_event(external_id, {'type': 'orderbook_snapshot', 'orderbook': orderbook})
        except Exception:
            pass

        data = MarketSerializer(market).data if local_market else {'external_id': external_id, 'title': external_id}
        data['orderbook'] = orderbook
        return Response(data)
