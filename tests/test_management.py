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
