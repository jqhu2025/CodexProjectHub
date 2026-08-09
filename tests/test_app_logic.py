import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


APP_PATH = Path(__file__).resolve().parents[1] / "app_qt.pyw"
SPEC = importlib.util.spec_from_file_location("codex_project_hub_app", APP_PATH)
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)


class ConversationMappingTests(unittest.TestCase):
    def test_path_fallback_runs_for_each_unmapped_thread(self):
        projects = [
            {
                "id": "project-a",
                "codexProjectId": "project-a",
                "path": "C:\\work",
                "rootPaths": ["C:\\work"],
            }
        ]
        index = {
            "sidebar-thread": {"cwd": "C:\\work"},
            "new-thread": {"cwd": "C:\\work\\feature"},
        }
        with patch.object(APP, "sidebar_thread_project_map", return_value={"sidebar-thread": "project-a"}):
            result = APP.codex_thread_project_map(projects, index)
        self.assertEqual(result["sidebar-thread"], "project-a")
        self.assertEqual(result["new-thread"], "project-a")


class ProjectDisplayStateTests(unittest.TestCase):
    def test_running_conversation_takes_priority(self):
        project = {"status": "completed", "conversations": [{"state": "working"}]}
        self.assertEqual(APP.project_display_state(project)[0], "running")

    def test_completed_conversation_does_not_complete_project(self):
        project = {"status": "active", "conversations": [{"state": "completed"}]}
        self.assertEqual(APP.project_display_state(project)[0], "linked")

    def test_project_completion_and_unlinked_states(self):
        self.assertEqual(APP.project_display_state({"status": "completed", "conversations": []})[0], "completed")
        self.assertEqual(APP.project_display_state({"status": "active", "conversations": []})[0], "unlinked")


class ProjectManagementInteractionTests(unittest.TestCase):
    def test_search_matches_conversation_title_and_status(self):
        search = SimpleNamespace(text=lambda: "benchmark")
        status_filter = SimpleNamespace(currentData=lambda: "running")
        window = SimpleNamespace(
            category="全部",
            search=search,
            status_filter=status_filter,
            projects=[
                {
                    "name": "Research project",
                    "category": "Research",
                    "conversations": [{"conversationLabel": "Benchmark review", "state": "working"}],
                },
                {
                    "name": "Other project",
                    "category": "Research",
                    "conversations": [{"conversationLabel": "Benchmark archive", "state": "completed"}],
                },
            ],
        )
        result = APP.MainWindow.shown(window)
        self.assertEqual([item["name"] for item in result], ["Research project"])

    def test_continue_project_prefers_running_conversation(self):
        linked = {"sessionId": "linked", "state": "linked"}
        running = {"sessionId": "running", "state": "working"}
        window = SimpleNamespace(copy_context=Mock(), open_codex_conversation=Mock())
        project = {"conversations": [linked, running]}
        APP.MainWindow.continue_project(window, project)
        window.copy_context.assert_called_once_with(project)
        window.open_codex_conversation.assert_called_once_with(running)

    def test_management_scope_surfaces_focus_and_missing_next_step(self):
        focus = {"priority": "focus", "status": "active", "nextStep": "Run validation"}
        missing = {"priority": "normal", "status": "active", "nextStep": ""}
        paused = {"priority": "normal", "status": "paused", "nextStep": "Decide whether to resume"}
        self.assertTrue(APP.project_management_scope_matches(focus, "focus"))
        self.assertTrue(APP.project_management_scope_matches(missing, "needs_next"))
        self.assertTrue(APP.project_management_scope_matches(paused, "paused"))
        self.assertFalse(APP.project_management_scope_matches(paused, "needs_next"))

    def test_focus_projects_sort_before_regular_projects(self):
        projects = [
            {"name": "Regular", "priority": "normal", "nextStep": "Continue"},
            {"name": "Focus", "priority": "focus", "nextStep": "Validate"},
        ]
        projects.sort(key=APP.project_management_sort_key)
        self.assertEqual([item["name"] for item in projects], ["Focus", "Regular"])


class DailySummaryTests(unittest.TestCase):
    def test_payload_uses_only_requested_date_and_resolves_project(self):
        tasks = [
            {"date": "2026-08-08", "title": "Validate model", "status": "doing", "projectId": "p1", "notes": "Compare alpha"},
            {"date": "2026-08-09", "title": "Today", "status": "planned", "projectId": "p1"},
        ]
        projects = [{"id": "p1", "name": "Denoising", "conversations": []}]
        payload = APP.build_daily_summary_payload(tasks, projects, "2026-08-08")
        self.assertEqual(len(payload["tasks"]), 1)
        self.assertEqual(payload["tasks"][0]["project"], "Denoising")
        self.assertEqual(payload["tasks"][0]["status"], "进行中")

    def test_prompt_requires_specific_structured_output(self):
        prompt = APP.daily_summary_prompt({"date": "2026-08-08", "tasks": [], "codexActivities": []})
        self.assertIn('"overview"', prompt)
        self.assertIn('"completed"', prompt)
        self.assertIn("不要虚构完成情况", prompt)

    def test_summary_thread_can_be_configured_without_committing_an_id(self):
        with patch.dict(APP.os.environ, {"CODEX_HUB_SUMMARY_THREAD_ID": "summary-thread"}):
            self.assertEqual(APP.daily_summary_thread_id(), "summary-thread")


if __name__ == "__main__":
    unittest.main()
