from decimal import Decimal
from django.test import TestCase

from users.models import CustomUser
from brokerage.models import Account, Wallet
from brokerage.services.ledger import create_transaction_with_entries, reserve_user_funds, release_user_funds


class LedgerReservationTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(phone_number='+254700000000', full_name='Test User', password='pass1234')
        # Create wallet
        Wallet.objects.create(user=self.user)

        # Ensure accounts exist
        self.cash = Account.objects.create(code='CASH', name='Cash')
        self.user_liability = Account.objects.create(code=f'LIABILITY_USER_{self.user.id}', name='User Liability')
        self.reserved = Account.objects.create(code=f'LIABILITY_RESERVED_{self.user.id}', name='Reserved Liability')

    def test_deposit_and_reserve(self):
        # Simulate deposit: Debit CASH, Credit USER LIABILITY
        tx = create_transaction_with_entries(self.user, 'DEPOSIT', [
            {'debit': 'CASH', 'credit': f'LIABILITY_USER_{self.user.id}', 'amount': '1000.00', 'description': 'Test deposit'}
        ], reference='deposit:test')

        # Balance should reflect deposit
        self.assertEqual(self.user_liability.balance(), Decimal('1000.00'))

        # Reserve 200
        reserve_user_funds(self.user, Decimal('200.00'))

        # After reserve: user liability decreased by 200, reserved increased by 200
        self.assertEqual(self.user_liability.balance(), Decimal('800.00'))
        self.assertEqual(self.reserved.balance(), Decimal('200.00'))

        # Release 200
        release_user_funds(self.user, Decimal('200.00'))

        # Balances should return to original
        self.assertEqual(self.user_liability.balance(), Decimal('1000.00'))
        self.assertEqual(self.reserved.balance(), Decimal('0'))
