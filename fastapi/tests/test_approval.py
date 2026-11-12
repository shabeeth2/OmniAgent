import tempfile
import unittest
from pathlib import Path
from langchain.tools import tool
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent_backend.agent.graph import BusinessAgent
from test_agent import Model, call

class ApprovalTest(unittest.IsolatedAsyncioTestCase):
    async def test_restart_batch_approval_with_mixed_decisions(self):
        executed=[]
        traces=[]
        @tool
        def remote(value: int, api_key: str) -> str:
            """Read external records."""
            executed.append(value)
            return str(value)
        remote.metadata={'origin':'mcp'}
        class Discovery:
            async def search(self,query): return ['remote']
        secret='Bearer never-expose-this'
        model=Model([call('system_search',{'query':'remote'}),AIMessage(content='',tool_calls=[
            {'name':'remote','args':{'value':1,'api_key':secret},'id':'a'},
            {'name':'remote','args':{'value':2,'api_key':secret},'id':'b'},
        ]),call('remote',{'value':2,'api_key':secret},'c'),AIMessage(content='done')])
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'checkpoints.db')
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                agent=BusinessAgent(model,Discovery(),{'remote':remote},checkpointer=saver)
                first=await agent.run([],run_id='run',on_trace=traces.append)
                self.assertEqual(first.status,'awaiting_approval')
                self.assertEqual([call['tool_call_id'] for call in first.approval['calls']], ['a', 'b'])
                self.assertEqual(first.approval['calls'][0]['arguments']['api_key'], '[redacted]')
                self.assertNotIn(secret, str(traces))
                paused_state=await agent.graph.aget_state({'configurable':{'thread_id':'lc:run'}})
                self.assertEqual(paused_state.values['executions'], 2)
                self.assertEqual(executed,[])
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                agent=BusinessAgent(model,Discovery(),{'remote':remote},checkpointer=saver)
                final=await agent.run(run_id='run',decision={'decisions':[
                    {'tool_call_id':'a','decision':'approve'}, {'tool_call_id':'b','decision':'reject'}]},on_trace=traces.append)
                self.assertEqual(final.status,'rejected')
                self.assertIn('rejected this exact operation', final.content)
                self.assertEqual(executed,[1])
                snapshot=await agent.graph.aget_state({'configurable':{'thread_id':'lc:run'}})
                self.assertEqual(snapshot.values['executions'],2)
                self.assertLessEqual(snapshot.values['remaining'],45)
                self.assertEqual([t['status'] for t in traces if t['call_id']=='a'], ['awaiting_approval','running','completed'])
                self.assertIn('rejected', [t['status'] for t in traces if t['call_id']=='b'])

    async def test_batch_approval_keeps_identical_call_ids_distinct(self):
        executed=[]
        @tool
        def remote(value: int) -> str:
            """Read external records."""
            executed.append(value)
            return str(value)
        remote.metadata={'origin':'mcp'}
        class Discovery:
            async def search(self,query): return ['remote']
        identical=AIMessage(content='',tool_calls=[
            {'name':'remote','args':{'value':1},'id':'first'},
            {'name':'remote','args':{'value':1},'id':'second'},
        ])
        model=Model([call('system_search',{'query':'remote'}),identical,AIMessage(content='done')])
        with tempfile.TemporaryDirectory() as directory:
            async with AsyncSqliteSaver.from_conn_string(str(Path(directory)/'checkpoints.db')) as saver:
                agent=BusinessAgent(model,Discovery(),{'remote':remote},checkpointer=saver)
                paused=await agent.run([],run_id='identical')
                self.assertEqual([c['tool_call_id'] for c in paused.approval['calls']],['first','second'])
                result=await agent.run(run_id='identical',decision={'decisions':[
                    {'tool_call_id':'first','decision':'reject'}, {'tool_call_id':'second','decision':'approve'}]})
        self.assertEqual(result.content,'done')
        self.assertEqual(executed,[1])
