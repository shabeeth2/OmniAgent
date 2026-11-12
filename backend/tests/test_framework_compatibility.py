"""Offline check that the installed agent keeps thread limits across batch approval."""
import unittest

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, ModelCallLimitMiddleware
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command


class ToolCallingModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class FrameworkCompatibilityTest(unittest.IsolatedAsyncioTestCase):
    async def test_thread_model_limit_survives_batched_approval_resume(self):
        executed = []

        @tool
        def write_record(value: int) -> str:
            """Write a test record."""
            executed.append(value)
            return str(value)

        agent = create_agent(
            ToolCallingModel(responses=[
                AIMessage(content='', tool_calls=[{'name': 'write_record', 'args': {'value': 1}, 'id': 'write'}]),
                AIMessage(content='unexpected second model call'),
            ]),
            tools=[write_record],
            middleware=[ModelCallLimitMiddleware(thread_limit=1),
                        HumanInTheLoopMiddleware(interrupt_on={'write_record': True}, interrupt_mode='batched')],
            checkpointer=InMemorySaver(),
        )
        config = {'configurable': {'thread_id': 'limited'}}
        paused = await agent.ainvoke({'messages': [HumanMessage(content='write')]}, config)
        self.assertEqual(len(paused['__interrupt__']), 1)
        result = await agent.ainvoke(Command(resume={'decisions': [{'type': 'approve'}]}), config)
        self.assertEqual(executed, [1])
        snapshot = await agent.aget_state(config)
        self.assertEqual(snapshot.values['thread_model_call_count'], 1)
        self.assertNotEqual(result['messages'][-1].content, 'unexpected second model call')
