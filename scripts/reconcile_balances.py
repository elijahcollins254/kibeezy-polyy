#!/usr/bin/env python3
"""
Reconciliation script: recompute CustomUser.balance from ledger entries.

This script:
 - Iterates through all users
 - Computes balance from ledger: LIABILITY_USER_{user_id} account balance
 - Compares to current CustomUser.balance
 - Reports discrepancies
 - Optionally fixes discrepancies (--fix flag)

Usage:
    python manage.py shell < scripts/reconcile_balances.py
    
Or directly:
    python scripts/reconcile_balances_runner.py [--fix] [--verbose]
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db.models import Sum
from brokerage.models import Account, LedgerEntry
import argparse
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

User = get_user_model()


def compute_user_balance_from_ledger(user):
    """
    Compute balance for a user from ledger entries.
    
    Balance = sum of credits to LIABILITY_USER_{user_id} - sum of debits from it
    
    Returns:
        Decimal balance, or None if no ledger account exists
    """
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


def reconcile(fix=False, verbose=False):
    """
    Main reconciliation function.
    
    Args:
        fix: If True, update user balances to match ledger
        verbose: If True, print details for all users (not just discrepancies)
    
    Returns:
        Tuple of (total_users, discrepancies_count, discrepancies_list)
    """
    
    users = User.objects.all()
    discrepancies = []
    
    logger.info(f"Reconciling {users.count()} users...")
    
    for user in users:
        ledger_balance = compute_user_balance_from_ledger(user)
        current_balance = user.balance
        
        # If no ledger account, skip (user may not have had any transactions)
        if ledger_balance is None:
            if verbose:
                logger.info(f"  {user.id} ({user.phone_number}): no ledger account (balance={current_balance})")
            continue
        
        # Convert to same decimal places for comparison
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
            logger.warning(
                f"  MISMATCH {user.id} ({user.phone_number}): "
                f"current={current_balance}, ledger={ledger_balance}, diff={ledger_balance - current_balance}"
            )
        elif verbose:
            logger.info(
                f"  OK {user.id} ({user.phone_number}): balance={current_balance}"
            )
    
    # Report summary
    logger.info(f"\nSummary: {len(discrepancies)} discrepancies found out of {users.count()} users")
    
    if discrepancies:
        logger.warning("\nDiscrepancies:")
        for disc in discrepancies:
            logger.warning(
                f"  User {disc['user_id']} ({disc['phone_number']}): "
                f"current={disc['current_balance']}, ledger={disc['ledger_balance']}, "
                f"diff={disc['difference']}"
            )
    
    # Fix if requested
    if fix and discrepancies:
        logger.info(f"\nFixing {len(discrepancies)} discrepancies...")
        for disc in discrepancies:
            user = User.objects.get(id=disc['user_id'])
            old_balance = user.balance
            user.balance = disc['ledger_balance']
            user.save()
            logger.info(
                f"  Fixed user {user.id}: {old_balance} -> {disc['ledger_balance']}"
            )
        logger.info("✓ All discrepancies fixed")
    elif discrepancies and not fix:
        logger.info("\nRun with --fix to update balances to match ledger")
    
    return len(users), len(discrepancies), discrepancies


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Reconcile user balances from ledger entries')
    parser.add_argument('--fix', action='store_true', help='Actually fix discrepancies (default is dry-run)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Print details for all users')
    
    args = parser.parse_args()
    
    total, disc_count, discrepancies = reconcile(fix=args.fix, verbose=args.verbose)
    
    # Exit with status code > 0 if discrepancies found (for CI/monitoring)
    sys.exit(1 if disc_count > 0 else 0)
