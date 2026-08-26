import builtins
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import deep_focus


class TestExport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db = deep_focus.DB_PATH
        deep_focus.DB_PATH = Path(self._tmp.name) / "results.db"
        self.export_dir = Path(self._tmp.name) / "exports"

        # Minimal schema + one matching row.
        conn = sqlite3.connect(str(deep_focus.DB_PATH))
        conn.execute(
            "CREATE TABLE services (ip TEXT, port INTEGER, service_type TEXT, banner TEXT, state TEXT)"
        )
        conn.execute(
            "INSERT INTO services VALUES ('1.2.3.4', 22, 'ssh', 'SSH-2.0-OpenSSH_8.9', 'open')"
        )
        conn.commit()
        conn.close()

        self._orig_load = deep_focus.config.load_config
        deep_focus.config.load_config = lambda: {"export_path": str(self.export_dir)}

    def tearDown(self):
        deep_focus.DB_PATH = self._orig_db
        deep_focus.config.load_config = self._orig_load
        self._tmp.cleanup()

    def test_export_writes_txt_and_json(self):
        orig_input = builtins.input
        builtins.input = lambda prompt="": "y"
        try:
            deep_focus.perform_export()
        finally:
            builtins.input = orig_input

        txt_files = list(self.export_dir.glob("*.txt"))
        json_files = list(self.export_dir.glob("*.json"))
        self.assertEqual(len(txt_files), 1)
        self.assertEqual(len(json_files), 1)

        data = json.loads(json_files[0].read_text())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["ip"], "1.2.3.4")
        self.assertEqual(data[0]["port"], 22)
        self.assertEqual(data[0]["service"], "ssh")

        self.assertIn("1.2.3.4:22", txt_files[0].read_text())

    def test_export_skips_on_no(self):
        orig_input = builtins.input
        builtins.input = lambda prompt="": "n"
        try:
            deep_focus.perform_export()
        finally:
            builtins.input = orig_input
        self.assertFalse(self.export_dir.exists())


class TestConfigureSettings(unittest.TestCase):
    def setUp(self):
        self._orig_load = deep_focus.config.load_config
        self._orig_save = deep_focus.config.save_config
        self._orig_input = builtins.input

    def tearDown(self):
        deep_focus.config.load_config = self._orig_load
        deep_focus.config.save_config = self._orig_save
        builtins.input = self._orig_input

    def _setup(self, cfg):
        deep_focus.config.load_config = lambda: cfg
        saved = {}
        deep_focus.config.save_config = lambda c: saved.update(c)
        return saved

    def test_ports_valid(self):
        cfg = {"target_network": "x", "power_level": 50, "scan_speed": 500,
               "export_path": "y", "ports": "old"}
        saved = self._setup(cfg)

        answers = iter(["5", "80,443,8080"])
        builtins.input = lambda prompt="": next(answers)
        deep_focus.configure_settings()
        self.assertEqual(saved.get("ports"), "80,443,8080")

    def test_ports_invalid_rejected(self):
        cfg = {"target_network": "x", "power_level": 50, "scan_speed": 500,
               "export_path": "y", "ports": "old"}
        saved = self._setup(cfg)

        answers = iter(["5", "80,abc"])
        builtins.input = lambda prompt="": next(answers)
        deep_focus.configure_settings()
        self.assertEqual(saved.get("ports"), "old")  # unchanged


if __name__ == "__main__":
    unittest.main()
