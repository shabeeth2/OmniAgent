import unittest
from agent_backend.tools.business import create_business_tools
class BusinessTest(unittest.TestCase):
    def test_money(self):
        tools = create_business_tools()
        args = {'start_date':'2026-10-01','end_date':'2026-11-01'}
        self.assertIsNotNone(tools['list_invoices'].invoke(args)['next_page'])
        result = tools['aggregate_outstanding'].invoke(args)
        self.assertEqual(result['totals'], {'USD':'125.50','EUR':'20.00'})
        self.assertEqual(result['count'], 3)

class BusinessEdgeTest(unittest.TestCase):
    def test_filters_validation_and_boundaries(self):
        from pydantic import ValidationError
        tools=create_business_tools()
        self.assertEqual(tools['search_customers'].invoke({'query':'ACME'})['customers'][0]['id'],'c1')
        result=tools['aggregate_outstanding'].invoke({'start_date':'2025-12-01','end_date':'2026-01-01'})
        self.assertEqual(result['totals'],{'USD':'10.00'})
        self.assertEqual(tools['aggregate_outstanding'].invoke({'start_date':'2026-08-01','end_date':'2026-09-01'})['count'],0)
        with self.assertRaises(ValueError):
            tools['list_invoices'].invoke({'start_date':'2026-11-01','end_date':'2026-10-01'})
        with self.assertRaises(ValidationError):
            tools['list_invoices'].invoke({'start_date':'bad','end_date':'2026-10-01'})
        self.assertIsNone(tools['list_invoices'].invoke({'start_date':'2026-10-01','end_date':'2026-11-01','page':2})['next_page'])
