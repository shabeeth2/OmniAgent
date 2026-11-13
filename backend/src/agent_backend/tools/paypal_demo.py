"""Local simulation only. No PayPal credentials, network calls, or real email."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
from langchain.tools import tool
from pydantic import Field
from .context import run_context
from .rag import BACKEND_DIR


@contextmanager
def database(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def create_paypal_tools(path: Path | None = None):
    path = path or BACKEND_DIR / 'data' / 'paypal-demo.db'
    path.parent.mkdir(parents=True, exist_ok=True)
    with database(path) as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_id TEXT PRIMARY KEY, operation_key TEXT UNIQUE NOT NULL,
                recipient TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY, day TEXT, currency TEXT, amount TEXT, status TEXT, kind TEXT);
            CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, payer_id TEXT);
            CREATE TABLE IF NOT EXISTS disputes (id TEXT PRIMARY KEY, payer_id TEXT, status TEXT);
        ''')
        db.executemany('INSERT OR IGNORE INTO transactions VALUES (?,?,?,?,?,?)', [
            ('TX1','2026-10-02','USD','100.00','COMPLETED','SALE'),
            ('TX2','2026-10-15','USD','50.00','COMPLETED','SALE'),
            ('TX3','2026-10-20','EUR','20.00','COMPLETED','SALE'),
            ('TX4','2026-10-21','USD','99.00','PENDING','SALE'),
            ('TX5','2026-10-22','USD','10.00','COMPLETED','REFUND'),
            ('TX6','2026-11-01','USD','70.00','COMPLETED','SALE')])
        db.executemany('INSERT OR IGNORE INTO users VALUES (?,?)', [('user_123','PAYER123'), ('user_456','PAYER456')])
        db.executemany('INSERT OR IGNORE INTO disputes VALUES (?,?,?)', [('D1','PAYER123','OPEN'), ('D2','PAYER123','CLOSED'), ('D3','PAYER123','OPEN')])

    @tool
    def paypal_create_invoice(recipient: Annotated[str, Field(pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$', max_length=254)],
                              amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)],
                              currency: Literal['USD','EUR','INR','GBP']) -> dict:
        """SIMULATED PayPal: create a draft invoice. Requires recipient email, amount and explicit currency; ask for missing values. Does not send. Write requires approval."""
        scope = run_context.get()
        if not scope:
            raise ValueError('A trusted request scope is required')
        recipient = recipient.strip().lower()
        amount_text = f'{amount:.2f}'
        operation = hashlib.sha256(json.dumps([scope, recipient, amount_text, currency]).encode()).hexdigest()
        with database(path) as db:
            db.execute('INSERT OR IGNORE INTO invoices VALUES (?,?,?,?,?,?)',
                       ('SIM-INV-'+uuid4().hex[:12], operation, recipient, amount_text, currency, 'DRAFT'))
            row = dict(db.execute('SELECT invoice_id,recipient,amount,currency,status FROM invoices WHERE operation_key=?', (operation,)).fetchone())
        return {'simulated': True, **row}

    @tool
    def paypal_send_invoice(invoice_id: str) -> dict:
        """SIMULATED PayPal: send a previously created invoice by ID; requires approval. No email or real PayPal call occurs. Repeated sends are idempotent."""
        with database(path) as db:
            if not db.execute('SELECT 1 FROM invoices WHERE invoice_id=?', (invoice_id,)).fetchone():
                raise ValueError('Unknown simulated invoice')
            db.execute("UPDATE invoices SET status='SENT_SIMULATED' WHERE invoice_id=?", (invoice_id,))
            row = dict(db.execute('SELECT invoice_id,recipient,amount,currency,status FROM invoices WHERE invoice_id=?', (invoice_id,)).fetchone())
        return {'simulated': True, **row}

    @tool
    def paypal_list_transactions(start_date: date, end_date: date, page: Annotated[int, Field(ge=1)] = 1) -> dict:
        """SIMULATED PayPal reporting: list transaction pages for total sales volume. Inclusive start, exclusive end; follow next_page until null. Gross sales = COMPLETED SALE amounts, excluding refunds, fees and pending payments; sum separately by currency."""
        if start_date >= end_date:
            raise ValueError('start_date must precede end_date')
        with database(path) as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM transactions WHERE day>=? AND day<? ORDER BY day,id LIMIT 3 OFFSET ?',
                                                    (start_date.isoformat(), end_date.isoformat(), (page-1)*2))]
        return {'simulated': True, 'transactions': rows[:2], 'next_page': page+1 if len(rows)>2 else None,
                'definition': 'Gross completed sales, excluding refunds, fees and pending payments; separate currencies.'}

    @tool
    def paypal_resolve_user(user_id: str) -> dict:
        """SIMULATED merchant directory: resolve an application user such as user_123 to a PayPal payer ID before dispute search. This mapping is merchant data, not a PayPal API endpoint."""
        with database(path) as db:
            row = db.execute('SELECT payer_id FROM users WHERE user_id=?', (user_id,)).fetchone()
        return {'simulated': True, 'user_id': user_id, 'payer_id': row['payer_id'] if row else None}

    @tool
    def paypal_list_disputes(payer_id: str, page: Annotated[int, Field(ge=1)] = 1) -> dict:
        """SIMULATED PayPal: find open or closed disputes for a resolved payer ID. Follow all pages; report only OPEN cases when asked for open disputes. Empty final pages confirm no matches."""
        with database(path) as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM disputes WHERE payer_id=? ORDER BY id LIMIT 3 OFFSET ?', (payer_id, (page-1)*2))]
        return {'simulated': True, 'disputes': rows[:2], 'next_page': page+1 if len(rows)>2 else None}

    tools = [paypal_create_invoice, paypal_send_invoice, paypal_list_transactions, paypal_resolve_user, paypal_list_disputes]
    for t in tools:
        t.metadata = {'origin': 'simulated', 'effect': 'write' if t in tools[:2] else 'read', 'service': 'paypal', 'version': '1'}
    return {t.name: t for t in tools}
