import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from porchlight.ai_analysis import run_ai_analysis
from porchlight.config import load_config


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class AiAnalysisTest(unittest.TestCase):
    def config_for(self, root: Path):
        env = {"MUSTER_MOCK_ROOT": str(root), "PORCHLIGHT_CONFIG_DIR": str(root / "etc/porchlight")}
        with mock.patch.dict(os.environ, env, clear=False):
            return load_config(apply=False)

    def write_snapshot(self, root: Path) -> None:
        www = root / "var/lib/porchlight/www"
        www.mkdir(parents=True)
        (www / "snapshot.json").write_text(
            json.dumps(
                {
                    "status": {"last_scan": "2026-05-21T00:00:00Z", "hosts_seen": 1, "open_ports": 1},
                    "hosts": [{"ip": "192.168.1.10", "display_name": "alpha", "status": "active"}],
                    "services": [{"ip": "192.168.1.10", "proto": "tcp", "port": 22, "service_name": "ssh"}],
                }
            ),
            encoding="utf-8",
        )
        (www / "changes.json").write_text(json.dumps({"irregularities": [], "recent_runs": []}), encoding="utf-8")

    def write_enabled_openai_config(self, root: Path) -> None:
        config_dir = root / "etc/porchlight"
        config_dir.mkdir(parents=True)
        (config_dir / "porchlight.openai.env").write_text(
            "\n".join(
                [
                    "OPENAI_API_KEY=sk-test-secret",
                    "PORCHLIGHT_AI_ANALYSIS_ENABLE=1",
                    "PORCHLIGHT_AI_MODEL=gpt-5-mini",
                    "PORCHLIGHT_AI_SERVICE_TIER=flex",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def generated_analysis(self):
        return {
            "environment": {
                "grade": "B",
                "headline": "Network looks steady.",
                "summary": "One host and one SSH service are visible.",
                "highlights": ["Snapshot is current."],
                "concerns": [],
                "suggestions": [],
            },
            "protocols": [
                {
                    "name": "ssh",
                    "grade": "B",
                    "headline": "SSH is present.",
                    "summary": "One host answers on SSH.",
                    "highlights": [],
                    "concerns": [],
                }
            ],
            "hosts": [{"ip": "192.168.1.10", "grade": "B", "headline": "Host is ordinary.", "summary": "SSH only.", "notes": []}],
            "irregularities": [],
        }

    def test_disabled_analysis_writes_local_status_without_api_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_snapshot(root)
            config = self.config_for(root)

            with mock.patch("porchlight.ai_analysis.urlopen") as urlopen:
                result = run_ai_analysis(config)

            self.assertEqual(result["status"], "disabled")
            self.assertFalse(urlopen.called)
            self.assertEqual(json.loads((root / "var/lib/porchlight/www/analysis.json").read_text())["status"], "disabled")

    def test_missing_key_skips_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_snapshot(root)
            config_dir = root / "etc/porchlight"
            config_dir.mkdir(parents=True)
            (config_dir / "porchlight.openai.env").write_text("PORCHLIGHT_AI_ANALYSIS_ENABLE=1\n", encoding="utf-8")
            config = self.config_for(root)

            result = run_ai_analysis(config)

            self.assertEqual(result["status"], "missing_key")

    def test_mocked_openai_response_writes_analysis_and_uses_configured_request_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_snapshot(root)
            self.write_enabled_openai_config(root)
            config = self.config_for(root)
            generated = self.generated_analysis()

            def fake_urlopen(request, timeout):
                body = json.loads(request.data.decode("utf-8"))
                self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
                self.assertEqual(request.get_header("Authorization"), "Bearer sk-test-secret")
                self.assertEqual(body["model"], "gpt-5-mini")
                self.assertEqual(body["service_tier"], "flex")
                self.assertFalse(body["store"])
                self.assertEqual(body["text"]["format"]["type"], "json_schema")
                return FakeResponse({"output": [{"content": [{"text": json.dumps(generated)}]}]})

            with mock.patch("porchlight.ai_analysis.urlopen", side_effect=fake_urlopen):
                result = run_ai_analysis(config)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["environment"]["headline"], "Network looks steady.")
            output = json.loads((root / "var/lib/porchlight/www/analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(output["source"], "openai")
            self.assertEqual(output["snapshot_hash"], result["snapshot_hash"])

    def test_rate_limited_response_is_classified_and_preserves_previous_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_snapshot(root)
            self.write_enabled_openai_config(root)
            previous = {
                "status": "ok",
                "source": "openai",
                "generated_at": "2026-05-22T00:00:00Z",
                "snapshot_hash": "previous-snapshot",
                "model": "gpt-5-mini",
                "service_tier": "flex",
                **self.generated_analysis(),
            }
            analysis_path = root / "var/lib/porchlight/www/analysis.json"
            analysis_path.write_text(json.dumps(previous), encoding="utf-8")
            config = self.config_for(root)

            def fake_urlopen(request, timeout):
                raise HTTPError(request.full_url, 429, "Too Many Requests", {"Retry-After": "60"}, None)

            with mock.patch("porchlight.ai_analysis.urlopen", side_effect=fake_urlopen):
                result = run_ai_analysis(config)

            self.assertEqual(result["status"], "rate_limited")
            self.assertEqual(result["http_status"], 429)
            self.assertEqual(result["retry_after"], "60")
            self.assertIn("rate limit", result["error"])
            self.assertNotIn("HTTP Error 429", result["error"])
            self.assertTrue(result["analysis_stale"])
            self.assertEqual(result["last_success_at"], "2026-05-22T00:00:00Z")
            self.assertEqual(result["environment"]["headline"], "Network looks steady.")


if __name__ == "__main__":
    unittest.main()
