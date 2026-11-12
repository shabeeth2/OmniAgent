"""Fixed-endpoint registry tools; remote configuration is never executable code."""
import asyncio
import importlib
import ipaddress
import json
import hashlib
import re
import socket
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from pydantic import ConfigDict, Field, create_model

LIMIT = 1_048_576
TIMEOUT = 10


class ConnectionFailure(ValueError):
    pass


def validate_schema(schema):
    if not isinstance(schema, dict) or set(schema) - {'type', 'properties', 'required', 'additionalProperties'}:
        raise ValueError('Input schema supports only type, properties, required, and additionalProperties')
    if schema.get('type') != 'object' or schema.get('additionalProperties', False) is not False:
        raise ValueError('Input schema must be an object with additionalProperties false')
    properties, required = schema.get('properties', {}), schema.get('required', [])
    if not isinstance(properties, dict) or len(properties) > 50 or not isinstance(required, list):
        raise ValueError('Input schema allows at most 50 properties and a required list')
    if any(not isinstance(key, str) or key not in properties for key in required):
        raise ValueError('Required names must exist in properties')
    for key, prop in properties.items():
        if not isinstance(key, str) or not key or len(key) > 100 or not isinstance(prop, dict):
            raise ValueError('Invalid input property')
        if set(prop) - {'type', 'description'} or prop.get('type') not in {'string', 'number', 'integer', 'boolean'}:
            raise ValueError('Only scalar input properties with type and description are supported')
        if 'description' in prop and (not isinstance(prop['description'], str) or len(prop['description']) > 1000):
            raise ValueError('Invalid input description')
    return {**schema, 'properties': properties, 'required': required, 'additionalProperties': False}


def argument_model(schema):
    schema = validate_schema(schema)
    types = {'string': str, 'number': float, 'integer': int, 'boolean': bool}
    fields = {}
    for name, prop in schema['properties'].items():
        annotation = types[prop['type']]
        default = ... if name in schema['required'] else None
        fields[name] = (annotation if default is ... else annotation | None,
                        Field(default=default, description=prop.get('description', '')))
    return create_model('QueryArguments', __config__=ConfigDict(extra='forbid', strict=True, allow_inf_nan=False), **fields)


def _headers(entry):
    scheme, key = entry.get('auth_scheme', 'none'), entry.get('api_key')
    if scheme == 'none':
        return {}
    if not key:
        raise ConnectionFailure('This authentication method requires an API key')
    return {'Authorization': f'Bearer {key}'} if scheme == 'bearer' else {entry.get('auth_header', 'Authorization'): key}


def _addresses(host, port):
    try:
        values = {result[4][0] for result in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except OSError:
        raise ConnectionFailure('The server hostname could not be resolved') from None
    explicit_loopback = host == 'localhost'
    try:
        explicit_loopback = explicit_loopback or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if not values:
        raise ConnectionFailure('The server hostname could not be resolved')
    for value in values:
        address = ipaddress.ip_address(value)
        if not (address.is_loopback if explicit_loopback else address.is_global):
            raise ConnectionFailure('Private, link-local, and reserved server addresses are blocked')
    return sorted(values)


def safe_client(entry, module=httpx, **kwargs):
    """Pin each request to a checked IP while preserving HTTP Host and TLS SNI."""
    endpoint = urlsplit(entry['url'])
    expected = (endpoint.hostname, endpoint.port or (443 if endpoint.scheme == 'https' else 80))

    class LimitedStream(module.AsyncByteStream):
        def __init__(self, stream):
            self.stream = stream

        async def __aiter__(self):
            size = 0
            async for chunk in self.stream:
                size += len(chunk)
                if size > LIMIT:
                    raise ConnectionFailure('Server response exceeded 1 MB')
                yield chunk

        async def aclose(self):
            await self.stream.aclose()

    class SafeTransport(module.AsyncBaseTransport):
        def __init__(self):
            self.transport = module.AsyncHTTPTransport()

        async def handle_async_request(self, request):
            host, port = request.url.host, request.url.port or (443 if request.url.scheme == 'https' else 80)
            if (host, port) != expected or request.url.scheme != endpoint.scheme:
                raise ConnectionFailure('Requests to another server are blocked')
            addresses = await asyncio.to_thread(_addresses, host, port)
            request.headers['accept-encoding'] = 'identity'
            pinned = module.Request(request.method, request.url.copy_with(host=addresses[0]),
                                    headers=request.headers, stream=request.stream,
                                    extensions={**request.extensions, 'sni_hostname': host})
            response = await self.transport.handle_async_request(pinned)
            if 300 <= response.status_code < 400:
                await response.aclose()
                raise ConnectionFailure('Server redirects are blocked')
            if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                await response.aclose()
                raise ConnectionFailure('Compressed server responses are unsupported')
            response.stream = LimitedStream(response.stream)
            return response

        async def aclose(self):
            await self.transport.aclose()

    kwargs.update(transport=SafeTransport(), follow_redirects=False, timeout=TIMEOUT, trust_env=False)
    return module.AsyncClient(**kwargs)


async def call_api(entry, arguments):
    if entry.get('method', 'GET') != 'GET':
        raise ConnectionFailure('Only GET API tools are supported')
    values = argument_model(entry['input_schema']).model_validate(arguments).model_dump(exclude_none=True)
    try:
        async with asyncio.timeout(TIMEOUT):
            async with safe_client(entry) as client:
                async with client.stream('GET', entry['url'], headers=_headers(entry), params=values) as response:
                    if response.status_code >= 400:
                        raise ConnectionFailure(f'Server returned HTTP {response.status_code}')
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > LIMIT:
                            raise ConnectionFailure('Server response exceeded 1 MB')
                        body.extend(chunk)
                    if not body:
                        return ''
                    media = response.headers.get('content-type', '').split(';')[0].strip().lower()
                    if media == 'application/json' or media.endswith('+json'):
                        return json.loads(body)
                    return body.decode(response.encoding or 'utf-8', errors='replace')
    except (ConnectionFailure, ValueError):
        raise
    except TimeoutError:
        raise ConnectionFailure('Connection timed out after 10 seconds') from None
    except Exception:
        raise ConnectionFailure('Could not complete the server request') from None


@asynccontextmanager
async def mcp_adapter(entry):
    from langchain.mcp import MCPAdapter
    from fastmcp.client.transports import StreamableHttpTransport
    try:
        module = importlib.import_module('httpx2')
    except ImportError:
        module = httpx

    def factory(**kwargs):
        return safe_client(entry, module=module, **kwargs)

    transport = StreamableHttpTransport(entry['url'], headers=_headers(entry),
                                       httpx_client_factory=factory, max_sse_event_size=LIMIT)
    async with MCPAdapter(transport) as adapter:
        yield adapter


def metadata(tool):
    schema = tool.args_schema
    if isinstance(schema, type):
        schema = schema.model_json_schema()
    return {'name': tool.name, 'description': tool.description or '', 'input_schema': schema or {'type': 'object', 'properties': {}}}


async def test_connection(entry, arguments):
    try:
        async with asyncio.timeout(TIMEOUT):
            if entry['kind'] == 'api':
                await call_api(entry, arguments)
                return [{'name': 'request', 'description': entry['description'] or entry['name'], 'input_schema': entry['input_schema']}]
            async with mcp_adapter(entry) as adapter:
                tools = [metadata(tool) for tool in await adapter.list_tools()]
                names = [item['name'] for item in tools]
                if any(not isinstance(name, str) or not name or len(name) > 256 for name in names) or len(set(names)) != len(names):
                    raise ConnectionFailure('Server returned invalid or duplicate tool names')
                from jsonschema import Draft202012Validator
                for item in tools:
                    if not isinstance(item['input_schema'], dict) or item['input_schema'].get('type') != 'object':
                        raise ConnectionFailure('Server returned invalid tool input schemas')
                    Draft202012Validator.check_schema(item['input_schema'])
                if len(json.dumps(tools).encode()) > LIMIT:
                    raise ConnectionFailure('Tool catalogue exceeded 1 MB')
                return tools
    except ConnectionFailure:
        raise
    except TimeoutError:
        raise ConnectionFailure('Connection timed out after 10 seconds') from None
    except Exception:
        raise ConnectionFailure('Connection or tool discovery failed; check endpoint and credentials') from None


def _build_tool(entry, item):
    from langchain_core.tools import StructuredTool
    upstream = item['name']
    slug = re.sub(r'[^A-Za-z0-9_-]', '_', upstream)[:20]
    digest = hashlib.sha256(upstream.encode()).hexdigest()[:8]
    name = f"r_{entry['id'].replace('-', '')}_{slug}_{digest}"

    async def invoke(**arguments):
        try:
            if len(json.dumps(arguments).encode()) > LIMIT:
                raise ConnectionFailure('Tool arguments exceeded 1 MB')
            async with asyncio.timeout(TIMEOUT):
                if entry['kind'] == 'api':
                    return await call_api(entry, arguments)
                async with mcp_adapter(entry) as adapter:
                    tools = await adapter.list_tools()
                    remote = next((tool for tool in tools if tool.name == upstream), None)
                    if remote is None:
                        raise ConnectionFailure('Enabled tool is no longer available; test the connection again')
                    if metadata(remote) != item:
                        raise ConnectionFailure('Tool definition changed; test the connection again and obtain a new approval')
                    return await remote.ainvoke(arguments)
        except ConnectionFailure:
            raise
        except Exception:
            raise ConnectionFailure('Tool execution failed; check the connection') from None

    return StructuredTool.from_function(name=name, description=item['description'] or upstream,
                                        args_schema=item['input_schema'], coroutine=invoke,
                                        metadata={'origin':entry['kind'],
                                                  'effect': 'read' if entry['kind'] == 'api' and entry.get('method', 'GET') == 'GET' else entry.get('tool_effects', {}).get(upstream, 'unknown'),
                                                  'configuration_hash':hashlib.sha256(json.dumps(entry,sort_keys=True,default=str).encode()).hexdigest()})


async def load_enabled_tools(entries):
    result = {}
    for entry in entries:
        if entry.get('status') != 'passed':
            continue
        if entry['kind'] == 'api' and entry.get('method', 'GET') != 'GET':
            continue
        for item in entry.get('tools', []):
            if item['name'] in entry.get('enabled_tools', []):
                tool = _build_tool(entry, item)
                result[tool.name] = tool
    return result
