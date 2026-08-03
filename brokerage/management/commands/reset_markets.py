from django.core.management.base import BaseCommand

from brokerage.models import Fill, Market, MarketCategory, MarketSubcategory, Order, Position


class Command(BaseCommand):
    help = 'Delete market-related records from the database'

    def handle(self, *args, **options):
        market_count = Market.objects.count()
        position_count = Position.objects.count()
        order_count = Order.objects.count()
        fill_count = Fill.objects.count()
        category_count = MarketCategory.objects.count()
        subcategory_count = MarketSubcategory.objects.count()

        Fill.objects.all().delete()
        Order.objects.all().delete()
        Position.objects.all().delete()
        Market.objects.all().delete()
        MarketSubcategory.objects.all().delete()
        MarketCategory.objects.all().delete()

        self.stdout.write(self.style.SUCCESS(
            f'Deleted {market_count} market(s), {position_count} position(s), '
            f'{order_count} order(s), {fill_count} fill(s), {category_count} category(ies), '
            f'{subcategory_count} subcategory(ies).'
        ))
