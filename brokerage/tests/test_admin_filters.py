from django.test import RequestFactory, TestCase
from django.utils import timezone

from brokerage.admin import MarketResolutionStatusFilter
from brokerage.models import Market


class MarketResolutionStatusFilterTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_resolved_filter_matches_markets_with_resolution_outcome_or_resolved_at(self):
        resolved_market = Market.objects.create(
            external_id='RESOLVED-1',
            title='Resolved market',
            source='polymarket',
            resolution_outcome='Yes',
            resolved_at=timezone.now(),
        )
        Market.objects.create(
            external_id='ACTIVE-1',
            title='Active market',
            source='polymarket',
        )

        request = self.factory.get('/')
        filter_instance = MarketResolutionStatusFilter(request, {'resolution_status': 'resolved'}, Market, None)
        queryset = filter_instance.queryset(request, Market.objects.all())

        self.assertEqual(list(queryset), [resolved_market])

    def test_closed_filter_matches_markets_marked_closed_in_metadata(self):
        closed_market = Market.objects.create(
            external_id='CLOSED-1',
            title='Closed market',
            source='polymarket',
            metadata={'is_closed': True},
        )
        Market.objects.create(
            external_id='ACTIVE-2',
            title='Active market',
            source='polymarket',
        )

        request = self.factory.get('/')
        filter_instance = MarketResolutionStatusFilter(request, {'resolution_status': 'closed'}, Market, None)
        queryset = filter_instance.queryset(request, Market.objects.all())

        self.assertEqual(list(queryset), [closed_market])
