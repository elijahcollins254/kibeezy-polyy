"""
Django management command for balance reconciliation.

Usage:
    python manage.py reconcile_balances [--fix] [--verbose]
"""
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db.models import Sum
from decimal import Decimal
from brokerage.models import Account, LedgerEntry
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = 'Reconcile user balances from ledger entries'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Actually fix discrepancies (default is dry-run)',
        )
        parser.add_argument(
            '--verbose', '-v',
            action='store_true',
            help='Print details for all users',
        )

    def compute_user_balance_from_ledger(self, user):
        """Compute balance for a user from ledger entries."""
        account_code = f"LIABILITY_USER_{user.id}"
        try:
            account = Account.objects.get(code=account_code)
        except Account.DoesNotExist:
            return None
        
        # Balance = credits - debits
        credits = LedgerEntry.objects.filter(
            credit_account=account
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        debits = LedgerEntry.objects.filter(
            debit_account=account
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        return credits - debits

    def handle(self, *args, **options):
        fix = options['fix']
        verbose = options['verbose']
        
        users = User.objects.all()
        discrepancies = []
        
        self.stdout.write(f"Reconciling {users.count()} users...")
        
        for user in users:
            ledger_balance = self.compute_user_balance_from_ledger(user)
            current_balance = user.balance
            
            if ledger_balance is None:
                if verbose:
                    self.stdout.write(f"  {user.id} ({user.phone_number}): no ledger account (balance={current_balance})")
                continue
            
            ledger_balance = ledger_balance.quantize(Decimal('0.01'))
            
            if ledger_balance != current_balance:
                discrepancy = {
                    'user_id': user.id,
                    'phone_number': user.phone_number,
                    'current_balance': current_balance,
                    'ledger_balance': ledger_balance,
                    'difference': ledger_balance - current_balance,
                }
                discrepancies.append(discrepancy)
                self.stdout.write(
                    self.style.WARNING(
                        f"  MISMATCH {user.id} ({user.phone_number}): "
                        f"current={current_balance}, ledger={ledger_balance}, diff={ledger_balance - current_balance}"
                    )
                )
            elif verbose:
                self.stdout.write(f"  OK {user.id} ({user.phone_number}): balance={current_balance}")
        
        # Report summary
        self.stdout.write(f"\nSummary: {len(discrepancies)} discrepancies found out of {users.count()} users")
        
        if discrepancies:
            self.stdout.write(self.style.WARNING("\nDiscrepancies:"))
            for disc in discrepancies:
                self.stdout.write(
                    self.style.WARNING(
                        f"  User {disc['user_id']} ({disc['phone_number']}): "
                        f"current={disc['current_balance']}, ledger={disc['ledger_balance']}, "
                        f"diff={disc['difference']}"
                    )
                )
        
        if fix and discrepancies:
            self.stdout.write(self.style.SUCCESS(f"\nFixing {len(discrepancies)} discrepancies..."))
            for disc in discrepancies:
                user = User.objects.get(id=disc['user_id'])
                old_balance = user.balance
                user.balance = disc['ledger_balance']
                user.save()
                self.stdout.write(
                    self.style.SUCCESS(f"  Fixed user {user.id}: {old_balance} -> {disc['ledger_balance']}")
                )
            self.stdout.write(self.style.SUCCESS("✓ All discrepancies fixed"))
        elif discrepancies and not fix:
            self.stdout.write("\nRun with --fix to update balances to match ledger")
            return 1
        
        return 0
