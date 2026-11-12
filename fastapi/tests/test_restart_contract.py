"""Offline upgrade fixtures exercise application recovery, not saved user state."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain.tools import tool
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from agent_backend.agent.graph import BusinessAgent
from agent_backend.database import initialize_schema
from agent_backend.main import lifespan
from agent_backend.models import AgentRun, Conversation, Message, RequestRecord, ToolTrace
from test_agent import Model, call


class RestartContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_application_recovery_keeps_pending_questions(self):
        from test_clarification import QUESTIONS, ANSWERS
        import json
        from agent_backend.routers.chat import pending_clarification
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = create_engine('sqlite:///' + str(root / 'app.db'))
            initialize_schema(engine)
            app = SimpleNamespace(state=SimpleNamespace())
            try:
                async with AsyncSqliteSaver.from_conn_string(str(root / 'agent-checkpoints.db')) as saver:
                    agent = BusinessAgent(Model([call('ask_user', {'questions': QUESTIONS})]), None, {}, checkpointer=saver)
                    pause = await agent.run([], run_id='questions')
                with Session(engine) as db:
                    db.add(Conversation(id=1, title='questions'))
                    db.add(Message(id=1, conversation_id=1, role='assistant', content='Which currency?'))
                    db.add(AgentRun(id='questions', conversation_id=1, assistant_message_id=1, status='awaiting_input',
                        engine_version=agent.engine_version,
                        clarification_id=pause.clarification['clarification_id'],
                        clarification_payload=json.dumps({'run_id':'questions', **pause.clarification})))
                    db.commit()
                def factory(saver):
                    return BusinessAgent(Model([AIMessage(content='EUR selected')]), None, {}, checkpointer=saver)
                with patch('agent_backend.database.initialize_schema', lambda: initialize_schema(engine)), \
                     patch('agent_backend.database.DB_PATH', root / 'app.db'), \
                     patch('agent_backend.database.SessionLocal', sessionmaker(bind=engine)), \
                     patch('agent_backend.agent.runtime.build_business_agent', factory):
                    async with lifespan(app):
                        with Session(engine) as db:
                            self.assertEqual(db.get(AgentRun, 'questions').status, 'awaiting_input')
                            self.assertEqual(db.get(RequestRecord, 'questions').status, 'awaiting_input')
                            self.assertEqual((await pending_clarification(1, db))['questions'], QUESTIONS)
                        result = await app.state.business_agent.run(run_id='questions', decision=ANSWERS)
                        self.assertEqual(result.content, 'EUR selected')
            finally:
                engine.dispose()

    async def test_application_recovery_preserves_pending_checkpoint_and_fails_active_records(self):
        effects = []

        @tool
        def remote(value: int) -> str:
            """Read an approved remote value."""
            effects.append(value)
            return str(value)

        remote.metadata = {'origin': 'api'}

        class Discovery:
            async def search(self, query):
                return ['remote']

        with tempfile.TemporaryDirectory() as directory:
            app = SimpleNamespace(state=SimpleNamespace())
            root = Path(directory)
            engine = create_engine('sqlite:///' + str(root / 'app.db'))
            initialize_schema(engine)
            try:
                async with AsyncSqliteSaver.from_conn_string(str(root / 'agent-checkpoints.db')) as saver:
                    agent = BusinessAgent(Model([call('system_search', {'query': 'remote'}, 'search'),
                        call('remote', {'value': 7}, 'remote-7')]), Discovery(), {'remote': remote}, checkpointer=saver)
                    paused = await agent.run([], run_id='pending')
                    before = await agent.graph.aget_state({'configurable': {'thread_id': 'lc:pending'}})
                    self.assertEqual(paused.status, 'awaiting_approval')
                with Session(engine) as db:
                    for number, status in [(1, 'awaiting_approval'), (2, 'running')]:
                        db.add(Conversation(id=number, title=status))
                        db.add(Message(id=number, conversation_id=number, role='assistant', content=''))
                        run_id = 'pending' if number == 1 else 'interrupted'
                        db.add(AgentRun(id=run_id, conversation_id=number, assistant_message_id=number,
                            status=status, engine_version=agent.engine_version,
                            approval_id=paused.approval['approval_id'] if number == 1 else None))
                        db.add(RequestRecord(id=run_id, conversation_id=number, assistant_message_id=number, status=status))
                        db.add(ToolTrace(id=run_id+':remote-7', message_id=number, call_id='remote-7', tool_name='remote',
                            status='awaiting_approval' if number == 1 else 'running'))
                    db.commit()

                def factory(saver):
                    return BusinessAgent(Model([AIMessage(content='done')]), Discovery(), {'remote': remote}, checkpointer=saver)

                with patch('agent_backend.database.initialize_schema', lambda: initialize_schema(engine)), \
                     patch('agent_backend.database.DB_PATH', root / 'app.db'), \
                     patch('agent_backend.database.SessionLocal', sessionmaker(bind=engine)), \
                     patch('agent_backend.agent.runtime.build_business_agent', factory):
                    async with lifespan(app):
                        with Session(engine) as db:
                            self.assertEqual(db.get(AgentRun, 'pending').status, 'awaiting_approval')
                            self.assertEqual(db.get(AgentRun, 'interrupted').status, 'failed')
                            self.assertEqual(db.get(RequestRecord, 'interrupted').status, 'failed')
                            self.assertEqual(db.query(ToolTrace).filter_by(message_id=2).one().status, 'failed')
                            self.assertEqual(db.query(ToolTrace).filter_by(message_id=1).one().status, 'awaiting_approval')
                        self.assertEqual(effects, [])
                        restored = app.state.business_agent
                        snapshot = await restored.graph.aget_state({'configurable': {'thread_id': 'lc:pending'}})
                        self.assertEqual(snapshot.values['thread_model_call_count'], before.values['thread_model_call_count'])
                        self.assertEqual(snapshot.values['remaining'], before.values['remaining'])
                        result = await restored.run(run_id='pending', decision='approve')
                        self.assertEqual(result.status, 'completed')
                        self.assertEqual(effects, [7])
            finally:
                engine.dispose()

    async def test_application_retires_pending_runs_from_previous_engines(self):
        from agent_backend.schemas import ChatRequest
        from agent_backend.routers.chat import chat_endpoint, pending_approval, pending_clarification
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = create_engine('sqlite:///' + str(root / 'app.db'))
            initialize_schema(engine)
            try:
                with Session(engine) as db:
                    for cid, run_id, status, version in [
                        (1, 'old-approval', 'awaiting_approval', 'langchain-v1'),
                        (2, 'old-question', 'awaiting_input', 'legacy'),
                    ]:
                        db.add(Conversation(id=cid, title=run_id))
                        db.add(Message(id=cid, conversation_id=cid, role='assistant', content='Which account?'))
                        db.add(AgentRun(id=run_id, conversation_id=cid, assistant_message_id=cid, status=status,
                            engine_version=version, approval_id='approval-id', approval_payload='{}',
                            clarification_id='clarification-id', clarification_payload='{}'))
                        db.add(RequestRecord(id=run_id, conversation_id=cid, assistant_message_id=cid,
                            status=status, engine_version=version))
                        db.add(ToolTrace(id=run_id + ':call', message_id=cid, call_id='call', tool_name='remote',
                            status='awaiting_approval'))
                    db.commit()

                def factory(saver):
                    return BusinessAgent(Model([AIMessage(content='unused')]), None, {}, checkpointer=saver)
                app = SimpleNamespace(state=SimpleNamespace())
                with patch('agent_backend.database.initialize_schema', lambda: initialize_schema(engine)), \
                     patch('agent_backend.database.DB_PATH', root / 'app.db'), \
                     patch('agent_backend.database.SessionLocal', sessionmaker(bind=engine)), \
                     patch('agent_backend.agent.runtime.build_business_agent', factory):
                    for startup in range(2):
                        async with lifespan(app):
                            with Session(engine) as db:
                                for cid, run_id in [(1, 'old-approval'), (2, 'old-question')]:
                                    run = db.get(AgentRun, run_id) if startup == 0 else None
                                    self.assertEqual(run.status if run else db.query(AgentRun).filter_by(conversation_id=cid).one().status, 'failed')
                                    record = db.get(RequestRecord, run_id)
                                    self.assertEqual(record.status, 'failed')
                                    message = db.get(Message, cid)
                                    self.assertIn('Which account?', message.content)
                                    self.assertEqual(message.content.count('agent engine upgrade'), 1)
                                    self.assertEqual(db.query(ToolTrace).filter_by(message_id=cid).one().status, 'failed')
                                    if startup == 0:
                                        self.assertIsNone(run.approval_id)
                                        self.assertIsNone(run.approval_payload)
                                        self.assertIsNone(run.clarification_id)
                                        self.assertIsNone(run.clarification_payload)
                                self.assertIsNone(await pending_approval(1, db))
                                self.assertIsNone(await pending_clarification(2, db))
                                if startup == 1:
                                    app.state.registry_agent_manager = None
                                    response = await chat_endpoint(ChatRequest(message='start fresh', conversation_id=1),
                                                                   SimpleNamespace(app=app), db)
                                    _ = [chunk async for chunk in response.body_iterator]
                                    self.assertEqual(db.get(RequestRecord, 'old-approval').status, 'failed')
                                    current = db.query(AgentRun).filter_by(conversation_id=1).one()
                                    self.assertEqual(current.engine_version, app.state.business_agent.engine_version)
                                    self.assertEqual(current.status, 'completed')
            finally:
                engine.dispose()

    async def test_changed_registry_blocks_legacy_pending_effect(self):
        effects = []

        @tool
        def remote(value: int) -> str:
            """Read remote value."""
            effects.append(value)
            return str(value)

        remote.metadata = {'origin': 'api', 'configuration_hash': 'old'}
        class Discovery:
            async def search(self, query): return ['remote']
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'legacy.db')
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                agent = BusinessAgent(Model([call('system_search', {'query': 'remote'}), call('remote', {'value': 1}, 'effect')]),
                    Discovery(), {'remote': remote}, checkpointer=saver)
                self.assertEqual((await agent.run([], run_id='legacy')).status, 'awaiting_approval')
            remote.metadata = {'origin': 'api', 'configuration_hash': 'changed'}
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                agent = BusinessAgent(Model([]), Discovery(), {'remote': remote}, checkpointer=saver)
                result = await agent.run(run_id='legacy', decision='approve')
                self.assertEqual(result.status, 'failed')
                self.assertIn('configuration changed', result.content)
                self.assertEqual(effects, [])
