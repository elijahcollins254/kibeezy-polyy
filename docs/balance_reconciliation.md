# Balance Reconciliation

Reconciliation tools to verify and fix `CustomUser.balance` against ledger entries.

## Why reconcile?

The ledger (`brokerage.models.LedgerEntry`) is the source of truth for user balances. This script compares `CustomUser.balance` against the computed balance from the ledger, reports discrepancies, and optionally fixes them.

## Usage

### Management Command (recommended)

Dry-run (check for discrepancies):
```bash
python manage.py reconcile_balances
```

Fix discrepancies:
```bash
python manage.py reconcile_balances --fix
```

Verbose output (show all users):
```bash
python manage.py reconcile_balances --verbose
python manage.py reconcile_balances --fix --verbose
```

### Script

Alternatively, run the standalone script:
```bash
python scripts/reconcile_balances.py [--fix] [--verbose]
```

## Algorithm

For each user:
1. Locate `LIABILITY_USER_{user_id}` account in ledger
2. Compute balance: sum(credits to account) - sum(debits from account)
3. Compare to `CustomUser.balance`
4. If mismatch, log as discrepancy
5. If `--fix`, update `CustomUser.balance` to match ledger

## Exit codes

- **0**: No discrepancies or all fixed
- **1**: Discrepancies found (dry-run) or fix failed

## Example output

```
Reconciling 42 users...
  MISMATCH 5 (+254712345678): current=1000.00, ledger=1050.00, diff=50.00
  MISMATCH 7 (+254798765432): current=2500.00, ledger=2000.00, diff=-500.00

Summary: 2 discrepancies found out of 42 users

Run with --fix to update balances to match ledger
```

## Notes

- This is a **dry-run by default**. Use `--fix` to actually modify balances.
- Ledger entries are immutable; this script only updates the `CustomUser.balance` field.
- Safe to run repeatedly; idempotent.
