import asyncio
import json
import unittest
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from agent_backend.models import Base, Conversation, Message
from agent_backend.routers.chat import chat_endpoint
from agent_backend.schemas import ChatRequest
from agent_backend.agent.graph import Outcome

class ChatTest(unittest.IsolatedAsyncioTestCase):
    async def test_history_sse_and_persistence(self):
        engine=create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        class Agent:
            async def run(self, history, **kwargs):
                self.history=history
                return Outcome('completed','Verified fixture answer')
        agent=Agent()
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(business_agent=agent)))
        with Session(engine) as db:
            conversation=Conversation(title='existing')
            db.add(conversation)
            db.flush()
            db.add_all([Message(conversation_id=conversation.id,role='user',content='earlier'),Message(conversation_id=conversation.id,role='assistant',content='previous')])
            db.commit()
            response=await chat_endpoint(ChatRequest(message='now',conversation_id=conversation.id),request,db)
            events=[chunk async for chunk in response.body_iterator]
            self.assertEqual([m.content for m in agent.history],['earlier','previous','now'])
            self.assertEqual(events[-1],'data: [DONE]\n\n')
            self.assertEqual(json.loads(events[1][6:])['content'],'Verified fixture answer')
            self.assertEqual(db.query(Message).order_by(Message.id.desc()).first().content,'Verified fixture answer')
    async def test_disconnect_cancels_work(self):
        engine=create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        cancelled=asyncio.Event()
        started=asyncio.Event()
        class Agent:
            async def run(self, history, **kwargs):
                started.set()
                try:
                    await asyncio.sleep(100)
                finally:
                    cancelled.set()
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(business_agent=Agent())))
        with Session(engine) as db:
            response=await chat_endpoint(ChatRequest(message='hello'),request,db)
            await anext(response.body_iterator)
            task=asyncio.create_task(anext(response.body_iterator))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(cancelled.is_set())
            self.assertIn('interrupted',db.query(Message).order_by(Message.id.desc()).first().content)

    async def test_approval_api_claims(self):
        from fastapi import HTTPException
        from agent_backend.routers.chat import pending_approval, resume_approval, ApprovalDecision
        engine=create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        class Agent:
            async def run(self, history=None, **kwargs):
                if kwargs.get('decision'):
                    return Outcome('completed','approved result')
                return Outcome('awaiting_approval',approval={'approval_id':'approval','tool_name':'remote','origin':'api','arguments':{'id':1}})
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(business_agent=Agent())))
        with Session(engine) as db:
            response=await chat_endpoint(ChatRequest(message='external'),request,db)
            events=[chunk async for chunk in response.body_iterator]
            cid=json.loads(events[0][6:])['conversation_id']
            self.assertIn('approval_required',events[1])
            self.assertEqual(db.query(Message).order_by(Message.id.desc()).first().content,'')
            self.assertEqual((await pending_approval(cid,db))['approval_id'],'approval')
            with self.assertRaises(HTTPException):
                await chat_endpoint(ChatRequest(message='blocked',conversation_id=cid),request,db)
            response=await resume_approval(cid,'approval',ApprovalDecision(decision='approve'),request,db)
            with self.assertRaises(HTTPException):
                await resume_approval(cid,'approval',ApprovalDecision(decision='approve'),request,db)
            result=[chunk async for chunk in response.body_iterator]
            self.assertIn('approved result',result[1])
            self.assertIsNone(await pending_approval(cid,db))
            response=await chat_endpoint(ChatRequest(message='next',conversation_id=cid),request,db)
            await response.body_iterator.aclose()
