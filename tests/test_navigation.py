from pathlib import Path
import unittest

from codex_hub.navigation import build_navigation_entries, search_navigation_entries


class NavigationCatalogTests(unittest.TestCase):
    def sample_catalog(self):
        projects = [{
            "id": "runtime-project",
            "savedId": "stable-project",
            "name": "Signal Modeling",
            "category": "Research",
            "priority": "focus",
            "stage": "validation",
            "status": "active",
            "objective": "Validate the denoising benchmark",
            "successCriteria": "Reproduce all benchmark metrics from a clean environment",
            "nextStep": "Compare alpha settings",
            "path": "C:\\work\\signals",
            "conversations": [
                {"sessionId": "thread-running", "conversationLabel": "Alpha benchmark", "state": "working", "summary": "Compare model noise levels"},
                {"sessionId": "thread-linked", "conversationLabel": "Release notes", "state": "completed"},
            ],
        }]
        tasks = [
            {"id": "doing", "title": "Validate alpha sweep", "projectId": "stable-project", "date": "2026-08-10", "status": "doing", "notes": "Compare 0.1 and 0.2"},
            {"id": "history", "title": "Old daily copy", "status": "doing", "carriedToTaskId": "doing"},
            {"id": "archived", "title": "Recycled task", "status": "planned", "archivedAt": "2026-08-09T10:00:00"},
        ]
        return build_navigation_entries(projects, tasks, today="2026-08-10")

    def test_catalog_combines_hierarchy_without_duplicate_or_retired_work(self):
        entries = self.sample_catalog()

        self.assertEqual([entry["kind"] for entry in entries], ["project", "conversation", "conversation", "task"])
        self.assertFalse(any(entry["title"] == "Old daily copy" for entry in entries))
        self.assertFalse(any(entry["title"] == "Recycled task" for entry in entries))

    def test_project_objective_task_notes_and_conversation_summary_are_searchable(self):
        entries = self.sample_catalog()

        self.assertEqual(search_navigation_entries(entries, "denoising")[0]["kind"], "project")
        self.assertEqual(search_navigation_entries(entries, "clean environment")[0]["kind"], "project")
        self.assertEqual(search_navigation_entries(entries, "0.1 0.2")[0]["kind"], "task")
        self.assertEqual(search_navigation_entries(entries, "noise levels")[0]["kind"], "conversation")

    def test_running_conversation_and_active_task_rank_before_static_projects(self):
        entries = self.sample_catalog()

        results = search_navigation_entries(entries)

        self.assertEqual(results[0]["key"], "conversation:thread-running")
        self.assertEqual(results[1]["key"], "task:doing")

    def test_exact_title_match_beats_a_higher_priority_metadata_match(self):
        entries = self.sample_catalog()

        results = search_navigation_entries(entries, "Signal Modeling")

        self.assertEqual(results[0]["kind"], "project")

    def test_navigation_module_has_no_qt_dependency(self):
        source = Path(build_navigation_entries.__code__.co_filename).read_text(encoding="utf-8")

        self.assertNotIn("PyQt", source)


if __name__ == "__main__":
    unittest.main()
