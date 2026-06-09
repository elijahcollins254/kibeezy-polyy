import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from django.contrib.auth import get_user_model
from brokerage.models import Market
from payments.models import Transaction


class PaymentsCallbackTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='payer', password='pass', phone_number='+254700000000')

    def test_b2c_result_success_records_withdrawal_and_updates_status(self):
        # Create a pending withdrawal transaction with merchant_request_id matching ConversationID
        tx = Transaction.objects.create(user=self.user, type='WITHDRAWAL', amount=100, phone_number=self.user.phone_number, status='PENDING', merchant_request_id='CONV123')

        payload = {
            'ConversationID': 'CONV123',
            'ResultCode': '0',
            'Result': {
                'ConversationID': 'CONV123',
                'ResultCode': 0,
            }
        }

        # Patch ledger function to return a fake ledger_tx and updated balance
        fake_ledger_tx = SimpleNamespace(id=999)
        with patch('payments.views.record_withdrawal_success_and_update_balance', return_value=(fake_ledger_tx, 500)):
            resp = self.client.post('/api/payments/b2c-callback/', json.dumps(payload), content_type='application/json')

        self.assertEqual(resp.status_code, 200)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'COMPLETED')
        self.assertIn('ledger_tx_id', tx.mpesa_response)

    def test_b2c_result_failure_records_reversal_and_marks_failed(self):
        tx = Transaction.objects.create(user=self.user, type='WITHDRAWAL', amount=150, phone_number=self.user.phone_number, status='PENDING', merchant_request_id='CONV456')

        payload = {
            'ConversationID': 'CONV456',
            'ResultCode': 1,
            'Result': {
                'ConversationID': 'CONV456',
                'ResultCode': 1,
            }
        }

        fake_reversal_tx = SimpleNamespace(id=1234)
        with patch('payments.views.record_withdrawal_reversal_and_update_balance', return_value=(fake_reversal_tx, 650)):
            resp = self.client.post('/api/payments/b2c-callback/', json.dumps(payload), content_type='application/json')

        self.assertEqual(resp.status_code, 200)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'FAILED')
        self.assertIn('callback_success', tx.mpesa_response)
