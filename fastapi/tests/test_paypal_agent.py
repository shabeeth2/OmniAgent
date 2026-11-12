import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent_backend.agent.graph import BusinessAgent
from agent_backend.tools.paypal_demo import create_paypal_tools, database
from test_agent import Model, call


class PayPalAgentTest(unittest.IsolatedAsyncioTestCase):
    async def test_approval_restart_send_and_rejection(self):
        class Discover:
            async def search(self, query):
                return ['paypal_create_invoice','paypal_send_invoice']
        class InvoiceModel(Model):
            async def ainvoke(self, messages):
                if isinstance(messages[-1], ToolMessage) and messages[-1].name == 'paypal_create_invoice':
                    invoice = json.loads(messages[-1].content)
                    return call('paypal_send_invoice', {'invoice_id':invoice['invoice_id']}, 'send')
                return await super().ainvoke(messages)
        with TemporaryDirectory() as directory:
            path = Path(directory)
            tools = create_paypal_tools(path/'paypal.db')
            model = InvoiceModel([call('system_search', {'query':'create and send PayPal invoice'}, 'discover'),
                                  call('paypal_create_invoice', {'recipient':'buyer@example.test','amount':'50.00','currency':'USD'}, 'create'),
                                  AIMessage(content='Draft created; simulated sending was rejected.')])
            async with AsyncSqliteSaver.from_conn_string(str(path/'checkpoint.db')) as saver:
                agent = BusinessAgent(model, Discover(), tools, checkpointer=saver)
                first = await agent.run([HumanMessage(content='Send USD 50 invoice to buyer@example.test')], run_id='invoice-request')
                self.assertEqual(first.approval['calls'][0]['origin'], 'simulated')
                with database(path/'paypal.db') as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0], 0)
            async with AsyncSqliteSaver.from_conn_string(str(path/'checkpoint.db')) as saver:
                agent = BusinessAgent(model, Discover(), tools, checkpointer=saver)
                second = await agent.run(run_id='invoice-request', decision='approve')
                self.assertEqual(second.approval['calls'][0]['tool_name'], 'paypal_send_invoice')
                final = await agent.run(run_id='invoice-request', decision='reject')
                self.assertEqual(final.status, 'rejected')
                with database(path/'paypal.db') as db:
                    self.assertEqual(db.execute('SELECT status FROM invoices').fetchone()[0], 'DRAFT')

    async def test_sales_all_pages_and_disputes_chain(self):
        class Discover:
            async def search(self, query): return list(tools)
        with TemporaryDirectory() as directory:
            tools = create_paypal_tools(Path(directory)/'paypal.db')
            model = Model([call('system_search', {'query':'PayPal sales volume'}, 'd'),
                *[call('paypal_list_transactions', {'start_date':'2026-10-01','end_date':'2026-11-01','page':p}, f'p{p}') for p in (1,2,3)],
                AIMessage(content='Simulated October gross sales: USD 150.00 and EUR 20.00; refunds and pending transactions excluded.')])
            traces = []
            outcome = await BusinessAgent(model, Discover(), tools).run([HumanMessage(content='Total sales last month?')], on_trace=traces.append)
            self.assertEqual(outcome.status, 'completed')
            completed = [row for row in traces if row['status']=='completed' and row['tool_name']=='paypal_list_transactions']
            self.assertEqual([row['arguments']['page'] for row in completed], [1,2,3])
            self.assertIsNone(completed[-1]['result']['next_page'])
            model = Model([call('system_search', {'query':'PayPal user disputes'}, 'd'),
                call('paypal_resolve_user', {'user_id':'user_123'}, 'user'),
                call('paypal_list_disputes', {'payer_id':'PAYER123','page':1}, 'one'),
                call('paypal_list_disputes', {'payer_id':'PAYER123','page':2}, 'two'), AIMessage(content='Simulated open disputes: D1 and D3.')])
            self.assertEqual((await BusinessAgent(model, Discover(), tools).run([])).status, 'completed')

    async def test_missing_details_does_not_create_invoice(self):
        model = Model([AIMessage(content='What recipient email and currency should I use?')])
        with TemporaryDirectory() as directory:
            tools = create_paypal_tools(Path(directory)/'paypal.db')
            result = await BusinessAgent(model, None, tools).run([HumanMessage(content='Send a $50 invoice')])
            self.assertIn('recipient', result.content)
            with database(Path(directory)/'paypal.db') as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0], 0)
