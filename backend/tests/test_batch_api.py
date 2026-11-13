import json
import unittest
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from agent_backend.database import initialize_schema
from agent_backend.models import AgentRun, RequestRecord
from agent_backend.schemas import ChatRequest
from agent_backend.agent.graph import Outcome
from agent_backend.routers.chat import chat_endpoint, resume_approval, ApprovalDecision


class BatchApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_complete_decisions_and_engine_history(self):
        class Agent:
            engine_version = 'langchain-batched-v1'
            async def run(self, history=None, **kwargs):
                if kwargs.get('decision'):
                    self.decision = kwargs['decision']
                    return Outcome('completed', 'done')
                return Outcome('awaiting_approval', approval={'approval_id': 'batch', 'calls': [
                    {'tool_call_id': id, 'tool_name': 'write', 'origin': 'mcp', 'arguments': {}} for id in ['a', 'b']]})
        agent = Agent()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(business_agent=agent)))
        engine = create_engine('sqlite:///:memory:')
        initialize_schema(engine)
        self.addCleanup(engine.dispose)
        with Session(engine) as db:
            response = await chat_endpoint(ChatRequest(message='writes'), request, db)
            chunks = [chunk async for chunk in response.body_iterator]
            cid = json.loads(chunks[0][6:])['conversation_id']
            for ids in [['a'], ['a', 'a'], ['a', 'foreign']]:
                body = ApprovalDecision(decisions=[{'tool_call_id': id, 'decision': 'approve'} for id in ids])
                with self.assertRaises(HTTPException) as error:
                    await resume_approval(cid, 'batch', body, request, db)
                self.assertEqual(error.exception.status_code, 422)
                self.assertEqual(db.query(AgentRun).one().status, 'awaiting_approval')
            body = ApprovalDecision(decisions=[{'tool_call_id': 'b', 'decision': 'reject'}, {'tool_call_id': 'a', 'decision': 'approve'}])
            response = await resume_approval(cid, 'batch', body, request, db)
            _ = [chunk async for chunk in response.body_iterator]
            self.assertEqual(agent.decision['decisions'][0]['decision'], 'reject')
            self.assertEqual(db.query(RequestRecord).one().engine_version, 'langchain-batched-v1')
            with self.assertRaises(HTTPException):
                await resume_approval(cid, 'batch', body, request, db)

    def test_additive_engine_migration_defaults_old_rows_to_legacy(self):
        from sqlalchemy import text
        engine = create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        with engine.begin() as db:
            db.execute(text('CREATE TABLE agent_runs (id TEXT PRIMARY KEY)'))
            db.execute(text("INSERT INTO agent_runs VALUES ('old')"))
            db.execute(text('CREATE TABLE request_records (id TEXT PRIMARY KEY)'))
            db.execute(text("INSERT INTO request_records VALUES ('old')"))
        initialize_schema(engine)
        initialize_schema(engine)
        with engine.connect() as db:
            for table in ['agent_runs', 'request_records']:
                self.assertEqual(db.execute(text(f'SELECT engine_version FROM {table}')).scalar(), 'legacy')
