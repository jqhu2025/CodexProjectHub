import inspect
import unittest
from datetime import datetime

from codex_hub import portfolio


class PortfolioModuleTests(unittest.TestCase):
    def test_domain_module_has_no_qt_dependency(self):
        self.assertNotIn("PyQt", inspect.getsource(portfolio))

    def test_decision_routing_assigns_each_project_to_one_primary_queue(self):
        risk = {"id": "risk"}
        quiet = {"id": "quiet"}
        missing = {"id": "missing"}
        review = {"id": "review"}
        routing = portfolio.route_project_decision_queues((
            ("attention", [risk]),
            ("lifecycle", [{"project": quiet}]),
            ("needs_next", [risk, quiet, missing]),
            ("review", [risk, quiet, missing, review]),
        ))
        self.assertEqual(routing["queues"]["attention"], [risk])
        self.assertEqual(routing["queues"]["lifecycle"], [{"project": quiet}])
        self.assertEqual(routing["queues"]["needs_next"], [missing])
        self.assertEqual(routing["queues"]["review"], [review])
        self.assertEqual(routing["routedTo"]["needs_next"], {"attention": 1, "lifecycle": 1})
        self.assertEqual(
            routing["routedTo"]["review"],
            {"attention": 1, "lifecycle": 1, "needs_next": 1},
        )

    def test_decision_routing_matches_project_aliases_after_runtime_id_changes(self):
        saved_copy = {"savedId": "stable", "name": "Project"}
        bridge_copy = {"id": "runtime", "savedId": "stable", "name": "Project"}
        runtime_copy = {"id": "runtime", "name": "Project"}
        routing = portfolio.route_project_decision_queues((
            ("attention", [saved_copy]),
            ("needs_next", [bridge_copy]),
            ("review", [runtime_copy]),
        ))
        self.assertEqual(routing["queues"]["attention"], [saved_copy])
        self.assertEqual(routing["queues"]["needs_next"], [])
        self.assertEqual(routing["queues"]["review"], [])
        self.assertEqual(routing["routedTo"]["needs_next"], {"attention": 1})
        self.assertEqual(routing["routedTo"]["review"], {"attention": 1})

    def test_primary_project_decision_resolves_the_single_owner_across_aliases(self):
        runtime = {"id": "runtime", "savedId": "stable", "name": "Release"}
        routing = {"queues": {
            "attention": [{"id": "other"}],
            "alignment": [{"project": {"id": "bridge", "savedId": "stable"}, "tasks": []}],
            "review": [runtime],
        }}

        primary = portfolio.primary_project_decision(runtime, routing)

        self.assertEqual(primary["queue"], "alignment")
        self.assertEqual(primary["item"]["project"]["savedId"], "stable")

    def test_workbench_command_keeps_one_primary_decision_and_preserves_execution_evidence(self):
        project = {
            "id": "runtime", "savedId": "stable", "status": "active",
            "health": "blocked", "blocker": "Reference data unavailable",
            "objective": "Validate release", "nextStep": "Run validation",
        }
        tasks = [{
            "id": "task", "projectId": "stable", "date": "2026-08-10",
            "status": "doing", "title": "Investigate fallback",
        }]

        command = portfolio.project_workbench_command(
            project, tasks, "2026-08-10", {"queue": "attention", "item": project},
            datetime(2026, 8, 10, 12, 0, 0),
        )

        self.assertEqual((command["key"], command["action"]), ("attention", "resolve_blocker"))
        self.assertEqual(command["evidence"]["doingCount"], 1)
        self.assertIn("Reference data unavailable", command["reason"])
        self.assertIn("1 进行", command["evidenceText"])

    def test_workbench_command_distinguishes_live_execution_from_a_ready_next_step(self):
        project = {
            "id": "stable", "status": "active", "health": "on_track",
            "objective": "Ship", "nextStep": "Package release", "conversations": [],
        }
        ready = portfolio.project_workbench_command(
            project, [], "2026-08-10", now=datetime(2026, 8, 10, 12, 0, 0)
        )
        self.assertEqual((ready["key"], ready["action"]), ("ready", "schedule_next_step"))

        live_tasks = [{
            "projectId": "stable", "date": "2026-08-10", "status": "doing",
            "title": "Package release", "updatedAt": "2026-08-10T11:00:00",
        }]
        live = portfolio.project_workbench_command(
            project, live_tasks, "2026-08-10", now=datetime(2026, 8, 10, 12, 0, 0)
        )
        self.assertEqual((live["key"], live["action"]), ("execute", "continue_codex"))
        self.assertIn("最近活动：今天", live["evidenceText"])

    def test_workbench_review_command_explains_governance_before_confirmation(self):
        project = {
            "id": "stable", "status": "active", "health": "on_track",
            "stage": "", "objective": "", "nextStep": "Validate",
        }

        command = portfolio.project_workbench_command(
            project, [], "2026-08-10", {"queue": "review", "item": project},
            datetime(2026, 8, 10, 12, 0, 0),
        )

        self.assertEqual(command["key"], "review")
        self.assertEqual(command["action"], "confirm_review")
        self.assertIn("项目目标", command["reason"])

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

    def test_focus_guidance_frames_live_work_as_candidates_with_a_capacity_limit(self):
        projects = [
            {"id": str(index), "status": "active", "priority": "normal", "activeTaskCount": 1}
            for index in range(4)
        ]
        state = portfolio.portfolio_focus_capacity_state(projects, 3)
        self.assertEqual(
            portfolio.portfolio_focus_guidance(state),
            "4 项执行候选 · 最多选 3 项",
        )

        projects[0]["priority"] = "focus"
        state = portfolio.portfolio_focus_capacity_state(projects, 3)
        self.assertEqual(portfolio.portfolio_focus_guidance(state), "3 项执行候选 · 还可选 2 项")

        for project in projects[:3]:
            project["priority"] = "focus"
        state = portfolio.portfolio_focus_capacity_state(projects, 3)
        self.assertEqual(portfolio.portfolio_focus_guidance(state), "容量已满 · 1 项执行在重点外")

    def test_focus_commitment_only_queues_a_declared_action_without_other_live_work(self):
        projects = [
            {"id": "ready", "status": "active", "priority": "focus", "nextStep": "Run validation"},
            {"id": "scheduled", "status": "active", "priority": "focus", "nextStep": "Package release"},
            {"id": "other", "status": "active", "priority": "focus", "nextStep": "Write report"},
            {"id": "codex", "status": "active", "priority": "focus", "nextStep": "Review output", "conversations": [{"state": "working"}]},
            {"id": "missing", "status": "active", "priority": "focus", "nextStep": ""},
            {"id": "regular", "status": "active", "priority": "normal", "nextStep": "Run benchmark"},
        ]
        tasks = [
            {"id": "scheduled-task", "projectId": "scheduled", "status": "planned", "title": "Package release"},
            {"id": "other-task", "projectId": "other", "status": "doing", "title": "Investigate failure"},
        ]
        self.assertEqual(portfolio.project_next_step_commitment_state(projects[0], tasks)["state"], "ready")
        self.assertEqual(portfolio.project_next_step_commitment_state(projects[1], tasks)["state"], "scheduled")
        self.assertEqual(portfolio.project_next_step_commitment_state(projects[2], tasks)["state"], "live_other")
        self.assertEqual(portfolio.project_next_step_commitment_state(projects[3], tasks)["state"], "live_other")
        self.assertEqual(portfolio.project_next_step_commitment_state(projects[4], tasks)["state"], "missing")
        queue = portfolio.portfolio_focus_commitment_queue(projects, tasks)
        self.assertEqual([item["project"]["id"] for item in queue], ["ready", "missing"])

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

    def test_rescheduling_is_real_project_activity_evidence(self):
        project = {"id": "runtime", "savedId": "stable", "reviewedAt": "2026-08-06T09:00:00", "conversations": []}
        tasks = [{
            "projectId": "stable", "date": "2026-08-10", "status": "planned",
            "scheduleHistory": [{
                "at": "2026-08-10T11:00:00", "from": "2026-08-08", "to": "2026-08-10", "source": "planning_review",
            }],
        }]

        evidence = portfolio.project_activity_evidence(project, tasks, datetime(2026, 8, 11, 12, 0, 0))

        self.assertEqual(evidence["source"], "任务记录")
        self.assertEqual(evidence["ageDays"], 1)

    def test_project_review_evidence_combines_today_work_codex_activity_and_direction(self):
        project = {
            "id": "runtime", "savedId": "stable", "status": "active",
            "nextStep": "Declared direction",
            "conversations": [{"at": "2026-08-10T11:00:00", "state": "working"}],
        }
        tasks = [
            {"id": "planned", "projectId": "stable", "date": "2026-08-10", "status": "planned"},
            {"id": "doing", "projectId": "runtime", "date": "2026-08-10", "status": "doing", "title": "Different work"},
            {"id": "done", "projectId": "stable", "date": "2026-08-10", "status": "done"},
            {"id": "archived", "projectId": "stable", "date": "2026-08-10", "status": "doing", "archivedAt": "2026-08-10T12:00:00"},
            {"id": "history", "projectId": "stable", "date": "2026-08-10", "status": "doing", "carriedToTaskId": "doing"},
            {"id": "other", "projectId": "other", "date": "2026-08-10", "status": "doing"},
        ]
        evidence = portfolio.project_review_evidence(
            project, tasks, "2026-08-10", datetime(2026, 8, 10, 12, 0, 0)
        )
        self.assertEqual(
            (evidence["taskCount"], evidence["plannedCount"], evidence["doingCount"], evidence["doneCount"]),
            (3, 1, 1, 1),
        )
        self.assertEqual(evidence["runningConversationCount"], 1)
        self.assertEqual(evidence["alignmentState"], "divergent")
        self.assertEqual(evidence["activity"]["ageDays"], 0)

        project["executionAlignmentSignature"] = evidence["alignment"]["signature"]
        acknowledged = portfolio.project_review_evidence(project, tasks, "2026-08-10")
        self.assertEqual(acknowledged["alignmentState"], "acknowledged")

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
