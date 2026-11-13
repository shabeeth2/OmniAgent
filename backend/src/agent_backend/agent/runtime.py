"""Application startup factories; importing performs no provider calls."""
import asyncio
import logging
from copy import deepcopy
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, Field, AliasChoices, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from ..tools.rag import BACKEND_DIR, create_retrieval_tool, create_store
from ..ingest import ingest
from ..tools.business import create_business_tools
from ..tools.paypal_demo import create_paypal_tools
from .discovery import ToolDiscovery, catalog_descriptions
from .graph import BusinessAgent

class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / '.env', extra='ignore', populate_by_name=True)
    agent_model: str = Field(min_length=1, validation_alias=AliasChoices('LLM_MODEL', 'AGENT_MODEL'))
    context_budget: int = Field(default=64000, ge=1000, le=1000000)
    openai_base_url: str | None = Field(default=None, validation_alias=AliasChoices('LLM_BASE_URL', 'OPENAI_BASE_URL'))
    openai_api_key: SecretStr = Field(validation_alias=AliasChoices('LLM_API_KEY', 'OPENAI_API_KEY'))

    @field_validator('openai_base_url')
    @classmethod
    def default_endpoint(cls, value):
        return value or None

def build_business_agent(checkpointer=None, demo_path=None):
    settings = AgentSettings()
    registry = {**create_business_tools(), **create_paypal_tools(demo_path)}
    docs = BACKEND_DIR / 'sample_docs'
    store = ingest(docs) if docs.is_dir() and any(p.suffix.lower() in {'.md','.txt','.pdf'} for p in docs.rglob('*') if p.is_file()) else create_store()
    registry['retrieve_knowledge'] = create_retrieval_tool(store, allow_empty=True)
    discovery = ToolDiscovery(registry, descriptions=catalog_descriptions(registry), cache_path=BACKEND_DIR / 'data' / 'tool-embeddings.db')
    model = ChatOpenAI(model=settings.agent_model, api_key=settings.openai_api_key, base_url=settings.openai_base_url, temperature=0, max_retries=0)
    return BusinessAgent(model, discovery, registry, checkpointer=checkpointer, context_budget=settings.context_budget)


class RegistryAgentManager:
    """Publish whole agent snapshots; in-flight requests keep their old registry."""

    def __init__(self, base_agent):
        self.base_agent = base_agent
        self._entries = None
        self._agent = None
        self._lock = asyncio.Lock()
        self._reload = None

    async def snapshot(self, fresh=False):
        from ..routers.tool_registry import read_snapshot
        from ..tools.registry_connections import load_enabled_tools

        while True:
            entries = deepcopy(await asyncio.to_thread(read_snapshot))
            published, pending = await self._check_snapshot(entries, load_enabled_tools)
            if pending is None:
                return published
            # Keep serving an immutable published snapshot during expensive indexing.
            if published is not None and not fresh:
                return published
            built = await pending
            if not fresh:
                return built
            # A second edit may have arrived while the previous index was building.
            # Approval resumes must compare against the latest saved configuration.

    async def _check_snapshot(self, entries, load_enabled_tools):
        async with self._lock:
            if entries == self._entries:
                return self._agent, None
            if self._reload is None or self._reload.done():
                self._reload = asyncio.create_task(self._build(entries, load_enabled_tools))
                self._reload.add_done_callback(self._report_reload)
            return self._agent, self._reload

    @staticmethod
    def _report_reload(task):
        if not task.cancelled() and task.exception() is not None:
            logging.getLogger(__name__).warning('registry_reload outcome=failed; retaining published snapshot')

    async def _build(self, entries, load_enabled_tools):
        remote_tools = await load_enabled_tools(entries)
        if not remote_tools:
            agent = self.base_agent
        else:
            if self.base_agent.registry.keys() & remote_tools.keys():
                raise ValueError("External tool names conflict with built-in tools")
            registry = {**self.base_agent.registry, **remote_tools}
            discovery = await asyncio.to_thread(
                ToolDiscovery, registry, descriptions=catalog_descriptions(registry),
                cache_path=BACKEND_DIR / 'data' / 'tool-embeddings.db')
            agent = BusinessAgent(
                self.base_agent.model, discovery, registry,
                clock=self.base_agent.clock, timeout=self.base_agent.timeout,
                checkpointer=self.base_agent.checkpointer,
                context_budget=getattr(self.base_agent, 'context_budget', 64000))
        async with self._lock:
            self._entries, self._agent = entries, agent
        return agent
