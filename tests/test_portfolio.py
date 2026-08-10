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

    def test_capacity_settings_are_bounded(self):
        self.assertEqual(portfolio.normalized_portfolio_focus_capacity(0), 1)
        self.assertEqual(portfolio.normalized_portfolio_focus_capacity(20), 9)
        self.assertEqual(portfolio.normalized_portfolio_inactivity_days(1), 7)
        self.assertEqual(portfolio.normalized_portfolio_inactivity_days(180), 90)
        self.assertEqual(portfolio.normalized_task_wip_limit(0), 1)
        self.assertEqual(portfolio.normalized_task_wip_limit(30), 9)


if __name__ == "__main__":
    unittest.main()
