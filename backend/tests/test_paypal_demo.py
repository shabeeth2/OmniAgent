import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from decimal import Decimal
from agent_backend.tools.paypal_demo import create_paypal_tools
from agent_backend.tools.context import run_context


class PayPalDemoTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'paypal.db'
        self.tools = create_paypal_tools(self.path)
        token = run_context.set('request-one')
        self.addCleanup(run_context.reset, token)

    def test_invoice_validation_persistence_and_idempotency(self):
        create = self.tools['paypal_create_invoice']
        args = {'recipient': 'buyer@example.test', 'amount': '50.00', 'currency': 'USD'}
        first = create.invoke(args)
        self.assertEqual(create.invoke(args)['invoice_id'], first['invoice_id'])
        self.assertEqual(first['status'], 'DRAFT')
        self.assertEqual(create.metadata['effect'], 'write')
        restarted = create_paypal_tools(self.path)
        sent = restarted['paypal_send_invoice'].invoke({'invoice_id': first['invoice_id']})
        self.assertEqual(sent['status'], 'SENT_SIMULATED')
        self.assertEqual(restarted['paypal_send_invoice'].invoke({'invoice_id': first['invoice_id']}), sent)
        for bad in [{**args, 'recipient': 'missing'}, {**args, 'amount': '-1'}, {**args, 'currency': 'ZZZ'}, {**args, 'amount': '1.001'}]:
            with self.assertRaises(ValueError):
                create.invoke(bad)

    def test_sales_pagination_and_dates(self):
        page = 1
        totals = {}
        while page:
            result = self.tools['paypal_list_transactions'].invoke({'start_date': '2026-10-01', 'end_date': '2026-11-01', 'page': page})
            for row in result['transactions']:
                if row['status'] == 'COMPLETED' and row['kind'] == 'SALE':
                    totals[row['currency']] = totals.get(row['currency'], Decimal(0)) + Decimal(row['amount'])
            page = result['next_page']
        self.assertEqual(totals, {'USD': Decimal('150.00'), 'EUR': Decimal('20.00')})

    def test_user_resolution_and_dispute_pages(self):
        user = self.tools['paypal_resolve_user'].invoke({'user_id': 'user_123'})
        page1 = self.tools['paypal_list_disputes'].invoke({'payer_id': user['payer_id']})
        self.assertIsNotNone(page1['next_page'])
        self.assertEqual(page1['disputes'][0]['status'], 'OPEN')
        self.assertIsNone(self.tools['paypal_resolve_user'].invoke({'user_id': 'unknown'})['payer_id'])
