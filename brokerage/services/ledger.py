import logging
from decimal import Decimal
from django.db import transaction
from django.conf import settings

from brokerage.models import Account, Transaction as BrokerageTransaction, LedgerEntry
from users.models import CustomUser

logger = logging.getLogger(__name__)


def _get_or_create_account(code, name=None, description=None):
    acc, created = Account.objects.get_or_create(
        code=code,
        defaults={'name': name or code, 'description': description or ''}
    )
    if created:
        logger.info(f"Created ledger account: {code}")
    return acc


def _user_liability_account(user: CustomUser):
    code = f"LIABILITY_USER_{user.id}"
    return _get_or_create_account(code, name=f"Liability - {user.phone_number}")


def _cash_account():
    return _get_or_create_account('CASH', name='Cash')


def create_deposit(user: CustomUser, amount: Decimal, reference: str = None, metadata: dict = None, description: str = None):
    """Record a deposit in the brokerage ledger: debit CASH, credit LIABILITY_USER_{user.id}

    Returns the created BrokerageTransaction instance.
    Also updates `user.balance` to reflect ledger-derived balance.
    """
    metadata = metadata or {}
    description = description or f"Deposit KES {amount}"

    with transaction.atomic():
        bt = BrokerageTransaction.objects.create(
            user=user,
            type='DEPOSIT',
            reference=reference,
            metadata=metadata,
        )

        cash = _cash_account()
        liability = _user_liability_account(user)

        LedgerEntry.objects.create(
            transaction=bt,
            debit_account=cash,
            credit_account=liability,
            amount=amount,
            description=description
        )

        # Recompute user balance from ledger and persist to user.balance
        try:
            bal = liability.balance()
            user.balance = bal
            user.save(update_fields=['balance'])
        except Exception as e:
            logger.warning(f"Failed to update user.balance after deposit ledger write: {e}")

    logger.info(f"Ledger deposit recorded: user={user.id}, amt={amount}, tx={bt.id}")
    return bt


def create_withdrawal_success(user: CustomUser, amount: Decimal, reference: str = None, metadata: dict = None, description: str = None):
    """Record a successful withdrawal in the brokerage ledger: debit LIABILITY_USER_{user.id}, credit CASH

    Returns the created BrokerageTransaction instance and updates `user.balance` from ledger.
    """
    metadata = metadata or {}
    description = description or f"Withdrawal KES {amount}"

    with transaction.atomic():
        bt = BrokerageTransaction.objects.create(
            user=user,
            type='WITHDRAWAL',
            reference=reference,
            metadata=metadata,
        )

        cash = _cash_account()
        liability = _user_liability_account(user)

        LedgerEntry.objects.create(
            transaction=bt,
            debit_account=liability,
            credit_account=cash,
            amount=amount,
            description=description
        )

        # Recompute and persist
        try:
            bal = liability.balance()
            user.balance = bal
            user.save(update_fields=['balance'])
        except Exception as e:
            logger.warning(f"Failed to update user.balance after withdrawal ledger write: {e}")

    logger.info(f"Ledger withdrawal recorded: user={user.id}, amt={amount}, tx={bt.id}")
    return bt


def create_withdrawal_reversal(user: CustomUser, amount: Decimal, reference: str = None, metadata: dict = None, description: str = None):
    """If a withdrawal failed and we need to reverse reserved amounts, record reversal entries.

    Implemented as credit LIABILITY_USER, debit CASH (opposite of successful withdrawal reversal).
    """
    metadata = metadata or {}
    description = description or f"Withdrawal reversal KES {amount}"

    with transaction.atomic():
        bt = BrokerageTransaction.objects.create(
            user=user,
            type='WITHDRAWAL',
            reference=reference,
            metadata=metadata,
        )

        cash = _cash_account()
        liability = _user_liability_account(user)

        # Reverse: debit cash, credit liability (i.e., put funds back to user liability)
        LedgerEntry.objects.create(
            transaction=bt,
            debit_account=cash,
            credit_account=liability,
            amount=amount,
            description=description
        )

        # Recompute and persist
        try:
            bal = liability.balance()
            user.balance = bal
            user.save(update_fields=['balance'])
        except Exception as e:
            logger.warning(f"Failed to update user.balance after withdrawal reversal ledger write: {e}")

    logger.info(f"Ledger withdrawal reversal recorded: user={user.id}, amt={amount}, tx={bt.id}")
    return bt
from decimal import Decimal
from typing import List, Dict
from django.db import transaction as db_transaction
from django.core.exceptions import ObjectDoesNotExist

from brokerage.models import Transaction, LedgerEntry, Account


class LedgerError(Exception):
    pass


def get_or_create_account(code: str, name: str = None) -> Account:
    acc, _ = Account.objects.get_or_create(code=code, defaults={'name': name or code})
    return acc


def validate_entries_balance(entries: List[Dict]) -> None:
    total_debits = sum(Decimal(e['amount']) for e in entries)
    total_credits = total_debits  # we expect debit==credit per provided structure
    # In our calling convention every entry included is a single debit+credit movement so amounts sum must be >=0
    if total_debits <= 0:
        raise LedgerError('Total movement must be positive')


def create_transaction_with_entries(user, tx_type: str, entries: List[Dict], reference: str = None, metadata: Dict = None) -> Transaction:
    """Create a Transaction and associated LedgerEntry rows atomically.

    entries: List of dicts with keys: debit (account_code), credit (account_code), amount (Decimal or numeric), description (optional)
    """
    if not entries:
        raise LedgerError('No ledger entries provided')

    # Basic sanity: ensure amounts positive and sum check on our side if needed
    for e in entries:
        if Decimal(e['amount']) <= 0:
            raise LedgerError('Entry amounts must be positive')

    with db_transaction.atomic():
        tx = Transaction.objects.create(user=user, type=tx_type, reference=reference, metadata=metadata or {})
        for e in entries:
            try:
                debit_acc = Account.objects.get(code=e['debit'])
            except ObjectDoesNotExist:
                debit_acc = get_or_create_account(e['debit'])
            try:
                credit_acc = Account.objects.get(code=e['credit'])
            except ObjectDoesNotExist:
                credit_acc = get_or_create_account(e['credit'])

            LedgerEntry.objects.create(
                transaction=tx,
                debit_account=debit_acc,
                credit_account=credit_acc,
                amount=Decimal(e['amount']),
                description=e.get('description', '')
            )

    return tx


def reserve_user_funds(user, amount):
    """Reserve funds from user's liability into a reserved-liability bucket."""
    liability_code = f"LIABILITY_USER_{user.id}"
    reserved_code = f"LIABILITY_RESERVED_{user.id}"
    entries = [
        {'debit': liability_code, 'credit': reserved_code, 'amount': amount, 'description': 'Reserve funds for order'},
    ]
    return create_transaction_with_entries(user, 'TRADE', entries, reference=f'reserve:{user.id}')


def release_user_funds(user, amount):
    liability_code = f"LIABILITY_USER_{user.id}"
    reserved_code = f"LIABILITY_RESERVED_{user.id}"
    entries = [
        {'debit': reserved_code, 'credit': liability_code, 'amount': amount, 'description': 'Release reserved funds'},
    ]
    return create_transaction_with_entries(user, 'TRADE', entries, reference=f'release:{user.id}')


def record_deposit(user, amount: Decimal, reference: str = None, metadata: Dict = None):
    """Record a deposit (e.g., M-Pesa STK push success).
    
    Creates ledger entry:
    - Debit: CASH (company receives cash)
    - Credit: LIABILITY_USER_{user.id} (user's liability increases)
    
    Returns the created Transaction.
    """
    liability_code = f"LIABILITY_USER_{user.id}"
    entries = [
        {
            'debit': 'CASH',
            'credit': liability_code, 
            'amount': amount,
            'description': f'Deposit of KES {amount}'
        },
    ]
    return create_transaction_with_entries(
        user, 
        'DEPOSIT', 
        entries, 
        reference=reference or f'deposit:{user.id}',
        metadata=metadata or {}
    )


def record_withdrawal_success(user, amount: Decimal, reference: str = None, metadata: Dict = None):
    """Record a successful withdrawal (e.g., B2C payout confirmed).
    
    Creates ledger entry:
    - Debit: LIABILITY_USER_{user.id} (user's liability decreases)
    - Credit: CASH (company sends cash)
    
    Returns the created Transaction.
    """
    liability_code = f"LIABILITY_USER_{user.id}"
    entries = [
        {
            'debit': liability_code,
            'credit': 'CASH',
            'amount': amount,
            'description': f'Withdrawal of KES {amount}'
        },
    ]
    return create_transaction_with_entries(
        user,
        'WITHDRAWAL',
        entries,
        reference=reference or f'withdrawal:{user.id}',
        metadata=metadata or {}
    )


def record_withdrawal_reversal(user, amount: Decimal, reference: str = None, metadata: Dict = None):
    """Record a failed withdrawal reversal (refund reserved funds back to available).
    
    Creates ledger entry:
    - Debit: LIABILITY_RESERVED_{user.id} (cancel reservation)
    - Credit: LIABILITY_USER_{user.id} (return to available)
    
    Returns the created Transaction.
    """
    liability_code = f"LIABILITY_USER_{user.id}"
    reserved_code = f"LIABILITY_RESERVED_{user.id}"
    entries = [
        {
            'debit': reserved_code,
            'credit': liability_code,
            'amount': amount,
            'description': f'Withdrawal reversal of KES {amount} due to failed payout'
        },
    ]
    return create_transaction_with_entries(
        user,
        'WITHDRAWAL',
        entries,
        reference=reference or f'withdrawal_reversal:{user.id}',
        metadata=metadata or {}
    )


# ============================================================================
# Atomic balance-updating functions (ledger + user.balance in single txn)
# ============================================================================

def record_deposit_and_update_balance(user, amount: Decimal, reference: str = None, metadata: Dict = None):
    """Atomically record deposit AND update user.balance.
    
    Ensures ledger entry and user.balance stay in sync.
    
    Args:
        user: Django User (CustomUser)
        amount: Decimal amount
        reference: Optional reference string
        metadata: Optional metadata dict
    
    Returns:
        Tuple: (Transaction ledger_tx, updated_balance)
    """
    with db_transaction.atomic():
        # Create ledger entry (locked transaction)
        ledger_tx = record_deposit(user, amount, reference=reference, metadata=metadata)
        
        # Update user balance immediately
        user.balance += amount
        user.save(update_fields=['balance'])
        
        return ledger_tx, user.balance


def record_withdrawal_success_and_update_balance(user, amount: Decimal, reference: str = None, metadata: Dict = None):
    """Atomically record withdrawal success AND update user.balance.
    
    Ensures ledger entry and user.balance stay in sync.
    
    Args:
        user: Django User (CustomUser)
        amount: Decimal amount to withdraw
        reference: Optional reference string
        metadata: Optional metadata dict
    
    Returns:
        Tuple: (Transaction ledger_tx, updated_balance)
    """
    with db_transaction.atomic():
        # Verify user has sufficient balance
        if user.balance < amount:
            raise LedgerError(f"Insufficient balance: {user.balance} < {amount}")
        
        # Create ledger entry (locked transaction)
        ledger_tx = record_withdrawal_success(user, amount, reference=reference, metadata=metadata)
        
        # Update user balance immediately
        user.balance -= amount
        user.save(update_fields=['balance'])
        
        return ledger_tx, user.balance


def record_withdrawal_reversal_and_update_balance(user, amount: Decimal, reference: str = None, metadata: Dict = None):
    """Atomically record withdrawal reversal AND update user.balance.
    
    Ensures ledger entry and user.balance stay in sync.
    
    Args:
        user: Django User (CustomUser)
        amount: Decimal amount to refund
        reference: Optional reference string
        metadata: Optional metadata dict
    
    Returns:
        Tuple: (Transaction ledger_tx, updated_balance)
    """
    with db_transaction.atomic():
        # Create ledger entry (locked transaction)
        ledger_tx = record_withdrawal_reversal(user, amount, reference=reference, metadata=metadata)
        
        # Update user balance immediately (return funds)
        user.balance += amount
        user.save(update_fields=['balance'])
        
        return ledger_tx, user.balance


def get_computed_balance(user):
    """Compute user's balance directly from ledger (never cached).
    
    This is useful for audits or reconciliation. For normal operations,
    use user.balance (which is sync'd when ledger entries are created).
    
    Returns:
        Decimal balance computed from LIABILITY_USER_{user_id} account
    """
    from django.db.models import Sum
    
    liability_code = f"LIABILITY_USER_{user.id}"
    try:
        acc = Account.objects.get(code=liability_code)
    except ObjectDoesNotExist:
        return Decimal('0')
    
    # Balance = credits - debits
    credits = LedgerEntry.objects.filter(
        credit_account=acc
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    debits = LedgerEntry.objects.filter(
        debit_account=acc
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    return credits - debits
