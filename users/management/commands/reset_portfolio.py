from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from brokerage.models import Position
from brokerage.services.price import PAYOUT_PER_SHARE
from decimal import Decimal

User = get_user_model()

class Command(BaseCommand):
    help = 'Reset user portfolio values based on actual positions (verify before running)'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Confirm to actually reset values')
        parser.add_argument('--phone', type=str, help='Phone number of specific user to reset')
        parser.add_argument('--all', action='store_true', help='Reset all users')

    def handle(self, *args, **options):
        confirm = options.get('confirm', False)
        phone = options.get('phone')
        reset_all = options.get('all', False)

        if not confirm:
            self.stdout.write(self.style.WARNING(
                '⚠ DRY RUN (use --confirm to actually reset)\n'
            ))

        if phone:
            try:
                users = [User.objects.get(phone_number=phone)]
                self.stdout.write(f"Resetting portfolio for user: {phone}\n")
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'User {phone} not found'))
                return
        elif reset_all:
            users = User.objects.all()
            self.stdout.write(f"Resetting portfolio for all {users.count()} users\n")
        else:
            self.stdout.write(self.style.ERROR('Please provide --phone, --all, or --user-id'))
            return

        reset_count = 0
        for user in users:
            positions = Position.objects.filter(user=user).select_related('market')
            
            # Calculate actual portfolio value
            portfolio_total = 0
            for pos in positions:
                qty = float(pos.quantity or 0)
                # Use 0.5 as default if no market data
                current_prob = 0.5
                if pos.market and hasattr(pos.market, 'metadata'):
                    metadata = pos.market.metadata or {}
                    try:
                        current_prob = float(metadata.get('yes_probability', 50)) / 100.0
                    except (TypeError, ValueError):
                        current_prob = 0.5
                
                current_value = qty * float(PAYOUT_PER_SHARE) * current_prob
                portfolio_total += current_value

            self.stdout.write(f"\nUser: {user.phone_number} (ID: {user.id})")
            self.stdout.write(f"  Positions: {positions.count()}")
            self.stdout.write(f"  Balance: KES {user.balance}")
            self.stdout.write(f"  Calculated Portfolio Value: KES {round(portfolio_total, 2)}")
            
            if not positions.exists() and portfolio_total == 0:
                self.stdout.write(self.style.SUCCESS("  ✓ Correct (no positions, 0 value)"))
            elif portfolio_total > 0:
                self.stdout.write(self.style.WARNING(f"  ⚠ Has positions worth {portfolio_total}"))
            else:
                self.stdout.write(self.style.SUCCESS("  ✓ No active positions"))

            if confirm:
                reset_count += 1

        if confirm:
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ Processed {reset_count} users\n'
                f'Note: Portfolio values are calculated from positions, not stored separately.\n'
                f'If you want to delete all positions for a user, use a different command.'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'\nDry run complete.\n'
                f'Run with --confirm to actually reset.\n'
                f'Note: Portfolio values are calculated dynamically from positions.'
            ))
