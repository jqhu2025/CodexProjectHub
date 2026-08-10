import inspect
import unittest
from datetime import datetime

from codex_hub import portfolio


class PortfolioModuleTests(unittest.TestCase):
    def test_domain_module_has_no_qt_dependency(self):
        self.assertNotIn("PyQt", inspect.getsource(portfolio))

    def test_focus_capacity_separates_strategy_from_live_execution(self):
        projects = [
            {"id": "focus", "status": "active", "priority": "focus", "conversations": []},
            {"id": "live", "status": "active", "priority": "normal", "activeTaskCount": 1, "conversations": []},
            {"id": "both", "status": "active", "priority": "focus", "conversations": [{"state": "working"}]},
            {"id": "paused", "status": "paused", "priority": "focus", "activeTaskCount": 1},
        ]
        state = portfolio.portfolio_focus_capacity_state(projects, 3)
        self.assertEqual([project["id"] for project in state["strategic"]], ["focus", "both"])
        self.assertEqual([project["id"] for project in state["executing"]], ["live", "both"])
        self.assertEqual([project["id"] for project in state["executionOutsideFocus"]], ["live"])
        self.assertEqual([project["id"] for project in state["focusWithoutExecution"]], ["focus"])

    def test_activity_evidence_resolves_stable_project_ids(self):
        project = {
            "id": "runtime", "savedId": "stable", "reviewedAt": "2026-08-06T09:00:00",
            "conversations": [{"at": "2026-08-08T10:00:00+00:00", "state": "linked"}],
        }
        tasks = [{
            "projectId": "stable", "date": "2026-08-07", "status": "done",
            "statusHistory": [{"at": "2026-08-07T12:00:00", "from": "doing", "to": "done", "source": "manual"}],
        }]
        evidence = portfolio.project_activity_evidence(project, tasks, datetime(2026, 8, 11, 12, 0, 0))
        self.assertEqual(evidence["source"], "Codex 对话")
        self.assertEqual(evidence["taskCount"], 1)
        self.assertEqual(evidence["conversationCount"], 1)

    def test_task_project_identity_distinguishes_current_historical_orphan_and_unlinked(self):
        task = {"projectId": "old", "projectNameSnapshot": "Original project"}
        self.assertEqual(portfolio.task_project_identity(task, {"name": "Renamed project"}), {"name": "Renamed project", "state": "current"})
        self.assertEqual(portfolio.task_project_identity(task), {"name": "Original project（历史关联）", "state": "historical"})
        self.assertEqual(portfolio.task_project_identity({"projectId": "missing"})["state"], "orphan")
        self.assertEqual(portfolio.task_project_identity({})["state"], "unlinked")

    def test_snapshot_reconciliation_backfills_only_unique_resolved_links(self):
        tasks = [
            {"id": "resolved", "projectId": "stable"},
            {"id": "preserved", "projectId": "stable", "projectNameSnapshot": "Original"},
            {"id": "orphan", "projectId": "missing"},
        ]
        projects = [{"id": "runtime", "savedId": "stable", "name": "Current", "category": "Research"}]
        changed = portfolio.reconcile_task_project_snapshots(tasks, projects)
        self.assertEqual(changed, 3)
        self.assertEqual(tasks[0]["projectNameSnapshot"], "Current")
        self.assertEqual(tasks[0]["projectCategorySnapshot"], "Research")
        self.assertEqual(tasks[1]["projectNameSnapshot"], "Original")
        self.assertEqual(tasks[1]["projectCategorySnapshot"], "Research")
        self.assertNotIn("projectNameSnapshot", tasks[2])

    def test_taxonomy_migration_updates_current_task_references_without_touching_history_events(self):
        tasks = [
            {"id": "linked", "projectId": "stable", "category": "Old", "projectCategorySnapshot": "Old"},
            {"id": "unlinked", "category": "Old"},
            {"id": "archived", "category": "Old", "archivedAt": "2026-08-10T12:00:00"},
            {"id": "other", "category": "Other"},
        ]
        changed = portfolio.migrate_task_category_references(tasks, "Old", "Renamed")
        self.assertEqual(changed, 3)
        self.assertEqual(tasks[0]["projectCategorySnapshot"], "Renamed")
        self.assertEqual(tasks[1]["category"], "Renamed")
        self.assertEqual(tasks[2]["category"], "Renamed")
        self.assertEqual(tasks[3]["category"], "Other")

        tasks[0]["category"] = "Inconsistent"
        project = {"id": "runtime", "savedId": "stable"}
        self.assertEqual(portfolio.migrate_project_task_category_references(tasks, project, "Research"), 1)
        self.assertEqual((tasks[0]["category"], tasks[0]["projectCategorySnapshot"]), ("Research", "Research"))

    def test_category_reconciliation_repairs_only_uniquely_resolved_links(self):
        projects = [
            {"id": "runtime", "savedId": "stable", "category": "Research"},
            {"id": "duplicate-a", "savedId": "ambiguous", "category": "A"},
            {"id": "duplicate-b", "savedId": "ambiguous", "category": "B"},
        ]
        tasks = [
            {
                "id": "repair", "projectId": "stable", "category": "Legacy",
                "projectCategorySnapshot": "Research", "updatedAt": "2026-08-01T09:00:00",
            },
            {"id": "ambiguous", "projectId": "ambiguous", "category": "Legacy"},
            {"id": "unlinked", "category": "Personal"},
        ]
        changed = portfolio.reconcile_task_project_categories(tasks, projects)
        self.assertEqual(changed, 1)
        self.assertEqual((tasks[0]["category"], tasks[0]["projectCategorySnapshot"]), ("Research", "Research"))
        self.assertEqual(tasks[0]["updatedAt"], "2026-08-01T09:00:00")
        self.assertEqual(tasks[1]["category"], "Legacy")
        self.assertEqual(tasks[2]["category"], "Personal")

    def test_project_link_issues_ignore_resolved_and_recycled_tasks(self):
        projects = [{"id": "runtime", "savedId": "stable"}]
        tasks = [
            {"id": "resolved", "projectId": "stable"},
            {"id": "orphan", "projectId": "missing"},
            {"id": "recycled", "projectId": "missing", "archivedAt": "2026-08-10T12:00:00"},
            {"id": "unlinked"},
        ]
        self.assertEqual(
            [task["id"] for task in portfolio.task_project_link_issues(tasks, projects)],
            ["orphan"],
        )

    def test_project_link_repair_preserves_task_activity_and_records_identity_evidence(self):
        task = {
            "id": "task", "projectId": "obsolete", "projectNameSnapshot": "Previous project",
            "category": "Old", "updatedAt": "2026-08-09T09:00:00", "status": "doing",
        }
        project = {"id": "runtime", "savedId": "stable", "name": "Current project", "category": "Research"}
        changed = portfolio.assign_task_project(task, project, "2026-08-10T10:00:00", "manual_repair")
        self.assertTrue(changed)
        self.assertEqual((task["projectId"], task["projectNameSnapshot"], task["category"]), ("stable", "Current project", "Research"))
        self.assertEqual((task["status"], task["updatedAt"]), ("doing", "2026-08-09T09:00:00"))
        event = portfolio.task_project_link_events(task)[0]
        self.assertEqual((event["fromProjectId"], event["toProjectId"], event["source"]), ("obsolete", "stable", "manual_repair"))
        self.assertFalse(portfolio.assign_task_project(task, project, "2026-08-10T11:00:00"))

    def test_conversation_repair_requires_one_unique_candidate_and_respects_archived_projects(self):
        tasks = [
            {"id": "recover", "projectId": "obsolete", "sessionId": "session-1"},
            {"id": "ambiguous", "projectId": "missing", "sessionId": "session-2"},
            {"id": "archived-valid", "projectId": "archived-stable", "sessionId": "session-1"},
        ]
        projects = [
            {"id": "one", "savedId": "stable-1", "name": "One", "category": "A", "conversations": [{"sessionId": "session-1"}, {"sessionId": "session-2"}]},
            {"id": "two", "savedId": "stable-2", "name": "Two", "category": "B", "conversations": [{"sessionId": "session-2"}]},
        ]
        known = [*projects, {"id": "archived", "savedId": "archived-stable", "name": "Archived"}]
        repaired = portfolio.reconcile_task_project_links_from_conversations(
            tasks, projects, "2026-08-10T10:00:00", known
        )
        self.assertEqual([task["id"] for task in repaired], ["recover"])
        self.assertEqual(tasks[0]["projectId"], "stable-1")
        self.assertEqual(tasks[1]["projectId"], "missing")
        self.assertEqual(tasks[2]["projectId"], "archived-stable")

    def test_lifecycle_queue_excludes_focus_live_risk_and_nonactive_projects(self):
        now = datetime(2026, 8, 10, 12, 0, 0)
        stale = {"id": "stale", "name": "Stale", "status": "active", "priority": "normal", "health": "on_track", "conversations": [{"at": "2026-07-01T09:00:00", "state": "linked"}]}
        no_evidence = {"id": "none", "name": "No evidence", "status": "active", "priority": "normal", "health": "on_track", "conversations": []}
        focused = {"id": "focus", "status": "active", "priority": "focus", "health": "on_track", "conversations": []}
        live = {"id": "live", "status": "active", "priority": "normal", "health": "on_track", "activeTaskCount": 1, "conversations": []}
        risk = {"id": "risk", "status": "active", "priority": "normal", "health": "attention", "conversations": []}
        paused = {"id": "paused", "status": "paused", "priority": "normal", "health": "on_track", "conversations": []}
        queue = portfolio.portfolio_lifecycle_calibration_queue(
            [stale, no_evidence, focused, live, risk, paused], [], now, 14
        )
        self.assertEqual([item["project"]["id"] for item in queue], ["none", "stale"])

    def test_wip_capacity_filters_day_status_archive_and_running_protection(self):
        tasks = [
            {"id": "run", "date": "2026-08-10", "status": "doing", "sessionId": "session-1"},
            {"id": "manual", "date": "2026-08-10", "status": "doing"},
            {"id": "planned", "date": "2026-08-10", "status": "planned"},
            {"id": "old", "date": "2026-08-09", "status": "doing"},
            {"id": "archived", "date": "2026-08-10", "status": "doing", "archivedAt": "2026-08-10T12:00:00"},
        ]
        state = portfolio.task_wip_capacity_state(tasks, "2026-08-10", 1, {"session-1"})
        self.assertEqual([task["id"] for task in state["doing"]], ["run", "manual"])
        self.assertEqual([task["id"] for task in state["protected"]], ["run"])
        self.assertEqual(state["overBy"], 1)

    def test_wip_recommendations_respect_project_priority_board_order_and_runtime_protection(self):
        tasks = [
            {"id": "focus", "projectId": "focus-project", "date": "2026-08-10", "status": "doing", "boardOrder": 0},
            {"id": "later", "projectId": "later-project", "date": "2026-08-10", "status": "doing", "boardOrder": 1},
            {"id": "normal", "projectId": "normal-project", "date": "2026-08-10", "status": "doing", "boardOrder": 2},
            {"id": "protected", "projectId": "later-project", "date": "2026-08-10", "status": "doing", "boardOrder": 3},
        ]
        projects = [
            {"id": "focus-project", "priority": "focus"},
            {"id": "later-project", "priority": "later"},
            {"id": "normal-project", "priority": "normal"},
        ]
        recommendations = portfolio.wip_deferral_recommendations(
            tasks, projects, "2026-08-10", 2, {"protected"}
        )
        self.assertEqual([item["task"]["id"] for item in recommendations], ["later", "normal"])
        self.assertIn("稍后处理", recommendations[0]["reason"])
        self.assertIn("非战略重点", recommendations[1]["reason"])
        self.assertEqual([task["status"] for task in tasks], ["doing"] * 4)

        focus_fallback = portfolio.wip_deferral_recommendations(
            tasks, projects, "2026-08-10", 3, {"protected"}
        )
        self.assertEqual([item["task"]["id"] for item in focus_fallback], ["later", "normal", "focus"])
        self.assertIn("其他候选不足", focus_fallback[-1]["reason"])

    def test_capacity_settings_are_bounded(self):
        self.assertEqual(portfolio.normalized_portfolio_focus_capacity(0), 1)
        self.assertEqual(portfolio.normalized_portfolio_focus_capacity(20), 9)
        self.assertEqual(portfolio.normalized_portfolio_inactivity_days(1), 7)
        self.assertEqual(portfolio.normalized_portfolio_inactivity_days(180), 90)
        self.assertEqual(portfolio.normalized_task_wip_limit(0), 1)
        self.assertEqual(portfolio.normalized_task_wip_limit(30), 9)


if __name__ == "__main__":
    unittest.main()
