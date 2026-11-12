"""Read-only fictional business records. No external business APIs."""
from datetime import date
from decimal import Decimal
from typing import Annotated
from pydantic import Field
from langchain.tools import tool

CUSTOMERS = [{'id':'c1','name':'Acme'}, {'id':'c2','name':'Orbit'}]
INVOICES = [
    {'id':f'i{i}', 'customer_id':customer, 'date':day, 'currency':currency,
     'amount':amount, 'paid':paid}
    for i, (customer, day, currency, amount, paid) in enumerate([
        ('c1','2026-10-03','USD','100.00','0.00'),
        ('c1','2026-10-12','USD','50.00','24.50'),
        ('c2','2026-10-20','EUR','20.00','0.00'),
        ('c2','2026-10-21','USD','80.00','80.00'),
        ('c1','2026-09-30','USD','30.00','0.00'),
        ('c2','2026-11-01','USD','40.00','0.00'),
        ('c1','2025-12-31','USD','10.00','0.00'),
    ], 1)
]

def create_business_tools():
    def filtered(start_date, end_date, customer_id, unpaid_only):
        if start_date >= end_date:
            raise ValueError('start_date must precede end_date')
        if customer_id and customer_id not in {c['id'] for c in CUSTOMERS}:
            raise ValueError('Unknown customer')
        return [dict(row, outstanding=f"{Decimal(row['amount'])-Decimal(row['paid']):.2f}")
                for row in INVOICES if start_date <= date.fromisoformat(row['date']) < end_date
                and (not customer_id or row['customer_id'] == customer_id)
                and (not unpaid_only or Decimal(row['amount']) > Decimal(row['paid']))]

    @tool
    def search_customers(query: Annotated[str, Field(min_length=1)]) -> dict:
        """Find fictional customers by case-insensitive name; returns customer IDs for invoice queries."""
        return {'customers':[dict(c) for c in CUSTOMERS if query.casefold() in c['name'].casefold()]}

    @tool
    def list_invoices(start_date: date, end_date: date, customer_id: str | None = None,
                      unpaid_only: bool = True, page: Annotated[int, Field(ge=1)] = 1) -> dict:
        """List invoices by inclusive start date and exclusive end date. Unpaid includes partial payments. Follow next_page until null; page size is two."""
        rows = filtered(start_date, end_date, customer_id, unpaid_only)
        offset = (page-1)*2
        return {'invoices':rows[offset:offset+2], 'next_page':page+1 if offset+2 < len(rows) else None}

    @tool
    def get_invoice(invoice_id: str) -> dict:
        """Get one invoice's amount, paid amount, currency, customer and date by invoice ID."""
        for row in INVOICES:
            if row['id'] == invoice_id:
                return dict(row)
        raise ValueError('Unknown invoice')

    @tool
    def aggregate_outstanding(start_date: date, end_date: date, customer_id: str | None = None) -> dict:
        """Calculate complete unpaid invoice counts and outstanding balances over ALL matching records, separately by currency. Includes partial payments; no pagination needed."""
        rows = filtered(start_date, end_date, customer_id, True)
        totals = {}
        for row in rows:
            currency = row['currency']
            totals[currency] = totals.get(currency, Decimal(0)) + Decimal(row['outstanding'])
        return {'count':len(rows), 'totals':{k:f'{v:.2f}' for k,v in totals.items()}, 'complete':True}

    tools = (search_customers, list_invoices, get_invoice, aggregate_outstanding)
    for t in tools:
        t.metadata = {"origin": "local", "effect": "read", "service": "business", "version": "1"}
    return {t.name:t for t in tools}
