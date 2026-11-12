import asyncio
import json
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import httpx
from fastapi import HTTPException
from agent_backend.routers import tool_registry as registry
from agent_backend.tools import registry_connections as connections


def config(**extra):
    return {'name': 'Example', 'kind': 'api', 'url': 'https://example.com/data', 'description': 'Records',
            'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query'], 'additionalProperties': False}, **extra}


class RegistryLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patcher = patch.object(registry, 'REGISTRY_PATH', Path(self.directory.name) / 'registry.json')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_edit_keeps_secret_but_requires_new_test_and_activation(self):
        created = registry.add_tool(config(api_key='private-key', auth_scheme='bearer'))
        with self.assertRaises(HTTPException):
            registry.edit_tool(created.id, {'enabled_tools': ['request']})
        metadata = [{'name': 'request', 'description': 'Records', 'input_schema': config()['input_schema']}]
        with patch.object(registry, 'test_connection', AsyncMock(return_value=metadata)):
            passed = asyncio.run(registry.test_tool(created.id, registry.TestArguments(arguments={'query': 'a'})))
        self.assertEqual(passed.status, 'passed')
        self.assertIsNotNone(passed.tested_at)
        active = registry.edit_tool(created.id, {'enabled_tools': ['request']})
        self.assertEqual(active.enabled_tools, ['request'])
        edited = registry.edit_tool(created.id, {'description': 'Edited'})
        self.assertEqual(edited.status, 'saved')
        self.assertEqual(edited.enabled_tools, [])
        self.assertEqual(registry.read_snapshot()[0]['api_key'], 'private-key')
        snapshot = registry.read_snapshot()
        snapshot[0]['name'] = 'Changed'
        self.assertEqual(registry.read_snapshot()[0]['name'], 'Example')

    def test_failure_is_saved_with_safe_diagnostic(self):
        created = registry.add_tool(config(api_key='private-key'))
        with patch.object(registry, 'test_connection', AsyncMock(side_effect=connections.ConnectionFailure('Connection timed out after 10 seconds'))):
            failed = asyncio.run(registry.test_tool(created.id, registry.TestArguments()))
        self.assertEqual(failed.status, 'failed')
        self.assertEqual(failed.tools, [])
        self.assertNotIn('private-key', failed.model_dump_json())

    def test_save_does_not_echo_invalid_secret(self):
        with self.assertRaises(HTTPException) as failure:
            registry.add_tool(config(api_key='private-key\r\nunsafe', auth_scheme='bearer'))
        self.assertNotIn('private-key', str(failure.exception.detail))

    def test_legacy_config_defaults_to_disabled(self):
        old = {**config(), 'id': str(uuid4()), 'auth_header': 'Authorization', 'api_key': None}
        registry.REGISTRY_PATH.write_text(json.dumps([old]))
        entry = registry.list_tools()[0]
        self.assertEqual(entry.status, 'saved')
        self.assertEqual(entry.enabled_tools, [])


class ConnectionTest(unittest.IsolatedAsyncioTestCase):
    async def request(self, response, **entry):
        def handler(request):
            self.assertEqual(request.url.host, '93.184.216.34')
            self.assertEqual(request.headers['host'], 'example.com')
            self.assertEqual(request.extensions['sni_hostname'], 'example.com')
            self.assertEqual(request.headers.get('authorization'), 'Bearer secret')
            return response
        with patch.object(connections, '_addresses', return_value=['93.184.216.34']), patch.object(httpx, 'AsyncHTTPTransport', return_value=httpx.MockTransport(handler)):
            return await connections.call_api(config(api_key='secret', auth_scheme='bearer', auth_header='X-Wrong', **entry), {'query': 'hello'})

    async def test_api_json_text_and_empty_success(self):
        self.assertEqual(await self.request(httpx.Response(200, json={'ok': True})), {'ok': True})
        self.assertEqual(await self.request(httpx.Response(200, text='healthy')), 'healthy')
        self.assertEqual(await self.request(httpx.Response(204)), '')

    async def test_redirect_error_and_oversize_are_rejected(self):
        for response in [httpx.Response(302, headers={'location': 'http://169.254.169.254'}), httpx.Response(403), httpx.Response(200, content=b'x' * (connections.LIMIT + 1))]:
            with self.subTest(status=response.status_code), self.assertRaises(connections.ConnectionFailure):
                await self.request(response)

    async def test_schema_rejects_extras_nested_and_nonfinite(self):
        for value in [{'query': 'a', 'extra': 1}, {'query': ['a']}]:
            with self.assertRaises(ValueError):
                connections.argument_model(config()['input_schema']).model_validate(value)
        with self.assertRaises(ValueError):
            connections.validate_schema({'type': 'object', 'properties': {'nested': {'type': 'object'}}})
        with self.assertRaises(ValueError):
            connections.argument_model({'type': 'object', 'properties': {'number': {'type': 'number'}}, 'required': ['number']}).model_validate({'number': float('nan')})

    async def test_non_get_and_timeout_fail_safely(self):
        with self.assertRaises(connections.ConnectionFailure):
            await connections.call_api(config(method='POST'), {'query': 'a'})
        class Client:
            async def __aenter__(self):
                raise TimeoutError('secret')
            async def __aexit__(self, *args):
                pass
        with patch.object(connections, 'safe_client', return_value=Client()):
            with self.assertRaisesRegex(connections.ConnectionFailure, 'timed out') as failure:
                await connections.call_api(config(), {'query': 'a'})
            self.assertNotIn('secret', str(failure.exception))

    async def test_mcp_discovery_is_not_execution_and_enabled_tools_reconnect(self):
        class Tool:
            name = 'a' * 100
            description = 'Find things'
            args_schema = {'type': 'object', 'properties': {}}
            ainvoke = AsyncMock(return_value={'ok': True})
        remote = Tool()
        adapter = SimpleNamespace(list_tools=AsyncMock(return_value=[remote]))
        opened = []
        @asynccontextmanager
        async def connection(entry):
            opened.append(entry['id'])
            yield adapter
        entry = config(id=str(uuid4()), kind='mcp', status='passed')
        with patch.object(connections, 'mcp_adapter', connection):
            tools = await connections.test_connection(entry, {})
            remote.ainvoke.assert_not_called()
            entry.update(tools=tools, enabled_tools=[remote.name])
            enabled = await connections.load_enabled_tools([entry])
            tool = next(iter(enabled.values()))
            self.assertLessEqual(len(tool.name), 64)
            self.assertEqual(await tool.ainvoke({}), {'ok': True})
            self.assertEqual(len(opened), 2)
            remote.ainvoke.assert_awaited_once()
            entry['enabled_tools'] = []
            self.assertEqual(await connections.load_enabled_tools([entry]), {})

    async def test_mcp_duplicate_definitions_fail(self):
        remote = SimpleNamespace(name='same', description='x', args_schema={'type': 'object'})
        @asynccontextmanager
        async def connection(entry):
            yield SimpleNamespace(list_tools=AsyncMock(return_value=[remote, remote]))
        with patch.object(connections, 'mcp_adapter', connection), self.assertRaises(connections.ConnectionFailure):
            await connections.test_connection(config(kind='mcp'), {})


class AddressPolicyTest(unittest.TestCase):
    def test_metadata_and_rebinding_are_blocked(self):
        for host, address in [('metadata.example', '169.254.169.254'), ('public.example', '127.0.0.1'), ('public.example', '192.168.1.2'), ('localhost', '93.184.216.34')]:
            with patch.object(connections.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', (address, 443))]), self.assertRaises(connections.ConnectionFailure):
                connections._addresses(host, 443)
        with patch.object(connections.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 8000))]):
            self.assertEqual(connections._addresses('localhost', 8000), ['127.0.0.1'])


if __name__ == '__main__':
    unittest.main()
