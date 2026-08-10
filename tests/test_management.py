import inspect
import unittest

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

    def test_decision_diff_ignores_cosmetic_whitespace(self):
        before = {"objective": "Validate   the model", "health": "on_track"}
        after = {"objective": " Validate the model ", "health": "attention"}
        changes = management.project_decision_changes(before, after)
        self.assertEqual([change["field"] for change in changes], ["health"])


if __name__ == "__main__":
    unittest.main()
