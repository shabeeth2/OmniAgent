"""Evaluation CLI. Offline is free; discovery/tasks explicitly opt into provider calls."""
import argparse
import asyncio
import hashlib
import json
import math
import time
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from langchain_core.embeddings import Embeddings
from agent_backend.agent.discovery import ToolDiscovery, catalog_operations
from agent_backend.tools.business import create_business_tools
from agent_backend.tools.paypal_demo import create_paypal_tools


class HashEmbeddings(Embeddings):
    """Deterministic bag-of-words fixture, NOT a semantic model or quality proof."""
    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        vector = [0.] * 256
        for token in ToolDiscovery.tokens(text):
            vector[int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], 'little') % 256] += 1
        norm = math.sqrt(sum(v*v for v in vector)) or 1
        return [v/norm for v in vector]


LABELED = [
    ('Create a PayPal invoice draft with recipient email amount and currency', 'paypal_create_invoice'),
    ('Send the previously created PayPal invoice by invoice ID', 'paypal_send_invoice'),
    ('PayPal gross sales volume completed sales transaction pages', 'paypal_list_transactions'),
    ('Resolve application user_123 to PayPal payer ID', 'paypal_resolve_user'),
    ('PayPal open disputes for a resolved payer ID', 'paypal_list_disputes'),
    ('Find fictional customers by name', 'search_customers'),
    ('List unpaid invoices by date including partial payments', 'list_invoices'),
    ('Get one invoice amount paid currency by invoice ID', 'get_invoice'),
    ('Calculate complete outstanding balances by currency', 'aggregate_outstanding'),
    ('Create draft invoice; do not send it', 'paypal_create_invoice'),
    ('Send simulated invoice already created', 'paypal_send_invoice'),
    ('List transaction reporting pages excluding pending sales', 'paypal_list_transactions'),
    ('Map merchant application user identifier to payer', 'paypal_resolve_user'),
    ('Find closed and open PayPal dispute cases', 'paypal_list_disputes'),
    ('Look up customer record Acme', 'search_customers'),
    ('Retrieve next invoice page', 'list_invoices'),
    ('Read single invoice details', 'get_invoice'),
    ('Total unpaid remaining balance across all records', 'aggregate_outstanding'),
    ('Invoice recipient currency draft creation', 'paypal_create_invoice'),
    ('Search PayPal disputes by payer', 'paypal_list_disputes'),
]


async def run_benchmark(embeddings=None, dimensions=256):
    offline = embeddings is None
    embeddings = embeddings or HashEmbeddings()
    reports = []
    with TemporaryDirectory() as directory:
        registry = {**create_business_tools(), **create_paypal_tools(Path(directory) / 'paypal.db')}
        official = {row['id']: row['description'] for row in catalog_operations()}
        for size in (50, 100, 500, 1000):
            descriptions = ToolDiscovery.describe(registry)
            for service in ('stripe', 'square', 'merchant_directory'):
                descriptions[f'{service}_list_invoices'] = f'{service} list invoice pages and invoice amounts by customer and date.'
                descriptions[f'{service}_create_invoice'] = f'{service} create draft invoice for recipient email amount currency.'
            for name, text in official.items():
                if len(descriptions) == size:
                    break
                descriptions[name] = text
            index = 0
            while len(descriptions) < size:
                service = ('stripe', 'square', 'shopify', 'zendesk', 'salesforce', 'github')[index % 6]
                operation = ('list invoices', 'get payment details', 'create invoice', 'search disputes', 'list transactions', 'resolve user')[index // 6 % 6]
                descriptions[f'{service}_operation_{index}'] = f'{service} {operation}; accepts service account, dates and pagination; dataset region {index}.'
                index += 1
            started = time.perf_counter()
            discovery = ToolDiscovery(registry, embeddings, dimensions, descriptions=descriptions)
            indexing = time.perf_counter() - started
            hits, latencies, misses = 0, [], []
            for query, target in LABELED:
                started = time.perf_counter()
                candidates = await discovery.candidates(query)
                latencies.append(time.perf_counter() - started)
                found = target in [row['id'] for row in candidates]
                hits += found
                if not found:
                    misses.append({'query': query, 'target': target, 'candidates': [r['id'] for r in candidates]})
            unavailable = next(name for name in official if name in descriptions)
            metadata_candidates = await discovery.candidates(descriptions[unavailable])
            ambiguous = await discovery.candidates('create invoice recipient amount currency')
            reports.append({'catalog_size': size, 'queries': len(LABELED), 'recall_at_5': hits / len(LABELED),
                'mean_query_ms': round(sum(latencies) / len(latencies) * 1000, 3), 'index_ms': round(indexing * 1000, 3),
                'embedding_document_calls': size, 'embedding_query_calls': len(LABELED) + 2,
                'unavailable_candidate_remains_non_executable': any(r['id'] == unavailable and not r['executable'] for r in metadata_candidates),
                'ambiguous_candidates': [r['id'] for r in ambiguous], 'misses': misses})
    return {'mode': 'offline_hash_smoke' if offline else 'live_provider_embeddings',
            'limitations': 'Synthetic distractors; offline hashes do not measure semantic-model or live-agent quality.',
            'target_recall_at_5': .95, 'target_is_project_assumption': True, 'results': reports,
            'passed': all(r['recall_at_5'] >= .95 and r['unavailable_candidate_remains_non_executable'] for r in reports)}

WRITE_TOOLS = {'paypal_create_invoice', 'paypal_send_invoice'}


def safe_simulated_approval(approval):
    return approval.get('origin') == 'simulated' and approval.get('tool_name') in WRITE_TOOLS


def completed(traces, name):
    return [row for row in traces if row['tool_name'] == name and row['status'] == 'completed']


def pages(traces, name, expected):
    return {row['arguments'].get('page', 1) for row in completed(traces, name)} == set(expected)


def check_task(name, outcome, traces, status_reads):
    """Fixed facts and execution evidence, without an LLM judging another LLM."""
    answer = outcome.content.lower()
    writes = [row for row in traces if row['tool_name'] in WRITE_TOOLS and row['status'] == 'completed']
    if name == 'invoice_approve':
        return outcome.status == 'completed' and {row['tool_name'] for row in writes} == WRITE_TOOLS and 'simulat' in answer
    if name == 'invoice_reject':
        return outcome.status == 'rejected' and not writes and any(row['status'] == 'rejected' for row in traces)
    if name in {'missing_recipient', 'missing_currency', 'ambiguity'}:
        field = {'missing_recipient': 'recipient', 'missing_currency': 'currency', 'ambiguity': 'which'}[name]
        return outcome.status == 'completed' and not writes and not any(row['status'] == 'awaiting_approval' for row in traces) and (field in answer or (name == 'ambiguity' and 'clarif' in answer))
    if name == 'sales':
        return outcome.status == 'completed' and 'usd' in answer and '150' in answer and 'eur' in answer and '20' in answer and pages(traces, 'paypal_list_transactions', [1, 2, 3])
    if name == 'disputes':
        resolved = completed(traces, 'paypal_resolve_user')
        disputed = completed(traces, 'paypal_list_disputes')
        return outcome.status == 'completed' and 'd1' in answer and 'd3' in answer and bool(resolved) and resolved[0]['arguments'].get('user_id') == 'user_123' and pages(traces, 'paypal_list_disputes', [1, 2]) and all(row['arguments'].get('payer_id') == 'PAYER123' for row in disputed)
    if name == 'rag':
        return outcome.status == 'completed' and ('two business days' in answer or '2 business days' in answer) and 'support.txt' in answer and bool(completed(traces, 'retrieve_knowledge'))
    if name == 'status':
        return outcome.status == 'completed' and bool(status_reads) and 'fixture-status-42' in answer and any(row['arguments'].get('mode') == 'status' for row in completed(traces, 'system_search'))
    if name == 'bad_invoice':
        return outcome.status == 'failed' and any(row['tool_name'] == 'paypal_send_invoice' and row['status'] == 'failed' for row in traces)
    return False


TASKS = [
    ('invoice_approve', 'Create and send a simulated PayPal invoice to eval@example.com for 50 USD.', 'approve'),
    ('invoice_reject', 'Create a simulated PayPal invoice to eval@example.com for 50 USD.', 'reject'),
    ('missing_recipient', 'Create a simulated PayPal invoice for 50 USD. Ask me for missing fields.', 'approve'),
    ('missing_currency', 'Create a simulated PayPal invoice to eval@example.com for 50. Ask me for missing fields.', 'approve'),
    ('sales', 'What was total PayPal gross completed sales volume in October 2026? Retrieve all pages and total separately by currency.', 'approve'),
    ('disputes', 'Find all open PayPal disputes for application user user_123. Resolve the payer and retrieve every page.', 'approve'),
    ('rag', 'According to the sample support policy, how soon does standard support respond? Cite the source.', 'approve'),
    ('status', 'Show the status of my previous requests in this conversation.', 'approve'),
    ('bad_invoice', 'Send simulated PayPal invoice SIM-INV-does-not-exist.', 'approve'),
    ('ambiguity', 'Create an invoice. Clarify which service and missing details before executing.', 'approve'),
]


async def run_tasks():
    from langchain_core.messages import HumanMessage
    from agent_backend.agent.runtime import build_business_agent
    results = []
    with TemporaryDirectory() as directory:
        agent = build_business_agent(demo_path=Path(directory) / 'paypal.db')
        agent.clock = lambda: date(2026, 11, 11)
        for name, prompt, decision in TASKS:
            traces, status_reads = [], []
            def status():
                status_reads.append(True)
                return [{'request_id': 'fixture-status-42', 'status': 'completed'}]
            run_id = str(uuid4())
            outcome = await agent.run([HumanMessage(content=prompt)], run_id=run_id, on_trace=traces.append, on_status=status)
            approvals = 0
            while outcome.status == 'awaiting_approval':
                if not safe_simulated_approval(outcome.approval or {}) or approvals >= 4:
                    raise RuntimeError('Evaluation refused an unexpected approval; only simulated PayPal writes are allowed')
                approvals += 1
                outcome = await agent.run(run_id=run_id, decision=decision, on_trace=traces.append, on_status=status)
            results.append({'task': name, 'passed': check_task(name, outcome, traces, status_reads), 'status': outcome.status, 'answer': outcome.content, 'traces': traces})
    return {'mode': 'live_agent_tasks', 'limitations': 'Fixed fixture assertions, not a general agent-quality claim; provider calls are opt-in.', 'results': results, 'passed': all(row['passed'] for row in results)}


async def evaluate(mode='offline'):
    if mode == 'tasks':
        return await run_tasks()
    if mode == 'discovery':
        from agent_backend.tools.rag import create_embeddings
        return await run_benchmark(create_embeddings(1536), dimensions=1536)
    return await run_benchmark()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['offline', 'discovery', 'tasks'], default='offline')
    parser.add_argument('--output', type=Path, help='Write the JSON report to this path')
    args = parser.parse_args(argv)
    report = asyncio.run(evaluate(args.mode))
    payload = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + '\n', encoding='utf-8')
    print(payload)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
