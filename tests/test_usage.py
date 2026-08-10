import json
import queue
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from codex_hub import usage


class _QueueStdout:
    def __init__(self):
        self.lines = queue.Queue()

    def push(self, message):
        self.lines.put(json.dumps(message) + "\n")

    def close(self):
        self.lines.put(None)

    def __iter__(self):
        return self

    def __next__(self):
        line = self.lines.get(timeout=1)
        if line is None:
            raise StopIteration
        return line


class _FakeStdin:
    def __init__(self, process):
        self.process = process

    def write(self, line):
        message = json.loads(line)
        self.process.methods.append(message.get("method"))
        if message.get("method") == "initialize":
            self.process.stdout.push({"id": message["id"], "result": {"platformFamily": "windows"}})
        elif message.get("method") == "account/rateLimits/read":
            self.process.stdout.push({
                "id": message["id"],
                "result": {"rateLimits": {
                    "primary": {"usedPercent": 25, "windowDurationMins": 10080, "resetsAt": 1786882891},
                    "planType": "pro",
                }},
            })
        return len(line)

    def flush(self):
        return None


class _FakeProcess:
    def __init__(self):
        self.stdout = _QueueStdout()
        self.stdin = _FakeStdin(self)
        self.methods = []
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self.stdout.close()

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def kill(self):
        self.returncode = -9
        self.stdout.close()


class CodexUsageTests(unittest.TestCase):
    def tearDown(self):
        usage.reset_local_token_cache()

    @staticmethod
    def token_record(total, timestamp="2026-08-10T12:00:00+08:00"):
        return json.dumps({
            "timestamp": timestamp,
            "payload": {"type": "token_count", "info": {"total_token_usage": {"total_tokens": total}}},
        }, separators=(",", ":"))

    def test_local_token_estimate_is_incremental_without_double_counting(self):
        now = datetime(2026, 8, 10, 20, 0, tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory() as folder:
            session = Path(folder) / "session.jsonl"
            session.write_text(self.token_record(100) + "\n" + self.token_record(160) + "\n", encoding="utf-8")

            self.assertEqual(usage.local_codex_tokens_for_date(folder, "2026-08-10", now), 160)
            self.assertEqual(usage.local_codex_tokens_for_date(folder, "2026-08-10", now), 160)

            with session.open("a", encoding="utf-8") as stream:
                stream.write(self.token_record(225) + "\n")
            self.assertEqual(usage.local_codex_tokens_for_date(folder, "2026-08-10", now), 225)

    def test_local_token_estimate_subtracts_the_previous_day_cumulative_baseline(self):
        now = datetime(2026, 8, 10, 20, 0, tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory() as folder:
            session = Path(folder) / "session.jsonl"
            session.write_text(
                self.token_record(500, "2026-08-09T15:00:00+00:00") + "\n" +
                self.token_record(620, "2026-08-10T02:00:00+00:00") + "\n",
                encoding="utf-8",
            )

            self.assertEqual(usage.local_codex_tokens_for_date(folder, "2026-08-10", now), 120)

    def test_rate_limit_reader_uses_only_supported_app_server_telemetry(self):
        process = _FakeProcess()
        with patch.object(usage.subprocess, "Popen", return_value=process):
            response = usage.read_codex_rate_limits("codex.exe", timeout=0.5)

        self.assertEqual(response["result"]["rateLimits"]["primary"]["usedPercent"], 25)
        self.assertEqual(process.methods, ["initialize", "initialized", "account/rateLimits/read"])

    def test_snapshot_keeps_quota_and_local_tokens_truthfully_separate(self):
        now = datetime(2026, 8, 10, 21, 30, tzinfo=timezone(timedelta(hours=8)))
        response = {"result": {"rateLimits": {
            "primary": {"usedPercent": 25.2, "windowDurationMins": 10080, "resetsAt": 1786882891},
            "planType": "pro",
        }}}

        snapshot = usage.build_codex_usage_snapshot(response, 123456, now)

        self.assertEqual((snapshot["usedPercent"], snapshot["remainingPercent"]), (25, 75))
        self.assertEqual(snapshot["todayTokens"], 123456)
        self.assertEqual(snapshot["todayTokensSource"], "local")
        self.assertEqual(snapshot["planType"], "pro")
        self.assertNotIn("error", snapshot)

    def test_quota_failure_still_returns_local_token_evidence(self):
        now = datetime(2026, 8, 10, 20, 0, tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory() as folder:
            session = Path(folder) / "session.jsonl"
            session.write_text(self.token_record(320) + "\n", encoding="utf-8")

            snapshot = usage.read_codex_usage(None, folder, now=now)

        self.assertEqual(snapshot["todayTokens"], 320)
        self.assertEqual(snapshot["todayTokensSource"], "local")
        self.assertIn("未找到", snapshot["error"])

    def test_invalid_quota_payload_is_not_presented_as_zero_usage(self):
        snapshot = usage.build_codex_usage_snapshot({"result": {}}, 40)

        self.assertIn("未返回主额度", snapshot["error"])
        self.assertNotIn("usedPercent", snapshot)


if __name__ == "__main__":
    unittest.main()
