import unittest
import json
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace
from pydantic import ValidationError
from agent_backend.agent.presentation import Presentation, build_surface
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from pydantic import Field


class Model(FakeMessagesListChatModel):
    bound: list = Field(default_factory=list)

    def __init__(self, responses):
        super().__init__(responses=responses)

    def bind_tools(self, tools, **kwargs):
        self.bound.append([tool.name for tool in tools])
        return self


def call(name, args, id='1'):
    return AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': id}])


class Discovery:
    async def search(self, query):
        return []


def sample():
    return {'title': 'Sales', 'source': 'User supplied example', 'components': [
        {'id': 'root', 'component': 'Column', 'children': ['metric']},
        {'id': 'metric', 'component': 'Metric', 'label': 'Total USD', 'value': '125'},
    ]}


class PresentationTest(unittest.TestCase):
    def test_surface_uses_versioned_catalog(self):
        surface = build_surface(Presentation.model_validate(sample()), 'call-1')
        self.assertEqual(surface['messages'][0]['version'], 'v0.9')
        self.assertEqual(surface['messages'][0]['createSurface']['surfaceId'], 'call-1')
        self.assertEqual(surface['messages'][1]['updateComponents']['components'][0]['id'], 'root')

    def test_rejects_unsafe_or_broken_components(self):
        for component in [
            {'id': 'root', 'component': 'Button', 'action': 'send'},
            {'id': 'root', 'component': 'Text', 'text': 'https://example.com'},
            {'id': 'root', 'component': 'Column', 'children': ['missing']},
            {'id': 'root', 'component': 'Column', 'children': ['root']},
        ]:
            with self.subTest(component=component), self.assertRaises(ValidationError):
                Presentation.model_validate({**sample(), 'components': [component]})

    def test_limits_are_errors_not_truncation(self):
        with self.assertRaises(ValidationError):
            Presentation.model_validate({**sample(), 'components': [
                {'id': 'root', 'component': 'Table', 'columns': ['x'], 'rows': [['x']] * 201}]})
        with self.assertRaises(ValidationError):
            Presentation.model_validate({**sample(), 'components': sample()['components'] * 26})


class PresentationAgentTest(unittest.IsolatedAsyncioTestCase):
    async def test_always_available_and_four_surface_limit(self):
        from langchain_core.messages import AIMessage, HumanMessage
        from agent_backend.agent.graph import BusinessAgent
        model = Model([*[call('present_ui', sample(), f'chart-{i}') for i in range(5)], AIMessage(content='Summary')])
        outcome = await BusinessAgent(model, Discovery(), {}).run([HumanMessage(content='Show metrics')])
        self.assertEqual(len(outcome.ui_surfaces), 4)
        self.assertTrue(all('present_ui' in names for names in model.bound))
        self.assertEqual(outcome.status, 'failed')  # Fifth surface was rejected, not silently dropped.

    async def test_presentation_does_not_authorize_write_and_survives_restart(self):
        from langchain_core.messages import AIMessage, HumanMessage
        from langchain.tools import tool
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from agent_backend.agent.graph import BusinessAgent
        effects = []

        @tool
        def write_note() -> str:
            """Write a note."""
            effects.append('write')
            return 'Saved'

        write_note.metadata = {'origin': 'api', 'effect': 'write', 'specialist': True}
        model = Model([call('present_ui', sample()), call('write_note', {}, 'write'), AIMessage(content='Saved')])
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / 'checkpoints.db')
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                agent = BusinessAgent(model, Discovery(), {'write_note': write_note}, checkpointer=saver)
                first = await agent.run([HumanMessage(content='Chart then write')], run_id='persist')
                self.assertEqual(first.status, 'awaiting_approval')
                self.assertEqual(len(first.ui_surfaces), 1)
                self.assertEqual(effects, [])
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                resumed = await BusinessAgent(model, Discovery(), {'write_note': write_note}, checkpointer=saver).run(run_id='persist', decision='approve')
                self.assertEqual(resumed.status, 'completed')
                self.assertEqual(resumed.ui_surfaces, first.ui_surfaces)
                self.assertEqual(effects, ['write'])

    async def test_reserved_name_and_mixed_calls(self):
        from langchain_core.messages import AIMessage, HumanMessage
        from agent_backend.agent.graph import BusinessAgent
        from agent_backend.agent.presentation import present_ui
        with self.assertRaises(ValueError):
            BusinessAgent(Model([AIMessage(content='')]), Discovery(), {'present_ui': present_ui})
        model = Model([AIMessage(content='', tool_calls=[
            {'name': 'present_ui', 'args': sample(), 'id': 'a'},
            {'name': 'system_search', 'args': {}, 'id': 'b'},
        ]), AIMessage(content='No operations executed')])
        result = await BusinessAgent(model, Discovery(), {}).run([HumanMessage(content='test')])
        self.assertEqual(result.ui_surfaces, [])

    async def test_clarification_starts_new_surface_collection(self):
        from langchain_core.messages import HumanMessage
        from agent_backend.agent.graph import BusinessAgent
        model = Model([
            *[call('present_ui', sample(), f'before-{i}') for i in range(4)],
            call('ask_user', {'questions': [{'id': 'q', 'q': 'Which currency?', 'type': 'radio', 'options': ['USD', 'EUR']}]}, 'ask'),
            call('present_ui', sample(), 'after'), AIMessage(content='Updated USD summary'),
        ])
        agent = BusinessAgent(model, Discovery(), {})
        first = await agent.run([HumanMessage(content='Show visuals then ask')], run_id='clarify-ui')
        self.assertEqual(first.status, 'awaiting_input')
        self.assertEqual(len(first.ui_surfaces), 4)
        result = await agent.run(run_id='clarify-ui', decision={'answers': [
            {'question_id': 'q', 'selected': [0], 'custom': '', 'skipped': False},
        ]})
        self.assertEqual(result.status, 'completed')
        self.assertEqual([surface['id'] for surface in result.ui_surfaces], ['after'])

    async def test_sse_is_persisted_and_restored(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from agent_backend.database import initialize_schema
        from agent_backend.models import Message
        from agent_backend.schemas import ChatRequest, ConversationRead
        from agent_backend.routers.chat import chat_endpoint, get_conversation
        from agent_backend.agent.graph import Outcome
        surface = build_surface(Presentation.model_validate(sample()), 'fixture')

        class Agent:
            async def run(self, history, **kwargs):
                return Outcome('completed', 'Total USD 125', ui_surfaces=[surface])

        engine = create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        initialize_schema(engine)
        initialize_schema(engine)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(business_agent=Agent())))
        with Session(engine) as db:
            response = await chat_endpoint(ChatRequest(message='chart'), request, db)
            events = []
            async for chunk in response.body_iterator:
                events.append(chunk)
                if 'ui_surfaces' in chunk:
                    self.assertEqual(db.query(Message).order_by(Message.id.desc()).first().ui_surfaces, [surface])
            cid = json.loads(events[0][6:])['conversation_id']
            restored = ConversationRead.model_validate(await get_conversation(cid, db))
            self.assertEqual(restored.messages[-1].ui_surfaces, [surface])
            self.assertEqual(restored.messages[0].ui_surfaces, [])
