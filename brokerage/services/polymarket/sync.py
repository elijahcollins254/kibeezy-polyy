from typing import Any, Dict, List, Optional

from django.db import transaction

from brokerage.models import Market
from brokerage.utils.category import extract_category, extract_subcategory


def _coerce_bool(value: Any) -> bool:
    return bool(value)


def _is_category_match(market_data: Dict[str, Any], category: Optional[str]) -> bool:
    if not category:
        return True
    normalized = str(category).strip().lower()
    if normalized == 'all':
        return True
    candidate = (market_data.get('category') or '')
    if str(candidate).strip().lower() == normalized:
        return True
    return extract_category(market_data).lower() == normalized


def fetch_polymarket_market_candidates(markets: List[Dict[str, Any]], limit: int = 50, category: Optional[str] = None) -> List[Dict[str, Any]]:
    candidates = []
    for market in markets:
        if _is_category_match(market, category):
            candidates.append(market)
            if len(candidates) >= limit:
                break
    return candidates


@transaction.atomic
def sync_polymarket_markets(markets: List[Dict[str, Any]], limit: int = 50, category: Optional[str] = None, approve: bool = False, selected_external_ids: Optional[List[str]] = None) -> int:
    candidates = fetch_polymarket_market_candidates(markets, limit=limit, category=category)
    selected_external_ids = set(selected_external_ids or [])

    created_count = 0
    for market in candidates:
        external_id = market.get('id') or market.get('market_id') or market.get('token')
        if not external_id:
            continue

        selected = not selected_external_ids or str(external_id) in selected_external_ids
        if not selected:
            continue

        category_value = extract_category(market)
        subcategory_value = extract_subcategory(market, category_value)
        approval_value = _coerce_bool(approve and selected)

        obj, created = Market.objects.update_or_create(
            external_id=str(external_id),
            defaults={
                'title': market.get('title') or market.get('name') or str(external_id),
                'question': market.get('question') or market.get('title') or market.get('name') or '',
                'description': market.get('description') or '',
                'category': category_value,
                'subcategory': subcategory_value,
                'source': 'polymarket',
                'metadata': market,
                'is_approved': approval_value,
            },
        )
        if created:
            created_count += 1
        if approval_value:
            obj.is_approved = True
            obj.save(update_fields=['is_approved', 'approved_at'])

    return created_count
