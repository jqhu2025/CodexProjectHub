import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


APP_PATH = Path(__file__).resolve().parents[1] / "app_qt.pyw"
SPEC = importlib.util.spec_from_file_location("codex_project_hub_app", APP_PATH)
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)


class StorageRecoveryNoticeTests(unittest.TestCase):
    def test_recovered_files_get_a_calm_status_notice(self):
        events = [SimpleNamespace(filename="today_tasks.json", recovered=True)]

        message, duration = APP.storage_recovery_notice(events)

        self.assertIn("已从本地安全副本恢复", message)
        self.assertIn("today_tasks.json", message)
        self.assertEqual(duration, 7000)

    def test_unrecovered_failure_takes_priority_over_recovery(self):
        events = [
            SimpleNamespace(filename="projects.json", recovered=True),
            SimpleNamespace(filename="categories.json", recovered=False),
        ]

        message, duration = APP.storage_recovery_notice(events)

        self.assertIn("本地数据无法读取", message)
        self.assertIn("categories.json", message)
        self.assertNotIn("projects.json", message)
        self.assertEqual(duration, 9000)

    def test_no_events_need_no_status_notice(self):
        self.assertIsNone(APP.storage_recovery_notice([]))


class GlobalCommandPaletteTests(unittest.TestCase):
    def command_window(self):
        return SimpleNamespace(
            today_tasks=[{"id": "task-1", "title": "Validate", "status": "doing"}],
            open_project_workspace=Mock(), show_task_audit=Mock(), open_codex_conversation=Mock(),
            new_today_task=Mock(), edit_project=Mock(), show_task_history=Mock(), refresh=Mock(),
            select_section=Mock(), show_running_conversations=Mock(), show_planning_backlog=Mock(),
            show_completion_evidence_queue=Mock(),
        )

    def test_project_task_and_conversation_results_return_to_existing_workflows(self):
        window = self.command_window()
        project = {"id": "project-1", "name": "Release"}
        task = {"id": "task-1", "title": "Validate"}
        conversation = {"sessionId": "thread-1", "conversationLabel": "Release checks"}

        self.assertTrue(APP.MainWindow.execute_command_entry(window, {"kind": "project", "payload": project}))
        self.assertTrue(APP.MainWindow.execute_command_entry(window, {"kind": "task", "payload": task}))
        self.assertTrue(APP.MainWindow.execute_command_entry(window, {"kind": "conversation", "payload": conversation}))

        window.open_project_workspace.assert_called_once_with(project)
        window.show_task_audit.assert_called_once_with(window.today_tasks[0])
        window.open_codex_conversation.assert_called_once_with(conversation)

    def test_action_results_reuse_existing_commands(self):
        window = self.command_window()

        handled = APP.MainWindow.execute_command_entry(
            window, {"kind": "action", "payload": {"action": "refresh"}}
        )

        self.assertTrue(handled)
        window.refresh.assert_called_once_with()

    def test_planning_backlog_action_opens_the_review_queue(self):
        window = self.command_window()

        handled = APP.MainWindow.execute_command_entry(
            window, {"kind": "action", "payload": {"action": "plan_backlog"}}
        )

        self.assertTrue(handled)
        window.show_planning_backlog.assert_called_once_with()

    def test_completion_evidence_action_opens_the_review_queue(self):
        window = self.command_window()

        handled = APP.MainWindow.execute_command_entry(
            window, {"kind": "action", "payload": {"action": "completion_evidence"}}
        )

        self.assertTrue(handled)
        window.show_completion_evidence_queue.assert_called_once_with()

    def test_command_catalog_surfaces_planning_backlog_only_when_actionable(self):
        window = SimpleNamespace(
            running_count=0,
            completion_evidence_queue=lambda: [],
            planning_backlog=lambda: [{"id": "task-1", "title": "Validate", "date": "2026-08-08"}],
            projects=[],
            today_tasks=[],
            _command_action=APP.MainWindow._command_action,
        )

        entries = APP.MainWindow.command_catalog(window)

        backlog = next(entry for entry in entries if entry.get("key") == "action:plan_backlog")
        self.assertIn("1 项", backlog["subtitle"])
        self.assertEqual(backlog["payload"]["action"], "plan_backlog")

        window.completion_evidence_queue = lambda: [{"id": "done", "title": "Delivered", "status": "done"}]
        entries = APP.MainWindow.command_catalog(window)
        evidence = next(entry for entry in entries if entry.get("key") == "action:completion_evidence")
        self.assertIn("1 项", evidence["subtitle"])

    def test_unknown_command_is_safely_ignored(self):
        window = self.command_window()

        self.assertFalse(APP.MainWindow.execute_command_entry(window, {"kind": "unknown", "payload": {}}))
        self.assertFalse(APP.MainWindow.execute_command_entry(window, {"kind": "action", "payload": {"action": "missing"}}))


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


class ProjectIdentityTests(unittest.TestCase):
    def test_codex_source_name_wins_until_an_explicit_local_override_exists(self):
        state = {
            "local-projects": {
                "codex-project": {
                    "name": "Codex source name",
                    "rootPaths": ["C:\\workspace\\project"],
                },
            },
            "project-order": ["codex-project"],
        }
        saved = [{
            "id": "saved-project",
            "name": "Legacy cached name",
            "path": "C:\\workspace\\project",
        }]
        with patch.object(APP, "codex_global_state", return_value=state):
            project = APP.codex_sidebar_projects(saved)[0]
        self.assertEqual(project["name"], "Codex source name")
        self.assertEqual(project["sourceName"], "Codex source name")

        saved[0]["nameOverride"] = "Portfolio display name"
        with patch.object(APP, "codex_global_state", return_value=state):
            project = APP.codex_sidebar_projects(saved)[0]
        self.assertEqual(project["name"], "Portfolio display name")
        self.assertEqual(project["sourceName"], "Codex source name")

    def test_display_name_override_can_be_restored_to_the_codex_source(self):
        project = {
            "codexProjectId": "codex-project",
            "name": "Portfolio display name",
            "sourceName": "Codex source name",
        }
        target = {"name": "Portfolio display name", "nameOverride": "Portfolio display name"}
        self.assertTrue(APP.apply_project_display_name(target, project, "Codex source name"))
        self.assertEqual(target["name"], "Codex source name")
        self.assertNotIn("nameOverride", target)

        self.assertTrue(APP.apply_project_display_name(target, project, "Executive portfolio"))
        self.assertEqual(target["nameOverride"], "Executive portfolio")


class ProjectArchiveTests(unittest.TestCase):
    def test_archived_manual_project_keeps_its_complete_management_record(self):
        saved = [{
            "id": "manual-id",
            "manualProject": True,
            "name": "Release planning",
            "path": "C:\\workspace\\release-planning",
            "category": "Operations",
            "objective": "Prepare the release",
            "nextStep": "Validate the package",
        }]
        layout = {"hiddenProjectIds": ["manual:manual-id"], "categoryOrders": {"Operations": ["manual:manual-id"]}}
        with patch.object(APP, "codex_sidebar_projects", return_value=[]):
            self.assertEqual(APP.visible_project_catalog(saved, layout), [])
            archived = APP.archived_project_catalog(saved, layout)
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["name"], "Release planning")
        self.assertEqual(archived[0]["objective"], "Prepare the release")
        self.assertEqual(archived[0]["nextStep"], "Validate the package")

    def test_archived_codex_project_can_be_resolved_for_restore(self):
        imported = [{
            "id": "codex-project-id",
            "codexProjectId": "codex-project-id",
            "name": "Model validation",
            "path": "C:\\workspace\\model-validation",
            "category": "Research",
        }]
        layout = {"hiddenProjectIds": ["codex-project-id"], "categoryOrders": {}}
        with patch.object(APP, "codex_sidebar_projects", return_value=imported):
            archived = APP.archived_project_catalog([], layout)
        self.assertEqual([project["id"] for project in archived], ["codex-project-id"])

    def test_restore_records_project_lifecycle_before_refresh(self):
        project = {"id": "project-1", "name": "Release"}
        status_bar = Mock()
        window = SimpleNamespace(
            project_layout={"hiddenProjectIds": ["project-1"], "categoryOrders": {}},
            record_project_lifecycle=Mock(), refresh=Mock(), view_signature="old", statusBar=lambda: status_bar,
        )
        with patch.object(APP, "save_json") as save:
            restored = APP.MainWindow.restore_project(window, project)
        self.assertTrue(restored)
        window.record_project_lifecycle.assert_called_once_with(project, "restore")
        save.assert_called_once_with(APP.PROJECT_LAYOUT_FILE, window.project_layout)
        window.refresh.assert_called_once_with(silent=True, scan=False)

    def test_archive_records_project_lifecycle_without_deleting_files(self):
        project = {"id": "project-1", "name": "Release"}
        status_bar = Mock()
        window = SimpleNamespace(
            project_layout={"hiddenProjectIds": [], "categoryOrders": {}},
            today_tasks=[], record_project_lifecycle=Mock(), refresh=Mock(), view_signature="old", statusBar=lambda: status_bar,
        )
        with patch.object(APP.QMessageBox, "question", return_value=APP.QMessageBox.Yes), patch.object(APP, "save_json") as save:
            APP.MainWindow.delete_project(window, project)
        self.assertEqual(window.project_layout["hiddenProjectIds"], ["project-1"])
        window.record_project_lifecycle.assert_called_once_with(project, "archive")
        save.assert_called_once_with(APP.PROJECT_LAYOUT_FILE, window.project_layout)
        window.refresh.assert_called_once_with(silent=True, scan=False)

    def test_archive_is_blocked_while_project_still_has_live_work(self):
        project = {"id": "project-1", "savedId": "stable-1", "name": "Release", "conversations": [{"state": "working"}]}
        task = {"id": "task-1", "projectId": "stable-1", "status": "doing"}
        window = SimpleNamespace(
            project_layout={"hiddenProjectIds": [], "categoryOrders": {}}, today_tasks=[task],
            record_project_lifecycle=Mock(), refresh=Mock(), view_signature="old", statusBar=lambda: Mock(),
        )
        with patch.object(APP.QMessageBox, "information") as information, patch.object(APP.QMessageBox, "question") as question:
            archived = APP.MainWindow.delete_project(window, project)
        self.assertFalse(archived)
        self.assertEqual(window.project_layout["hiddenProjectIds"], [])
        information.assert_called_once()
        question.assert_not_called()
        window.record_project_lifecycle.assert_not_called()


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
    def test_category_migration_updates_catalog_tasks_layout_and_audit_together(self):
        visible = {
            "id": "runtime-1", "savedId": "stable-1", "name": "Alpha",
            "category": "Old", "status": "active",
        }
        detached = {
            "id": "saved:stable-2", "savedId": "stable-2", "name": "Beta",
            "category": "Old", "status": "active", "_detached": True,
        }
        saved_alpha = {**visible, "id": "stable-1"}
        saved_beta = {**detached, "id": "stable-2"}
        saved_by_id = {"stable-1": saved_alpha, "stable-2": saved_beta}
        tasks = [
            {
                "id": "linked", "projectId": "stable-1", "category": "Wrong",
                "projectCategorySnapshot": "Old",
            },
            {"id": "unlinked", "category": "Old"},
            {"id": "other", "category": "Other"},
        ]
        window = SimpleNamespace(
            categories=["全部", "Renamed", "未分类"],
            saved_projects=[saved_alpha, saved_beta],
            today_tasks=tasks,
            project_layout={
                "hiddenProjectIds": [],
                "categoryOrders": {"Old": ["runtime-1"], "Renamed": ["existing"]},
            },
            project_decisions=[],
            managed_project_catalog=lambda: [visible, detached],
            saved_record_for_project=lambda project: saved_by_id[project["savedId"]],
        )

        with patch.object(APP, "save_json") as save:
            result = APP.MainWindow.apply_category_migration(
                window, "Old", "Renamed", occurred_at="2026-08-10T10:00:00"
            )

        self.assertEqual(result, {"projects": 2, "tasks": 2, "decisions": 2})
        self.assertEqual((saved_alpha["category"], saved_beta["category"]), ("Renamed", "Renamed"))
        self.assertEqual((tasks[0]["category"], tasks[0]["projectCategorySnapshot"]), ("Renamed", "Renamed"))
        self.assertEqual(tasks[1]["category"], "Renamed")
        self.assertEqual(tasks[2]["category"], "Other")
        self.assertEqual(window.project_layout["categoryOrders"]["Renamed"], ["existing", "runtime-1"])
        self.assertNotIn("Old", window.project_layout["categoryOrders"])
        self.assertEqual({entry["source"] for entry in window.project_decisions}, {"category"})
        self.assertTrue(all(entry["changes"][0]["field"] == "category" for entry in window.project_decisions))
        saved_paths = {call.args[0] for call in save.call_args_list}
        self.assertEqual(
            saved_paths,
            {
                APP.CATEGORIES_FILE, APP.PROJECTS_FILE, APP.PROJECT_LAYOUT_FILE,
                APP.TASKS_FILE, APP.PROJECT_DECISIONS_FILE,
            },
        )

    def test_category_rollback_restores_removed_taxonomy_and_linked_task_snapshot(self):
        project = {
            "id": "runtime", "savedId": "stable", "name": "Release",
            "status": "active", "category": "Research", "priority": "normal",
            "stage": "validation", "health": "on_track", "objective": "Ship",
            "nextStep": "Validate", "blocker": "",
        }
        target = {**project, "id": "stable"}
        task = {
            "id": "task-1", "projectId": "stable", "category": "Research",
            "projectCategorySnapshot": "Research",
        }
        window = SimpleNamespace(
            categories=["全部", "Research", "未分类"],
            project_layout={"categoryOrders": {"Research": ["runtime"]}},
            saved_projects=[target], project_decisions=[], today_tasks=[task],
            saved_record_for_project=lambda _project: target,
            apply_project_completion_lifecycle=Mock(return_value=True),
            refresh=Mock(), statusBar=lambda: Mock(), view_signature="old",
        )

        def record_decision(identity, before, after, source, occurred_at):
            entry = APP.build_project_decision_entry(identity, before, after, source, occurred_at)
            if entry:
                window.project_decisions.append(entry)
            return entry

        window.record_project_decision = Mock(side_effect=record_decision)
        rollback = {
            "priority": "normal", "stage": "validation", "health": "on_track",
            "status": "active", "category": "Retired", "objective": "Ship",
            "nextStep": "Validate", "blocker": "",
        }
        with patch.object(APP, "save_json") as save:
            result = APP.MainWindow.update_project_management(
                window, project, rollback, notify=False, source="undo"
            )

        self.assertEqual(result["category"], "Retired")
        self.assertEqual(window.categories, ["全部", "Research", "Retired", "未分类"])
        self.assertEqual((project["category"], target["category"]), ("Retired", "Retired"))
        self.assertEqual((task["category"], task["projectCategorySnapshot"]), ("Retired", "Retired"))
        self.assertEqual(window.project_decisions[-1]["source"], "undo")
        saved_paths = {call.args[0] for call in save.call_args_list}
        self.assertIn(APP.CATEGORIES_FILE, saved_paths)
        self.assertIn(APP.TASKS_FILE, saved_paths)

    def test_rejected_rollback_does_not_create_a_missing_category(self):
        project = {
            "id": "runtime", "savedId": "stable", "name": "Release",
            "status": "active", "category": "Research", "priority": "normal",
            "stage": "validation", "health": "on_track", "objective": "Ship",
            "nextStep": "Validate", "blocker": "",
        }
        saved_lookup = Mock()
        window = SimpleNamespace(
            categories=["全部", "Research", "未分类"], project_decisions=[],
            saved_record_for_project=saved_lookup, statusBar=lambda: Mock(),
        )
        rejected = {
            "priority": "normal", "stage": "completion", "health": "on_track",
            "status": "completed", "category": "Retired", "objective": "Ship",
            "nextStep": "", "blocker": "",
        }

        result = APP.MainWindow.update_project_management(
            window, project, rejected, notify=False, source="undo"
        )

        self.assertIsNone(result)
        self.assertEqual(window.categories, ["全部", "Research", "未分类"])
        saved_lookup.assert_not_called()

    def test_project_closeout_requires_an_objective_outcome_and_explicit_acceptance(self):
        accepted = Mock()
        checkbox = SimpleNamespace(isChecked=lambda: False)
        dialog = SimpleNamespace(
            objective_snapshot="", value=lambda: "Delivered release", acceptance=checkbox, accept=accepted,
        )
        with patch.object(APP.QMessageBox, "information") as information:
            APP.ProjectCloseoutDialog.accept_outcome(dialog)
        self.assertIn("项目目标缺失", information.call_args.args[1])
        accepted.assert_not_called()

        dialog.objective_snapshot = "Deliver a validated release"
        with patch.object(APP.QMessageBox, "information") as information:
            APP.ProjectCloseoutDialog.accept_outcome(dialog)
        self.assertIn("尚未确认验收", information.call_args.args[1])
        accepted.assert_not_called()

        dialog.acceptance = SimpleNamespace(isChecked=lambda: True)
        APP.ProjectCloseoutDialog.accept_outcome(dialog)
        accepted.assert_called_once_with()
        self.assertEqual(APP.ProjectCloseoutDialog.acceptance_objective(dialog), "Deliver a validated release")

    def test_project_next_step_becomes_a_stably_linked_daily_task(self):
        project = {
            "id": "current-id", "savedId": "stable-id", "name": "Release", "category": "Research",
            "nextStep": "Run validation set",
        }
        task = APP.build_project_next_step_task(
            project, "2026-08-10", "2026-08-10T09:00:00", task_id="task-1"
        )
        self.assertEqual(task["projectId"], "stable-id")
        self.assertEqual(task["title"], "Run validation set")
        self.assertEqual(task["origin"], "project_next_step")
        self.assertEqual(task["status"], "planned")
        self.assertEqual(task["statusHistory"][0]["source"], "project")
        self.assertEqual(task["projectNameSnapshot"], "Release")
        self.assertEqual(task["projectCategorySnapshot"], "Research")

    def test_project_next_step_duplicate_detection_spans_dates_and_ignores_rollover_history(self):
        project = {"id": "current-id", "savedId": "stable-id"}
        tasks = [
            {
                "id": "history", "projectId": "stable-id", "title": "Run validation set",
                "date": "2026-08-09", "status": "doing", "carriedToTaskId": "current",
            },
            {
                "id": "current", "projectId": "stable-id", "title": " Run   Validation Set ",
                "date": "2026-08-10", "status": "doing", "carriedFromTaskId": "history",
            },
        ]
        duplicate = APP.find_open_project_next_step_task(tasks, project, "run validation set")
        self.assertIs(duplicate, tasks[1])

    def test_scheduling_an_existing_next_step_navigates_instead_of_duplicating_it(self):
        project = {"id": "project", "nextStep": "Validate release"}
        existing = {
            "id": "existing", "projectId": "project", "title": "Validate release",
            "date": "2026-08-08", "status": "planned",
        }
        date_field = Mock(); status_bar = Mock()
        window = SimpleNamespace(
            today_tasks=[existing], board_date_field=date_field,
            render_today_tasks=Mock(), statusBar=lambda: status_bar,
        )

        result = APP.MainWindow.schedule_project_next_step(window, project)

        self.assertIs(result, existing)
        selected_date = date_field.setDate.call_args.args[0]
        self.assertEqual(selected_date.toString(APP.Qt.ISODate), "2026-08-08")
        window.render_today_tasks.assert_called_once_with()
        self.assertIn("已为你定位", status_bar.showMessage.call_args.args[0])

    def test_completed_project_next_step_returns_project_to_next_decision(self):
        project = {"nextStep": "Run validation set"}
        task = {"origin": "project_next_step", "title": "Run validation set"}
        update = APP.project_next_step_completion_update(project, task, "2026-08-10T10:00:00")
        self.assertEqual(update["nextStep"], "")
        self.assertTrue(update["nextStepReviewNeeded"])
        project.update(update)
        self.assertIn("请明确后续动作", APP.project_control_state(project)[4])

    def test_completed_task_does_not_clear_a_newer_project_next_step(self):
        project = {"nextStep": "Review final report"}
        task = {"origin": "project_next_step", "projectNextStep": "Run validation set"}
        self.assertIsNone(APP.project_next_step_completion_update(project, task, "2026-08-10T10:00:00"))

    def test_reopening_completed_next_step_restores_the_project_handoff(self):
        project = {
            "status": "active", "nextStep": "", "nextStepReviewNeeded": True,
            "lastCompletedNextStep": "Run validation set", "lastCompletedNextStepAt": "2026-08-10T10:00:00",
        }
        task = {"origin": "project_next_step", "projectNextStep": "Run validation set"}
        update = APP.project_next_step_reopen_update(project, task)
        self.assertEqual(update["nextStep"], "Run validation set")
        self.assertFalse(update["nextStepReviewNeeded"])
        self.assertEqual(update["lastCompletedNextStep"], "")
        self.assertEqual(update["lastCompletedOutcome"], "")

    def test_late_completion_outcome_is_synced_to_project_handoff(self):
        project = {
            "id": "current-id", "savedId": "stable-id",
            "lastCompletedNextStep": "Run validation set", "lastCompletedOutcome": "",
        }
        saved = dict(project)
        task = {
            "status": "done", "origin": "project_next_step", "projectId": "stable-id",
            "projectNextStep": "Run validation set", "completionNote": "Confirmed stable results on 3 validation sets.",
            "completionRecordedAt": "2026-08-10T10:30:00",
        }
        window = SimpleNamespace(
            project_by_id=lambda _project_id: project,
            saved_record_for_project=lambda _project: saved,
            saved_projects=[saved],
        )
        with patch.object(APP, "save_json") as save:
            changed = APP.MainWindow.sync_project_completion_outcome(window, task, "2026-08-10T10:30:00")
        self.assertTrue(changed)
        self.assertEqual(project["lastCompletedOutcome"], "Confirmed stable results on 3 validation sets.")
        self.assertEqual(saved["lastCompletedOutcomeAt"], "2026-08-10T10:30:00")
        save.assert_called_once()

    def test_reopening_never_overwrites_a_newer_project_decision(self):
        project = {
            "status": "active", "nextStep": "Review final report", "nextStepReviewNeeded": False,
            "lastCompletedNextStep": "Run validation set",
        }
        task = {"origin": "project_next_step", "projectNextStep": "Run validation set"}
        self.assertIsNone(APP.project_next_step_reopen_update(project, task))
        self.assertIsNone(APP.project_next_step_reopen_update({**project, "status": "completed", "nextStep": ""}, task))

    def test_project_reference_ids_keep_tasks_linked_after_codex_id_changes(self):
        project = {"id": "current-id", "savedId": "stable-id", "codexProjectId": "codex-id"}
        self.assertTrue(APP.task_matches_project({"projectId": "stable-id"}, project))
        self.assertTrue(APP.task_matches_project({"projectId": "current-id"}, project))
        self.assertFalse(APP.task_matches_project({"projectId": "another-id"}, project))

    def test_live_work_automatically_becomes_portfolio_focus(self):
        task_focus = {"priority": "normal", "activeTaskCount": 1, "conversations": []}
        codex_focus = {"priority": "normal", "activeTaskCount": 0, "conversations": [{"state": "working"}]}
        idle = {"priority": "normal", "activeTaskCount": 0, "conversations": []}
        self.assertEqual(APP.project_focus_state(task_focus)[:2], (True, "推进中"))
        self.assertEqual(APP.project_focus_state(codex_focus)[:2], (True, "推进中"))
        self.assertFalse(APP.project_focus_state(idle)[0])
        self.assertTrue(APP.project_management_scope_matches(task_focus, "focus"))
        self.assertTrue(APP.project_management_scope_matches(codex_focus, "focus"))

    def test_focus_capacity_separates_declared_priority_from_live_execution(self):
        focused_idle = {"id": "focus", "status": "active", "priority": "focus", "activeTaskCount": 0, "conversations": []}
        focused_live = {"id": "both", "status": "active", "priority": "focus", "activeTaskCount": 1, "conversations": []}
        live_regular = {"id": "live", "status": "active", "priority": "normal", "activeTaskCount": 0, "conversations": [{"state": "working"}]}
        paused_focus = {"id": "paused", "status": "paused", "priority": "focus", "activeTaskCount": 1, "conversations": []}
        state = APP.portfolio_focus_capacity_state([focused_idle, focused_live, live_regular, paused_focus], 3)
        self.assertEqual([project["id"] for project in state["strategic"]], ["focus", "both"])
        self.assertEqual([project["id"] for project in state["executing"]], ["both", "live"])
        self.assertEqual([project["id"] for project in state["executionOutsideFocus"]], ["live"])
        self.assertEqual([project["id"] for project in state["focusWithoutExecution"]], ["focus"])
        self.assertEqual(state["remaining"], 1)
        self.assertEqual(state["overBy"], 0)

    def test_focus_capacity_is_bounded_and_reports_overcommitment(self):
        projects = [{"id": str(index), "status": "active", "priority": "focus"} for index in range(4)]
        state = APP.portfolio_focus_capacity_state(projects, 2)
        self.assertEqual(state["overBy"], 2)
        self.assertEqual(state["remaining"], 0)
        self.assertEqual(APP.normalized_portfolio_focus_capacity(0), 1)
        self.assertEqual(APP.normalized_portfolio_focus_capacity(20), 9)
        self.assertEqual(APP.normalized_portfolio_focus_capacity("bad"), APP.DEFAULT_PORTFOLIO_FOCUS_CAPACITY)

    def test_focus_priority_action_uses_audited_management_update(self):
        project = {
            "id": "project-1", "name": "Release", "status": "active", "priority": "normal",
            "stage": "execution", "health": "on_track", "category": "Research", "objective": "Ship",
            "nextStep": "Validate", "blocker": "",
        }
        status_bar = Mock()
        window = SimpleNamespace(update_project_management=Mock(return_value={"priority": "focus"}), statusBar=lambda: status_bar)
        changed = APP.MainWindow.set_project_focus_priority(window, project, True)
        self.assertTrue(changed)
        update = window.update_project_management.call_args.args[1]
        self.assertEqual(update["priority"], "focus")
        self.assertEqual(window.update_project_management.call_args.kwargs["source"], "focus")

    def test_focus_commitment_action_reuses_the_project_next_step_scheduler(self):
        project = {"id": "focus", "nextStep": "Run validation"}
        task = {"id": "task"}
        dialog = SimpleNamespace(
            window=SimpleNamespace(schedule_project_next_step=Mock(return_value=task)),
            render_state=Mock(),
        )
        result = APP.FocusCapacityDialog.commit_project(dialog, project)
        self.assertEqual(result, task)
        dialog.window.schedule_project_next_step.assert_called_once_with(project)
        dialog.render_state.assert_called_once_with()

    def test_activity_evidence_uses_the_latest_real_task_codex_or_review_timestamp(self):
        project = {
            "id": "runtime", "savedId": "stable", "reviewedAt": "2026-08-06T09:00:00",
            "conversations": [{"at": "2026-08-08T10:00:00+00:00", "state": "linked"}],
        }
        tasks = [{
            "projectId": "stable", "date": "2026-08-07", "status": "done",
            "statusHistory": [{"at": "2026-08-07T12:00:00", "from": "doing", "to": "done", "source": "manual"}],
        }]
        evidence = APP.project_activity_evidence(project, tasks, datetime(2026, 8, 11, 12, 0, 0))
        self.assertEqual(evidence["source"], "Codex 对话")
        self.assertEqual(evidence["ageDays"], 2)
        self.assertEqual(evidence["taskCount"], 1)
        self.assertEqual(evidence["conversationCount"], 1)

    def test_lifecycle_calibration_surfaces_only_neutral_quiet_active_projects(self):
        now = datetime(2026, 8, 10, 12, 0, 0)
        stale = {"id": "stale", "name": "Stale", "status": "active", "priority": "normal", "health": "on_track", "conversations": [{"at": "2026-07-19T09:00:00", "state": "linked"}]}
        no_evidence = {"id": "none", "name": "No evidence", "status": "active", "priority": "normal", "health": "on_track", "conversations": []}
        reviewed = {"id": "reviewed", "status": "active", "priority": "normal", "health": "on_track", "reviewedAt": "2026-08-08T09:00:00", "conversations": []}
        focused = {"id": "focus", "status": "active", "priority": "focus", "health": "on_track", "conversations": []}
        live = {"id": "live", "status": "active", "priority": "normal", "health": "on_track", "activeTaskCount": 1, "conversations": []}
        attention = {"id": "attention", "status": "active", "priority": "normal", "health": "attention", "conversations": []}
        paused = {"id": "paused", "status": "paused", "priority": "normal", "health": "on_track", "conversations": []}
        queue = APP.portfolio_lifecycle_calibration_queue(
            [stale, no_evidence, reviewed, focused, live, attention, paused], [], now, 14
        )
        self.assertEqual([item["project"]["id"] for item in queue], ["none", "stale"])
        self.assertGreaterEqual(queue[1]["state"]["ageDays"], 21)
        self.assertIn("没有新的执行或复核记录", queue[1]["state"]["reason"])

    def test_inactivity_threshold_is_bounded(self):
        self.assertEqual(APP.normalized_portfolio_inactivity_days(1), 7)
        self.assertEqual(APP.normalized_portfolio_inactivity_days(180), 90)
        self.assertEqual(APP.normalized_portfolio_inactivity_days("bad"), APP.DEFAULT_PORTFOLIO_INACTIVITY_DAYS)

    def test_calibration_pause_uses_audited_status_and_priority_change(self):
        project = {
            "id": "project-1", "name": "Quiet project", "status": "active", "priority": "normal",
            "stage": "execution", "health": "on_track", "category": "Research", "objective": "Ship",
            "nextStep": "Validate", "blocker": "",
        }
        status_bar = Mock()
        window = SimpleNamespace(today_tasks=[], update_project_management=Mock(return_value={"status": "paused"}), statusBar=lambda: status_bar)
        changed = APP.MainWindow.pause_project_from_calibration(window, project)
        self.assertTrue(changed)
        update = window.update_project_management.call_args.args[1]
        self.assertEqual(update["status"], "paused")
        self.assertEqual(update["priority"], "later")
        self.assertEqual(window.update_project_management.call_args.kwargs["source"], "calibration")

    def test_task_wip_capacity_uses_only_active_tasks_on_the_selected_day(self):
        tasks = [
            {"id": "run", "date": "2026-08-10", "status": "doing", "sessionId": "session-1"},
            {"id": "manual", "date": "2026-08-10", "status": "doing"},
            {"id": "planned", "date": "2026-08-10", "status": "planned"},
            {"id": "other-day", "date": "2026-08-09", "status": "doing"},
            {"id": "archived", "date": "2026-08-10", "status": "doing", "archivedAt": "2026-08-10T12:00:00"},
        ]
        state = APP.task_wip_capacity_state(tasks, "2026-08-10", 1, {"session-1"})
        self.assertEqual([task["id"] for task in state["doing"]], ["run", "manual"])
        self.assertEqual([task["id"] for task in state["protected"]], ["run"])
        self.assertEqual(state["overBy"], 1)
        self.assertEqual(state["remaining"], 0)

    def test_task_wip_limit_is_bounded(self):
        self.assertEqual(APP.normalized_task_wip_limit(0), 1)
        self.assertEqual(APP.normalized_task_wip_limit(30), 9)
        self.assertEqual(APP.normalized_task_wip_limit("bad"), APP.DEFAULT_TASK_WIP_LIMIT)

    def test_wip_reduction_never_defers_a_running_codex_task(self):
        task = {"id": "task-1", "date": "2026-08-10", "status": "doing", "sessionId": "running"}
        status_bar = Mock(); move = Mock(return_value=True)
        window = SimpleNamespace(
            today_tasks=[task], running_codex_session_ids=lambda: {"running"}, move_task_on_board=move,
            task_wip_state=Mock(return_value={"overBy": 0}), statusBar=lambda: status_bar,
        )
        self.assertFalse(APP.MainWindow.defer_task_from_wip(window, task))
        move.assert_not_called()

    def test_wip_reduction_reuses_the_audited_board_transition(self):
        task = {"id": "task-1", "date": "2026-08-10", "status": "doing", "sessionId": "idle"}
        status_bar = Mock(); move = Mock(return_value=True)
        window = SimpleNamespace(
            today_tasks=[task], running_codex_session_ids=lambda: set(), move_task_on_board=move,
            task_wip_state=Mock(return_value={"overBy": 0}), statusBar=lambda: status_bar,
        )
        self.assertTrue(APP.MainWindow.defer_task_from_wip(window, task))
        move.assert_called_once_with("task-1", "planned", None, source="manual")

    def test_wip_recommendation_still_uses_the_existing_reversible_action(self):
        task = {"id": "task-1", "status": "doing"}
        dialog = SimpleNamespace(recommendations=[{"task": task}], defer_task=Mock())
        APP.TaskWipDialog.apply_recommendation(dialog)
        dialog.defer_task.assert_called_once_with(task)

        dialog.recommendations = []
        dialog.defer_task.reset_mock()
        APP.TaskWipDialog.apply_recommendation(dialog)
        dialog.defer_task.assert_not_called()

    def test_non_active_project_never_leaks_into_current_focus(self):
        completed = {"status": "completed", "priority": "focus", "activeTaskCount": 1, "conversations": [{"state": "working"}]}
        self.assertFalse(APP.project_focus_state(completed)[0])
        self.assertFalse(APP.project_management_scope_matches(completed, "focus"))

    def test_blocker_automatically_controls_health(self):
        normalized, notes = APP.normalize_project_management_decision(
            {"status": "active"},
            {"status": "active", "stage": "execution", "health": "on_track", "blocker": "Awaiting calibration", "nextStep": "Validate"},
        )
        self.assertEqual(normalized["health"], "blocked")
        self.assertTrue(notes)

    def test_project_update_engine_persists_blocker_start_and_resolution_metadata(self):
        project = {
            "id": "runtime", "savedId": "stable", "name": "Release", "status": "active", "category": "Research",
            "priority": "normal", "stage": "validation", "health": "on_track", "objective": "Ship", "nextStep": "Validate", "blocker": "",
        }
        target = {**project, "id": "stable"}
        status_bar = Mock()
        window = SimpleNamespace(
            categories=["全部", "Research"], project_layout={"categoryOrders": {}}, saved_projects=[target], project_decisions=[],
            saved_record_for_project=lambda _project: target,
            apply_project_completion_lifecycle=Mock(return_value=True),
            refresh=Mock(), statusBar=lambda: status_bar, view_signature="old",
        )

        def record_decision(identity, before, after, source, occurred_at):
            entry = APP.build_project_decision_entry(identity, before, after, source, occurred_at)
            if entry:
                window.project_decisions.append(entry)
            return entry

        window.record_project_decision = Mock(side_effect=record_decision)
        blocked_data = {
            "priority": "normal", "stage": "validation", "health": "on_track", "status": "active", "category": "Research",
            "objective": "Ship", "nextStep": "Validate", "blocker": "Waiting for reference data",
        }
        with patch.object(APP, "save_json"):
            saved = APP.MainWindow.update_project_management(window, project, blocked_data, notify=True)
        self.assertEqual(saved["health"], "blocked")
        self.assertTrue(saved["blockedAt"])
        self.assertEqual(project["blockedAt"], saved["blockedAt"])
        self.assertEqual(window.project_decisions[-1]["blockerLifecycle"]["action"], "started")

        resolved_data = {**blocked_data, "health": "on_track", "blocker": ""}
        with patch.object(APP, "save_json"):
            saved = APP.MainWindow.update_project_management(window, project, resolved_data, notify=True)
        self.assertNotIn("blockedAt", saved)
        self.assertEqual(saved["lastResolvedBlocker"], "Waiting for reference data")
        self.assertTrue(saved["lastBlockerResolvedAt"])
        self.assertEqual(window.project_decisions[-1]["blockerLifecycle"]["action"], "resolved")

    def test_codex_update_establishes_review_only_after_all_governance_gaps_are_filled(self):
        project = {
            "id": "runtime", "savedId": "stable", "name": "Release", "status": "active", "category": "Research",
            "priority": "normal", "stage": "", "health": "on_track", "objective": "", "nextStep": "Validate", "blocker": "",
        }
        target = {**project, "id": "stable"}
        window = SimpleNamespace(
            categories=["全部", "Research"], project_layout={"categoryOrders": {}}, saved_projects=[target], project_decisions=[],
            saved_record_for_project=lambda _project: target,
            apply_project_completion_lifecycle=Mock(return_value=True),
            refresh=Mock(), statusBar=lambda: Mock(), view_signature="old",
        )

        def record_decision(identity, before, after, source, occurred_at):
            return APP.build_project_decision_entry(identity, before, after, source, occurred_at)

        window.record_project_decision = Mock(side_effect=record_decision)
        partial = {
            "priority": "normal", "stage": "validation", "health": "on_track", "status": "active", "category": "Research",
            "objective": "", "nextStep": "Validate", "blocker": "",
        }
        with patch.object(APP, "save_json"):
            APP.MainWindow.update_project_management(window, project, partial, notify=False, source="codex")
        self.assertNotIn("reviewedAt", project)
        self.assertNotIn("reviewedAt", target)

        complete = {**partial, "objective": "Ship a validated release"}
        with patch.object(APP, "save_json"):
            APP.MainWindow.update_project_management(window, project, complete, notify=False, source="codex")
        self.assertTrue(project.get("reviewedAt"))
        self.assertEqual(project["reviewedAt"], target["reviewedAt"])

    def test_incomplete_project_editor_save_does_not_claim_a_review_baseline(self):
        data = {
            "name": "Research workspace", "path": "C:/sample/research", "color": "#58d7f6",
            "category": "Research", "status": "active", "priority": "normal",
            "stage": "planning", "health": "on_track", "objective": "",
            "nextStep": "", "blocker": "", "icon": "",
        }
        dialog = Mock()
        dialog.exec_.return_value = APP.QDialog.Accepted
        dialog.value.return_value = data
        dialog.insight_applied = False
        status_bar = Mock()
        window = SimpleNamespace(
            categories=["全部", "Research"], saved_projects=[], project_layout={"hiddenProjectIds": [], "categoryOrders": {}},
            apply_project_completion_lifecycle=Mock(return_value=True),
            record_project_decision=Mock(return_value={"id": "decision"}),
            refresh=Mock(), statusBar=lambda: status_bar, view_signature="old",
        )
        with patch.object(APP, "ProjectEditor", return_value=dialog), patch.object(
            APP, "codex_sidebar_projects", return_value=[]
        ), patch.object(APP, "save_json"):
            APP.MainWindow.edit_project(window, None)

        self.assertEqual(len(window.saved_projects), 1)
        self.assertNotIn("reviewedAt", window.saved_projects[0])
        window.record_project_decision.assert_called_once()

    def test_completed_project_is_closed_as_one_coherent_decision(self):
        normalized, notes = APP.normalize_project_management_decision(
            {"status": "active"},
            {"status": "completed", "stage": "execution", "health": "blocked", "blocker": "Review", "nextStep": "Run again"},
        )
        self.assertEqual(normalized["stage"], "completion")
        self.assertEqual(normalized["health"], "on_track")
        self.assertEqual(normalized["blocker"], "")
        self.assertEqual(normalized["nextStep"], "")
        self.assertFalse(normalized["nextStepReviewNeeded"])
        self.assertTrue(notes)

    def test_blocked_health_requires_a_specific_reason(self):
        self.assertIn("阻塞原因", APP.project_management_validation_error({"status": "active", "health": "blocked", "blocker": ""}))
        self.assertEqual(APP.project_management_validation_error({"status": "completed", "health": "blocked", "blocker": ""}), "")

    def test_open_project_tasks_use_stable_links_and_exclude_completed_work(self):
        project = {"id": "current", "savedId": "stable"}
        tasks = [
            {"id": "planned", "projectId": "stable", "status": "planned"},
            {"id": "doing", "projectId": "current", "status": "doing"},
            {
                "id": "previous-day-snapshot", "projectId": "stable", "status": "doing",
                "carriedToTaskId": "doing",
            },
            {"id": "done", "projectId": "stable", "status": "done"},
            {"id": "archived", "projectId": "stable", "status": "doing", "archivedAt": "2026-08-10T11:00:00"},
            {"id": "other", "projectId": "other", "status": "planned"},
        ]
        self.assertEqual([task["id"] for task in APP.open_project_tasks(tasks, project)], ["planned", "doing"])

    def test_task_status_transition_rejects_same_or_unknown_columns(self):
        task = {"status": "planned"}
        self.assertTrue(APP.task_status_transition_allowed(task, "doing"))
        self.assertTrue(APP.task_status_transition_allowed(task, "done"))
        self.assertFalse(APP.task_status_transition_allowed(task, "planned"))
        self.assertFalse(APP.task_status_transition_allowed(task, "blocked"))
        self.assertFalse(APP.task_status_transition_allowed(None, "doing"))
        self.assertFalse(APP.task_status_transition_allowed(
            {"status": "doing", "carriedToTaskId": "next-day"}, "done"
        ))
        frozen = {"id": "previous-day", "status": "doing", "date": "2026-08-09", "carriedToTaskId": "next-day"}
        self.assertFalse(APP.reorder_task_board([frozen], "previous-day", "done")["changed"])

    def test_historical_task_navigation_opens_latest_rollover_record(self):
        previous = {"id": "previous", "title": "Validation", "date": "2026-08-09", "carriedToTaskId": "current"}
        current = {"id": "current", "title": "Validation", "date": "2026-08-10", "carriedFromTaskId": "previous"}
        date_field = Mock()
        status_bar = Mock()
        window = SimpleNamespace(
            today_tasks=[previous, current], board_date_field=date_field,
            render_today_tasks=Mock(), statusBar=lambda: status_bar,
        )

        self.assertTrue(APP.MainWindow.open_current_task_record(window, previous))
        selected_date = date_field.setDate.call_args.args[0]
        self.assertEqual(selected_date.toString(APP.Qt.ISODate), "2026-08-10")
        window.render_today_tasks.assert_called_once_with()
        self.assertIn("最新记录", status_bar.showMessage.call_args.args[0])

    def test_editing_a_historical_snapshot_redirects_to_current_record(self):
        historical = {"id": "previous", "carriedToTaskId": "current"}
        window = SimpleNamespace(open_current_task_record=Mock())

        APP.MainWindow.edit_today_task(window, historical)

        window.open_current_task_record.assert_called_once_with(historical)

    def test_portfolio_decision_groups_surface_actions_without_forcing_exclusivity(self):
        active_attention = {
            "name": "Active risk", "status": "active", "health": "attention",
            "activeTaskCount": 1, "nextStep": "Review", "reviewedAt": datetime.now().isoformat(timespec="seconds"),
        }
        blocked = {"name": "Blocked", "status": "active", "blocker": "Missing input", "nextStep": "Wait"}
        needs_next = {"name": "Needs next", "status": "active", "nextStep": ""}
        legacy_review = {"name": "Needs review", "status": "active", "health": "attention", "nextStep": "Confirm"}
        paused = {"name": "Paused", "status": "paused", "nextStep": ""}
        groups = APP.portfolio_decision_groups([active_attention, blocked, needs_next, legacy_review, paused])
        self.assertIn(active_attention, groups["focus"])
        self.assertIn(active_attention, groups["attention"])
        self.assertNotIn(active_attention, groups["review"])
        self.assertIn(blocked, groups["attention"])
        self.assertIn(legacy_review, groups["review"])
        self.assertNotIn(legacy_review, groups["attention"])
        self.assertEqual(groups["needs_next"], [needs_next])

    def test_portfolio_priority_selects_one_decision_in_management_order(self):
        risk = {"name": "Blocked release", "status": "active", "blocker": "Missing input"}
        alignment = {"project": {"name": "Model validation"}}
        needs_next = {"name": "Research plan"}
        outside_focus = {"name": "Live experiment"}
        review = {"name": "Portfolio review"}
        lifecycle = {"project": {"name": "Quiet project"}}
        groups = {"attention": [risk], "needs_next": [needs_next], "review": [review]}
        capacity = {
            "overBy": 0, "executionOutsideFocus": [outside_focus],
            "strategic": [], "capacity": 3,
        }

        decision = APP.portfolio_priority_decision(groups, capacity, [alignment], [lifecycle])
        self.assertEqual((decision["scope"], decision["title"]), ("attention", "先处理风险与阻塞"))
        self.assertEqual(decision["secondary"], "执行校准 1 · 生命周期 1")

        groups["attention"] = []
        wip = {
            "count": 4, "limit": 3, "overBy": 1,
            "doing": [{"title": "Validation"}, {"title": "Packaging"}],
            "protected": [{"title": "Validation"}],
        }
        wip_decision = APP.portfolio_priority_decision(
            groups, capacity, [alignment], [lifecycle], wip_state=wip
        )
        self.assertEqual((wip_decision["scope"], wip_decision["count"]), ("task_wip", 1))
        self.assertIn("Codex 运行保护", wip_decision["summary"])

        alignment_decision = APP.portfolio_priority_decision(groups, capacity, [alignment], [lifecycle])
        self.assertEqual(alignment_decision["scope"], "alignment")
        self.assertEqual(alignment_decision["secondary"], "生命周期 1")
        backlog = [{"title": "Recheck experiment", "date": "2026-08-07"}]
        completion = [{"title": "Publish validation result", "date": "2026-08-08"}]
        completion_decision = APP.portfolio_priority_decision(
            groups, capacity, [], [lifecycle], overdue_tasks=backlog, completion_tasks=completion
        )
        self.assertEqual(completion_decision["scope"], "completion_evidence")
        self.assertIn("可验证结果", completion_decision["summary"])
        self.assertEqual(completion_decision["secondary"], "生命周期 1 · 待安排计划 1")
        backlog_decision = APP.portfolio_priority_decision(
            groups, capacity, [], [lifecycle], overdue_tasks=backlog
        )
        self.assertEqual(backlog_decision["scope"], "plan_backlog")
        self.assertIn("2026-08-07", backlog_decision["summary"])
        self.assertEqual(backlog_decision["secondary"], "生命周期 1")
        self.assertEqual(APP.portfolio_priority_decision(groups, capacity, [], [lifecycle])["scope"], "needs_next")

        groups["needs_next"] = []
        self.assertEqual(APP.portfolio_priority_decision(groups, capacity, [], [lifecycle])["scope"], "focus_capacity")
        capacity["executionOutsideFocus"] = []
        commitment = {"project": {"name": "Release candidate"}}
        commitment_decision = APP.portfolio_priority_decision(
            groups, capacity, [], [lifecycle], focus_commitments=[commitment]
        )
        self.assertEqual(commitment_decision["scope"], "focus_commitment")
        self.assertIn("形成当前任务", commitment_decision["summary"])
        self.assertEqual(APP.portfolio_priority_decision(groups, capacity, [], [lifecycle])["scope"], "review")
        groups["review"] = []
        self.assertEqual(APP.portfolio_priority_decision(groups, capacity, [], [lifecycle])["scope"], "lifecycle")
        self.assertIsNone(APP.portfolio_priority_decision(groups, capacity, [], []))

    def test_portfolio_priority_routes_to_the_existing_decision_flow(self):
        window = SimpleNamespace(
            _portfolio_priority_scope="alignment",
            show_execution_alignment_queue=Mock(), show_lifecycle_calibration=Mock(),
            open_project_scope=Mock(),
        )
        APP.MainWindow.open_portfolio_priority_decision(window)
        window.show_execution_alignment_queue.assert_called_once_with()
        window.open_project_scope.assert_not_called()

        window._portfolio_priority_scope = "task_wip"
        window.show_task_wip = Mock()
        APP.MainWindow.open_portfolio_priority_decision(window)
        window.show_task_wip.assert_called_once_with()

        window._portfolio_priority_scope = "plan_backlog"
        window.show_planning_backlog = Mock()
        APP.MainWindow.open_portfolio_priority_decision(window)
        window.show_planning_backlog.assert_called_once_with()

        window._portfolio_priority_scope = "completion_evidence"
        window.show_completion_evidence_queue = Mock()
        APP.MainWindow.open_portfolio_priority_decision(window)
        window.show_completion_evidence_queue.assert_called_once_with()

        window._portfolio_priority_scope = "review"
        APP.MainWindow.open_portfolio_priority_decision(window)
        window.open_project_scope.assert_called_once_with("review")

        window._portfolio_priority_scope = "focus_commitment"
        window.show_focus_capacity = Mock()
        APP.MainWindow.open_portfolio_priority_decision(window)
        window.show_focus_capacity.assert_called_once_with()

    def test_project_insight_requires_an_existing_project_folder(self):
        with patch.object(APP, "find_summary_codex_binary", return_value="codex"):
            result = APP.generate_project_insight({"path": "Z:/definitely-missing-project"})
        self.assertEqual(result["error"], "请先选择有效的项目文件夹")

    def test_portfolio_governance_only_queues_actionable_local_projects(self):
        with tempfile.TemporaryDirectory() as folder:
            window = SimpleNamespace(projects=[
                {"id": "eligible", "status": "active", "objective": "", "nextStep": "Run", "stage": "execution", "health": "on_track", "path": folder},
                {"id": "complete", "status": "completed", "objective": "", "stage": "completion", "health": "on_track", "path": folder},
                {"id": "invalid-path", "status": "active", "objective": "", "nextStep": "Run", "stage": "execution", "health": "on_track", "path": str(Path(folder) / "missing")},
                {"id": "governed", "status": "active", "objective": "Ship", "nextStep": "Run", "stage": "execution", "health": "on_track", "path": folder},
            ])
            candidates = APP.MainWindow.project_governance_candidates(window)
        self.assertEqual([project["id"] for project in candidates], ["eligible"])

    def test_control_state_prioritizes_blockers_missing_decisions_and_baseline_review(self):
        blocked = {"status": "active", "health": "on_track", "blocker": "Waiting for calibration", "objective": "Ship", "nextStep": "Test"}
        missing_next = {"status": "active", "health": "on_track", "objective": "Ship", "nextStep": ""}
        healthy = {"status": "active", "stage": "execution", "health": "on_track", "objective": "Ship", "nextStep": "Test"}
        incomplete = {**healthy, "objective": "", "reviewedAt": datetime.now().isoformat(timespec="seconds")}
        self.assertEqual(APP.project_control_state(blocked)[0], "blocked")
        self.assertIn("calibration", APP.project_control_state(blocked)[4])
        self.assertEqual(APP.project_control_state(missing_next)[0], "on_track")
        self.assertIn("尚未设置下一步", APP.project_control_state(missing_next)[4])
        self.assertEqual(APP.project_control_state(healthy)[0], "review")
        self.assertIn("首次复核基线", APP.project_control_state(healthy)[4])
        self.assertEqual(APP.project_control_state(incomplete)[:2], ("review", "待补全"))
        self.assertIn("项目目标", APP.project_control_state(incomplete)[4])

    def test_legacy_attention_becomes_review_instead_of_current_risk(self):
        legacy_attention = {"status": "active", "stage": "execution", "health": "attention", "objective": "Ship", "nextStep": "Review"}
        fresh_attention = {**legacy_attention, "reviewedAt": datetime.now().isoformat(timespec="seconds")}
        overdue_attention = {**legacy_attention, "reviewedAt": "2000-01-01T00:00:00"}
        self.assertEqual(APP.project_control_state(legacy_attention)[:2], ("review", "待复核"))
        self.assertTrue(APP.project_management_scope_matches(legacy_attention, "review"))
        self.assertEqual(APP.project_control_state(fresh_attention)[:2], ("attention", "需关注"))
        self.assertEqual(APP.project_control_state(overdue_attention)[:2], ("attention", "需关注"))
        self.assertFalse(APP.project_management_scope_matches(overdue_attention, "review"))

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

    def test_home_review_queue_uses_guided_review_instead_of_a_plain_filter(self):
        window = SimpleNamespace(show_portfolio_review_queue=Mock())
        APP.MainWindow.open_project_scope(window, "review")
        window.show_portfolio_review_queue.assert_called_once_with()

    def test_guided_review_limits_each_session_to_a_manageable_batch(self):
        projects = [{"id": f"project-{index}"} for index in range(8)]
        window = SimpleNamespace(portfolio_review_queue=Mock(return_value=projects))
        with patch.object(APP, "PortfolioReviewDialog") as dialog:
            APP.MainWindow.show_portfolio_review_queue(window)
        dialog.assert_called_once_with(window, projects[:5], total_count=8)
        dialog.return_value.exec_.assert_called_once_with()

    def test_incomplete_review_routes_to_codex_governance_before_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            project = {
                "id": "project", "status": "active", "path": folder,
                "objective": "", "nextStep": "Validate", "stage": "execution", "health": "on_track",
            }
            window = SimpleNamespace(show_project_governance=Mock(), open_project_workspace=Mock())
            dialog = SimpleNamespace(current_project=lambda: project, accept=Mock(), window=window)
            APP.PortfolioReviewDialog.confirm_current(dialog)
        dialog.accept.assert_called_once_with()
        window.show_project_governance.assert_called_once_with([project])
        window.open_project_workspace.assert_not_called()

    def test_stale_review_routes_to_execution_alignment_before_confirmation(self):
        today = datetime.now().date().isoformat()
        project = {
            "id": "project", "savedId": "stable", "status": "active",
            "objective": "Ship", "nextStep": "Validate release",
            "stage": "validation", "health": "on_track",
        }
        task = {
            "id": "task", "projectId": "stable", "date": today,
            "status": "doing", "title": "Repair benchmark",
        }
        window = SimpleNamespace(today_tasks=[task], record_project_review=Mock())
        dialog = SimpleNamespace(current_project=lambda: project, accept=Mock(), window=window)
        with patch.object(APP, "ExecutionAlignmentDialog") as alignment_dialog:
            APP.PortfolioReviewDialog.confirm_current(dialog)
        dialog.accept.assert_called_once_with()
        alignment_dialog.assert_called_once()
        self.assertEqual(alignment_dialog.call_args.args[1][0]["project"], project)
        alignment_dialog.return_value.exec_.assert_called_once_with()
        window.record_project_review.assert_not_called()

    def test_review_queue_prioritizes_incomplete_governance_records(self):
        ready = {"id": "ready", "status": "active", "objective": "Ship", "nextStep": "Test", "stage": "execution", "health": "on_track"}
        incomplete = {**ready, "id": "incomplete", "objective": ""}
        window = SimpleNamespace(
            projects=[ready, incomplete], lifecycle_calibration_queue=Mock(return_value=[]),
            execution_alignment_queue=Mock(return_value=[]),
        )
        with patch.object(APP, "portfolio_decision_groups", return_value={"review": [ready, incomplete]}):
            queue = APP.MainWindow.portfolio_review_queue(window)
        self.assertEqual(queue, [incomplete, ready])

    def test_task_editor_preserves_an_unresolved_historical_association(self):
        date_value = Mock(); date_value.toString.return_value = "2026-08-10"
        editor = SimpleNamespace(
            project_field=SimpleNamespace(currentData=lambda: "old-project"),
            projects=[], unresolved_project_id="old-project", unresolved_project_name="Original project",
            task={"category": "Research", "projectCategorySnapshot": "Research", "conversationTitle": "Original conversation"},
            conversation_field=SimpleNamespace(currentData=lambda: "old-session", currentText=lambda: "Original conversation · 历史关联"),
            preferred_session_id="old-session",
            title_field=SimpleNamespace(text=lambda: "Historical task"), category_field=SimpleNamespace(currentData=lambda: "Research"),
            status_field=SimpleNamespace(currentData=lambda: "done"), date_field=SimpleNamespace(date=lambda: date_value),
            notes_field=SimpleNamespace(toPlainText=lambda: ""), outcome_field=SimpleNamespace(toPlainText=lambda: "Completed"),
        )
        value = APP.TaskEditor.value(editor)
        self.assertEqual(value["projectId"], "old-project")
        self.assertEqual(value["projectNameSnapshot"], "Original project")
        self.assertEqual(value["sessionId"], "old-session")
        self.assertEqual(value["conversationTitle"], "Original conversation")

    def test_task_editor_persists_the_stable_project_identity(self):
        date_value = Mock(); date_value.toString.return_value = "2026-08-10"
        project = {
            "id": "current-codex-id", "codexProjectId": "current-codex-id", "savedId": "stable-project-id",
            "name": "Release project", "category": "Research",
        }
        editor = SimpleNamespace(
            project_field=SimpleNamespace(currentData=lambda: "current-codex-id"),
            projects=[project], unresolved_project_id=None, unresolved_project_name="", task={},
            conversation_field=SimpleNamespace(currentData=lambda: None, currentText=lambda: ""), preferred_session_id=None,
            title_field=SimpleNamespace(text=lambda: "Validate release"), category_field=SimpleNamespace(currentData=lambda: "Research"),
            status_field=SimpleNamespace(currentData=lambda: "planned"), date_field=SimpleNamespace(date=lambda: date_value),
            notes_field=SimpleNamespace(toPlainText=lambda: ""), outcome_field=SimpleNamespace(toPlainText=lambda: ""),
        )
        value = APP.TaskEditor.value(editor)
        self.assertEqual(value["projectId"], "stable-project-id")
        self.assertEqual(value["projectNameSnapshot"], "Release project")

    def test_manual_link_repair_saves_once_and_refreshes_without_rewriting_activity(self):
        task = {
            "id": "task-1", "projectId": "obsolete", "status": "doing",
            "updatedAt": "2026-08-09T09:00:00",
        }
        project = {
            "id": "runtime", "savedId": "stable", "name": "Release project", "category": "Research",
        }
        status_bar = Mock()
        window = SimpleNamespace(
            today_tasks=[task], task_link_project_catalog=lambda: [project],
            view_signature="old", refresh=Mock(), statusBar=lambda: status_bar,
        )
        with patch.object(APP, "save_json") as save:
            repaired = APP.MainWindow.repair_task_project_links(
                window, [("task-1", "runtime")], occurred_at="2026-08-10T10:00:00"
            )
        self.assertEqual(repaired, 1)
        self.assertEqual(task["projectId"], "stable")
        self.assertEqual(task["updatedAt"], "2026-08-09T09:00:00")
        save.assert_called_once_with(APP.TASKS_FILE, window.today_tasks)
        window.refresh.assert_called_once_with(silent=True, scan=False)

    def test_review_queue_defers_to_more_specific_alignment_and_lifecycle_decisions(self):
        normal = {"id": "normal", "status": "active"}
        quiet = {"id": "quiet", "status": "active"}
        ready = {"id": "ready", "status": "active"}
        window = SimpleNamespace(
            projects=[normal, quiet, ready],
            execution_alignment_queue=Mock(return_value=[{"project": normal}]),
            lifecycle_calibration_queue=Mock(return_value=[{"project": quiet, "state": {"due": True}}]),
        )
        with patch.object(APP, "portfolio_decision_groups", return_value={"review": [normal, quiet, ready]}):
            queue = APP.MainWindow.portfolio_review_queue(window)
        self.assertEqual(queue, [ready])

    def test_management_scope_surfaces_attention_and_blocked_projects(self):
        blocked = {"status": "active", "blocker": "Dependency unavailable", "objective": "Ship", "nextStep": "Wait"}
        attention = {"status": "active", "health": "attention", "objective": "Ship", "nextStep": "Review", "reviewedAt": datetime.now().isoformat(timespec="seconds")}
        legacy_attention = {"status": "active", "stage": "execution", "health": "attention", "objective": "Ship", "nextStep": "Confirm"}
        healthy = {"status": "active", "stage": "execution", "health": "on_track", "objective": "Ship", "nextStep": "Test"}
        due_review = {"status": "active", "stage": "execution", "health": "on_track", "objective": "Ship", "nextStep": "Test", "reviewedAt": "2000-01-01T00:00:00"}
        self.assertTrue(APP.project_management_scope_matches(blocked, "blocked"))
        self.assertTrue(APP.project_management_scope_matches(blocked, "attention"))
        self.assertTrue(APP.project_management_scope_matches(attention, "attention"))
        self.assertFalse(APP.project_management_scope_matches(legacy_attention, "attention"))
        self.assertTrue(APP.project_management_scope_matches(legacy_attention, "review"))
        self.assertFalse(APP.project_management_scope_matches(healthy, "attention"))
        self.assertTrue(APP.project_management_scope_matches(healthy, "review"))
        self.assertTrue(APP.project_management_scope_matches(due_review, "review"))

    def test_focus_projects_sort_before_regular_projects(self):
        projects = [
            {"name": "Regular", "priority": "normal", "nextStep": "Continue"},
            {"name": "Focus", "priority": "focus", "nextStep": "Validate"},
        ]
        projects.sort(key=APP.project_management_sort_key)
        self.assertEqual([item["name"] for item in projects], ["Focus", "Regular"])

    def test_active_task_sorts_as_focus_without_overwriting_manual_priority(self):
        projects = [
            {"name": "Regular", "priority": "normal", "nextStep": "Continue"},
            {"name": "Active", "priority": "normal", "activeTaskCount": 1, "nextStep": "Validate"},
        ]
        projects.sort(key=APP.project_management_sort_key)
        self.assertEqual([item["name"] for item in projects], ["Active", "Regular"])

    def test_blocked_project_sorts_before_healthy_focus_project(self):
        projects = [
            {"name": "Focus", "priority": "focus", "objective": "Ship", "nextStep": "Test"},
            {"name": "Blocked", "priority": "normal", "objective": "Ship", "nextStep": "Wait", "blocker": "Missing input"},
        ]
        projects.sort(key=APP.project_management_sort_key)
        self.assertEqual([item["name"] for item in projects], ["Blocked", "Focus"])

    def test_confirmed_attention_sorts_before_neutral_review(self):
        projects = [
            {"name": "Review", "status": "active", "health": "attention", "nextStep": "Confirm"},
            {"name": "Risk", "status": "active", "health": "attention", "nextStep": "Mitigate", "reviewedAt": datetime.now().isoformat(timespec="seconds")},
        ]
        projects.sort(key=APP.project_management_sort_key)
        self.assertEqual([item["name"] for item in projects], ["Risk", "Review"])


class ProjectDecisionHistoryTests(unittest.TestCase):
    def test_changes_include_only_real_normalized_field_differences(self):
        before = {"objective": "Ship   a validated model", "stage": "planning", "blocker": ""}
        after = {"objective": " Ship a validated model ", "stage": "execution", "blocker": "Waiting for data"}
        changes = APP.project_decision_changes(before, after)
        self.assertEqual([item["field"] for item in changes], ["stage", "blocker"])
        self.assertEqual(changes[1]["before"], "")

    def test_entry_uses_stable_project_id_and_known_source(self):
        project = {"id": "current-id", "savedId": "stable-id", "name": "Model validation"}
        entry = APP.build_project_decision_entry(
            project,
            {"health": "on_track"},
            {"health": "attention"},
            "codex",
            "2026-08-10T11:30:00",
            entry_id="decision-1",
        )
        self.assertEqual(entry["projectId"], "stable-id")
        self.assertEqual(entry["source"], "codex")
        self.assertEqual(entry["id"], "decision-1")

    def test_management_updates_preserve_alias_and_rename_rollback_restores_source(self):
        project = {
            "id": "runtime", "savedId": "stable", "codexProjectId": "codex-project",
            "name": "Portfolio display name", "sourceName": "Codex source name",
            "status": "active", "category": "Research", "priority": "normal",
            "stage": "validation", "health": "on_track", "objective": "Ship",
            "nextStep": "Validate", "blocker": "",
        }
        target = {
            **project, "id": "stable", "name": "Portfolio display name",
            "nameOverride": "Portfolio display name",
        }
        status_bar = Mock()
        window = SimpleNamespace(
            categories=["全部", "Research"], project_layout={"categoryOrders": {}},
            saved_projects=[target], project_decisions=[], view_signature="old",
            saved_record_for_project=lambda _project: target,
            apply_project_completion_lifecycle=Mock(return_value=True),
            refresh=Mock(), statusBar=lambda: status_bar,
        )

        def record_decision(identity, before, after, source, occurred_at):
            entry = APP.build_project_decision_entry(identity, before, after, source, occurred_at)
            if entry:
                window.project_decisions.append(entry)
            return entry

        window.record_project_decision = Mock(side_effect=record_decision)
        management = {
            "priority": "normal", "stage": "validation", "health": "attention",
            "status": "active", "category": "Research", "objective": "Ship",
            "nextStep": "Validate", "blocker": "",
        }
        with patch.object(APP, "save_json"):
            APP.MainWindow.update_project_management(window, project, management, notify=False, source="focus")
        self.assertEqual((target["name"], target["nameOverride"]), ("Portfolio display name", "Portfolio display name"))
        self.assertEqual([change["field"] for change in window.project_decisions[-1]["changes"]], ["health"])

        with patch.object(APP, "save_json"):
            saved = APP.MainWindow.update_project_management(
                window, project, {**management, "name": "Codex source name"}, notify=False, source="undo"
            )
        self.assertEqual((saved["name"], project["name"]), ("Codex source name", "Codex source name"))
        self.assertNotIn("nameOverride", saved)
        self.assertEqual([change["field"] for change in window.project_decisions[-1]["changes"]], ["name"])

    def test_entry_is_not_created_when_nothing_changed(self):
        entry = APP.build_project_decision_entry(
            {"id": "project-1"},
            {"nextStep": "Run validation"},
            {"nextStep": " Run   validation "},
            "manual",
            "2026-08-10T11:30:00",
        )
        self.assertIsNone(entry)

    def test_display_and_summary_use_readable_management_labels(self):
        entry = {
            "changes": [
                {"field": "stage", "label": "当前阶段", "before": "planning", "after": "execution"},
                {"field": "blocker", "label": "当前阻塞", "before": "", "after": "Awaiting review"},
                {"field": "health", "label": "项目健康度", "before": "on_track", "after": "attention"},
            ]
        }
        self.assertEqual(APP.display_project_decision_value("stage", "execution"), "执行")
        self.assertEqual(APP.display_project_decision_value("blocker", ""), "无")
        summary = APP.format_project_decision_summary(entry)
        self.assertIn("当前阶段：规划 → 执行", summary)
        self.assertIn("另 1 项", summary)

    def test_project_completion_lifecycle_keeps_current_truth_and_history_together(self):
        project = {
            "id": "runtime", "savedId": "stable", "name": "Release",
            "status": "active", "objective": "Deliver a validated release package",
        }
        before = dict(project)
        target = {
            "id": "stable", "name": "Release", "status": "completed",
            "objective": "Deliver a validated release package",
        }
        window = SimpleNamespace(record_project_closeout=Mock())
        self.assertTrue(APP.MainWindow.apply_project_completion_lifecycle(
            window,
            project,
            before,
            target,
            {
                "status": "completed", "completionSummary": "Passed all release checks.",
                "completionObjectiveSnapshot": "Deliver a validated release package",
            },
            "2026-08-10T12:00:00",
            "manual",
        ))
        self.assertEqual(project["completionSummary"], "Passed all release checks.")
        self.assertEqual(target["completedAt"], "2026-08-10T12:00:00")
        self.assertEqual(target["completionObjectiveSnapshot"], "Deliver a validated release package")
        self.assertEqual(target["completionAcceptedAt"], "2026-08-10T12:00:00")
        args = window.record_project_closeout.call_args.args
        self.assertEqual((args[0]["savedId"], args[1:]), ("stable", ("complete", "Passed all release checks.", "2026-08-10T12:00:00")))

        completed = {**project, "status": "completed"}
        target["status"] = "active"
        window.record_project_closeout.reset_mock()
        self.assertTrue(APP.MainWindow.apply_project_completion_lifecycle(
            window, project, completed, target, {"status": "active"}, "2026-08-10T13:00:00", "manual"
        ))
        self.assertNotIn("completionSummary", project)
        self.assertNotIn("completionObjectiveSnapshot", project)
        self.assertEqual(target["completionHistory"][-1]["source"], "reopen")
        args = window.record_project_closeout.call_args.args
        self.assertEqual((args[0]["savedId"], args[1:]), ("stable", ("reopen", "Passed all release checks.", "2026-08-10T13:00:00")))

    def test_project_decision_rollback_uses_the_normal_update_engine_and_audits_it(self):
        project = {"id": "current", "savedId": "stable", "objective": "New objective", "status": "active"}
        entry = {
            "projectId": "stable",
            "changes": [{"field": "objective", "before": "Previous objective", "after": "New objective"}],
        }
        status_bar = Mock()
        window = SimpleNamespace(project_decisions=[], statusBar=lambda: status_bar)

        def update_project(_project, data, notify=True, source="manual"):
            self.assertFalse(notify)
            self.assertEqual(source, "undo")
            self.assertEqual(data["objective"], "Previous objective")
            window.project_decisions.append({"source": source})
            return data

        window.update_project_management = Mock(side_effect=update_project)
        changed = APP.MainWindow.rollback_project_decision(window, project, entry)
        self.assertTrue(changed)
        window.update_project_management.assert_called_once()
        self.assertEqual(window.project_decisions[-1]["source"], "undo")

    def test_project_decision_rollback_rejects_a_record_from_another_project(self):
        status_bar = Mock()
        window = SimpleNamespace(project_decisions=[], statusBar=lambda: status_bar, update_project_management=Mock())
        changed = APP.MainWindow.rollback_project_decision(
            window,
            {"id": "project-a", "savedId": "stable-a", "objective": "A"},
            {"projectId": "stable-b", "changes": [{"field": "objective", "before": "Old", "after": "A"}]},
        )
        self.assertFalse(changed)
        window.update_project_management.assert_not_called()

    def test_project_review_updates_recency_and_adds_an_audit_event(self):
        project = {
            "id": "current", "savedId": "stable", "name": "Release", "status": "active",
            "priority": "normal", "stage": "validation", "health": "attention", "objective": "Ship", "nextStep": "Verify",
        }
        target = {"id": "stable", "name": "Release"}
        status_bar = Mock()
        window = SimpleNamespace(
            saved_projects=[target], project_decisions=[], view_signature="old", today_tasks=[],
            saved_record_for_project=lambda _project: target,
            refresh=Mock(), statusBar=lambda: status_bar,
        )
        with patch.object(APP, "save_json") as save:
            entry = APP.MainWindow.record_project_review(
                window, project, audit=True, occurred_at="2026-08-10T12:00:00"
            )
        self.assertEqual(project["reviewedAt"], "2026-08-10T12:00:00")
        self.assertEqual(target["reviewedAt"], "2026-08-10T12:00:00")
        self.assertEqual(entry["kind"], "review")
        self.assertEqual(window.project_decisions[-1]["source"], "review")
        self.assertEqual(save.call_count, 2)
        window.refresh.assert_called_once_with(silent=True, scan=False)

    def test_project_review_rejects_an_incomplete_management_record(self):
        project = {
            "id": "current", "status": "active", "stage": "validation", "health": "on_track",
            "objective": "", "nextStep": "Verify",
        }
        status_bar = Mock()
        window = SimpleNamespace(today_tasks=[], saved_record_for_project=Mock(), statusBar=lambda: status_bar)
        result = APP.MainWindow.record_project_review(window, project)
        self.assertFalse(result)
        window.saved_record_for_project.assert_not_called()
        status_bar.showMessage.assert_called_once()

    def test_project_review_rejects_unresolved_live_direction_drift(self):
        today = datetime.now().date().isoformat()
        project = {
            "id": "runtime", "savedId": "stable", "status": "active",
            "stage": "validation", "health": "on_track", "objective": "Ship",
            "nextStep": "Validate release",
        }
        task = {
            "id": "task-1", "projectId": "stable", "date": today,
            "status": "doing", "title": "Repair benchmark",
        }
        status_bar = Mock(); saved_lookup = Mock()
        window = SimpleNamespace(
            today_tasks=[task], saved_record_for_project=saved_lookup,
            statusBar=lambda: status_bar,
        )
        result = APP.MainWindow.record_project_review(window, project)
        self.assertFalse(result)
        saved_lookup.assert_not_called()
        self.assertIn("执行方向", status_bar.showMessage.call_args.args[0])

    def test_keep_execution_direction_records_signature_and_audit_event(self):
        today = datetime.now().date().isoformat()
        project = {"id": "runtime", "savedId": "stable", "name": "Release", "status": "active", "nextStep": "Ship candidate"}
        task = {"id": "task-1", "projectId": "stable", "date": today, "status": "doing", "title": "Repair benchmark"}
        target = {"id": "stable", "name": "Release", "nextStep": "Ship candidate"}
        alignment = APP.project_execution_alignment(project, [task], today)
        status_bar = Mock()
        window = SimpleNamespace(
            today_tasks=[task], saved_projects=[target], project_decisions=[], view_signature="old",
            saved_record_for_project=lambda _project: target,
            refresh=Mock(), statusBar=lambda: status_bar,
        )
        with patch.object(APP, "save_json") as save:
            changed = APP.MainWindow.acknowledge_execution_alignment(window, alignment)
        self.assertTrue(changed)
        self.assertEqual(target["executionAlignmentSignature"], alignment["signature"])
        self.assertEqual(window.project_decisions[-1]["kind"], "alignment")
        self.assertEqual(save.call_count, 2)
        window.refresh.assert_called_once_with(silent=True, scan=False)

    def test_adopt_live_task_updates_only_project_next_step_through_decision_path(self):
        today = datetime.now().date().isoformat()
        project = {
            "id": "runtime", "savedId": "stable", "name": "Release", "status": "active", "category": "Lab",
            "priority": "normal", "stage": "validation", "health": "on_track", "objective": "Ship", "nextStep": "Ship candidate", "blocker": "",
        }
        task = {"id": "task-1", "projectId": "stable", "date": today, "status": "doing", "title": "Repair benchmark"}
        alignment = APP.project_execution_alignment(project, [task], today)
        status_bar = Mock()
        window = SimpleNamespace(
            today_tasks=[task], update_project_management=Mock(return_value={"nextStep": "Repair benchmark"}),
            statusBar=lambda: status_bar, view_signature="old", refresh=Mock(),
        )
        with patch.object(APP, "save_json") as save:
            changed = APP.MainWindow.adopt_execution_alignment(window, alignment, task)
        self.assertTrue(changed)
        _project, data = window.update_project_management.call_args.args[:2]
        self.assertEqual(data["nextStep"], "Repair benchmark")
        self.assertEqual(window.update_project_management.call_args.kwargs["source"], "alignment")
        self.assertEqual((task["origin"], task["projectNextStep"]), ("project_next_step", "Repair benchmark"))
        save.assert_called_once_with(APP.TASKS_FILE, window.today_tasks)
        window.refresh.assert_called_once_with(silent=True, scan=False)
        handoff = APP.project_next_step_completion_update({**project, "nextStep": "Repair benchmark"}, task, "2026-08-10T13:00:00")
        self.assertEqual((handoff or {}).get("nextStep"), "")
        self.assertTrue((handoff or {}).get("nextStepReviewNeeded"))


class TaskStatusHistoryTests(unittest.TestCase):
    def test_status_history_records_real_transitions_and_sources(self):
        task = {"id": "task-1", "status": "planned"}
        self.assertTrue(APP.record_task_status_event(task, "planned", "doing", "2026-08-10T09:00:00", "drag"))
        self.assertFalse(APP.record_task_status_event(task, "doing", "doing", "2026-08-10T09:01:00", "selector"))
        self.assertTrue(APP.record_task_status_event(task, "doing", "done", "2026-08-10T10:00:00", "codex"))
        self.assertEqual([event["source"] for event in task["statusHistory"]], ["drag", "codex"])
        self.assertEqual(task["statusHistory"][-1]["to"], "done")
        self.assertTrue(APP.record_task_status_event(task, "done", "doing", "2026-08-10T10:01:00", "undo"))
        self.assertEqual(task["statusHistory"][-1]["source"], "undo")

    def test_task_events_are_sorted_and_legacy_tasks_get_a_truthful_fallback(self):
        tasks = [
            {"id": "legacy", "title": "Legacy", "status": "doing", "updatedAt": "2026-08-10T09:30:00", "autoStartedAt": "2026-08-10T09:30:00"},
            {
                "id": "tracked", "title": "Tracked", "status": "done",
                "statusHistory": [
                    {"at": "2026-08-10T08:00:00", "from": "", "to": "planned", "source": "manual"},
                    {"at": "2026-08-10T10:00:00", "from": "doing", "to": "done", "source": "drag"},
                ],
            },
        ]
        events = APP.task_status_events(tasks)
        self.assertEqual([event["task"]["id"] for event in events], ["tracked", "legacy", "tracked"])
        self.assertEqual(events[1]["source"], "codex")

    def test_rollover_starts_a_new_daily_history_without_copying_old_events(self):
        tasks = [
            {
                "id": "old", "title": "Continue work", "status": "doing", "date": "2026-08-09",
                "boardOrder": 3,
                "statusHistory": [{"at": "2026-08-09T09:00:00", "from": "planned", "to": "doing", "source": "manual"}],
            },
            {
                "id": "archived-old", "title": "Removed work", "status": "doing", "date": "2026-08-09",
                "archivedAt": "2026-08-09T12:00:00",
            },
        ]
        rolled, changed = APP.rollover_in_progress_tasks(tasks, "2026-08-10")
        self.assertTrue(changed)
        carried = next(task for task in rolled if task.get("carriedFromTaskId") == "old")
        self.assertEqual(len(carried["statusHistory"]), 1)
        self.assertEqual(carried["statusHistory"][0]["source"], "rollover")
        self.assertEqual(carried["statusHistory"][0]["to"], "doing")
        self.assertNotIn("boardOrder", carried)
        self.assertFalse(any(task.get("carriedFromTaskId") == "archived-old" for task in rolled))

    def test_planning_review_reschedules_without_faking_a_status_change(self):
        task = {"id": "task-1", "title": "Validate release", "date": "2026-08-08", "status": "planned", "boardOrder": 0}
        status_bar = Mock(); date_field = Mock()
        window = SimpleNamespace(
            today_tasks=[task], board_date_field=date_field, view_signature="old",
            render_today_tasks=Mock(), render_portfolio_decisions=Mock(), statusBar=lambda: status_bar,
        )

        with patch.object(APP, "save_json") as save:
            changed = APP.MainWindow.reschedule_planned_task(window, task, "2026-08-10")

        self.assertTrue(changed)
        self.assertEqual((task["date"], task["status"]), ("2026-08-10", "planned"))
        self.assertEqual(task["scheduleHistory"][0]["source"], "planning_review")
        self.assertNotIn("statusHistory", task)
        save.assert_called_once_with(APP.TASKS_FILE, window.today_tasks)
        self.assertEqual(date_field.setDate.call_args.args[0].toString(APP.Qt.ISODate), "2026-08-10")
        window.render_portfolio_decisions.assert_called_once_with()

    def test_manual_status_move_offers_an_undo_without_bypassing_the_normal_engine(self):
        task = {"id": "task-1", "status": "planned", "statusHistory": []}
        status_bar = Mock()
        window = SimpleNamespace(
            today_tasks=[task],
            complete_project_next_step=Mock(return_value=False),
            reopen_project_next_step=Mock(return_value=False),
            sync_project_workload=Mock(),
            render_today_tasks=Mock(),
            render=Mock(),
            statusBar=lambda: status_bar,
            offer_task_undo=Mock(),
            view_signature=None,
        )
        with patch.object(APP, "save_json"):
            changed = APP.MainWindow.set_task_status(window, "task-1", "doing", source="drag")
        self.assertTrue(changed)
        self.assertEqual(task["status"], "doing")
        self.assertEqual(task["statusHistory"][-1]["source"], "drag")
        window.offer_task_undo.assert_called_once()

    def test_completing_without_an_outcome_keeps_status_but_requests_evidence(self):
        task = {"id": "task-1", "title": "Validate release", "date": "2026-08-10", "status": "doing"}
        status_bar = Mock()
        window = SimpleNamespace(
            today_tasks=[task],
            complete_project_next_step=Mock(return_value=False),
            reopen_project_next_step=Mock(return_value=False),
            sync_project_workload=Mock(), render_today_tasks=Mock(), render=Mock(),
            statusBar=lambda: status_bar, offer_task_undo=Mock(), view_signature=None,
        )

        with patch.object(APP, "save_json"):
            changed = APP.MainWindow.set_task_status(window, "task-1", "done", source="selector")

        self.assertTrue(changed)
        self.assertEqual(task["status"], "done")
        self.assertEqual(APP.tasks_missing_completion_outcomes([task]), [task])
        self.assertIn("记录实际成果", status_bar.showMessage.call_args.args[0])
        window.offer_task_undo.assert_called_once()

    def test_same_column_drag_changes_priority_without_faking_a_status_event(self):
        tasks = [
            {"id": "first", "title": "First", "date": "2026-08-10", "status": "doing", "boardOrder": 0, "statusHistory": []},
            {"id": "second", "title": "Second", "date": "2026-08-10", "status": "doing", "boardOrder": 1, "statusHistory": []},
        ]
        status_bar = Mock()
        window = SimpleNamespace(
            today_tasks=tasks,
            render_today_tasks=Mock(),
            statusBar=lambda: status_bar,
        )
        with patch.object(APP, "save_json"):
            changed = APP.MainWindow.move_task_on_board(window, "second", "doing", 0, source="drag")
        self.assertTrue(changed)
        self.assertEqual([task["id"] for task in APP.ordered_board_tasks(tasks, "2026-08-10", "doing")], ["second", "first"])
        self.assertEqual(tasks[1]["statusHistory"], [])
        window.render_today_tasks.assert_called_once()

    def test_reselecting_the_current_status_does_not_silently_reorder(self):
        tasks = [
            {"id": "first", "date": "2026-08-10", "status": "doing", "boardOrder": 0},
            {"id": "second", "date": "2026-08-10", "status": "doing", "boardOrder": 1},
        ]
        window = SimpleNamespace(today_tasks=tasks)
        changed = APP.MainWindow.set_task_status(window, "first", "doing", source="selector")
        self.assertFalse(changed)
        self.assertEqual([task["id"] for task in APP.ordered_board_tasks(tasks, "2026-08-10", "doing")], ["first", "second"])

    def test_removing_a_task_preserves_it_in_the_recycle_bin(self):
        task = {
            "id": "task-1", "title": "Validate", "date": "2026-08-10", "status": "doing",
            "statusHistory": [{"at": "09:00", "from": "planned", "to": "doing", "source": "manual"}],
        }
        status_bar = Mock()
        window = SimpleNamespace(
            today_tasks=[task], pending_task_undo=None, clear_task_undo=Mock(),
            sync_project_workload=Mock(), render_today_tasks=Mock(), render=Mock(),
            statusBar=lambda: status_bar, view_signature=None,
        )
        with patch.object(APP.QMessageBox, "question", return_value=APP.QMessageBox.Yes), patch.object(APP, "save_json"):
            APP.MainWindow.delete_today_task(window, task)
        self.assertEqual(window.today_tasks, [task])
        self.assertTrue(APP.task_is_archived(task))
        self.assertEqual(len(task["statusHistory"]), 1)
        window.sync_project_workload.assert_called_once()
        window.render_today_tasks.assert_called_once()

    def test_restoring_a_task_returns_it_to_the_original_date_and_status(self):
        task = {
            "id": "task-1", "title": "Validate", "date": "2026-08-10", "status": "doing",
            "archivedAt": "2026-08-10T11:00:00", "statusHistory": [],
        }
        status_bar = Mock(); date_field = Mock()
        window = SimpleNamespace(
            today_tasks=[task], board_date_field=date_field,
            sync_project_workload=Mock(), render_today_tasks=Mock(), render=Mock(),
            statusBar=lambda: status_bar, view_signature=None,
        )
        with patch.object(APP, "save_json"):
            restored = APP.MainWindow.restore_archived_task(window, task)
        self.assertTrue(restored)
        self.assertFalse(APP.task_is_archived(task))
        self.assertEqual(task["status"], "doing")
        date_field.setDate.assert_called_once()
        window.render_today_tasks.assert_called_once()

    def test_restoring_an_old_project_next_step_never_creates_a_duplicate(self):
        archived = {
            "id": "old", "title": "Validate release", "projectNextStep": "Validate release",
            "origin": "project_next_step", "projectId": "stable", "date": "2026-08-10",
            "status": "planned", "archivedAt": "2026-08-10T10:00:00",
        }
        active = {
            "id": "new", "title": "Validate release", "origin": "project_next_step",
            "projectId": "stable", "date": "2026-08-11", "status": "doing",
        }
        project = {"id": "current", "savedId": "stable"}
        window = SimpleNamespace(today_tasks=[archived, active], project_by_id=lambda _project_id: project)
        with patch.object(APP.QMessageBox, "information") as information:
            restored = APP.MainWindow.restore_archived_task(window, archived)
        self.assertFalse(restored)
        self.assertTrue(APP.task_is_archived(archived))
        information.assert_called_once()

    def test_restoring_a_superseded_snapshot_preserves_history_without_duplicating_work(self):
        archived = {
            "id": "old", "title": "Validate release", "projectNextStep": "Validate release",
            "origin": "project_next_step", "projectId": "stable", "date": "2026-08-09",
            "status": "doing", "archivedAt": "2026-08-10T10:00:00",
            "carriedToTaskId": "current", "carriedToDate": "2026-08-10",
        }
        current = {
            "id": "current", "title": "Validate release", "origin": "project_next_step",
            "projectId": "stable", "date": "2026-08-10", "status": "doing",
            "carriedFromTaskId": "old",
        }
        project = {"id": "current-project", "savedId": "stable"}
        date_field = Mock(); status_bar = Mock()
        window = SimpleNamespace(
            today_tasks=[archived, current], project_by_id=lambda _project_id: project,
            board_date_field=date_field, sync_project_workload=Mock(), render_today_tasks=Mock(),
            render=Mock(), statusBar=lambda: status_bar, view_signature=None,
        )
        with patch.object(APP, "save_json"):
            restored = APP.MainWindow.restore_archived_task(window, archived)

        self.assertTrue(restored)
        self.assertFalse(APP.task_is_archived(archived))
        self.assertTrue(APP.task_is_superseded_daily_record(archived))
        self.assertEqual(APP.open_project_tasks(window.today_tasks, project), [current])

    def test_undo_reenters_the_status_engine_and_rejects_stale_transitions(self):
        event = {"at": "2026-08-10T10:00:00", "from": "doing", "to": "done", "source": "drag"}
        task = {"id": "task-1", "status": "done", "statusHistory": [event]}
        status_bar = Mock()
        window = SimpleNamespace(
            pending_task_undo={"taskId": "task-1", "from": "doing", "to": "done", "at": event["at"]},
            today_tasks=[task],
            clear_task_undo=Mock(),
            set_task_status=Mock(return_value=True),
            statusBar=lambda: status_bar,
        )
        APP.MainWindow.undo_last_task_transition(window)
        window.set_task_status.assert_called_once_with("task-1", "doing", source="undo", allow_undo=False)

        window.set_task_status.reset_mock()
        task["statusHistory"].append({"at": "2026-08-10T10:01:00", "from": "done", "to": "planned", "source": "selector"})
        APP.MainWindow.undo_last_task_transition(window)
        window.set_task_status.assert_not_called()


class DailySummaryTests(unittest.TestCase):
    def test_new_task_choices_exclude_completed_projects_but_existing_links_survive(self):
        projects = [
            {"id": "active", "savedId": "active-stable", "status": "active"},
            {"id": "closed", "savedId": "closed-stable", "status": "completed"},
        ]
        self.assertEqual(
            [project["id"] for project in APP.task_editor_project_choices(projects)],
            ["active"],
        )
        self.assertEqual(
            [project["id"] for project in APP.task_editor_project_choices(projects, {"projectId": "closed-stable"})],
            ["active", "closed"],
        )

    def test_next_focus_suggestion_builds_an_editable_provenance_aware_draft(self):
        projects = [
            {"id": "short", "name": "RamanVerse", "status": "active"},
            {"id": "full", "name": "RamanVerse Software", "status": "active"},
            {"id": "closed", "name": "Archived Release", "status": "completed"},
        ]
        draft, project = APP.daily_summary_suggestion_draft(
            "RamanVerse Software：Run the release validation suite", projects, "2026-08-08"
        )
        self.assertEqual(project["id"], "full")
        self.assertEqual(draft["title"], "Run the release validation suite")
        self.assertEqual(draft["origin"], "daily_summary")
        self.assertEqual(draft["sourceSummaryDate"], "2026-08-08")
        self.assertIn("原建议", draft["notes"])

        ambiguous, project = APP.daily_summary_suggestion_draft(
            "Compare RamanVerse with RamanVerse Software", projects, "2026-08-08"
        )
        self.assertIsNone(project)
        self.assertEqual(ambiguous["title"], "Compare RamanVerse with RamanVerse Software")
        closed_draft, closed_project = APP.daily_summary_suggestion_draft(
            "Archived Release：Start a follow-up", projects, "2026-08-08"
        )
        self.assertIsNone(closed_project)
        self.assertEqual(closed_draft["title"], "Archived Release：Start a follow-up")

    def test_summary_suggestion_duplicate_guard_survives_title_edits_and_ignores_archive_history(self):
        current = {
            "id": "current", "origin": "daily_summary", "sourceSummaryDate": "2026-08-08",
            "sourceSuggestion": "Run validation", "title": "Edited task title", "status": "done",
        }
        archived = {
            "id": "archived", "origin": "daily_summary", "sourceSummaryDate": "2026-08-08",
            "sourceSuggestion": "Archived idea", "archivedAt": "2026-08-10T10:00:00",
        }
        self.assertIs(APP.find_daily_summary_suggestion_task([current], "2026-08-08", "run validation"), current)
        self.assertIsNone(APP.find_daily_summary_suggestion_task([archived], "2026-08-08", "Archived idea"))

    def test_summary_suggestion_opens_a_confirmable_today_task_draft(self):
        project = {"id": "project", "name": "Model Validation"}
        created = {"id": "task", "projectId": "project"}
        status_bar = Mock()
        window = SimpleNamespace(
            today_tasks=[], projects=[project], edit_today_task=Mock(return_value=created),
            statusBar=lambda: status_bar, render_today_tasks=Mock(),
        )
        summary = {"date": "2026-08-08"}
        result = APP.MainWindow.plan_daily_summary_suggestion(
            window, summary, "Model Validation：Compare the held-out datasets"
        )
        self.assertIs(result, created)
        call = window.edit_today_task.call_args
        self.assertEqual(call.args[:3], (None, "planned", "project"))
        self.assertEqual(call.kwargs["draft"]["origin"], "daily_summary")
        self.assertEqual(call.kwargs["draft"]["date"], APP.QDate.currentDate().toString(APP.Qt.ISODate))
        self.assertIn("Model Validation", status_bar.showMessage.call_args.args[0])

    def test_created_summary_task_keeps_provenance_and_audited_source(self):
        dialog = Mock()
        dialog.exec_.return_value = APP.QDialog.Accepted
        dialog.value.return_value = {
            "title": "Run validation", "status": "planned",
            "date": "2026-08-10", "notes": "Review suggestion", "completionNote": "",
        }
        dialog.codex_requested = False
        status_bar = Mock()
        window = SimpleNamespace(
            projects=[], today_tasks=[], board_date_field=Mock(),
            sync_project_workload=Mock(), render_today_tasks=Mock(), render=Mock(),
            statusBar=lambda: status_bar, view_signature="old",
        )
        draft = {
            "origin": "daily_summary", "sourceSummaryDate": "2026-08-08",
            "sourceSuggestion": "Run validation",
        }
        with patch.object(APP, "TaskEditor", return_value=dialog), patch.object(APP, "save_json"), patch.object(APP, "record_task_status_event") as event:
            task = APP.MainWindow.edit_today_task(window, draft=draft)
        self.assertEqual(task["origin"], "daily_summary")
        self.assertEqual(task["sourceSummaryDate"], "2026-08-08")
        self.assertEqual(task["sourceSuggestion"], "Run validation")
        self.assertEqual(event.call_args.args[-1], "summary")

    def test_payload_preserves_a_historical_project_snapshot_when_the_live_link_is_gone(self):
        tasks = [{
            "id": "task-1", "title": "Publish report", "date": "2026-08-08", "status": "done",
            "projectId": "removed-project", "projectNameSnapshot": "Original project",
        }]
        payload = APP.build_daily_summary_payload(tasks, [], "2026-08-08")
        self.assertEqual(payload["tasks"][0]["project"], "Original project（历史关联）")
        self.assertEqual(payload["tasks"][0]["projectLinkState"], "historical")

    def test_payload_uses_only_requested_date_and_resolves_project(self):
        tasks = [
            {"date": "2026-08-08", "title": "Validate model", "status": "doing", "projectId": "p1", "notes": "Compare alpha", "completionNote": "Stale result"},
            {"date": "2026-08-08", "title": "Removed duplicate", "status": "planned", "projectId": "p1", "archivedAt": "2026-08-08T12:00:00"},
            {"date": "2026-08-09", "title": "Today", "status": "planned", "projectId": "p1"},
        ]
        projects = [{"id": "p1", "name": "Denoising", "conversations": []}]
        payload = APP.build_daily_summary_payload(tasks, projects, "2026-08-08")
        self.assertEqual(len(payload["tasks"]), 1)
        self.assertEqual(payload["tasks"][0]["project"], "Denoising")
        self.assertEqual(payload["tasks"][0]["status"], "进行中")
        self.assertEqual(payload["tasks"][0]["completionOutcome"], "")
        self.assertEqual(payload["tasks"][0]["statusTransitions"][0]["source"], "历史记录")

    def test_payload_exposes_confirmed_completion_outcome_separately_from_plan_notes(self):
        tasks = [{
            "date": "2026-08-08", "title": "Validate model", "status": "done", "projectId": "p1",
            "notes": "Plan to compare alpha and beta.",
            "completionNote": "Beta reduced validation error by 8% across three runs.",
        }]
        payload = APP.build_daily_summary_payload(tasks, [{"id": "p1", "name": "Denoising"}], "2026-08-08")
        task = payload["tasks"][0]
        self.assertEqual(task["notes"], "Plan to compare alpha and beta.")
        self.assertEqual(task["completionOutcome"], "Beta reduced validation error by 8% across three runs.")

    def test_payload_includes_ordered_task_status_transitions(self):
        tasks = [{
            "date": "2026-08-08", "title": "Validate", "status": "done", "projectId": "p1",
            "statusHistory": [
                {"at": "2026-08-08T09:00:00", "from": "", "to": "planned", "source": "manual"},
                {"at": "2026-08-08T10:00:00", "from": "planned", "to": "doing", "source": "codex"},
                {"at": "2026-08-08T11:00:00", "from": "doing", "to": "done", "source": "drag"},
            ],
        }]
        payload = APP.build_daily_summary_payload(tasks, [{"id": "p1", "name": "Denoising"}], "2026-08-08")
        transitions = payload["tasks"][0]["statusTransitions"]
        self.assertEqual([item["to"] for item in transitions], ["计划", "进行中", "已完成"])
        self.assertEqual(transitions[-1]["source"], "看板拖放")

    def test_payload_keeps_rescheduling_separate_from_execution_evidence(self):
        tasks = [{
            "date": "2026-08-08", "title": "Validate", "status": "planned", "projectId": "p1",
            "scheduleHistory": [{
                "at": "2026-08-08T08:30:00", "from": "2026-08-07", "to": "2026-08-08", "source": "planning_review",
            }],
        }]

        payload = APP.build_daily_summary_payload(tasks, [{"id": "p1", "name": "Denoising"}], "2026-08-08")

        self.assertEqual(payload["tasks"][0]["scheduleChanges"][0]["source"], "计划复核")
        prompt = APP.daily_summary_prompt(payload)
        self.assertIn("scheduleChanges 只表示计划日期", prompt)
        self.assertIn("不能写入 completed", prompt)

    def test_payload_resolves_tasks_saved_with_a_stable_project_id(self):
        tasks = [{"date": "2026-08-08", "title": "Validate", "status": "doing", "projectId": "stable-id"}]
        projects = [{"id": "current-id", "savedId": "stable-id", "name": "Denoising", "conversations": []}]
        payload = APP.build_daily_summary_payload(tasks, projects, "2026-08-08")
        self.assertEqual(payload["tasks"][0]["project"], "Denoising")

    def test_payload_includes_only_that_days_audited_project_decisions(self):
        projects = [{"id": "current-id", "savedId": "stable-id", "name": "Denoising", "conversations": []}]
        decisions = [
            {
                "at": "2026-08-08T09:00:00", "projectId": "stable-id", "projectName": "Denoising", "source": "editor",
                "changes": [{"field": "stage", "label": "当前阶段", "before": "planning", "after": "validation"}],
            },
            APP.build_project_review_entry({"savedId": "stable-id", "name": "Denoising", "stage": "validation", "health": "on_track", "nextStep": "Verify"}, "2026-08-08T10:00:00", "review-1"),
            APP.build_project_alignment_entry({"savedId": "stable-id", "name": "Denoising", "nextStep": "Verify"}, [{"title": "Repair benchmark"}], "2026-08-08T11:00:00", "alignment-1"),
            APP.build_project_lifecycle_entry({"savedId": "stable-id", "name": "Denoising", "category": "Research"}, "archive", "2026-08-08T12:00:00", "archive-1"),
            {"at": "2026-08-09T09:00:00", "projectId": "stable-id", "source": "editor", "changes": []},
        ]
        payload = APP.build_daily_summary_payload([], projects, "2026-08-08", decisions)
        self.assertEqual(len(payload["projectDecisions"]), 4)
        self.assertEqual([item["kind"] for item in payload["projectDecisions"]], ["项目决策", "项目复核", "执行方向确认", "项目生命周期"])
        self.assertEqual(payload["projectDecisions"][0]["changes"][0]["after"], "验证")
        self.assertTrue(any("保留下一步" in item["summary"] for item in payload["projectDecisions"]))

    def test_daily_summary_treats_only_confirmed_project_closeout_as_completion_evidence(self):
        project = {
            "id": "runtime", "savedId": "stable", "name": "Release",
            "completionObjectiveSnapshot": "Deliver a validated release package",
            "completionAcceptedAt": "2026-08-08T15:00:00",
        }
        decisions = [
            APP.build_project_closeout_entry(project, "complete", "Passed 18 release checks.", "2026-08-08T15:00:00", "closeout-1"),
            APP.build_project_closeout_entry(project, "reopen", "Passed 18 release checks.", "2026-08-08T16:00:00", "closeout-2"),
        ]
        payload = APP.build_daily_summary_payload([], [project], "2026-08-08", decisions)
        self.assertEqual([item["kind"] for item in payload["projectDecisions"]], ["项目收尾", "项目收尾"])
        self.assertEqual([item["isCompletionEvidence"] for item in payload["projectDecisions"]], [True, False])
        self.assertIn("验收目标", payload["projectDecisions"][0]["summary"])
        prompt = APP.daily_summary_prompt(payload)
        self.assertIn("isCompletionEvidence 为 true", prompt)
        self.assertIn("重新打开都不能写入 completed", prompt)

    def test_prompt_requires_specific_structured_output(self):
        prompt = APP.daily_summary_prompt({"date": "2026-08-08", "tasks": [], "codexActivities": []})
        self.assertIn('"overview"', prompt)
        self.assertIn('"completed"', prompt)
        self.assertIn("不要虚构完成情况", prompt)
        self.assertIn("下一步进化建议", prompt)
        self.assertIn("completionOutcome 是人工确认的实际完成成果", prompt)
        self.assertIn("projectDecisions 是人工确认的项目管理活动", prompt)

    def test_visible_prompt_is_readable_and_has_writeback_marker(self):
        prompt = APP.daily_summary_prompt({"date": "2026-08-08", "tasks": [{}, {}], "codexActivities": [{"userTurns": 3}], "projectDecisions": [{}, {}]}, visible=True)
        self.assertIn("本次覆盖：5 个工作项 · 2 项计划任务 · 1 个 Codex 对话 · 2 项项目决策 · 3 次提问", prompt)
        self.assertIn("工作概览 / 完成成果 / 仍在推进 / 下一步进化建议", prompt)
        self.assertIn("CODEX_HUB_JSON:", prompt)

    def test_visible_summary_marker_is_parsed_for_writeback(self):
        raw = (
            "## 工作概览\n已完成检查。\n"
            'CODEX_HUB_JSON: {"overview":"已完成检查。","completed":["项目：检查完成"],'
            '"inProgress":[],"nextFocus":["项目：增加回归验证"]}'
        )
        result = APP.parse_daily_summary_response(
            raw,
            {"date": "2026-08-08", "tasks": [{}], "codexActivities": [], "projectDecisions": [{}, {}]},
            "summary-thread",
        )
        self.assertEqual(result["overview"], "已完成检查。")
        self.assertEqual(result["nextFocus"], ["项目：增加回归验证"])
        self.assertEqual(result["sourceCounts"]["tasks"], 1)
        self.assertEqual(result["sourceCounts"]["projectDecisions"], 2)

    def test_summary_generation_passes_project_decision_history_into_payload(self):
        worker = SimpleNamespace(
            generated=SimpleNamespace(connect=Mock()),
            finished=SimpleNamespace(connect=Mock()),
            start=Mock(),
        )
        status_bar = Mock()
        window = SimpleNamespace(
            daily_summary_worker=None, summary_attempt_date=None, daily_summary_error="",
            today_tasks=[{"id": "task-1"}], projects=[{"id": "project-1"}], project_decisions=[{"id": "decision-1"}],
            daily_summary_target_date=lambda: "2026-08-08", daily_summary_for_date=lambda _date: None,
            render_daily_summary=Mock(), on_daily_summary_generated=Mock(), finish_daily_summary=Mock(), statusBar=lambda: status_bar,
        )
        with patch.object(APP, "build_daily_summary_payload", return_value={"date": "2026-08-08"}) as build, patch.object(APP, "DailySummaryWorker", return_value=worker):
            APP.MainWindow.start_daily_summary(window, force=False)
        build.assert_called_once_with(window.today_tasks, window.projects, "2026-08-08", window.project_decisions)
        worker.start.assert_called_once()

    def test_codex_activity_scan_uses_real_record_timestamps(self):
        with tempfile.TemporaryDirectory() as folder:
            rollout = Path(folder) / "rollout-test-thread.jsonl"
            records = [
                {"timestamp": "2026-08-07T15:55:00Z", "type": "event_msg", "payload": {"type": "user_message", "message": "too early"}},
                {"timestamp": "2026-08-08T02:00:00Z", "type": "event_msg", "payload": {"type": "user_message", "message": "Compare denoising variants"}},
                {"timestamp": "2026-08-08T02:10:00Z", "type": "event_msg", "payload": {"type": "agent_message", "message": "Validation plan prepared"}},
                {"timestamp": "2026-08-08T16:10:00Z", "type": "event_msg", "payload": {"type": "user_message", "message": "next local day"}},
            ]
            rollout.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
            timestamp = datetime.fromisoformat("2026-08-09T01:00:00").timestamp()
            os.utime(rollout, (timestamp, timestamp))
            projects = [{"id": "p1", "name": "Denoising", "path": "C:\\work"}]
            index = {"thread-1": {"title": "Experiment", "cwd": "C:\\work", "rolloutPath": str(rollout)}}
            with patch.object(APP, "daily_summary_thread_id", return_value="summary-thread"):
                result = APP.codex_activities_for_date(projects, "2026-08-08", index=index, thread_projects={"thread-1": "p1"})
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["conversation"], "Experiment")
            self.assertEqual(result[0]["userTurns"], 1)
            self.assertEqual(result[0]["recentRequests"], ["Compare denoising variants"])

    def test_summary_thread_can_be_configured_without_committing_an_id(self):
        with patch.dict(APP.os.environ, {"CODEX_HUB_SUMMARY_THREAD_ID": "summary-thread"}):
            self.assertEqual(APP.daily_summary_thread_id(), "summary-thread")

    def test_compact_summary_prefers_a_complete_sentence(self):
        text = "昨天完成了数据核验。随后继续调整训练参数并记录结果，今天准备补充对照实验。"
        compact = APP.compact_summary_text(text, 20)
        self.assertEqual(compact, "昨天完成了数据核验。")

    def test_compact_summary_uses_ellipsis_without_sentence_boundary(self):
        compact = APP.compact_summary_text("一段没有句号但明显超过限制的工作总结内容", 12)
        self.assertTrue(compact.endswith("…"))
        self.assertLessEqual(len(compact), 12)


if __name__ == "__main__":
    unittest.main()
