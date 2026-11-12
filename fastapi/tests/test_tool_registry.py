import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi import HTTPException
from pydantic import ValidationError
from agent_backend.routers import tool_registry as registry


class ToolRegistryTest(unittest.TestCase):
    def test_create_list_delete_never_returns_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(registry, "REGISTRY_PATH", Path(directory) / "registry.json"):
                config = registry.ToolConfig(name="Example", kind="api", url="https://example.com/api", api_key="private-key")
                created = registry.add_tool(config)
                self.assertTrue(created.has_api_key)
                self.assertNotIn("private-key", created.model_dump_json())
                self.assertNotIn("api_key", created.model_dump())
                self.assertNotIn("private-key", registry.list_tools()[0].model_dump_json())
                self.assertIn("private-key", registry.REGISTRY_PATH.read_text())
                registry.delete_tool(created.id)
                self.assertEqual(registry.list_tools(), [])
                with self.assertRaises(HTTPException) as error:
                    registry.delete_tool(created.id)
                self.assertEqual(error.exception.status_code, 404)

    def test_rejects_unsafe_or_invalid_configuration(self):
        for change in [{"name": " "}, {"url": "file:///secret"}, {"url": "http://example.com"}, {"url": "https://user:password@example.com"}, {"auth_header": "bad\r\nheader"}, {"kind": "shell"}, {"method": "EXEC"}, {"auth_scheme": "basic"}, {"api_key": "k" * 8193}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                registry.ToolConfig(**{"name": "Example", "kind": "mcp", "url": "https://example.com/mcp", **change})

    def test_loopback_http_and_auth_fields(self):
        for url in ["http://localhost:8000/mcp", "http://127.0.0.1:8000/mcp", "http://[::1]:8000/mcp"]:
            config = registry.ToolConfig(name="Local", kind="api", url=url, method="POST", auth_scheme="bearer", api_key="key")
            self.assertEqual(config.method, "POST")
            self.assertEqual(config.auth_scheme, "bearer")

    def test_corrupt_store_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text("invalid")
            with patch.object(registry, "REGISTRY_PATH", path), self.assertRaises(HTTPException):
                registry.add_tool(registry.ToolConfig(name="Example", kind="mcp", url="https://example.com"))
            self.assertEqual(path.read_text(), "invalid")


if __name__ == "__main__":
    unittest.main()
