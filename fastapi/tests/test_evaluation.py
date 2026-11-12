import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from scripts.evaluation import LABELED, main, pages, run_benchmark, safe_simulated_approval

class BenchmarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_sizes_and_gates(self):
        report = await run_benchmark()
        self.assertEqual(len(LABELED), 20)
        self.assertEqual([r['catalog_size'] for r in report['results']], [50, 100, 500, 1000])
        self.assertTrue(report['passed'])
        for row in report['results']:
            self.assertEqual(row['queries'], 20)
            self.assertGreaterEqual(row['recall_at_5'], .95)
            self.assertTrue(row['unavailable_candidate_remains_non_executable'])
            self.assertGreaterEqual(row['index_ms'], 0)
            self.assertGreaterEqual(row['mean_query_ms'], 0)

class EvaluationGuards(unittest.TestCase):
    def test_approval_is_simulation_and_allowlisted(self):
        self.assertTrue(safe_simulated_approval({'origin':'simulated','tool_name':'paypal_create_invoice'}))
        for origin, tool in [('api','paypal_create_invoice'),('mcp','paypal_send_invoice'),('simulated','delete_account')]:
            self.assertFalse(safe_simulated_approval({'origin':origin,'tool_name':tool}))
        self.assertFalse(safe_simulated_approval({}))

    def test_cli_defaults_offline_and_writes_failing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'report.json'
            with patch('scripts.evaluation.evaluate', new=AsyncMock(return_value={'passed':False})) as evaluate:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['--output',str(target)]), 1)
                evaluate.assert_awaited_once_with('offline')
            self.assertFalse(json.loads(target.read_text())['passed'])

    def test_pages_need_completed_traces(self):
        rows = [{'tool_name':'sales','status':'completed','arguments':{'page':p}} for p in [1,2]]
        self.assertFalse(pages(rows, 'sales', [1,2,3]))
        rows.append({'tool_name':'sales','status':'running','arguments':{'page':3}})
        self.assertFalse(pages(rows, 'sales', [1,2,3]))
