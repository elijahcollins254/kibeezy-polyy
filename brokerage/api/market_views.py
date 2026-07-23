from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from django.shortcuts import get_object_or_404
from django.db import models
from django.contrib.auth import get_user_model
from decimal import Decimal
import logging
import json
import uuid

from brokerage.models import Market, ChatMessage, Order, Position
from brokerage.api.market_serializers import MarketSerializer
from brokerage.services.polymarket.adapter import PolymarketAdapter
from brokerage.services.polymarket.sync import fetch_polymarket_market_candidates, sync_polymarket_markets
from brokerage.utils.category import extract_category, extract_subcategory
from django.core.cache import cache
from django.utils import timezone
from brokerage.publish import publish_market_event

logger = logging.getLogger(__name__)


def _parse_clob_token_ids(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            return []
    return []


def _get_clob_token_id(market, outcome='Yes', token_id=None):
    if token_id:
        return str(token_id)

    if not market or not market.metadata:
        return None

    token_ids = _parse_clob_token_ids(
        market.metadata.get('clobTokenIds') or market.metadata.get('clob_token_ids')
    )
    if not token_ids:
        return None

    outcome_index = 0 if str(outcome).lower() in ('yes', 'true', '0') else 1
    if outcome_index >= len(token_ids):
        return None
    return str(token_ids[outcome_index])


def _price_history_params(period):
    period = (period or '1D').upper()
    mapping = {
        '1H': {'interval': '1h', 'fidelity': 1},
        '6H': {'interval': '6h', 'fidelity': 5},
        '1D': {'interval': '1d', 'fidelity': 15},
        '1W': {'interval': '1w', 'fidelity': 60},
        '1M': {'interval': '1m', 'fidelity': 240},
        'ALL': {'interval': 'max', 'fidelity': 1440},
    }
    return mapping.get(period, mapping['1D'])


def _is_active_polymarket_listing(market):
    if not isinstance(market, dict):
        return True

    status = str(market.get('status') or market.get('market_status') or '').upper()
    if status in {'CLOSED', 'RESOLVED', 'INVALID', 'ENDED', 'SETTLED'}:
        return False

    if market.get('is_resolved') is True or market.get('resolved') is True:
        return False

    if market.get('is_closed') is True:
        return False

    return True


class MarketAvailabilityView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, market_id):
        return Response({
            'market_id': market_id,
            'available_shares': [],
            'message': 'availability_data_not_available',
        }, status=status.HTTP_200_OK)


class LiquidityCompatibilityView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        path = request.path
        if path.endswith('/liquidity/positions/'):
            return Response({'positions': [], 'count': 0}, status=status.HTTP_200_OK)
        if path.endswith('/liquidity/analytics/'):
            return Response({'analytics': [], 'lp_provider_id': request.query_params.get('lp_provider_id')}, status=status.HTTP_200_OK)
        if path.endswith('/liquidity/fee-analytics/'):
            return Response({'fee_analytics': []}, status=status.HTTP_200_OK)
        if path.endswith('/liquidity/pool-stats/'):
            return Response({'pool_stats': {}}, status=status.HTTP_200_OK)
        if path.endswith('/liquidity/risk-score/'):
            return Response({'risk_score': 0, 'market_id': request.query_params.get('market_id')}, status=status.HTTP_200_OK)
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)

    def post(self, request):
        path = request.path
        if path.endswith('/liquidity/deposit/') or path.endswith('/liquidity/withdraw/') or path.endswith('/add-liquidity/'):
            return Response({'status': 'ok', 'message': 'request_received'}, status=status.HTTP_200_OK)
        if path.endswith('/liquidity/claim-fees/'):
            return Response({'status': 'ok', 'message': 'fees_claimed'}, status=status.HTTP_200_OK)
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


class MarketListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        # Support search via query param `q` which will proxy to Polymarket Data/Gamma
        q = request.query_params.get('q')
        limit = int(request.query_params.get('limit', 500))
        offset = int(request.query_params.get('offset', 0))
        limit = min(limit, 1000)  # Cap at 1000 per request
        adapter = PolymarketAdapter()
        
        # If search query provided, fetch from our database first, then fallback to Polymarket API
        if q:
            try:
                # First try searching in our database for approved markets
                qs = Market.objects.filter(
                    is_approved=True,
                    source__in=['local', 'polymarket']
                ).filter(
                    models.Q(title__icontains=q) | 
                    models.Q(question__icontains=q) | 
                    models.Q(category__icontains=q) |
                    models.Q(subcategory__icontains=q)
                ).exclude(
                    models.Q(source='polymarket', polymarket_status__in=['CLOSED', 'RESOLVED', 'INVALID']) |
                    models.Q(source='polymarket', resolved_at__isnull=False)
                ).order_by('-created_at')
                
                total = qs.count()
                qs = qs[offset:offset + limit]
                
                if qs.exists():
                    out = MarketSerializer(qs, many=True)
                    response = Response({
                        'results': out.data,
                        'count': total,
                        'limit': limit,
                        'offset': offset,
                        'next': offset + limit if offset + limit < total else None,
                        'previous': offset - limit if offset > 0 else None
                    })
                else:
                    # Fallback to Polymarket API if not in database
                    params = {'q': q, 'limit': min(1000, limit)}
                    markets = adapter.get_markets(params=params)
                    # Add category extraction to raw Polymarket markets
                    if isinstance(markets, list):
                        markets = [market for market in markets if _is_active_polymarket_listing(market)]
                        for market in markets:
                            if 'category' not in market or market['category'] == 'Other':
                                market['category'] = extract_category(market)
                            if not market.get('subcategory'):
                                market['subcategory'] = extract_subcategory(market, market.get('category'))
                            market['category_slug'] = market.get('category_slug') or market['category'].lower().replace(' ', '-')
                            market['subcategory_slug'] = market.get('subcategory_slug') or (market['subcategory'].lower().replace(' ', '-') if market.get('subcategory') else '')
                    response = Response({
                        'results': markets,
                        'count': len(markets) if isinstance(markets, list) else 0,
                        'limit': limit,
                        'offset': offset,
                        'next': None,
                        'previous': None
                    })
            except Exception as e:
                logger.warning(f"Failed to search markets: {str(e)}")
                response = Response([], status=status.HTTP_200_OK)
        else:
            # By default, fetch approved Polymarket markets from our database (which have categories)
            try:
                qs = Market.objects.filter(
                    is_approved=True,
                    source__in=['local', 'polymarket']
                ).exclude(
                    models.Q(source='polymarket', polymarket_status__in=['CLOSED', 'RESOLVED', 'INVALID']) |
                    models.Q(source='polymarket', resolved_at__isnull=False)
                ).order_by('-created_at')
                
                total = qs.count()
                qs = qs[offset:offset + limit]
                
                if qs.exists():
                    out = MarketSerializer(qs, many=True)
                    response = Response({
                        'results': out.data,
                        'count': total,
                        'limit': limit,
                        'offset': offset,
                        'next': offset + limit if offset + limit < total else None,
                        'previous': offset - limit if offset > 0 else None
                    })
                else:
                    # Fallback to Polymarket API if no approved markets in database
                    polymarkets = adapter.get_markets(params={'limit': min(1000, limit)})
                    # Add category extraction to raw Polymarket markets
                    if isinstance(polymarkets, list):
                        polymarkets = [market for market in polymarkets if _is_active_polymarket_listing(market)]
                        for market in polymarkets:
                            if 'category' not in market or market['category'] == 'Other':
                                market['category'] = extract_category(market)
                            if not market.get('subcategory'):
                                market['subcategory'] = extract_subcategory(market, market.get('category'))
                            market['category_slug'] = market.get('category_slug') or market['category'].lower().replace(' ', '-')
                            market['subcategory_slug'] = market.get('subcategory_slug') or (market['subcategory'].lower().replace(' ', '-') if market.get('subcategory') else '')
                    logger.info(f"Successfully fetched {len(polymarkets) if isinstance(polymarkets, list) else 1} Polymarket markets from API")
                    response = Response({
                        'results': polymarkets,
                        'count': len(polymarkets) if isinstance(polymarkets, list) else 0,
                        'limit': limit,
                        'offset': offset,
                        'next': None,
                        'previous': None
                    })
            except Exception as e:
                logger.error(f"Failed to fetch Polymarket markets: {str(e)}", exc_info=True)
                response = Response([], status=status.HTTP_200_OK)
        
        # Disable caching for live market data
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response


class AllMarketsView(APIView):
    """Returns ALL markets (approved or not) - for debugging only."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        try:
            limit = int(request.query_params.get('limit', 500))
            offset = int(request.query_params.get('offset', 0))
            limit = min(limit, 1000)  # Cap at 1000
            
            # Return all markets with count breakdown
            all_count = Market.objects.count()
            approved_count = Market.objects.filter(is_approved=True).count()
            polymarket_count = Market.objects.filter(source='polymarket').count()
            approved_poly_count = Market.objects.filter(is_approved=True, source='polymarket').count()
            
            qs = Market.objects.all().order_by('-created_at')
            total = qs.count()
            qs = qs[offset:offset + limit]
            out = MarketSerializer(qs, many=True)
            
            response = Response({
                'debug_info': {
                    'total_markets': all_count,
                    'approved_markets': approved_count,
                    'polymarket_markets': polymarket_count,
                    'approved_polymarket_markets': approved_poly_count,
                },
                'markets': out.data,
                'count': total,
                'limit': limit,
                'offset': offset,
                'next': offset + limit if offset + limit < total else None,
                'previous': offset - limit if offset > 0 else None
            })
        except Exception as e:
            logger.error(f"Failed to fetch all markets: {str(e)}", exc_info=True)
            response = Response({'error': str(e), 'markets': []}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response


class DebugMarketsView(APIView):
    """Returns diagnostic info about the database connection and market records."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        try:
            from django.db import connection
            
            # Try to get DB info
            db_config = connection.settings_dict
            db_name = db_config.get('NAME', 'unknown')
            db_host = db_config.get('HOST', 'unknown')
            
            # Count records in each state
            stats = {
                'database': {
                    'name': db_name,
                    'host': db_host,
                    'engine': db_config.get('ENGINE', 'unknown'),
                },
                'market_counts': {
                    'total': Market.objects.count(),
                    'approved': Market.objects.filter(is_approved=True).count(),
                    'not_approved': Market.objects.filter(is_approved=False).count(),
                    'source_polymarket': Market.objects.filter(source='polymarket').count(),
                    'source_local': Market.objects.filter(source='local').count(),
                    'approved_and_polymarket': Market.objects.filter(is_approved=True, source='polymarket').count(),
                },
                'sample_markets': {
                    'approved_polymarket': list(
                        Market.objects.filter(is_approved=True, source='polymarket')
                        .values('id', 'external_id', 'title', 'is_approved', 'source')[:5]
                    ),
                    'not_approved_polymarket': list(
                        Market.objects.filter(is_approved=False, source='polymarket')
                        .values('id', 'external_id', 'title', 'is_approved', 'source')[:5]
                    ),
                },
            }
            response = Response(stats)
        except Exception as e:
            logger.error(f"Debug view error: {str(e)}", exc_info=True)
            response = Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response


def _get_latest_price_from_orderbook(orderbook):
    if not isinstance(orderbook, dict):
        return None

    for key in ('mid', 'midpoint', 'bestBid', 'best_bid', 'last_trade_price'):
        value = orderbook.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue

    bids = orderbook.get('bids') or []
    if isinstance(bids, list) and bids:
        first = bids[0]
        if isinstance(first, dict):
            value = first.get('price')
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass

    return None


class MarketLatestPriceView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, external_id):
        adapter = PolymarketAdapter()
        market = None

        try:
            market = Market.objects.get(external_id=external_id)
        except Market.DoesNotExist:
            market = None

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

        price = _get_latest_price_from_orderbook(orderbook)
        if price is None or price <= 0:
            try:
                price = float(adapter.get_midpoint(external_id))
            except Exception:
                price = None

        if price is None or price <= 0:
            if market and getattr(market, 'yes_probability', None) is not None:
                price = float(market.yes_probability) / 100.0
            else:
                price = 0.5

        data = MarketSerializer(market).data if market else {'external_id': external_id}
        data['price'] = price
        data['yes_probability'] = int(round(price * 100))
        data['orderbook'] = orderbook
        return Response(data)


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

        # Price history endpoint (CLOB token history; returns chart-ready points)
        if request.path.endswith('/price-history/'):
            try:
                outcome = request.query_params.get('outcome', 'Yes')
                token_id = _get_clob_token_id(
                    market,
                    outcome=outcome,
                    token_id=request.query_params.get('token_id'),
                )

                if not token_id:
                    return Response(
                        {'error': 'missing_clob_token_id', 'history': []},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                params = _price_history_params(request.query_params.get('period'))
                price_history = adapter.get_price_history(token_id, params=params)
                response = Response(
                    {
                        'token_id': token_id,
                        'outcome': outcome,
                        'period': request.query_params.get('period', '1D'),
                        **price_history,
                    },
                    status=status.HTTP_200_OK,
                )
                response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                response['Pragma'] = 'no-cache'
                response['Expires'] = '0'
                return response
            except Exception as e:
                logger.error(f"Failed to fetch price history for {external_id}: {str(e)}", exc_info=True)
                response = Response({'history': []}, status=status.HTTP_200_OK)
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


def _serialize_market_for_admin(market):
    if not market:
        return None

    metadata = getattr(market, 'metadata', None) or {}
    yes_probability = metadata.get('yes_probability')
    if yes_probability is None:
        yes_probability = 50
    try:
        yes_probability = float(yes_probability)
    except (TypeError, ValueError):
        yes_probability = 50.0

    status = getattr(market, 'polymarket_status', None) or ('RESOLVED' if getattr(market, 'resolution_outcome', None) else 'OPEN')
    return {
        'id': market.id,
        'external_id': market.external_id,
        'question': market.question or market.title,
        'title': market.title,
        'category': market.category or 'Other',
        'description': market.description or '',
        'status': status,
        'created_at': market.created_at.isoformat() if market.created_at else None,
        'end_date': market.resolved_at.isoformat() if market.resolved_at else None,
        'yes_probability': round(yes_probability * 100, 2),
        'resolved_outcome': market.resolution_outcome,
        'resolved_at': market.resolved_at.isoformat() if market.resolved_at else None,
        'source': market.source,
        'is_approved': market.is_approved,
        'total_wagered': '0.00',
    }


class AdminMarketListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        markets = Market.objects.order_by('-created_at')[:200]
        return Response({'markets': [_serialize_market_for_admin(m) for m in markets], 'count': markets.count()})


class AdminMarketCreateView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        payload = request.data or {}
        question = (payload.get('question') or '').strip()
        if not question:
            return Response({'error': 'question_required'}, status=status.HTTP_400_BAD_REQUEST)

        market = Market.objects.create(
            external_id=payload.get('external_id') or f"local-{uuid.uuid4().hex[:10]}",
            title=question,
            question=question,
            description=(payload.get('description') or '').strip(),
            category=(payload.get('category') or 'Other').strip() or 'Other',
            source='local',
            is_approved=bool(payload.get('is_approved', True)),
            metadata=payload.get('metadata') or {},
        )
        return Response({'market': _serialize_market_for_admin(market)}, status=status.HTTP_201_CREATED)


class AdminMarketResolveView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        payload = request.data or {}
        market_id = payload.get('market_id')
        outcome = (payload.get('outcome') or '').strip()
        if not market_id:
            return Response({'error': 'market_id_required'}, status=status.HTTP_400_BAD_REQUEST)

        market = Market.objects.filter(id=market_id).first() or Market.objects.filter(external_id=market_id).first()
        if not market:
            return Response({'error': 'market_not_found'}, status=status.HTTP_404_NOT_FOUND)

        market.resolution_outcome = outcome or market.resolution_outcome
        market.resolution = outcome or market.resolution
        market.polymarket_status = 'RESOLVED'
        market.resolved_at = market.resolved_at or timezone.now()
        market.save(update_fields=['resolution_outcome', 'resolution', 'polymarket_status', 'resolved_at'])
        return Response({'market': _serialize_market_for_admin(market)})


class AdminMarketDetailView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def delete(self, request, market_id):
        market = Market.objects.filter(id=market_id).first() or Market.objects.filter(external_id=market_id).first()
        if not market:
            return Response({'error': 'market_not_found'}, status=status.HTTP_404_NOT_FOUND)

        market.delete()
        return Response({'deleted': True})


class AdminMarketPositionsView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, market_id):
        market = Market.objects.filter(id=market_id).first() or Market.objects.filter(external_id=market_id).first()
        if not market:
            return Response({'error': 'market_not_found'}, status=status.HTTP_404_NOT_FOUND)

        positions = Position.objects.filter(market=market).select_related('user').order_by('-quantity')
        payload = []
        for position in positions:
            payload.append({
                'user_id': position.user_id,
                'username': getattr(position.user, 'username', '') or getattr(position.user, 'full_name', ''),
                'email': getattr(position.user, 'email', '') or '',
                'yes_amount': 0,
                'no_amount': 0,
                'total_amount': float(position.quantity or 0),
                'yes_shares': float(position.quantity or 0),
                'no_shares': 0,
                'potential_winnings': float(position.quantity or 0),
            })
        return Response({'positions': payload})


class AdminMarketActivityView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, market_id):
        market = Market.objects.filter(id=market_id).first() or Market.objects.filter(external_id=market_id).first()
        if not market:
            return Response({'error': 'market_not_found'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'activity': []})


class AdminAnalyticsView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        return Response({
            'metrics': {
                'active_users_30d': 0,
                'open_markets': Market.objects.filter(is_approved=True).count(),
            },
            'daily_volume': [],
        })


class AdminRiskView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        return Response({'risk_summary': {'total_exposure': 0, 'high_risk_markets': []}})


class AdminBulkDeleteView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        ids = request.data.get('market_ids') or []
        deleted_count = Market.objects.filter(id__in=ids).delete()[0]
        return Response({'deleted_count': deleted_count})


class PolymarketSyncPreviewView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        category = (request.query_params.get('category') or 'all').strip() or 'all'
        limit = int(request.query_params.get('limit') or 20)
        adapter = PolymarketAdapter()

        try:
            markets = adapter.get_markets(params={
                'limit': max(limit, 1),
                'offset': 0,
                'active': True,
                'closed': False,
                'order': 'volume',
                'ascending': False,
            }) or []
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        candidates = fetch_polymarket_market_candidates(markets, limit=limit, category=category)
        enriched = []
        for market in candidates:
            external_id = market.get('id') or market.get('market_id') or market.get('token')
            existing = None
            if external_id:
                existing = Market.objects.filter(external_id=str(external_id)).first()
            enriched.append({
                'external_id': str(external_id) if external_id else None,
                'title': market.get('title') or market.get('name') or '',
                'question': market.get('question') or market.get('title') or market.get('name') or '',
                'category': extract_category(market),
                'subcategory': extract_subcategory(market, extract_category(market)),
                'source': 'polymarket',
                'already_exists': existing is not None,
                'is_approved': bool(existing and existing.is_approved) if existing else False,
            })

        return Response({
            'category': category,
            'limit': limit,
            'count': len(enriched),
            'markets': enriched,
        })


class PolymarketSyncImportView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        payload = request.data or {}
        category = (payload.get('category') or 'all').strip() or 'all'
        limit = int(payload.get('limit') or 20)
        approve = bool(payload.get('approve', False))
        selected_external_ids = payload.get('selected_external_ids') or []

        adapter = PolymarketAdapter()
        try:
            markets = adapter.get_markets(params={
                'limit': max(limit, 1),
                'offset': 0,
                'active': True,
                'closed': False,
                'order': 'volume',
                'ascending': False,
            }) or []
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        created_count = sync_polymarket_markets(
            markets,
            limit=limit,
            category=category,
            approve=approve,
            selected_external_ids=[str(item) for item in selected_external_ids],
        )

        return Response({
            'category': category,
            'limit': limit,
            'approve': approve,
            'created_count': created_count,
            'selected_count': len(selected_external_ids or []),
        })


class PolymarketSyncRunView(APIView):
    """Admin endpoint to trigger the background/full Polymarket sync (management command or Celery task)."""
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        payload = request.data or {}
        limit = int(payload.get('limit') or 500)
        only_sports = bool(payload.get('only_sports', False))

        # Try to enqueue Celery task if available
        try:
            from brokerage.tasks import sync_polymarket_markets_task
            try:
                result = sync_polymarket_markets_task.delay(limit=limit, only_sports=only_sports)
                return Response({'status': 'queued', 'task_id': getattr(result, 'id', None)}, status=status.HTTP_202_ACCEPTED)
            except Exception:
                # Fall back to synchronous call
                pass
        except Exception:
            # Celery not available or import failed; fall back
            pass

        # Fallback: call the management command synchronously
        try:
            from django.core.management import call_command
            args = ['--limit', str(limit)]
            if only_sports:
                args.append('--only-sports')
            call_command('sync_polymarket_markets', *args)
            return Response({'status': 'completed', 'limit': limit, 'only_sports': only_sports}, status=status.HTTP_200_OK)
        except Exception as exc:
            logger.exception('Failed to run sync_polymarket_markets')
            return Response({'status': 'error', 'error': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LegacyMarketDetailsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, market_id):
        market = None
        if market_id and str(market_id).isdigit():
            market = Market.objects.filter(id=market_id).first()
        if not market:
            market = Market.objects.filter(external_id=market_id).first()
        if not market:
            market = Market.objects.filter(question__icontains=market_id).first()

        if not market:
            return Response({'error': 'market_not_found'}, status=status.HTTP_404_NOT_FOUND)

        comments = ChatMessage.objects.filter(market=market).select_related('user', 'parent').order_by('created_at')
        data = {
            'id': market.id,
            'external_id': market.external_id,
            'title': market.title,
            'question': market.question,
            'description': market.description,
            'comments': [
                {
                    'id': comment.id,
                    'message': comment.message,
                    'parent_id': comment.parent_id,
                    'user_id': comment.user_id,
                    'user_name': getattr(comment.user, 'full_name', None) or getattr(comment.user, 'username', None) or 'User',
                    'created_at': comment.created_at.isoformat() if comment.created_at else None,
                }
                for comment in comments
            ],
            'positions': [],
            'top_holders': {'yes': [], 'no': []},
            'activity': [],
        }
        return Response(data)


class LegacyMarketChatView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, market_id):
        market = Market.objects.filter(id=market_id).first() or Market.objects.filter(external_id=market_id).first()
        if not market:
            return Response({'error': 'market_not_found'}, status=status.HTTP_404_NOT_FOUND)

        comments = ChatMessage.objects.filter(market=market).select_related('user', 'parent').order_by('created_at')
        return Response({'comments': [
            {
                'id': comment.id,
                'message': comment.message,
                'parent_id': comment.parent_id,
                'user_id': comment.user_id,
                'user_name': getattr(comment.user, 'full_name', None) or getattr(comment.user, 'username', None) or 'User',
                'created_at': comment.created_at.isoformat() if comment.created_at else None,
            }
            for comment in comments
        ]})

    def post(self, request, market_id):
        market = Market.objects.filter(id=market_id).first() or Market.objects.filter(external_id=market_id).first()
        if not market:
            return Response({'error': 'market_not_found'}, status=status.HTTP_404_NOT_FOUND)

        payload = request.data or {}
        message = (payload.get('message') or '').strip()
        if not message:
            return Response({'error': 'message_required'}, status=status.HTTP_400_BAD_REQUEST)

        parent_id = payload.get('reply_to')
        parent = None
        if parent_id:
            parent = ChatMessage.objects.filter(id=parent_id, market=market).first()

        comment = ChatMessage.objects.create(user=request.user, market=market, parent=parent, message=message)
        return Response({'message': {
            'id': comment.id,
            'message': comment.message,
            'parent_id': comment.parent_id,
            'user_id': comment.user_id,
            'user_name': getattr(comment.user, 'full_name', None) or getattr(comment.user, 'username', None) or 'User',
            'created_at': comment.created_at.isoformat() if comment.created_at else None,
        }})


class LegacyBitcoinMarketView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        market = Market.objects.filter(question__icontains='bitcoin').order_by('-created_at').first()
        if not market:
            return Response({
                'id': 'bitcoin',
                'external_id': 'bitcoin',
                'title': 'Bitcoin',
                'question': 'Will Bitcoin reach $100,000?',
                'description': 'Bitcoin market',
                'category': 'Crypto',
                'source': 'local',
                'metadata': {},
            })
        return Response(MarketSerializer(market).data)


class LegacyBitcoinPriceView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        market = Market.objects.filter(question__icontains='bitcoin').order_by('-created_at').first()
        current_price = 100000
        if market and market.metadata:
            current_price = market.metadata.get('current_price', current_price)
        return Response({'current_price': current_price})


class LegacyBetView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        payload = request.data or {}
        market_id = payload.get('market_id')
        market = None
        if market_id and str(market_id).isdigit():
            market = Market.objects.filter(id=market_id).first()
        if not market:
            market = Market.objects.filter(external_id=market_id).first()
        if not market:
            return Response({'error': 'market_not_found'}, status=status.HTTP_404_NOT_FOUND)

        action = (payload.get('action') or 'buy').lower()
        outcome = payload.get('outcome') or 'Yes'
        amount = Decimal(str(payload.get('amount') or 1))
        limit_price = Decimal(str(payload.get('limit_price') or 50))

        side = 'BUY' if action != 'sell' else 'SELL'
        order = Order.objects.create(
            user=request.user,
            market=market,
            side=side,
            size=amount,
            price=limit_price,
            status='FILLED',
        )
        Position.objects.get_or_create(
            user=request.user,
            market=market,
            defaults={'quantity': amount, 'average_price': limit_price},
        )
        return Response({'ok': True, 'order_id': order.id, 'outcome': outcome, 'action': action})
