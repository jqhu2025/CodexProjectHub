import json
from pathlib import Path
import tempfile
import unittest

from codex_hub import storage


class JsonStorageTests(unittest.TestCase):
    def setUp(self):
        storage.consume_json_recovery_events()
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "data.json"

    def tearDown(self):
        storage.consume_json_recovery_events()
        self.folder.cleanup()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_valid_primary_loads_without_recovery_event(self):
        self.write(self.path, {"projects": 3})

        self.assertEqual(storage.load_json(self.path, {}), {"projects": 3})
        self.assertEqual(storage.consume_json_recovery_events(), [])

    def test_corrupt_primary_uses_backup_and_reports_once(self):
        self.path.write_text("{broken", encoding="utf-8")
        self.write(storage.json_backup_path(self.path), {"tasks": ["safe"]})

        self.assertEqual(storage.load_json(self.path, {}), {"tasks": ["safe"]})
        events = storage.consume_json_recovery_events()
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].recovered)
        self.assertEqual(events[0].filename, "data.json")

        self.assertEqual(storage.load_json(self.path, {}), {"tasks": ["safe"]})
        self.assertEqual(storage.consume_json_recovery_events(), [])

    def test_missing_primary_uses_an_existing_backup(self):
        self.write(storage.json_backup_path(self.path), {"projects": ["safe"]})

        self.assertEqual(storage.load_json(self.path, {}), {"projects": ["safe"]})
        events = storage.consume_json_recovery_events()
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].recovered)
        self.assertEqual(events[0].reason, "missing")

    def test_corrupt_primary_never_replaces_good_backup_during_save(self):
        self.path.write_text("not json", encoding="utf-8")
        backup = storage.json_backup_path(self.path)
        self.write(backup, {"version": "safe"})

        storage.save_json(self.path, {"version": "new"})

        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"version": "new"})
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), {"version": "safe"})

    def test_normal_save_keeps_previous_valid_document(self):
        self.write(self.path, {"version": 1})

        storage.save_json(self.path, {"version": 2})

        self.assertEqual(storage.load_json(self.path, {}), {"version": 2})
        self.assertEqual(storage.load_json(storage.json_backup_path(self.path), {}), {"version": 1})

    def test_serialization_failure_leaves_primary_intact_and_no_temporary_file(self):
        self.write(self.path, {"version": 1})

        with self.assertRaises(TypeError):
            storage.save_json(self.path, {"unsupported": {1, 2}})

        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"version": 1})
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_missing_primary_and_backup_returns_default_without_warning(self):
        default = {"firstRun": True}

        self.assertIs(storage.load_json(self.path, default), default)
        self.assertEqual(storage.consume_json_recovery_events(), [])

    def test_invalid_primary_without_backup_reports_unrecovered_failure(self):
        self.path.write_text("[", encoding="utf-8")

        self.assertEqual(storage.load_json(self.path, []), [])
        events = storage.consume_json_recovery_events()
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0].recovered)
        self.assertEqual(events[0].reason, "invalid")

    def test_storage_module_has_no_qt_dependency(self):
        source = Path(storage.__file__).read_text(encoding="utf-8")

        self.assertNotIn("PyQt", source)


if __name__ == "__main__":
    unittest.main()
