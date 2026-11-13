import asyncio
import json
import unittest
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from agent_backend.models import Base, Message
from agent_backend.routers.chat import chat_endpoint, get_conversation
from agent_backend.schemas import ChatRequest, ConversationRead
from agent_backend.agent.graph import Outcome
from agent_backend.utils.traces import preview


class TraceTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_agent_approval_resume_and_repeated_calls(self):
        from langchain.tools import tool
        from langchain_core.messages import AIMessage
        from agent_backend.agent.graph import BusinessAgent
        from agent_backend.routers.chat import resume_approval, ApprovalDecision
        from test_agent import Model, call

        @tool
        def todo(id: int) -> str:
            """Read a todo."""
            return 'todo title'
        todo.metadata = {'origin': 'api'}
        class Discovery:
            async def search(self, query): return ['todo']
        model = Model([call('system_search', {'query': 'todo'}, 'discovery'),
                       AIMessage(content='', tool_calls=[{'name': 'todo', 'args': {'id': 1}, 'id': 'a'}, {'name': 'todo', 'args': {'id': 2}, 'id': 'b'}]),
                       AIMessage(content='done')])
        agent = BusinessAgent(model, Discovery(), {'todo': todo})
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(business_agent=agent)))
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        with Session(engine) as db:
            response = await chat_endpoint(ChatRequest(message='todos'), request, db)
            events = [json.loads(chunk[6:]) async for chunk in response.body_iterator if '[DONE]' not in chunk]
            cid = events[0]['conversation_id']
            first = events[-1]['approval_required']
            self.assertEqual([item['tool_call_id'] for item in first['calls']], ['a', 'b'])
            response = await resume_approval(cid, first['approval_id'], ApprovalDecision(decisions=[
                {'tool_call_id': 'a', 'decision': 'approve'},
                {'tool_call_id': 'b', 'decision': 'reject'},
            ]), request, db)
            _ = [chunk async for chunk in response.body_iterator]
        with Session(engine) as db:
            saved = ConversationRead.model_validate(await get_conversation(cid, db))
            self.assertEqual([t.call_id for t in saved.messages[-1].traces], ['discovery', 'a', 'b'])
            self.assertEqual([t.status for t in saved.messages[-1].traces], ['completed', 'completed', 'rejected'])

    async def test_interruption_retains_failed_trace(self):
        started = asyncio.Event()
        class Agent:
            async def run(self, history, on_trace=None, **kwargs):
                on_trace({'call_id': 'slow', 'tool_name': 'slow', 'status': 'running'})
                started.set()
                await asyncio.Event().wait()
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(business_agent=Agent())))
        with Session(engine) as db:
            response = await chat_endpoint(ChatRequest(message='slow'), request, db)
            cid = json.loads((await anext(response.body_iterator))[6:])['conversation_id']
            await anext(response.body_iterator)
            await started.wait()
            await response.body_iterator.aclose()
        with Session(engine) as db:
            saved = ConversationRead.model_validate(await get_conversation(cid, db))
            self.assertEqual(saved.messages[-1].traces[0].status, 'failed')
            self.assertIn('interrupted', saved.messages[-1].content)

    def test_redaction_and_bounded_previews(self):
        from agent_backend.utils.traces import redact
        for value in [
            {'nested': {'Authorization': 'hidden'}},
            '{"access_token":"hidden"}',
            "{'password': 'hidden'}",
            'response: {"api_key": "hidden"}',
            'https://user:hidden@example.test/?token=hidden&ok=yes',
            'Authorization: Bearer hidden',
        ]:
            self.assertNotIn('hidden', preview(value))
        safe = redact({'authorization': 'Bearer hidden', 'nested': ['token=hidden', {'ok': 'yes'}]})
        self.assertEqual(safe, {'authorization': '[redacted]', 'nested': ['token=[redacted]', {'ok': 'yes'}]})
        self.assertTrue(preview('x' * 13000).endswith('[truncated]'))
        self.assertIn('[truncated]', preview(list(range(101))))

    async def test_live_events_saved_before_answer_and_retained_across_turns(self):
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        release = asyncio.Event()

        class Agent:
            async def run(self, history, on_trace=None, **kwargs):
                on_trace({'call_id': 'todo', 'tool_name': 'get_todo', 'status': 'running',
                          'arguments': {'id': 1, 'api_key': 'do-not-save'}})
                await release.wait()
                on_trace({'call_id': 'todo', 'tool_name': 'get_todo', 'status': 'completed',
                          'result': '{"title":"todo", "token":"do-not-save"}', 'duration_ms': 12})
                return Outcome('completed', 'todo')

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(business_agent=Agent())))
        with Session(engine) as db:
            response = await chat_endpoint(ChatRequest(message='todo'), request, db)
            cid = json.loads((await anext(response.body_iterator))[6:])['conversation_id']
            live = json.loads((await anext(response.body_iterator))[6:])['trace']
            self.assertEqual(live['status'], 'running')
            self.assertNotIn('do-not-save', json.dumps(live))
            self.assertEqual(db.query(Message).order_by(Message.id.desc()).first().content, '')
            release.set()
            rest = [chunk async for chunk in response.body_iterator]
            self.assertNotIn('do-not-save', ''.join(rest))
            response = await chat_endpoint(ChatRequest(message='again', conversation_id=cid), request, db)
            _ = [chunk async for chunk in response.body_iterator]
        with Session(engine) as db:
            saved = ConversationRead.model_validate(await get_conversation(cid, db)).model_dump()
            assistants = [m for m in saved['messages'] if m['role'] == 'assistant']
            self.assertEqual([len(m['traces']) for m in assistants], [1, 1])
            self.assertEqual(assistants[0]['traces'][0]['status'], 'completed')
            self.assertNotIn('do-not-save', str(saved))
