import json
import tempfile
import unittest
from pathlib import Path

from execution import config


class TestConfig(unittest.TestCase):
    def setUp(self):
        # Isolate the config file for the duration of each test.
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = config.CONFIG_FILE
        config.CONFIG_FILE = Path(self._tmp.name) / "settings.json"

    def tearDown(self):
        config.CONFIG_FILE = self._orig
        self._tmp.cleanup()

    def test_default_config_created_when_missing(self):
        cfg = config.load_config()
        self.assertTrue(config.CONFIG_FILE.exists())
        self.assertEqual(cfg["scan_speed"], 100)
        self.assertIn("ports", cfg)

    def test_missing_keys_merged_from_defaults(self):
        with open(config.CONFIG_FILE, "w") as f:
            json.dump({"scan_speed": 777}, f)
        cfg = config.load_config()
        self.assertEqual(cfg["scan_speed"], 777)
        # Missing keys should be backfilled from defaults.
        self.assertEqual(cfg["power_level"], 50)
        self.assertIn("ports", cfg)

    def test_invalid_json_falls_back_to_defaults(self):
        with open(config.CONFIG_FILE, "w") as f:
            f.write("{not valid json")
        cfg = config.load_config()
        self.assertEqual(cfg["scan_speed"], 100)

    def test_save_and_reload_roundtrip(self):
        cfg = config.load_config()
        cfg["target_network"] = "10.0.0.0/8"
        config.save_config(cfg)
        reloaded = config.load_config()
        self.assertEqual(reloaded["target_network"], "10.0.0.0/8")

    def test_ports_default_includes_smtp_ldaps(self):
        cfg = config.load_config()
        ports = set(p.strip() for p in cfg["ports"].split(","))
        self.assertIn("25", ports)
        self.assertIn("587", ports)
        self.assertIn("636", ports)


if __name__ == "__main__":
    unittest.main()
