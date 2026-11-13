import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent_backend.agent.graph import BusinessAgent
from test_agent import Model, call, Discovery


QUESTIONS = [{'id': 'currency', 'q': 'Which currency?', 'type': 'radio', 'options': ['USD', 'EUR']}]
ANSWERS = {'answers': [{'question_id': 'currency', 'selected': [1], 'custom': '', 'skipped': False}]}


class ClarificationTest(unittest.IsolatedAsyncioTestCase):
    async def test_answers_still_require_external_call_approval(self):
        from langchain.tools import tool
        effects = []
        @tool
        def remote(currency: str) -> str:
            """Read remote currency records."""
            effects.append(currency)
            return currency
        remote.metadata = {'origin': 'api'}
        class RemoteDiscovery:
            async def search(self, query): return ['remote']
        model = Model([call('ask_user', {'questions': QUESTIONS}), call('system_search', {'query': 'remote'}, 'search'),
                       call('remote', {'currency': 'EUR'}, 'remote'), AIMessage(content='approved')])
        agent = BusinessAgent(model, RemoteDiscovery(), {'remote': remote})
        await agent.run([], run_id='approval-after-answer')
        result = await agent.run(run_id='approval-after-answer', decision=ANSWERS)
        self.assertEqual(result.status, 'awaiting_approval')
        self.assertEqual(effects, [])
        await agent.run(run_id='approval-after-answer', decision='approve')
        self.assertEqual(effects, ['EUR'])

    async def test_restart_and_answers_preserve_request_budget(self):
        class RecordingModel(Model):
            async def ainvoke(self, messages):
                object.__setattr__(self, 'messages', messages)
                return await super().ainvoke(messages)
        model = RecordingModel([call('ask_user', {'questions': QUESTIONS}), AIMessage(content='EUR selected')])
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'checkpoint.db')
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                agent = BusinessAgent(model, Discovery(), {}, checkpointer=saver)
                paused = await agent.run([HumanMessage(content='Send an invoice for $50')], run_id='clarify')
                self.assertEqual(paused.status, 'awaiting_input')
                self.assertEqual(paused.clarification['questions'], QUESTIONS)
                before = (await agent.graph.aget_state({'configurable': {'thread_id': 'lc:clarify'}})).values
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                agent = BusinessAgent(model, Discovery(), {}, checkpointer=saver)
                result = await agent.run(run_id='clarify', decision=ANSWERS)
                self.assertEqual(result.content, 'EUR selected')
                messages = [m for m in model.messages if isinstance(m, ToolMessage)]
                self.assertEqual(json.loads(messages[-1].content)['answers'][0]['selected'], [1])
                after = (await agent.graph.aget_state({'configurable': {'thread_id': 'lc:clarify'}})).values
                self.assertEqual(after['thread_model_call_count'], 2)
                self.assertEqual(after['executions'], 0)
                self.assertLessEqual(after['remaining'], before['remaining'])
                self.assertGreater(after['remaining'], before['remaining'] - 2)

    async def test_clear_request_does_not_pause(self):
        model = Model([AIMessage(content='Hello')])
        self.assertEqual((await BusinessAgent(model, Discovery(), {}).run([])).status, 'completed')
        self.assertIn('ask_user', model.bound[0])

    async def test_mixed_calls_execute_nothing(self):
        from langchain.tools import tool
        effects = []
        @tool
        def local() -> str:
            """A local action that must not run with a question."""
            effects.append(True)
            return 'done'
        local.metadata = {'origin': 'local'}
        mixed = AIMessage(content='', tool_calls=[
            {'name': 'ask_user', 'args': {'questions': QUESTIONS}, 'id': 'ask'},
            {'name': 'system_search', 'args': {'query': 'invoice'}, 'id': 'search'},
            {'name': 'local', 'args': {}, 'id': 'local'},
        ])
        model = Model([mixed, AIMessage(content='Please clarify')])
        agent = BusinessAgent(model, Discovery(), {'local': local})
        result = await agent.run([], run_id='mixed')
        self.assertEqual(result.status, 'failed')
        state = (await agent.graph.aget_state({'configurable': {'thread_id': 'lc:mixed'}})).values
        self.assertEqual(state['executions'], 0)
        self.assertEqual(state['discoveries'], 0)
        self.assertEqual(len([m for m in state['messages'] if isinstance(m, ToolMessage)]), 3)
        self.assertEqual(effects, [])

    async def test_skipped_answer_is_explicit(self):
        model = Model([call('ask_user', {'questions': QUESTIONS}), AIMessage(content='Currency is still needed')])
        agent = BusinessAgent(model, Discovery(), {})
        await agent.run([], run_id='skip')
        result = await agent.run(run_id='skip', decision={'answers': [
            {'question_id': 'currency', 'selected': [], 'custom': '', 'skipped': True}
        ]})
        self.assertEqual(result.content, 'Currency is still needed')
        state = (await agent.graph.aget_state({'configurable': {'thread_id': 'lc:skip'}})).values
        self.assertTrue(json.loads(next(m.content for m in state['messages'] if isinstance(m, ToolMessage)))['answers'][0]['skipped'])


class ClarificationApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_validation_claim_history_and_locks(self):
        from fastapi import HTTPException
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from agent_backend.models import Base, Message, AgentRun, RequestRecord
        from agent_backend.schemas import ChatRequest
        from agent_backend.agent.graph import Outcome
        from agent_backend.agent.clarification import Answers
        from agent_backend.routers.chat import chat_endpoint, pending_clarification, resume_clarification, delete_conversation
        class Agent:
            async def run(self, history=None, **kwargs):
                self.decision = kwargs.get('decision')
                if self.decision is not None:
                    return Outcome('completed', 'EUR selected')
                return Outcome('awaiting_input', clarification={'clarification_id': 'q1', 'questions': QUESTIONS})
        agent = Agent()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(business_agent=agent)))
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        with Session(engine) as db:
            response = await chat_endpoint(ChatRequest(message='invoice'), request, db)
            events = [chunk async for chunk in response.body_iterator]
            cid = json.loads(events[0][6:])['conversation_id']
            self.assertIn('clarification_required', ''.join(events))
            self.assertEqual((await pending_clarification(cid, db))['questions'], QUESTIONS)
            self.assertEqual(db.query(RequestRecord).one().status, 'awaiting_input')
            for action in [lambda: chat_endpoint(ChatRequest(message='blocked', conversation_id=cid), request, db),
                           lambda: delete_conversation(cid, db)]:
                with self.assertRaises(HTTPException) as error:
                    await action()
                self.assertEqual(error.exception.status_code, 409)
            for answers in [[{'question_id': 'currency', 'selected': [99], 'custom': '', 'skipped': False}],
                            [{'question_id': 'currency', 'selected': [], 'custom': '', 'skipped': False}]]:
                with self.assertRaises(HTTPException) as error:
                    await resume_clarification(cid, 'q1', Answers(answers=answers), request, db)
                self.assertEqual(error.exception.status_code, 422)
                self.assertEqual(db.query(AgentRun).one().status, 'awaiting_input')
            response = await resume_clarification(cid, 'q1', Answers(**ANSWERS), request, db)
            with self.assertRaises(HTTPException) as error:
                await resume_clarification(cid, 'q1', Answers(**ANSWERS), request, db)
            self.assertEqual(error.exception.status_code, 409)
            await anext(response.body_iterator)
            rest = [chunk async for chunk in response.body_iterator]
            self.assertIn('EUR selected', ''.join(rest))
            self.assertEqual(agent.decision, ANSWERS)
            self.assertIsNone(await pending_clarification(cid, db))
            rows = db.query(Message).order_by(Message.id).all()
            self.assertEqual([m.role for m in rows], ['user', 'assistant', 'user', 'assistant'])
            self.assertIn('Which currency?', rows[1].content)
            self.assertIn('EUR', rows[2].content)
            self.assertEqual(rows[3].content, 'EUR selected')


class AnswerValidationTest(unittest.TestCase):
    def test_rejects_malformed_answers_and_questions(self):
        from agent_backend.agent.clarification import Answers, Questions, validate_answers
        from pydantic import ValidationError
        for answers in [[], [{**ANSWERS['answers'][0], 'selected': [True]}], [{**ANSWERS['answers'][0], 'custom': 'x'*2001}]]:
            with self.assertRaises(ValidationError):
                Answers(answers=answers)
        for patch in [{'selected': [0, 1]}, {'selected': [1, 1]}, {'selected': [-1]}, {'selected': [1], 'skipped': True},
                      {'selected': [], 'skipped': False}, {'custom': 'GBP'}, {'question_id': 'unknown'}]:
            with self.assertRaises(ValueError):
                validate_answers(QUESTIONS, Answers(answers=[{**ANSWERS['answers'][0], **patch}]))
        with self.assertRaises(ValueError):
            validate_answers(QUESTIONS, Answers(answers=ANSWERS['answers'] * 2))
        for questions in [[], QUESTIONS * 2, [{**QUESTIONS[0], 'options': ['USD', 'USD']}], QUESTIONS * 4]:
            with self.assertRaises(ValidationError):
                Questions(questions=questions)

    def test_custom_and_multi_answers_have_labels(self):
        from agent_backend.agent.clarification import Answers, validate_answers
        questions = [{**QUESTIONS[0], 'type': 'check'}]
        result = validate_answers(questions, Answers(answers=[{**ANSWERS['answers'][0], 'selected': [0, 1], 'custom': ' GBP '}]))
        self.assertEqual(result[0]['selected_labels'], ['USD', 'EUR'])
        self.assertEqual(result[0]['custom'], 'GBP')
