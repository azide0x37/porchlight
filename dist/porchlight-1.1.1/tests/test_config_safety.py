import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from porchlight.config import load_config, validate_scan_network


class ConfigSafetyTest(unittest.TestCase):
    def test_mock_paths_reroot_absolute_appliance_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "etc/porchlight"
            config_dir.mkdir(parents=True)
            (config_dir / "porchlight.env").write_text(
                "PORCHLIGHT_STATE_DIR=/run/porchlight\n"
                "PORCHLIGHT_DATA_DIR=/var/lib/porchlight\n"
                "PORCHLIGHT_WWW_DIR=/var/lib/porchlight/www\n",
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"MUSTER_MOCK_ROOT": str(root)}, clear=False):
                config = load_config(apply=False)

            self.assertEqual(config.state_dir, root / "run/porchlight")
            self.assertEqual(config.data_dir, root / "var/lib/porchlight")

    def test_scan_safety_rejects_broad_or_public_cidrs(self):
        config = load_config(apply=False)

        with self.assertRaises(ValueError):
            validate_scan_network("192.168.16.0/22", config)
        with self.assertRaises(ValueError):
            validate_scan_network("8.8.8.0/24", config)
        self.assertEqual(str(validate_scan_network("192.168.17.0/24", config)), "192.168.17.0/24")


if __name__ == "__main__":
    unittest.main()
