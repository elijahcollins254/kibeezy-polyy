from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from brokerage.models import Position
from decimal import Decimal

User = get_user_model()

class Command(BaseCommand):
    help = 'Check user balance and portfolio positions'

    def add_arguments(self, parser):
        parser.add_argument('--phone', type=str, help='Phone number to check')
        parser.add_argument('--user-id', type=int, help='User ID to check')

    def handle(self, *args, **options):
        phone = options.get('phone')
        user_id = options.get('user_id')

        if not phone and not user_id:
            self.stdout.write(self.style.ERROR('Please provide --phone or --user-id'))
            return

        try:
            if user_id:
                user = User.objects.get(id=user_id)
            else:
                user = User.objects.get(phone_number=phone)

            self.stdout.write(f"\n===== USER: {user.phone_number} (ID: {user.id}) =====")
            self.stdout.write(f"Balance: KES {user.balance}")
            self.stdout.write(f"Full Name: {user.full_name}")
            self.stdout.write(f"Date Joined: {user.date_joined}")

            positions = Position.objects.filter(user=user).select_related('market')
            self.stdout.write(f"\nTotal Positions: {positions.count()}")

            if positions.exists():
                self.stdout.write("\n===== POSITIONS =====")
                for pos in positions:
                    avg_price = pos.average_price or Decimal('0')
                    qty = pos.quantity or Decimal('0')
                    amount = float(avg_price * qty)
                    realized = pos.realized_pnl or Decimal('0')
                    
                    self.stdout.write(f"\nPosition ID: {pos.id}")
                    self.stdout.write(f"  Market: {pos.market.question[:50] if pos.market else 'N/A'}")
                    self.stdout.write(f"  Market ID: {pos.market_id}")
                    self.stdout.write(f"  Quantity: {qty}")
                    self.stdout.write(f"  Average Price: {avg_price}")
                    self.stdout.write(f"  Amount Invested: KES {amount}")
                    self.stdout.write(f"  Realized P&L: KES {realized}")
                    self.stdout.write(f"  Updated: {pos.updated_at}")
            else:
                self.stdout.write(self.style.WARNING("\nNo positions found"))

            # Calculate expected portfolio value
            from brokerage.services.price import PAYOUT_PER_SHARE
            portfolio_total = 0
            for pos in positions:
                qty = float(pos.quantity or 0)
                # Assume 0.5 midpoint for calculation if we don't have actual price
                current_prob = 0.5
                current_value = qty * float(PAYOUT_PER_SHARE) * current_prob
                portfolio_total += current_value
            
            self.stdout.write(f"\n===== CALCULATION =====")
            self.stdout.write(f"Expected Portfolio Value (at 0.5 midpoint): KES {round(portfolio_total, 2)}")
            if portfolio_total == 0 and not positions.exists():
                self.stdout.write(self.style.SUCCESS("\n✓ Portfolio should be 0 (no positions)"))
            elif portfolio_total == 0 and positions.exists():
                self.stdout.write(self.style.WARNING("\n⚠ Portfolio is 0 but has positions (likely all zero quantity)"))
            else:
                self.stdout.write(f"\n⚠ Portfolio is {portfolio_total} KES")

        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User not found'))
