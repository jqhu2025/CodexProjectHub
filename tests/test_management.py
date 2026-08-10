import inspect
import unittest
from datetime import datetime

from codex_hub import management


class ManagementModuleTests(unittest.TestCase):
    def test_domain_module_has_no_qt_dependency(self):
        self.assertNotIn("PyQt", inspect.getsource(management))

    def test_only_complete_full_governance_changes_establish_a_review_baseline(self):
        complete = {
            "status": "active", "objective": "Ship validated release", "nextStep": "Run acceptance checks",
            "stage": "validation", "health": "on_track", "blocker": "",
        }
        incomplete = {**complete, "objective": ""}

        for source in ("manual", "editor", "codex", "created", "review_resolution"):
            self.assertTrue(management.project_change_establishes_review(complete, source, True))
        for source in ("focus", "calibration", "alignment", "category", "undo"):
            self.assertFalse(management.project_change_establishes_review(complete, source, True))
        self.assertFalse(management.project_change_establishes_review(incomplete, "editor", True))
        self.assertFalse(management.project_change_establishes_review(complete, "editor", False))
        self.assertEqual(management.PROJECT_DECISION_SOURCES["review_resolution"], "复核校准")

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

    def test_wip_reduction_has_a_distinct_audit_source(self):
        self.assertEqual(management.TASK_EVENT_SOURCES["wip"], "WIP 收敛")
        task = {"id": "task-1", "status": "doing"}
        self.assertTrue(management.record_task_status_event(
            task, "doing", "planned", "2026-08-10T09:10:00", "wip"
        ))
        self.assertEqual(task["statusHistory"][-1]["source"], "wip")

    def test_rollover_predecessor_is_historical_evidence_not_current_work(self):
        predecessor = {"id": "previous-day-task", "status": "doing", "carriedToTaskId": "next-day-task"}
        successor = {"id": "next-day-task", "status": "doing", "carriedFromTaskId": "previous-day-task"}

        self.assertTrue(management.task_is_superseded_daily_record(predecessor))
        self.assertFalse(management.task_is_superseded_daily_record(successor))
        self.assertFalse(management.task_is_superseded_daily_record(None))
        self.assertEqual(management.active_task_records([predecessor]), [predecessor])
        self.assertIs(management.current_task_record([predecessor, successor], predecessor), successor)

    def test_current_task_record_stops_at_missing_or_cyclic_rollover_links(self):
        missing = {"id": "missing", "carriedToTaskId": "not-stored"}
        first = {"id": "first", "carriedToTaskId": "second"}
        second = {"id": "second", "carriedToTaskId": "first"}

        self.assertIs(management.current_task_record([missing], missing), missing)
        self.assertIs(management.current_task_record([first, second], first), second)
        self.assertIsNone(management.current_task_record([], None))

    def test_completion_outcome_is_audited_and_only_active_for_completed_tasks(self):
        task = {"id": "task-1", "status": "done"}
        self.assertTrue(management.record_task_completion_outcome(
            task, "Validated all 12 release checks.", "2026-08-10T11:00:00", "outcome_editor"
        ))
        self.assertEqual(management.task_completion_outcome(task), "Validated all 12 release checks.")
        self.assertFalse(management.record_task_completion_outcome(
            task, "  Validated   all 12 release checks.  ", "2026-08-10T11:01:00", "outcome_editor"
        ))
        self.assertEqual(len(task["completionHistory"]), 1)
        task["status"] = "doing"
        self.assertEqual(management.task_completion_outcome(task), "")
        self.assertTrue(management.clear_task_completion_outcome(task, "2026-08-10T11:02:00"))
        self.assertNotIn("completionNote", task)
        self.assertEqual(task["completionHistory"][-1]["source"], "reopen")

    def test_completion_outcome_rejects_unfinished_tasks(self):
        task = {"id": "task-1", "status": "doing"}
        self.assertFalse(management.record_task_completion_outcome(
            task, "This must not become completion evidence.", "2026-08-10T11:00:00"
        ))
        self.assertNotIn("completionNote", task)

    def test_completion_revisions_are_newest_first_and_support_legacy_records(self):
        task = {
            "status": "done",
            "completionHistory": [
                {"at": "2026-08-10T10:00:00", "text": "Initial result", "previous": "", "source": "task_editor"},
                {"at": "2026-08-10T11:00:00", "text": "Verified result", "previous": "Initial result", "source": "outcome_editor"},
            ],
        }
        self.assertEqual([item["text"] for item in management.task_completion_revisions(task)], ["Verified result", "Initial result"])
        legacy = {"status": "done", "completionNote": "Imported outcome", "updatedAt": "2026-08-09T12:00:00"}
        revision = management.task_completion_revisions(legacy)[0]
        self.assertEqual((revision["text"], revision["source"]), ("Imported outcome", "legacy"))
        self.assertEqual(management.task_completion_revisions(None), [])

    def test_project_completion_outcome_forms_a_reopen_safe_audit_chain(self):
        project = {
            "id": "project-1", "status": "completed",
            "objective": "Deliver a validated release package",
            "successCriteria": "Pass all 18 release checks and publish the package",
        }
        self.assertTrue(management.record_project_completion_outcome(
            project, "Delivered the validated release package.", "2026-08-10T12:00:00"
        ))
        self.assertEqual(management.project_completion_outcome(project), "Delivered the validated release package.")
        self.assertEqual(project["completedAt"], "2026-08-10T12:00:00")
        self.assertEqual(project["completionObjectiveSnapshot"], "Deliver a validated release package")
        self.assertEqual(project["completionCriteriaSnapshot"], "Pass all 18 release checks and publish the package")
        self.assertEqual(project["completionAcceptedAt"], "2026-08-10T12:00:00")
        self.assertTrue(management.record_project_completion_outcome(
            project, "Delivered the package and passed 18 release checks.", "2026-08-10T12:30:00", "closeout_editor"
        ))
        self.assertEqual(project["completedAt"], "2026-08-10T12:00:00")
        self.assertEqual(len(project["completionHistory"]), 2)
        project["status"] = "active"
        self.assertEqual(management.project_completion_outcome(project), "")
        self.assertTrue(management.clear_project_completion_outcome(project, "2026-08-10T13:00:00"))
        self.assertNotIn("completionSummary", project)
        self.assertNotIn("completedAt", project)
        self.assertNotIn("completionObjectiveSnapshot", project)
        self.assertNotIn("completionCriteriaSnapshot", project)
        self.assertNotIn("completionAcceptedAt", project)
        self.assertEqual(project["completionHistory"][-1]["source"], "reopen")
        self.assertEqual(project["completionHistory"][-1]["objective"], "Deliver a validated release package")
        self.assertEqual(project["completionHistory"][-1]["criteria"], "Pass all 18 release checks and publish the package")
        self.assertEqual(
            management.latest_project_completion_outcome(project),
            "Delivered the package and passed 18 release checks.",
        )

    def test_project_completion_outcome_rejects_unfinished_or_empty_evidence(self):
        active = {"status": "active"}
        completed = {"status": "completed"}
        self.assertFalse(management.record_project_completion_outcome(active, "Not final", "2026-08-10T12:00:00"))
        self.assertFalse(management.record_project_completion_outcome(completed, "  ", "2026-08-10T12:00:00"))
        self.assertNotIn("completionSummary", active)
        self.assertNotIn("completionSummary", completed)

    def test_project_closeout_event_distinguishes_completion_from_reopen(self):
        project = {
            "id": "runtime", "savedId": "stable", "name": "Release",
            "completedAt": "2026-08-10T12:00:00",
            "completionObjectiveSnapshot": "Deliver a validated release package",
            "completionCriteriaSnapshot": "Pass all 18 release checks",
            "completionAcceptedAt": "2026-08-10T12:00:00",
        }
        completed = management.build_project_closeout_entry(
            project, "complete", "Passed the release gate.", "2026-08-10T12:00:00", "closeout-1"
        )
        reopened = management.build_project_closeout_entry(
            project, "reopen", "Passed the release gate.", "2026-08-10T13:00:00", "closeout-2"
        )
        self.assertEqual((completed["projectId"], completed["kind"], completed["action"]), ("stable", "closeout", "complete"))
        self.assertEqual(completed["snapshot"]["objective"], "Deliver a validated release package")
        self.assertEqual(completed["snapshot"]["criteria"], "Pass all 18 release checks")
        self.assertIn("验收目标", management.format_project_decision_summary(completed))
        self.assertIn("验收标准", management.format_project_decision_summary(completed))
        self.assertIn("重新打开", management.format_project_decision_summary(reopened))
        self.assertIsNone(management.build_project_closeout_entry(project, "archive", "Result", "2026-08-10T14:00:00"))

    def test_success_criteria_is_audited_without_becoming_a_legacy_governance_gap(self):
        project = {
            "id": "project-1", "status": "active", "objective": "Ship release",
            "nextStep": "Run checks", "stage": "validation", "health": "on_track",
        }
        self.assertNotIn("successCriteria", management.project_governance_gaps(project))
        changes = management.project_decision_changes(
            project, {**project, "successCriteria": "Pass all checks and publish artifacts"}
        )
        self.assertEqual(changes, [{
            "field": "successCriteria", "label": "验收标准", "before": "",
            "after": "Pass all checks and publish artifacts",
        }])

    def test_blocker_lifecycle_preserves_continuous_age_and_records_resolution(self):
        project = {"status": "active", "blocker": "Waiting for calibration"}
        started = management.reconcile_project_blocker_lifecycle(
            {"status": "active", "blocker": ""}, project, "2026-08-10T09:00:00"
        )
        self.assertEqual(started["action"], "started")
        self.assertEqual(project["blockedAt"], "2026-08-10T09:00:00")
        self.assertNotIn("blockedAtEstimated", project)

        revised = {**project, "blocker": "Waiting for calibrated reference"}
        updated = management.reconcile_project_blocker_lifecycle(
            project, revised, "2026-08-10T11:00:00"
        )
        self.assertEqual(updated["action"], "updated")
        self.assertEqual(revised["blockedAt"], "2026-08-10T09:00:00")
        self.assertEqual(revised["blockerUpdatedAt"], "2026-08-10T11:00:00")

        resolved = {**revised, "blocker": ""}
        event = management.reconcile_project_blocker_lifecycle(
            revised, resolved, "2026-08-10T14:00:00", "Calibrated reference delivered and verified"
        )
        self.assertEqual(event["action"], "resolved")
        self.assertNotIn("blockedAt", resolved)
        self.assertEqual(resolved["lastResolvedBlocker"], "Waiting for calibrated reference")
        self.assertEqual(resolved["lastBlockerResolvedAt"], "2026-08-10T14:00:00")
        self.assertEqual(resolved["lastBlockerResolution"], "Calibrated reference delivered and verified")
        self.assertEqual(event["resolution"], "Calibrated reference delivered and verified")

    def test_legacy_blocker_timing_is_marked_as_estimated_from_confirmation(self):
        legacy = {"status": "active", "blocker": "External dependency"}
        target = dict(legacy)
        event = management.reconcile_project_blocker_lifecycle(
            legacy, target, "2026-08-10T09:00:00"
        )
        self.assertEqual(event["action"], "confirmed")
        self.assertTrue(target["blockedAtEstimated"])
        self.assertEqual(target["blockedAt"], "2026-08-10T09:00:00")

    def test_blocker_duration_label_uses_hours_then_days(self):
        project = {"blocker": "Dependency unavailable", "blockedAt": "2026-08-10T09:00:00"}
        self.assertEqual(
            management.project_blocker_duration_label(project, datetime(2026, 8, 10, 9, 30)),
            "不足 1 小时",
        )
        self.assertEqual(
            management.project_blocker_duration_label(project, datetime(2026, 8, 10, 14, 0)),
            "5 小时",
        )
        self.assertEqual(
            management.project_blocker_duration_label(project, datetime(2026, 8, 12, 10, 0)),
            "2 天",
        )

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

    def test_overdue_plans_are_detected_without_moving_or_guessing(self):
        tasks = [
            {"id": "overdue", "date": "2026-08-08", "status": "planned"},
            {"id": "today", "date": "2026-08-10", "status": "planned"},
            {"id": "future", "date": "2026-08-11", "status": "planned"},
            {"id": "doing", "date": "2026-08-08", "status": "doing"},
            {"id": "done", "date": "2026-08-08", "status": "done"},
            {"id": "archived", "date": "2026-08-08", "status": "planned", "archivedAt": "2026-08-09T10:00:00"},
            {"id": "history", "date": "2026-08-08", "status": "planned", "carriedToTaskId": "today"},
            {"id": "invalid", "date": "not-a-date", "status": "planned"},
        ]

        result = management.overdue_planned_tasks(tasks, "2026-08-10")

        self.assertEqual([task["id"] for task in result], ["overdue"])
        self.assertEqual(tasks[0]["date"], "2026-08-08")

    def test_reschedule_preserves_source_and_target_board_order_and_audit(self):
        tasks = [
            {"id": "old-first", "date": "2026-08-08", "status": "planned", "boardOrder": 0},
            {"id": "move", "date": "2026-08-08", "status": "planned", "boardOrder": 1},
            {"id": "today-first", "date": "2026-08-10", "status": "planned", "boardOrder": 0},
        ]

        result = management.reschedule_task_date(
            tasks, "move", "2026-08-10", "2026-08-10T09:00:00", "planning_review"
        )

        self.assertTrue(result["changed"])
        self.assertEqual([task["id"] for task in management.ordered_board_tasks(tasks, "2026-08-08", "planned")], ["old-first"])
        self.assertEqual([task["id"] for task in management.ordered_board_tasks(tasks, "2026-08-10", "planned")], ["today-first", "move"])
        moved = tasks[1]
        self.assertEqual(moved["date"], "2026-08-10")
        self.assertEqual(moved["status"], "planned")
        self.assertNotIn("statusHistory", moved)
        self.assertEqual(moved["scheduleHistory"], [{
            "at": "2026-08-10T09:00:00", "from": "2026-08-08", "to": "2026-08-10", "source": "planning_review",
        }])

        undo = management.reschedule_task_date(
            tasks, "move", "2026-08-08", "2026-08-10T09:01:00", "undo"
        )

        self.assertTrue(undo["changed"])
        self.assertEqual([task["id"] for task in management.ordered_board_tasks(tasks, "2026-08-08", "planned")], ["old-first", "move"])
        self.assertEqual([task["id"] for task in management.ordered_board_tasks(tasks, "2026-08-10", "planned")], ["today-first"])
        self.assertEqual(moved["scheduleHistory"][-1]["source"], "undo")
        self.assertEqual(management.TASK_SCHEDULE_SOURCES["undo"], "撤销改期")

    def test_reschedule_rejects_noop_nonplanned_and_invalid_dates(self):
        planned = {"id": "planned", "date": "2026-08-08", "status": "planned"}
        doing = {"id": "doing", "date": "2026-08-08", "status": "doing"}
        tasks = [planned, doing]

        self.assertFalse(management.reschedule_task_date(tasks, "planned", "2026-08-08", "now")["changed"])
        self.assertFalse(management.reschedule_task_date(tasks, "doing", "2026-08-10", "now")["changed"])
        self.assertFalse(management.reschedule_task_date(tasks, "planned", "invalid", "now")["changed"])
        self.assertNotIn("scheduleHistory", planned)

    def test_schedule_events_are_separate_from_status_transitions(self):
        task = {"id": "task", "date": "2026-08-10", "status": "planned"}

        self.assertTrue(management.record_task_schedule_event(task, "2026-08-08", "2026-08-10", "2026-08-10T09:00:00", "editor"))

        self.assertEqual(management.task_status_events([task])[0]["source"], "legacy")
        self.assertEqual(management.task_schedule_events([task])[0]["source"], "editor")

    def test_missing_completion_evidence_only_includes_current_unverified_work(self):
        tasks = [
            {"id": "recent", "title": "Recent", "date": "2026-08-10", "status": "done", "updatedAt": "2026-08-10T11:00:00"},
            {"id": "older", "title": "Older", "date": "2026-08-08", "status": "done", "updatedAt": "2026-08-08T11:00:00"},
            {"id": "verified", "date": "2026-08-10", "status": "done", "completionNote": "Passed all checks."},
            {"id": "doing", "date": "2026-08-10", "status": "doing"},
            {"id": "archived", "date": "2026-08-10", "status": "done", "archivedAt": "2026-08-10T12:00:00"},
            {"id": "snapshot", "date": "2026-08-09", "status": "done", "carriedToTaskId": "current"},
        ]

        result = management.tasks_missing_completion_outcomes(tasks)

        self.assertEqual([task["id"] for task in result], ["recent", "older"])

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
        task = {
            "origin": "project_next_step", "projectNextStep": "Validate release", "status": "done",
            "completionNote": "Release passed 12 regression checks.",
            "completionRecordedAt": "2026-08-10T09:55:00",
        }
        completed = management.project_next_step_completion_update(
            {"nextStep": "Validate release"}, task, "2026-08-10T10:00:00"
        )
        self.assertEqual(completed["lastCompletedOutcome"], "Release passed 12 regression checks.")
        self.assertEqual(completed["lastCompletedOutcomeAt"], "2026-08-10T09:55:00")
        project = {"status": "active", **completed}
        reopened = management.project_next_step_reopen_update(project, task)
        self.assertEqual(reopened["nextStep"], "Validate release")
        self.assertEqual(reopened["lastCompletedOutcome"], "")
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

    def test_every_active_project_requires_a_truthful_baseline_review(self):
        attention = {"status": "active", "priority": "normal", "health": "attention"}
        healthy = {"status": "active", "priority": "normal", "health": "on_track"}
        paused = {"status": "paused", "priority": "normal", "health": "on_track"}
        self.assertEqual(management.project_review_status(attention), (True, None, 7))
        self.assertEqual(management.project_review_status(healthy), (True, None, 7))
        self.assertEqual(management.project_review_status(paused), (False, None, 7))
        self.assertEqual(management.project_review_phase(attention), "baseline")
        self.assertEqual(management.project_review_phase(healthy), "baseline")
        self.assertEqual(management.project_review_phase(paused), "inactive")

    def test_review_cadence_tracks_management_priority(self):
        now = datetime(2026, 8, 10, 12, 0, 0)
        focus = {"status": "active", "priority": "focus", "health": "on_track", "reviewedAt": "2026-08-06T12:00:00"}
        normal = {"status": "active", "priority": "normal", "health": "on_track", "reviewedAt": "2026-08-06T12:00:00"}
        self.assertEqual(management.project_review_status(focus, now), (True, 4, 3))
        self.assertEqual(management.project_review_status(normal, now), (False, 4, 7))
        self.assertEqual(management.project_review_phase(focus, now), "overdue")
        self.assertEqual(management.project_review_phase(normal, now), "current")

    def test_review_overdue_days_excludes_baselines_and_measures_only_cadence_debt(self):
        now = datetime(2026, 8, 10, 12, 0, 0)
        baseline = {"status": "active", "priority": "normal"}
        current = {"status": "active", "priority": "normal", "reviewedAt": "2026-08-05T12:00:00"}
        due_today = {"status": "active", "priority": "normal", "reviewedAt": "2026-08-03T12:00:00"}
        overdue = {"status": "active", "priority": "normal", "reviewedAt": "2026-07-30T12:00:00"}
        paused = {"status": "paused", "priority": "normal", "reviewedAt": "2026-07-01T12:00:00"}

        self.assertIsNone(management.project_review_overdue_days(baseline, now))
        self.assertIsNone(management.project_review_overdue_days(current, now))
        self.assertEqual(management.project_review_overdue_days(due_today, now), 0)
        self.assertEqual(management.project_review_overdue_days(overdue, now), 4)
        self.assertIsNone(management.project_review_overdue_days(paused, now))

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

        batched = management.build_project_review_entry(
            project,
            "2026-08-10T12:00:00",
            "review-2",
            batch_id="batch-1",
            previous_review={"reviewedAt": "", "reviewBaseline": None},
        )
        self.assertEqual(batched["batchId"], "batch-1")
        self.assertEqual(batched["previousReview"]["reviewedAt"], "")
        undone = management.build_project_review_entry(
            project,
            "2026-08-10T12:05:00",
            "review-undo-1",
            action="undo",
        )
        undone["source"] = "review_undo"
        self.assertEqual(management.PROJECT_DECISION_SOURCES["review_undo"], "撤销复核")
        self.assertIn("撤销本次复核", management.format_project_decision_summary(undone))

    def test_review_baseline_reports_only_real_decision_drift_and_can_be_refreshed(self):
        project = {
            "status": "active", "objective": "Ship release", "successCriteria": "Pass 18 checks",
            "stage": "validation", "health": "on_track", "nextStep": "Run checks", "blocker": "",
        }
        baseline = management.establish_project_review_baseline(project, "2026-08-01T09:00:00")
        self.assertEqual(baseline["successCriteria"], "Pass 18 checks")
        self.assertEqual(management.project_review_drift(project), [])

        project.update({"successCriteria": "Pass 20 checks", "health": "attention", "nextStep": "Fix failures"})
        drift = management.project_review_drift(project)
        self.assertEqual([change["field"] for change in drift], ["successCriteria", "health", "nextStep"])
        self.assertEqual(drift[0]["label"], "验收标准")

        management.establish_project_review_baseline(project, "2026-08-10T12:00:00")
        self.assertEqual(management.project_review_drift(project), [])
        self.assertEqual(project["reviewBaseline"]["at"], "2026-08-10T12:00:00")

        legacy = {**project, "reviewedAt": "2026-07-01T09:00:00"}
        legacy.pop("reviewBaseline")
        self.assertEqual(management.project_review_drift(legacy), [])

    def test_execution_alignment_only_surfaces_unreviewed_real_divergence(self):
        project = {
            "id": "runtime-id", "savedId": "stable-id", "name": "Release",
            "status": "active", "priority": "normal", "nextStep": "Run verification",
        }
        matching = {"id": "task-1", "projectId": "stable-id", "date": "2026-08-10", "status": "doing", "title": " Run   verification "}
        self.assertIsNone(management.project_execution_alignment(project, [matching], "2026-08-10"))

        live = {**matching, "title": "Investigate failed benchmark"}
        alignment = management.project_execution_alignment(project, [live], "2026-08-10")
        self.assertFalse(alignment["acknowledged"])
        self.assertEqual(alignment["tasks"], [live])
        self.assertEqual(len(management.portfolio_execution_alignment_queue([project], [live], "2026-08-10")), 1)

        project["executionAlignmentSignature"] = alignment["signature"]
        self.assertEqual(management.portfolio_execution_alignment_queue([project], [live], "2026-08-10"), [])
        changed_live = {**live, "title": "Validate corrected benchmark"}
        self.assertEqual(len(management.portfolio_execution_alignment_queue([project], [changed_live], "2026-08-10")), 1)
        self.assertIsNone(management.project_execution_alignment(project, [{**live, "archivedAt": "2026-08-10T12:00:00"}], "2026-08-10"))

    def test_execution_alignment_confirmation_has_a_truthful_audit_summary(self):
        project = {"id": "runtime", "savedId": "stable", "name": "Release", "nextStep": "Run verification"}
        tasks = [{"title": "Investigate failed benchmark"}, {"title": "Update fixtures"}]
        entry = management.build_project_alignment_entry(project, tasks, "2026-08-10T12:00:00", "alignment-1")
        self.assertEqual((entry["kind"], entry["source"], entry["projectId"]), ("alignment", "alignment", "stable"))
        summary = management.format_project_decision_summary(entry)
        self.assertIn("保留下一步", summary)
        self.assertIn("Investigate failed benchmark", summary)

    def test_project_archive_and_restore_are_lifecycle_audit_events(self):
        project = {"id": "runtime", "savedId": "stable", "name": "Release", "category": "Operations", "status": "active", "stage": "validation", "nextStep": "Verify package"}
        archived = management.build_project_lifecycle_entry(project, "archive", "2026-08-10T12:00:00", "archive-1")
        restored = management.build_project_lifecycle_entry(project, "restore", "2026-08-10T13:00:00", "restore-1")
        self.assertEqual((archived["kind"], archived["source"], archived["projectId"]), ("lifecycle", "archive", "stable"))
        self.assertIn("验证阶段", management.format_project_decision_summary(archived))
        self.assertIn("Verify package", management.format_project_decision_summary(archived))
        self.assertIn("Operations", management.format_project_decision_summary(restored))
        completed = management.build_project_lifecycle_entry(
            {**project, "status": "completed", "stage": "completion", "nextStep": "", "completionSummary": "Passed 18 release checks."},
            "archive", "2026-08-10T14:00:00", "archive-2",
        )
        self.assertIn("成果：Passed 18 release checks.", management.format_project_decision_summary(completed))
        self.assertIsNone(management.build_project_lifecycle_entry(project, "delete", "2026-08-10T14:00:00"))

    def test_decision_diff_ignores_cosmetic_whitespace(self):
        before = {"objective": "Validate   the model", "health": "on_track"}
        after = {"objective": " Validate the model ", "health": "attention"}
        changes = management.project_decision_changes(before, after)
        self.assertEqual([change["field"] for change in changes], ["health"])

    def test_project_rename_is_audited_with_the_new_identity_and_can_be_rolled_back(self):
        project = {"id": "stable", "name": "Old portfolio name"}
        entry = management.build_project_decision_entry(
            project,
            {"name": "Old portfolio name", "health": "on_track"},
            {"name": "New portfolio name", "health": "on_track"},
            "editor",
            "2026-08-10T10:00:00",
            "rename",
        )
        self.assertEqual(entry["projectName"], "New portfolio name")
        self.assertEqual([change["field"] for change in entry["changes"]], ["name"])
        self.assertIn("项目名称：Old portfolio name → New portfolio name", management.format_project_decision_summary(entry))

        requested, affected, conflicts = management.build_project_decision_rollback(
            {"name": "New portfolio name", "health": "on_track"}, entry
        )
        self.assertEqual(requested["name"], "Old portfolio name")
        self.assertEqual([item["field"] for item in affected], ["name"])
        self.assertEqual(conflicts, [])

    def test_partial_decision_patch_does_not_clear_an_omitted_project_name(self):
        changes = management.project_decision_changes(
            {"name": "Stable identity", "health": "on_track"},
            {"health": "attention"},
        )
        self.assertEqual([change["field"] for change in changes], ["health"])

    def test_blocker_decision_history_explains_start_update_and_resolution(self):
        project = {"id": "stable", "name": "Release"}
        started_after = {"blocker": "Waiting for input", "blockedAt": "2026-08-10T09:00:00"}
        started = management.build_project_decision_entry(
            project, {"blocker": ""}, started_after, "editor", "2026-08-10T09:00:00", "start"
        )
        self.assertEqual(started["blockerLifecycle"]["action"], "started")
        self.assertIn("阻塞计时开始", management.format_project_decision_summary(started))

        updated_after = {"blocker": "Waiting for verified input", "blockedAt": "2026-08-10T09:00:00"}
        updated = management.build_project_decision_entry(
            project, started_after, updated_after, "editor", "2026-08-10T11:00:00", "update"
        )
        self.assertEqual(updated["blockerLifecycle"]["duration"], "2 小时")
        self.assertIn("计时未重置", management.format_project_decision_summary(updated))

        resolved_after = {"blocker": "", "lastBlockerResolution": "Verified input was delivered and accepted"}
        resolved = management.build_project_decision_entry(
            project, updated_after, resolved_after, "editor", "2026-08-11T11:00:00", "resolve"
        )
        self.assertEqual(resolved["blockerLifecycle"]["action"], "resolved")
        self.assertEqual(resolved["blockerLifecycle"]["duration"], "1 天")
        self.assertEqual(resolved["blockerLifecycle"]["resolution"], "Verified input was delivered and accepted")
        self.assertIn("阻塞已解除", management.format_project_decision_summary(resolved))
        self.assertIn("Verified input was delivered", management.format_project_decision_summary(resolved))

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
