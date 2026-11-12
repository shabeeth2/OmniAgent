import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent_backend.agent.graph import BusinessAgent
from agent_backend.tools.paypal_demo import create_paypal_tools, database
from scripts.browser_demo import FixtureModel


class BrowserFixtureTest(unittest.IsolatedAsyncioTestCase):
    async def test_requested_amount_and_separate_send_approval(self):
        class Discovery:
            async def search(self, query):
                return ['paypal_create_invoice', 'paypal_send_invoice']

        with TemporaryDirectory() as directory:
            root = Path(directory)
            tools = create_paypal_tools(root / 'paypal.db')
            async with AsyncSqliteSaver.from_conn_string(str(root / 'checkpoints.db')) as saver:
                agent = BusinessAgent(FixtureModel(), Discovery(), tools, checkpointer=saver)
                result = await agent.run([HumanMessage(content=(
                    'Draft a PayPal invoice for alex@example.com for USD 125. '
                    'Ask me before sending it.'))], run_id='video-fixture')
                call = result.approval['calls'][0]
                self.assertEqual(call['tool_name'], 'paypal_create_invoice')
                self.assertEqual(call['arguments']['amount'], '125.00')
                with database(root / 'paypal.db') as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0], 0)
                result = await agent.run(run_id='video-fixture', decision='approve')
                call = result.approval['calls'][0]
                self.assertEqual(call['tool_name'], 'paypal_send_invoice')
                invoice_id = call['arguments']['invoice_id']
                with database(root / 'paypal.db') as db:
                    row = db.execute('SELECT status,amount FROM invoices WHERE invoice_id=?', (invoice_id,)).fetchone()
                    self.assertEqual(tuple(row), ('DRAFT', '125.00'))
                result = await agent.run(run_id='video-fixture', decision='approve')
                self.assertEqual(result.status, 'completed')
                self.assertIn('SENT_SIMULATED', result.content)
                self.assertIn('125.00', result.content)
                self.assertIn(invoice_id, result.content)
                with database(root / 'paypal.db') as db:
                    self.assertEqual(db.execute('SELECT status FROM invoices WHERE invoice_id=?', (invoice_id,)).fetchone()[0], 'SENT_SIMULATED')
