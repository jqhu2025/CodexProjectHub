import inspect
import unittest
from datetime import datetime

from codex_hub import management


class ManagementModuleTests(unittest.TestCase):
    def test_domain_module_has_no_qt_dependency(self):
        self.assertNotIn("PyQt", inspect.getsource(management))

    def test_task_history_records_only_real_transitions(self):
        task = {"id": "task-1", "status": "planned"}
        self.assertTrue(management.record_task_status_event(
            task, "planned", "doing", "2026-08-10T09:00:00", "drag"
        ))
        self.assertFalse(management.record_task_status_event(
            task, "doing", "doing", "2026-08-10T09:01:00", "selector"
        ))
        event = management.task_status_events([task])[0]
        self.assertEqual((event["from"], event["to"], event["source"]), ("planned", "doing", "drag"))

    def test_task_archive_round_trip_preserves_status_and_transition_history(self):
        task = {
            "id": "task-1",
            "status": "doing",
            "date": "2026-08-10",
            "boardOrder": 2,
            "statusHistory": [{"at": "09:00", "from": "planned", "to": "doing", "source": "manual"}],
        }
        self.assertTrue(management.archive_task_record(task, "2026-08-10T11:00:00"))
        self.assertTrue(management.task_is_archived(task))
        self.assertEqual(management.active_task_records([task]), [])
        self.assertEqual(management.archived_task_records([task]), [task])
        self.assertEqual(task["status"], "doing")
        self.assertEqual(len(task["statusHistory"]), 1)
        self.assertTrue(management.restore_task_record(task, "2026-08-10T11:30:00"))
        self.assertFalse(management.task_is_archived(task))
        self.assertEqual(task["lastArchivedAt"], "2026-08-10T11:00:00")
        self.assertEqual(task["status"], "doing")
        self.assertEqual(len(task["statusHistory"]), 1)
        self.assertNotIn("boardOrder", task)

    def test_archived_tasks_never_participate_in_board_order(self):
        tasks = [
            {"id": "active", "date": "2026-08-10", "status": "doing", "boardOrder": 1},
            {"id": "archived", "date": "2026-08-10", "status": "doing", "boardOrder": 0, "archivedAt": "2026-08-10T10:00:00"},
        ]
        self.assertEqual([task["id"] for task in management.ordered_board_tasks(tasks, "2026-08-10", "doing")], ["active"])
        self.assertFalse(management.reorder_task_board(tasks, "archived", "planned", 0)["changed"])

    def test_project_archive_round_trip_preserves_category_order(self):
        layout = {"hiddenProjectIds": [], "categoryOrders": {"Research": ["project-1", "project-2"]}}
        archived, changed = management.archive_project_layout(layout, "project-1")
        self.assertTrue(changed)
        self.assertEqual(archived["hiddenProjectIds"], ["project-1"])
        self.assertEqual(archived["categoryOrders"], layout["categoryOrders"])
        restored, changed = management.restore_project_layout(archived, "project-1")
        self.assertTrue(changed)
        self.assertEqual(restored["hiddenProjectIds"], [])
        self.assertEqual(restored["categoryOrders"], layout["categoryOrders"])

    def test_project_archive_is_idempotent(self):
        layout = {"hiddenProjectIds": ["project-1"], "categoryOrders": {}}
        archived, changed = management.archive_project_layout(layout, "project-1")
        self.assertFalse(changed)
        self.assertEqual(archived["hiddenProjectIds"], ["project-1"])
        restored, changed = management.restore_project_layout(layout, "unknown")
        self.assertFalse(changed)
        self.assertEqual(restored["hiddenProjectIds"], ["project-1"])

    def test_task_board_reorders_within_a_column(self):
        tasks = [
            {"id": "first", "date": "2026-08-10", "status": "planned", "boardOrder": 0, "createdAt": "09:00"},
            {"id": "second", "date": "2026-08-10", "status": "planned", "boardOrder": 1, "createdAt": "10:00"},
        ]
        movement = management.reorder_task_board(tasks, "second", "planned", 0)
        self.assertTrue(movement["changed"])
        self.assertEqual(movement["previousIndex"], 1)
        ordered = management.ordered_board_tasks(tasks, "2026-08-10", "planned")
        self.assertEqual([task["id"] for task in ordered], ["second", "first"])
        self.assertEqual([task["boardOrder"] for task in ordered], [0, 1])

    def test_task_board_cross_column_move_reindexes_both_columns(self):
        tasks = [
            {"id": "planned-a", "date": "2026-08-10", "status": "planned", "boardOrder": 0},
            {"id": "planned-b", "date": "2026-08-10", "status": "planned", "boardOrder": 1},
            {"id": "doing-a", "date": "2026-08-10", "status": "doing", "boardOrder": 0},
        ]
        movement = management.reorder_task_board(tasks, "planned-b", "doing", 0)
        self.assertEqual(movement["previousStatus"], "planned")
        self.assertEqual([task["id"] for task in management.ordered_board_tasks(tasks, "2026-08-10", "planned")], ["planned-a"])
        self.assertEqual([task["id"] for task in management.ordered_board_tasks(tasks, "2026-08-10", "doing")], ["planned-b", "doing-a"])
        self.assertEqual([task["boardOrder"] for task in management.ordered_board_tasks(tasks, "2026-08-10", "doing")], [0, 1])

    def test_task_board_legacy_order_is_stable_until_user_reorders(self):
        tasks = [
            {"id": "later", "date": "2026-08-10", "status": "doing", "createdAt": "2026-08-10T10:00:00"},
            {"id": "earlier", "date": "2026-08-10", "status": "doing", "createdAt": "2026-08-10T09:00:00"},
        ]
        ordered = management.ordered_board_tasks(tasks, "2026-08-10", "doing")
        self.assertEqual([task["id"] for task in ordered], ["earlier", "later"])

    def test_completed_project_uses_a_real_displayable_completion_stage(self):
        normalized, notes = management.normalize_project_management_decision(
            {"status": "active"},
            {
                "status": "completed",
                "stage": "execution",
                "health": "blocked",
                "blocker": "Awaiting review",
                "nextStep": "Run again",
            },
        )
        self.assertEqual(normalized["stage"], "completion")
        self.assertEqual(management.PROJECT_STAGE[normalized["stage"]], "收尾")
        self.assertEqual(normalized["blocker"], "")
        self.assertTrue(notes)

    def test_completed_next_step_can_be_reopened_without_overwriting_newer_work(self):
        task = {"origin": "project_next_step", "projectNextStep": "Validate release"}
        completed = management.project_next_step_completion_update(
            {"nextStep": "Validate release"}, task, "2026-08-10T10:00:00"
        )
        project = {"status": "active", **completed}
        reopened = management.project_next_step_reopen_update(project, task)
        self.assertEqual(reopened["nextStep"], "Validate release")
        project["nextStep"] = "Publish report"
        self.assertIsNone(management.project_next_step_reopen_update(project, task))

    def test_project_governance_gaps_follow_real_management_requirements(self):
        active = {
            "status": "active", "objective": "", "nextStep": "", "stage": "execution",
            "health": "blocked", "blocker": "",
        }
        self.assertEqual(
            management.project_governance_gaps(active),
            ["objective", "nextStep", "blocker"],
        )
        paused = {"status": "paused", "objective": "", "nextStep": "", "stage": "planning", "health": "on_track"}
        self.assertEqual(management.project_governance_gaps(paused), ["objective"])

    def test_codex_governance_merge_only_fills_missing_human_decisions(self):
        project = {
            "status": "active",
            "objective": "Deliver the verified release",
            "nextStep": "",
            "stage": "validation",
            "health": "on_track",
            "blocker": "",
            "nextStepReviewNeeded": True,
        }
        insight = {
            "objective": "Replace the human objective",
            "nextStep": "Run the release verification suite",
            "stage": "delivery",
            "health": "blocked",
            "blocker": "Invented blocker",
        }
        merged, applied = management.merge_missing_project_insight(project, insight)
        self.assertEqual(applied, ["nextStep"])
        self.assertEqual(merged["objective"], project["objective"])
        self.assertEqual(merged["stage"], "validation")
        self.assertEqual(merged["health"], "on_track")
        self.assertEqual(merged["blocker"], "")
        self.assertEqual(merged["nextStep"], "Run the release verification suite")
        self.assertFalse(merged["nextStepReviewNeeded"])

    def test_codex_governance_merge_rechecks_gaps_after_analysis(self):
        project = {
            "status": "active", "objective": "Human decision made while Codex ran",
            "nextStep": "Ship it", "stage": "execution", "health": "on_track",
        }
        merged, applied = management.merge_missing_project_insight(
            project,
            {"objective": "Stale suggestion", "nextStep": "Stale next step"},
            allowed_fields=["objective", "nextStep"],
        )
        self.assertEqual(applied, [])
        self.assertEqual(merged, project)

    def test_legacy_attention_requires_review_without_flagging_healthy_legacy_projects(self):
        attention = {"status": "active", "priority": "normal", "health": "attention"}
        healthy = {"status": "active", "priority": "normal", "health": "on_track"}
        self.assertEqual(management.project_review_status(attention), (True, None, 7))
        self.assertEqual(management.project_review_status(healthy), (False, None, 7))

    def test_review_cadence_tracks_management_priority(self):
        now = datetime(2026, 8, 10, 12, 0, 0)
        focus = {"status": "active", "priority": "focus", "health": "on_track", "reviewedAt": "2026-08-06T12:00:00"}
        normal = {"status": "active", "priority": "normal", "health": "on_track", "reviewedAt": "2026-08-06T12:00:00"}
        self.assertEqual(management.project_review_status(focus, now), (True, 4, 3))
        self.assertEqual(management.project_review_status(normal, now), (False, 4, 7))

    def test_explicit_project_review_is_auditable_without_fake_field_changes(self):
        project = {
            "id": "runtime-id", "savedId": "stable-id", "name": "Release",
            "stage": "validation", "health": "attention", "nextStep": "Run verification", "blocker": "",
        }
        entry = management.build_project_review_entry(project, "2026-08-10T12:00:00", "review-1")
        self.assertEqual(entry["id"], "review-1")
        self.assertEqual(entry["projectId"], "stable-id")
        self.assertEqual(entry["source"], "review")
        self.assertEqual(entry["changes"], [])
        self.assertIn("验证阶段", management.format_project_decision_summary(entry))
        self.assertIn("需关注", management.format_project_decision_summary(entry))

    def test_decision_diff_ignores_cosmetic_whitespace(self):
        before = {"objective": "Validate   the model", "health": "on_track"}
        after = {"objective": " Validate the model ", "health": "attention"}
        changes = management.project_decision_changes(before, after)
        self.assertEqual([change["field"] for change in changes], ["health"])

    def test_decision_rollback_is_selective_and_detects_newer_changes(self):
        project = {"objective": "Validated model", "health": "blocked", "nextStep": "Publish report"}
        entry = {"changes": [
            {"field": "objective", "label": "项目目标", "before": "Baseline model", "after": "Validated model"},
            {"field": "health", "label": "项目健康度", "before": "on_track", "after": "attention"},
        ]}
        requested, affected, conflicts = management.build_project_decision_rollback(project, entry)
        self.assertEqual(requested["objective"], "Baseline model")
        self.assertEqual(requested["health"], "on_track")
        self.assertEqual(requested["nextStep"], "Publish report")
        self.assertEqual([item["field"] for item in affected], ["objective", "health"])
        self.assertEqual([item["field"] for item in conflicts], ["health"])

    def test_latest_decision_rollback_has_no_false_conflict(self):
        project = {"stage": "validation", "health": "attention"}
        entry = {"changes": [
            {"field": "stage", "before": "execution", "after": "validation"},
            {"field": "health", "before": "on_track", "after": "attention"},
            {"field": "unsupported", "before": "x", "after": "y"},
        ]}
        requested, affected, conflicts = management.build_project_decision_rollback(project, entry)
        self.assertEqual(requested["stage"], "execution")
        self.assertEqual(requested["health"], "on_track")
        self.assertEqual(len(affected), 2)
        self.assertEqual(conflicts, [])


if __name__ == "__main__":
    unittest.main()
