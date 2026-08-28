import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from porchlight.config import load_config
from porchlight.health import health


class HealthFreshnessTest(unittest.TestCase):
    def config_for(self, root: Path):
        env = {
            "MUSTER_MOCK_ROOT": str(root),
            "PORCHLIGHT_CONFIG_DIR": str(root / "etc/porchlight"),
            "PORCHLIGHT_SCAN_STALE_SECONDS": "1200",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            return load_config(apply=False)

    def prepare_runtime(self, root: Path, last_scan: str) -> None:
        state = root / "run/porchlight"
        www = root / "var/lib/porchlight/www"
        state.mkdir(parents=True)
        www.mkdir(parents=True)
        (root / "var/lib/porchlight/porchlight.db").touch()
        (www / "snapshot.json").write_text("{}\n", encoding="utf-8")
        (state / "status.json").write_text(json.dumps({"last_scan": last_scan}), encoding="utf-8")

    def test_current_scan_is_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare_runtime(root, "2026-08-28T17:00:00Z")
            result = health(self.config_for(root), datetime(2026, 8, 28, 17, 10, tzinfo=timezone.utc))

            self.assertEqual(result["health"], "healthy")
            self.assertEqual(result["scan_age_seconds"], 600.0)

    def test_old_scan_is_explicitly_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare_runtime(root, "2026-08-28T16:00:00Z")
            result = health(self.config_for(root), datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc))

            self.assertEqual(result["health"], "degraded")
            self.assertFalse(result["scanner_online"])
            self.assertEqual(result["problems"], ["scan status stale (3600s old)"])
