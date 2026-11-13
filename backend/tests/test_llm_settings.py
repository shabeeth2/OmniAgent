import os
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_backend.routers import llm_settings


class LlmSettingsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / '.env'
        self.path_patch = patch.object(llm_settings, 'ENV_PATH', self.path)
        self.path_patch.start()
        # Keep Windows runtime variables available to imports and worker threads.
        clean = {key: value for key, value in os.environ.items()
                 if key not in {name for names in llm_settings.NAMES.values() for name in names}}
        self.env_patch = patch.dict(os.environ, clean, clear=True)
        self.env_patch.start()
        app = FastAPI()
        app.include_router(llm_settings.router, prefix='/api')
        self.client = TestClient(app)

    def tearDown(self):
        self.path_patch.stop()
        self.env_patch.stop()
        self.directory.cleanup()

    def test_missing_configuration_is_readable(self):
        data = self.client.get('/api/settings/llm').json()
        self.assertEqual(data['llm_model'], '')
        self.assertFalse(data['llm_api_key_configured'])

    def test_save_preserves_secrets_and_unrelated_values(self):
        self.path.write_text("# local settings\nOPENAI_API_KEY='old-secret'\nOTHER=value\n")
        response = self.client.put('/api/settings/llm', json={
            'llm_model': 'test-model', 'llm_base_url': 'https://chat.example/v1',
            'embedding_model': 'test-embeddings', 'embedding_base_url': 'https://embed.example/v1/embeddings',
            'context_budget': 32000, 'llm_api_key': '', 'embedding_api_key': 'new-secret',
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['restart_required'])
        self.assertTrue(response.json()['llm_api_key_configured'])
        self.assertNotIn('old-secret', response.text)
        self.assertNotIn('new-secret', response.text)
        saved = self.path.read_text()
        self.assertIn('OTHER=value', saved)
        self.assertIn('# local settings', saved)
        self.assertIn('LLM_MODEL=', saved)
        self.assertIn('EMBEDDING_API_KEY=', saved)

    def test_rejects_newlines_and_credential_urls_without_leaking_key(self):
        for field, value in [('llm_model', 'model\nOTHER=bad'), ('llm_base_url', 'https://key:secret@example.com')]:
            response = self.client.put('/api/settings/llm', json={field: value, 'llm_api_key': 'private-key'})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('private-key', response.text)
        self.assertFalse(self.path.exists())

    def test_rejects_cross_origin_writes(self):
        response = self.client.put('/api/settings/llm', json={'llm_model': 'x'}, headers={'origin': 'https://evil.example'})
        self.assertEqual(response.status_code, 403)

    def test_generic_and_legacy_environment_names(self):
        from agent_backend.agent.runtime import AgentSettings
        from agent_backend.tools.rag import RagSettings
        with patch.dict(os.environ, {'LLM_MODEL': 'generic', 'LLM_API_KEY': 'chat-key',
                                     'EMBEDDING_MODEL': 'embed', 'EMBEDDING_API_KEY': 'embed-key',
                                     'EMBEDDING_BASE_URL': 'https://embed.example'}):
            self.assertEqual(AgentSettings(_env_file=None).agent_model, 'generic')
            self.assertEqual(RagSettings(_env_file=None).jina_embedding_model, 'embed')
        with patch.dict(os.environ, {'AGENT_MODEL': 'legacy', 'OPENAI_API_KEY': 'old-key'}):
            self.assertEqual(AgentSettings(_env_file=None).agent_model, 'legacy')

    def test_unconfigured_lifespan_serves_settings_and_rejects_chat(self):
        from agent_backend.agent.runtime import AgentSettings
        from agent_backend.main import lifespan
        from agent_backend.routers.chat import chat_endpoint
        from agent_backend.schemas import ChatRequest
        from fastapi import HTTPException
        from pydantic import ValidationError
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from agent_backend.database import initialize_schema

        engine = create_engine('sqlite:///' + str(Path(self.directory.name) / 'test.db'))
        initialize_schema(engine)
        app = SimpleNamespace(state=SimpleNamespace())
        with self.assertRaises(ValidationError) as invalid:
            AgentSettings(_env_file=None)

        async def verify(failure):
            with patch('agent_backend.database.initialize_schema', lambda: None), \
                 patch('agent_backend.database.DB_PATH', Path(self.directory.name) / 'test.db'), \
                 patch('agent_backend.database.SessionLocal', sessionmaker(bind=engine)), \
                 patch('agent_backend.agent.runtime.build_business_agent', side_effect=failure), \
                 patch('agent_backend.agent.runtime.ChatOpenAI') as provider:
                async with lifespan(app):
                    self.assertIsNone(app.state.business_agent)
                    self.assertIsNone(app.state.registry_agent_manager)
                    self.assertEqual(llm_settings.public_settings(SimpleNamespace(app=app))['llm_model'], '')
                    with self.assertRaises(HTTPException) as error:
                        await chat_endpoint(ChatRequest(message='hello'), SimpleNamespace(app=app), None)
                    self.assertEqual(error.exception.status_code, 503)
                    provider.assert_not_called()
        try:
            for failure in (invalid.exception, RuntimeError('provider failed with private-key')):
                with self.subTest(failure=type(failure).__name__):
                    asyncio.run(verify(failure))
        finally:
            engine.dispose()
