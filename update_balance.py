#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()

from users.models import CustomUser
from decimal import Decimal
from brokerage.services.ledger import get_computed_balance, record_deposit_and_update_balance, record_withdrawal_reversal_and_update_balance

# Update user balance safely via ledger adjustments
phone_number = '0718693484'
try:
    user = CustomUser.objects.get(phone_number=phone_number)
    target = Decimal('15000.00')

    current_ledger = get_computed_balance(user)
    delta = target - current_ledger

    if delta == 0:
        print(f"✓ Ledger already at target for {phone_number}: KES {current_ledger}")
    elif delta > 0:
        # Create deposit to bring ledger up to target
        tx, new_bal = record_deposit_and_update_balance(user, delta, reference=f'admin:set_balance:{phone_number}')
        print(f"✅ Deposited {delta} to user via ledger tx {tx.id}. New balance: KES {new_bal}")
    else:
        # Negative delta: attempt reversal/withdrawal to reduce ledger balance
        amt = abs(delta)
        tx, new_bal = record_withdrawal_reversal_and_update_balance(user, amt, reference=f'admin:set_balance:{phone_number}')
        print(f"✅ Reversed {amt} via ledger tx {tx.id}. New balance: KES {new_bal}")

except CustomUser.DoesNotExist:
    print(f"❌ User with phone number {phone_number} not found")
except Exception as e:
    print(f"❌ Error: {e}")
