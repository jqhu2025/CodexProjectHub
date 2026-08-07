import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from codex_hub.runtime import activity_state, analyze_session_records, find_codex_binary, read_user_thread_rows


def event(event_type, **payload):
    return {"type": "event_msg", "payload": {"type": event_type, **payload}}


class SessionStateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)

    def test_fresh_open_turn_is_running(self):
        records = [event("task_started"), event("user_message", message="Run the checks")]
        result = analyze_session_records(records, self.now - timedelta(seconds=20), self.now)
        self.assertEqual(result["state"], "working")

    def test_terminal_event_marks_turn_completed(self):
        records = [event("task_started"), event("user_message"), event("task_complete")]
        result = analyze_session_records(records, self.now, self.now)
        self.assertEqual(result["state"], "completed")

    def test_new_turn_after_terminal_is_running(self):
        records = [event("task_started"), event("task_complete"), event("task_started"), event("user_message")]
        result = analyze_session_records(records, self.now - timedelta(seconds=10), self.now)
        self.assertEqual(result["state"], "working")

    def test_stale_unterminated_turn_degrades_to_linked(self):
        records = [event("task_started"), event("user_message")]
        result = analyze_session_records(records, self.now - timedelta(minutes=8), self.now)
        self.assertEqual(result["state"], "linked")

    def test_ui_has_only_three_states(self):
        self.assertEqual(activity_state({"state": "working"}), "running")
        self.assertEqual(activity_state({"state": "completed"}), "completed")
        self.assertEqual(activity_state({"state": "waiting"}), "linked")


class ThreadQueryTests(unittest.TestCase):
    def test_only_user_threads_are_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.sqlite"
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE threads (
                    id TEXT, cwd TEXT, name TEXT, title TEXT, recency_at_ms INTEGER,
                    updated_at_ms INTEGER, updated_at INTEGER, created_at_ms INTEGER,
                    created_at INTEGER, preview TEXT, first_user_message TEXT,
                    rollout_path TEXT, archived INTEGER, thread_source TEXT, source TEXT
                )
                """
            )
            rows = [
                ("user-1", "C:/work", "User task", "", 1, 0, 0, 0, 0, "", "", "a.jsonl", 0, "user", "vscode"),
                ("legacy-user", "C:/work", "Legacy user", "", 2, 0, 0, 0, 0, "", "", "b.jsonl", 0, None, "vscode"),
                ("sub-1", "C:/work", "Subagent", "", 3, 0, 0, 0, 0, "", "", "c.jsonl", 0, "subagent", "vscode"),
                ("legacy-sub", "C:/work", "Legacy subagent", "", 4, 0, 0, 0, 0, "", "", "d.jsonl", 0, None, '{"subagent":{"other":"guardian"}}'),
                ("old-1", "C:/work", "Archived", "", 5, 0, 0, 0, 0, "", "", "e.jsonl", 1, "user", "vscode"),
            ]
            connection.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            connection.commit()
            connection.close()
            result = read_user_thread_rows(database)
            self.assertEqual([row[0] for row in result], ["user-1", "legacy-user"])


class BinaryDiscoveryTests(unittest.TestCase):
    def test_override_takes_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "custom-codex.exe"
            binary.touch()
            self.assertEqual(find_codex_binary(override=binary), str(binary))

    def test_desktop_direct_binary_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "OpenAI" / "Codex" / "bin" / "codex.exe"
            binary.parent.mkdir(parents=True)
            binary.touch()
            self.assertEqual(find_codex_binary(local_app_data=directory, path_env=""), str(binary))


if __name__ == "__main__":
    unittest.main()
