import unittest
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from agent_backend.models import Base, RequestRecord
from agent_backend.routers.chat import chat_endpoint
from agent_backend.schemas import ChatRequest
from agent_backend.agent.graph import Outcome


class RequestHistoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_previous_runs_survive_new_turns_and_are_scoped(self):
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        seen = []
        class Agent:
            async def run(self, history, on_status=None, **kwargs):
                seen.append(on_status())
                return Outcome('completed', 'done')
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(business_agent=Agent())))
        with Session(engine) as db:
            first = await chat_endpoint(ChatRequest(message='first'), request, db)
            _ = [x async for x in first.body_iterator]
            cid = db.query(RequestRecord).one().conversation_id
            second = await chat_endpoint(ChatRequest(message='second', conversation_id=cid), request, db)
            _ = [x async for x in second.body_iterator]
            self.assertEqual(db.query(RequestRecord).count(), 2)
            self.assertEqual(seen[0], [])
            self.assertEqual(seen[1][0]['status'], 'completed')
            other = await chat_endpoint(ChatRequest(message='other conversation'), request, db)
            _ = [x async for x in other.body_iterator]
            self.assertEqual(seen[-1], [])
