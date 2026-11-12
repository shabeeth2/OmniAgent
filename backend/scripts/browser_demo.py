"""Offline browser fixture: scripted responses, temporary databases, no provider calls.

For UI verification only, not a replacement for live model evaluation.
Run from fastapi: .venv/Scripts/python scripts/browser_demo.py
"""
import json
import re
import os
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from agent_backend.agent.discovery import ToolDiscovery, catalog_descriptions
from scripts.evaluation import HashEmbeddings
from agent_backend.agent.graph import BusinessAgent
from agent_backend.database import Base, get_db
from agent_backend.routers import chat, tool_registry
from agent_backend.tools.business import create_business_tools
from agent_backend.tools.paypal_demo import create_paypal_tools
from agent_backend.tools.rag import NAMESPACE, create_store, create_retrieval_tool


class FixtureModel(BaseChatModel):
    model_name: str = 'offline-fixture'

    @property
    def _llm_type(self):
        return 'offline-fixture'

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        # Optional editorial hold for capturing the actual submitted-card UI.
        # Default is zero; this is never used by the production runtime.
        if isinstance(messages[-1], ToolMessage) and messages[-1].name in ('paypal_create_invoice', 'paypal_send_invoice'):
            time.sleep(min(6, max(0, float(os.getenv('AGENT_FIXTURE_CAPTURE_DELAY', '0')))))
        return ChatResult(generations=[ChatGeneration(message=self.scripted_response(messages))])

    def scripted_response(self, messages):
        current = max(i for i,m in enumerate(messages) if isinstance(m, HumanMessage))
        request = messages[current].content.lower()
        results = [m for m in messages[current+1:] if isinstance(m, ToolMessage)]
        def call(name, args):
            return AIMessage(content='', tool_calls=[{'name':name, 'args':args, 'id':f'fixture-{len(results)}'}])
        def final(text):
            return AIMessage(content=text)
        if 'batch approval' in request:
            if any(message.name == 'paypal_create_invoice' or 'User rejected the tool call' in str(message.content)
                   for message in results):
                created = [json.loads(message.content) for message in results
                           if message.name == 'paypal_create_invoice' and 'User rejected the tool call' not in str(message.content)]
                rejected = sum('User rejected the tool call' in str(message.content) for message in results)
                details = ', '.join(f"{item['invoice_id']} ({item['currency']} {item['amount']})" for item in created) or 'none'
                return final(f'Batch approval result: created drafts {details}; rejected calls {rejected}. Simulation only; no invoice was sent.')
            if not results:
                return call('system_search', {'query':'paypal create invoice draft'})
            if any('candidates' in json.loads(message.content) for message in results if str(message.content).startswith('{')):
                return AIMessage(content='', tool_calls=[
                    {'name':'paypal_create_invoice','args':{'recipient':'ada@example.test','amount':'10.00','currency':'USD'},'id':'fixture-batch-1'},
                    {'name':'paypal_create_invoice','args':{'recipient':'grace@example.test','amount':'20.00','currency':'EUR'},'id':'fixture-batch-2'},
                ])
            return final('The batch capability was unavailable in this fixture.')
        if 'clarification' in request:
            if results and results[-1].name == 'ask_user':
                data = json.loads(results[-1].content)
                return final('Offline clarification received (no external calls):\n\n' + '\n'.join(
                    answer['question'] + ': ' + ('Skipped; still unknown' if answer['skipped'] else
                        '; '.join(answer['selected_labels'] + ([answer['custom']] if answer['custom'] else [])))
                    for answer in data['answers']))
            return call('ask_user', {'questions': [
                {'id':'currency','q':'Which currency should the invoice use?','type':'radio','options':['USD','EUR','GBP']},
                {'id':'include','q':'What should the summary include?','type':'check','options':['Invoice details','Tool activity']},
                {'id':'recipient','q':'What is the recipient email?','type':'radio','options':[]},
            ]})
        if not results:
            if 'status' in request or 'previous' in request:
                return call('system_search', {'mode':'status'})
            if 'support' in request or 'knowledge' in request:
                return call('retrieve_knowledge', {'query':'support response time'})
            if 'invoice' in request and not re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+', request):
                return final('What recipient email and currency should I use? This is a simulation.')
            query = 'paypal create draft send invoice recipient currency' if 'invoice' in request else 'paypal gross sales volume transaction reporting' if 'sales' in request else 'paypal resolve user payer open disputes'
            return call('system_search', {'query':query})
        last = results[-1]
        if 'User rejected' in last.content:
            return final('The simulated operation was rejected. Any draft already created remains a draft; no real email was sent.')
        try:
            data = json.loads(last.content)
        except ValueError:
            return final(('Sample support policy: two business days. Source: support.txt.\n\n' if last.name == 'retrieve_knowledge' else 'The scripted fixture could not complete this step.\n\n')+last.content)
        if 'requests' in data:
            return final('Previous request status (local fixture):\n\n'+json.dumps(data['requests'], indent=2))
        if 'candidates' in data:
            if 'invoice' in request:
                draft = next((json.loads(m.content) for m in results if m.name == 'paypal_create_invoice'), None)
                if draft:
                    return call('paypal_send_invoice', {'invoice_id':draft['invoice_id']})
                email = re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+', request)[0].rstrip('.?,')
                money = re.search(r'\b(usd|eur|inr|gbp)\s+(\d+(?:\.\d{1,2})?)\b', request)
                if not money:
                    return final('What amount and currency should I use? This is a simulation.')
                return call('paypal_create_invoice', {'recipient':email, 'amount':f'{Decimal(money[2]):.2f}', 'currency':money[1].upper()})
            if 'sales' in request:
                return call('paypal_list_transactions', {'start_date':'2026-10-01','end_date':'2026-11-01','page':1})
            resolved = next((json.loads(m.content) for m in results if m.name == 'paypal_resolve_user'), None)
            if resolved:
                return call('paypal_list_disputes', {'payer_id':resolved['payer_id'],'page':1})
            return call('paypal_resolve_user', {'user_id':'user_123'})
        if last.name == 'paypal_create_invoice':
            return call('system_search', {'query':'Send the previously created PayPal invoice by invoice ID'})
        if last.name == 'paypal_send_invoice':
            return final(f"Simulated invoice {data['invoice_id']}: {data['currency']} {data['amount']}, {data['status']}. No real email or payment was sent.")
        if last.name == 'paypal_list_transactions':
            if data['next_page']:
                return call('paypal_list_transactions', {'start_date':'2026-10-01','end_date':'2026-11-01','page':data['next_page']})
            totals = {}
            for message in results:
                if message.name == 'paypal_list_transactions':
                    for row in json.loads(message.content)['transactions']:
                        if row['status']=='COMPLETED' and row['kind']=='SALE':
                            totals[row['currency']] = totals.get(row['currency'], Decimal(0))+Decimal(row['amount'])
            return final('Simulated October 2026 gross completed sales: '+', '.join(f'{c} {v:.2f}' for c,v in totals.items())+'. All three pages read; refunds and pending payments excluded.')
        if last.name == 'paypal_resolve_user':
            return call('system_search', {'query':'paypal_list_disputes list disputes for payer ID'})
        if last.name == 'paypal_list_disputes' and data['next_page']:
            return call('paypal_list_disputes', {'payer_id':'PAYER123','page':data['next_page']})
        return final('Simulated open disputes for user_123: D1 and D3. All pages read.')


@asynccontextmanager
async def lifespan(app):
    with TemporaryDirectory(prefix='agent-browser-fixture-') as directory:
        root = Path(directory)
        engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        def session():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_db] = session
        original_registry = tool_registry.REGISTRY_PATH
        tool_registry.REGISTRY_PATH = root/'registry.json'
        registry = {**create_business_tools(), **create_paypal_tools(root/'paypal.db')}
        store = create_store(HashEmbeddings(), 256)
        store.put(NAMESPACE, 'support', {'text':'Support responds within two business days.', 'citation':'support.txt'})
        registry['retrieve_knowledge'] = create_retrieval_tool(store)
        discovery = ToolDiscovery(registry, HashEmbeddings(), 256, descriptions=catalog_descriptions(registry))
        try:
            async with AsyncSqliteSaver.from_conn_string(str(root/'checkpoints.db')) as saver:
                app.state.business_agent = BusinessAgent(FixtureModel(), discovery, registry, checkpointer=saver)
                yield
        finally:
            tool_registry.REGISTRY_PATH = original_registry
            engine.dispose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000','http://127.0.0.1:3000'], allow_methods=['*'], allow_headers=['*'])
app.include_router(chat.router, prefix='/api')
app.include_router(tool_registry.router, prefix='/api')

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000)
