import json
from copy import deepcopy
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, ValidationError, field_validator, model_validator
from ..tools.registry_connections import ConnectionFailure, test_connection, validate_schema

router = APIRouter(prefix="/tool-registry", tags=["tool-registry"])

@router.get('/catalog')
async def catalog(request: Request):
    from ..agent.graph import ask_user, system_search
    from ..agent.presentation import present_ui
    manager = getattr(request.app.state, 'registry_agent_manager', None)
    try:
        agent = await manager.snapshot() if manager else request.app.state.business_agent
    except Exception:
        raise HTTPException(503, 'Tool registry is unavailable. Check enabled connections and retry.') from None
    from ..agent.discovery import catalog_operations
    executable = [{'name': tool.name, 'description': tool.description, 'origin': (tool.metadata or {}).get('origin', 'system'),
                   'executable': True, 'service': (tool.metadata or {}).get('service', 'business'),
                   'input_schema': tool.args, 'version': (tool.metadata or {}).get('version', '1')}
                  for tool in [system_search, ask_user, present_ui, *agent.registry.values()]]
    return executable + [{'name': row['id'], **row, 'origin': 'catalog'} for row in catalog_operations()]
REGISTRY_PATH = Path(__file__).resolve().parents[3] / "data" / "tool-registry.json"
_lock = Lock()


def empty_schema():
    return {'type': 'object', 'properties': {}, 'additionalProperties': False}


class ToolConfig(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["mcp", "api"]
    url: AnyHttpUrl
    description: str = Field(default="", max_length=4000)
    api_key: SecretStr | None = Field(default=None, exclude=True, max_length=8192)
    auth_header: str = Field(default="Authorization", pattern=r"^[A-Za-z0-9-]+$", max_length=100)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    auth_scheme: Literal["none", "bearer", "api_key"] = "none"
    input_schema: dict = Field(default_factory=empty_schema)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("Name must not be blank")
        return value.strip()

    @field_validator("url")
    @classmethod
    def safe_url(cls, value):
        if value.username or value.password:
            raise ValueError("Use the API key field instead of URL credentials")
        host = value.host.strip("[]")
        try:
            loopback = ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if value.scheme != "https" and not loopback:
            raise ValueError("Use HTTPS except for local loopback servers")
        return value

    @field_validator('input_schema')
    @classmethod
    def scalar_schema(cls, value):
        return validate_schema(value)

    @model_validator(mode='after')
    def auth_requires_key(self):
        if self.auth_scheme != 'none' and (not self.api_key or not self.api_key.get_secret_value().strip()):
            raise ValueError('Selected authentication requires an API key')
        if self.api_key and any(char in self.api_key.get_secret_value() for char in '\r\n'):
            raise ValueError('API key must not contain newlines')
        if self.auth_scheme == 'bearer':
            self.auth_header = 'Authorization'
        return self


class ToolRead(BaseModel):
    id: str
    name: str
    kind: Literal["mcp", "api"]
    url: str
    description: str
    auth_header: str
    method: str = "GET"
    auth_scheme: Literal["none", "bearer", "api_key"] = "none"
    input_schema: dict = Field(default_factory=empty_schema)
    has_api_key: bool
    status: Literal['saved', 'passed', 'failed'] = 'saved'
    tested_at: str | None = None
    error: str | None = None
    tools: list[dict] = Field(default_factory=list)
    enabled_tools: list[str] = Field(default_factory=list)
    tool_effects: dict[str, Literal['read', 'write', 'unknown']] = Field(default_factory=dict)


class TestArguments(BaseModel):
    arguments: dict = Field(default_factory=dict)


def _read():
    if not REGISTRY_PATH.exists():
        return []
    try:
        entries = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if not isinstance(entries, list) or any(not isinstance(entry, dict) or not entry.get('id') for entry in entries):
            raise ValueError()
        for entry in entries:
            for key, value in {'status': 'saved', 'tested_at': None, 'error': None, 'tools': [], 'enabled_tools': [], 'tool_effects': {}, 'input_schema': empty_schema()}.items():
                entry.setdefault(key, deepcopy(value))
        return entries
    except (OSError, ValueError):
        raise HTTPException(500, "Cannot read tool registry") from None


def read_snapshot():
    with _lock:
        return deepcopy(_read())


def _write(entries):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=REGISTRY_PATH.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(entries, file, indent=2)
        temporary.replace(REGISTRY_PATH)
    except OSError:
        raise HTTPException(500, "Cannot save tool registry") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _public(entry):
    public = ToolRead(**{**entry, "has_api_key": bool(entry.get("api_key"))})
    key = entry.get('api_key')
    if key:
        def redact(value):
            if isinstance(value, str):
                return value.replace(key, '[redacted]')
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {name: redact(item) for name, item in value.items()}
            return value
        public = public.model_copy(update={name: redact(getattr(public, name)) for name in ['name', 'url', 'description', 'error', 'tools', 'input_schema']})
    return public


def _find(entries, tool_id):
    for entry in entries:
        if entry['id'] == tool_id:
            return entry
    raise HTTPException(404, 'Tool configuration not found')


def _config_data(config):
    return {**config.model_dump(mode='json'), 'api_key': config.api_key.get_secret_value() if config.api_key else None}


# shortcut: one local server process; use database transactions before multiple workers.
@router.get("", response_model=list[ToolRead])
def list_tools():
    return [_public(entry) for entry in read_snapshot()]


@router.post("", response_model=ToolRead, status_code=201)
def add_tool(config: dict):
    try:
        config = ToolConfig.model_validate(config) if not isinstance(config, ToolConfig) else config
    except ValidationError:
        raise HTTPException(422, 'Invalid tool configuration; check URL, authentication, and input schema') from None
    entry = {**_config_data(config), 'id': str(uuid4()), 'status': 'saved', 'tested_at': None,
             'error': None, 'tools': [], 'enabled_tools': []}
    with _lock:
        entries = _read()
        entries.append(entry)
        _write(entries)
    return _public(entry)


@router.patch('/{tool_id}', response_model=ToolRead)
def edit_tool(tool_id: str, changes: dict):
    allowed = set(ToolConfig.model_fields) | {'enabled_tools', 'tool_effects'}
    if not changes or set(changes) - allowed:
        raise HTTPException(422, 'Unknown or empty configuration changes')
    with _lock:
        entries = _read()
        entry = _find(entries, tool_id)
        if set(changes) == {'tool_effects'}:
            effects = changes['tool_effects']
            names = {item['name'] for item in entry['tools']}
            if not isinstance(effects, dict) or any(name not in names or not isinstance(effect, str) or effect not in {'read', 'write', 'unknown'} for name, effect in effects.items()):
                raise HTTPException(422, 'Classifications must name discovered tools and use read, write, or unknown')
            if entry['kind'] != 'mcp':
                raise HTTPException(422, 'Supported GET API tools are classified as read-only automatically')
            entry['tool_effects'] = effects
        elif set(changes) == {'enabled_tools'}:
            enabled = changes['enabled_tools']
            if not isinstance(enabled, list) or any(not isinstance(name, str) for name in enabled):
                raise HTTPException(422, 'Enabled tools must be a list of names')
            names = {item['name'] for item in entry['tools']}
            if enabled and (entry['status'] != 'passed' or set(enabled) - names or (entry['kind'] == 'api' and entry.get('method', 'GET') != 'GET')):
                raise HTTPException(409, 'Test this configuration successfully before enabling its tools')
            entry['enabled_tools'] = list(dict.fromkeys(enabled))
        else:
            if 'enabled_tools' in changes or 'tool_effects' in changes:
                raise HTTPException(422, 'Save configuration separately from activation')
            try:
                config = ToolConfig.model_validate({**{key: value for key, value in entry.items() if key in ToolConfig.model_fields}, **changes})
            except ValidationError:
                raise HTTPException(422, 'Invalid tool configuration; check URL, authentication, and input schema') from None
            entry.update(_config_data(config))
            entry.update(status='saved', tested_at=None, error=None, tools=[], enabled_tools=[], tool_effects={})
        _write(entries)
        return _public(entry)


@router.post('/{tool_id}/test', response_model=ToolRead)
async def test_tool(tool_id: str, request: TestArguments):
    entry = _find(read_snapshot(), tool_id)
    try:
        config = ToolConfig.model_validate({key: value for key, value in entry.items() if key in ToolConfig.model_fields})
        checked = {**entry, **_config_data(config)}
        tools = await test_connection(checked, request.arguments)
        status, error = 'passed', None
    except ConnectionFailure as failure:
        tools, status, error = [], 'failed', str(failure)
    except ValidationError:
        tools, status, error = [], 'failed', 'Invalid configuration or test arguments.'
    with _lock:
        entries = _read()
        current = _find(entries, tool_id)
        if current != entry:
            raise HTTPException(409, 'Configuration changed during testing; try again')
        current.update(status=status, error=error, tested_at=datetime.now(timezone.utc).isoformat(), tools=tools, enabled_tools=[], tool_effects={})
        _write(entries)
        return _public(current)


@router.delete("/{tool_id}", status_code=204)
def delete_tool(tool_id: str):
    with _lock:
        entries = _read()
        _find(entries, tool_id)
        _write([entry for entry in entries if entry['id'] != tool_id])
