"""Local provider configuration. Saved changes take effect after restart."""
import os
import re
import tempfile
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from ..tools.rag import BACKEND_DIR

class SettingsRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validate_without_echoing_secrets(request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, 'Invalid LLM settings. Check models, endpoint URLs, and context budget.') from None
        return validate_without_echoing_secrets


router = APIRouter(route_class=SettingsRoute)
ENV_PATH = BACKEND_DIR / '.env'
_lock = Lock()
NAMES = {
    'llm_model': ('LLM_MODEL', 'AGENT_MODEL'),
    'llm_base_url': ('LLM_BASE_URL', 'OPENAI_BASE_URL'),
    'llm_api_key': ('LLM_API_KEY', 'OPENAI_API_KEY'),
    'embedding_model': ('EMBEDDING_MODEL', 'JINA_EMBEDDING_MODEL'),
    'embedding_base_url': ('EMBEDDING_BASE_URL', 'JINA_BASE_URL'),
    'embedding_api_key': ('EMBEDDING_API_KEY', 'JINA_API_KEY'),
    'context_budget': ('CONTEXT_BUDGET',),
}


class LlmSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    llm_model: str | None = Field(default=None, min_length=1, max_length=500)
    llm_base_url: str | None = Field(default=None, max_length=2000)
    llm_api_key: SecretStr | None = None
    embedding_model: str | None = Field(default=None, min_length=1, max_length=500)
    embedding_base_url: str | None = Field(default=None, max_length=2000)
    embedding_api_key: SecretStr | None = None
    context_budget: int | None = Field(default=None, ge=1000, le=1000000)

    @field_validator('llm_model', 'embedding_model', 'llm_base_url', 'embedding_base_url')
    @classmethod
    def single_line(cls, value):
        if value is not None and any(ord(char) < 32 for char in value):
            raise ValueError('Use a single line without control characters')
        if value is not None and value and not value.strip():
            raise ValueError('Use a nonblank value')
        return value

    @field_validator('llm_base_url', 'embedding_base_url')
    @classmethod
    def http_url(cls, value):
        if value:
            try:
                url = urlsplit(value)
                valid = url.scheme in {'http', 'https'} and url.hostname and not url.username and not url.password and not url.query and not url.fragment
            except ValueError:
                valid = False
            if not valid:
                raise ValueError('Use an HTTP or HTTPS URL without credentials, query, or fragment')
        return value

    @field_validator('embedding_base_url')
    @classmethod
    def embedding_url_required(cls, value):
        if value == '':
            raise ValueError('An embedding endpoint is required')
        return value


def read_settings():
    saved = dotenv_values(ENV_PATH, interpolate=False)
    values = {}
    for field, names in NAMES.items():
        values[field] = next((source[name] for source in (os.environ, saved) for name in names if source.get(name) is not None), '')
    return values


def public_settings(request):
    values = read_settings()
    for field in ('llm_api_key', 'embedding_api_key'):
        values[field + '_configured'] = bool(values.pop(field))
    for field in ('llm_base_url', 'embedding_base_url'):
        try:
            url = urlsplit(values[field])
            if url.username or url.password or url.query or url.fragment:
                values[field] = ''
        except ValueError:
            values[field] = ''
    try:
        values['context_budget'] = int(values['context_budget'] or 64000)
    except ValueError:
        values['context_budget'] = 64000
    values['restart_required'] = getattr(request.app.state, 'llm_restart_required', False)
    values['environment_overrides'] = [field for field, names in NAMES.items() if any(name in os.environ for name in names)]
    return values


@router.get('/settings/llm')
def get_settings(request: Request):
    return public_settings(request)


@router.put('/settings/llm')
def update_settings(body: LlmSettingsUpdate, request: Request):
    if request.headers.get('origin') not in {None, 'http://localhost:3000', 'http://127.0.0.1:3000'}:
        raise HTTPException(403, 'Settings can only be changed from the local app.')
    updates = {}
    for field in body.model_fields_set:
        value = getattr(body, field)
        if value is None:
            continue
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
            if not value:
                continue
            if len(value) > 16000 or any(ord(char) < 32 for char in value):
                raise HTTPException(422, 'API keys must be a single line without control characters.')
        updates[NAMES[field][0]] = str(value)
    with _lock:
        temporary = None
        try:
            original = ENV_PATH.read_text(encoding='utf-8') if ENV_PATH.exists() else ''
            for name, value in updates.items():
                # Single quoted dotenv values preserve literal dollar signs and quotes.
                line = name + "='" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"
                pattern = re.compile(r'^\s*(?:export\s+)?' + re.escape(name) + r'\s*=.*$', re.MULTILINE)
                if pattern.search(original):
                    original = pattern.sub(lambda _: line, original)
                else:
                    original = original.rstrip('\n') + '\n' + line + '\n'
            ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=ENV_PATH.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(original)
            temporary.replace(ENV_PATH)
        except OSError:
            raise HTTPException(500, 'Unable to save local settings.') from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
    request.app.state.llm_restart_required = True
    return public_settings(request)
