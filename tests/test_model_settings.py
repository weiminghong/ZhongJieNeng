"""Private configuration and the actual Agent share one validated provider contract."""

from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from fastapi.testclient import TestClient
from cecep_console.api import create_app
from cecep_console.model_settings import (
    load_settings, public_settings, save_settings, select_evidence,
    ModelSettings, ProviderError, validate_endpoint, _NoRedirect,
)
from cecep_console.storage import Store
from cecep_console.storage_demo import seed_demo


class ModelSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_tmp = tempfile.TemporaryDirectory()
        cls.fixture = Path(cls.fixture_tmp.name) / "fixture.sqlite"
        with Store(cls.fixture) as store:
            store.initialize()
            seed_demo(store)

    @classmethod
    def tearDownClass(cls):
        cls.fixture_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config/private.json"
        self.db_path = Path(self.tmp.name) / "test.sqlite"
        with closing(sqlite3.connect(self.fixture)) as original, closing(sqlite3.connect(self.db_path)) as copy:
            original.backup(copy)
        self.env = patch.dict(os.environ, {
            "CECEP_LLM_SETTINGS_PATH": str(self.path),
            "CECEP_DB_PATH": str(self.db_path),
            "CECEP_LLM_API_KEY": "",
            "CECEP_LLM_BASE_URL": "",
            "CECEP_LLM_MODEL": "qwen3.8-27b",
        })
        self.env.start()
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.headers = {"X-CECEP-Settings": "1"}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        self.tmp.cleanup()

    def configured(self, **changes):
        return save_settings({
            "enabled": True, "base_url": "https://provider.example/compatible-mode/v1",
            "model": "qwen3.8-27b", "api_key": "fixture-secret-do-not-return", **changes,
        })

    @staticmethod
    def provider_response(indices):
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps({"selected_fact_indices": indices})}}]}).encode())

    def test_unconfigured_qwen_default_is_deterministic(self):
        response = self.client.get("/api/v1/settings/llm")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"], "qwen3.8-27b")
        self.assertEqual(response.json()["llm_mode"], "deterministic_tools_only")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_key_can_be_saved_disabled_until_endpoint_is_known(self):
        result = save_settings({"enabled": False, "api_key": "pending-secret"})
        self.assertTrue(result["api_key_configured"])
        self.assertFalse(result["ready"])
        self.assertNotIn("pending-secret", json.dumps(result))
        self.assertEqual(load_settings().api_key, "pending-secret")

    def test_save_is_private_and_read_does_not_return_key(self):
        result = self.configured()
        self.assertTrue(result["ready"])
        self.assertNotIn("api_key", result)
        self.assertNotIn("fixture-secret", self.client.get("/api/v1/settings/llm").text)
        self.assertNotIn("fixture-secret", repr(load_settings()))
        if os.name != "nt":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_edit_preserves_key_and_clear_is_explicit(self):
        self.configured()
        save_settings({"model": "qwen3.8-27b-v2", "api_key": ""})
        self.assertEqual(load_settings().api_key, "fixture-secret-do-not-return")
        save_settings({"enabled": False, "clear_api_key": True})
        self.assertFalse(public_settings()["api_key_configured"])

    def test_invalid_update_preserves_old_config(self):
        self.configured()
        old = self.path.read_bytes()
        with self.assertRaises(ValueError):
            save_settings({"base_url": "https://user:secret@example.com/v1"})
        self.assertEqual(self.path.read_bytes(), old)
        with self.assertRaises(ValueError):
            save_settings({"enabled": True, "clear_api_key": True})
        self.assertEqual(self.path.read_bytes(), old)

    def test_endpoints_reject_credentials_query_and_redirects(self):
        for address in ["https://x/v1?key=secret", "https://x/v1#secret", "https://u:p@x/v1", "http://outside.example/v1", "https://x/v1/chat/completions"]:
            with self.assertRaises(ValueError):
                validate_endpoint(address)
        self.assertEqual(validate_endpoint("http://127.0.0.1:8000/v1/"), "http://127.0.0.1:8000/v1")
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://elsewhere.example"))

    def test_write_requires_same_origin_marker(self):
        self.assertEqual(self.client.post("/api/v1/settings/llm", json={"enabled": False}).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/settings/llm", json={"enabled": False}, headers={**self.headers, "Origin": "https://unrelated.example"}).status_code, 403)

    def test_validation_errors_never_echo_submitted_secret(self):
        response = self.client.post("/api/v1/settings/llm", headers=self.headers, json={"api_key": "never-echo-this", "timeout_seconds": "invalid"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("never-echo-this", response.text)

    def test_real_test_route_calls_configured_model(self):
        self.configured()
        with patch("cecep_console.model_settings.provider_open", return_value=self.provider_response([0])) as upstream:
            response = self.client.post("/api/v1/settings/llm/test", headers=self.headers, json={})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["evidence_contract_passed"])
        request = upstream.call_args.args[0]
        self.assertEqual(request.full_url, "https://provider.example/compatible-mode/v1/chat/completions")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "qwen3.8-27b")
        self.assertIs(payload["enable_thinking"], False)
        self.assertEqual(len(json.loads(payload["messages"][1]["content"])["facts"]), 1)

    def test_provider_error_is_safe_and_explicit(self):
        self.configured()
        failure = HTTPError("https://provider.example", 401, "fixture-secret-do-not-return", {}, None)
        with patch("cecep_console.model_settings.provider_open", side_effect=failure):
            response = self.client.post("/api/v1/settings/llm/test", headers=self.headers, json={})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "provider_http_401")
        self.assertNotIn("fixture-secret", response.text)

    def test_invalid_selection_is_not_success(self):
        config = ModelSettings(enabled=True, base_url="https://provider.example/v1", api_key="test", model="qwen3.8-27b")
        for selection in [[False], [1], [0, 999], "0", []]:
            with self.assertRaises(ProviderError):
                select_evidence(config, ["fact"], "question", transport=lambda *a, **k: self.provider_response(selection))

    def test_actual_agent_hot_reloads_saved_settings_and_audits_model(self):
        self.configured()
        with patch("cecep_console.agent_service.urlopen", return_value=self.provider_response([0])) as upstream:
            response = self.client.post("/api/v1/agent/query", json={"question": "请核对当前预测偏差"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["llm_mode"], "openai_compatible_evidence_summary")
        self.assertEqual(json.loads(upstream.call_args.args[0].data)["model"], "qwen3.8-27b")
        with Store(self.db_path, readonly=True) as store:
            model = store.db.execute("SELECT model_name FROM agent_run WHERE agent_run_id=?", (response.json()["agent_run_id"],)).fetchone()[0]
        self.assertEqual(model, "qwen3.8-27b")
        save_settings({"enabled": False})
        with patch("cecep_console.agent_service.urlopen") as unused:
            result = self.client.post("/api/v1/agent/query", json={"question": "请核对当前预测偏差"})
        self.assertEqual(result.json()["llm_mode"], "deterministic_tools_only")
        unused.assert_not_called()


if __name__ == "__main__":
    unittest.main()
