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
    def test_project_next_step_becomes_a_stably_linked_daily_task(self):
        project = {
            "id": "current-id", "savedId": "stable-id", "category": "Research",
            "nextStep": "Run validation set",
        }
        task = APP.build_project_next_step_task(
            project, "2026-08-10", "2026-08-10T09:00:00", task_id="task-1"
        )
        self.assertEqual(task["projectId"], "stable-id")
        self.assertEqual(task["title"], "Run validation set")
        self.assertEqual(task["origin"], "project_next_step")
        self.assertEqual(task["status"], "planned")

    def test_project_next_step_duplicate_detection_ignores_spacing_and_case(self):
        project = {"id": "current-id", "savedId": "stable-id"}
        tasks = [{
            "projectId": "stable-id", "title": " Run   Validation Set ",
            "date": "2026-08-10", "status": "doing",
        }]
        duplicate = APP.find_open_project_next_step_task(tasks, project, "run validation set", "2026-08-10")
        self.assertIs(duplicate, tasks[0])

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

    def test_portfolio_decision_groups_surface_actions_without_forcing_exclusivity(self):
        active_attention = {
            "name": "Active risk", "status": "active", "health": "attention",
            "activeTaskCount": 1, "nextStep": "Review",
        }
        blocked = {"name": "Blocked", "status": "active", "blocker": "Missing input", "nextStep": "Wait"}
        needs_next = {"name": "Needs next", "status": "active", "nextStep": ""}
        paused = {"name": "Paused", "status": "paused", "nextStep": ""}
        groups = APP.portfolio_decision_groups([active_attention, blocked, needs_next, paused])
        self.assertIn(active_attention, groups["focus"])
        self.assertIn(active_attention, groups["attention"])
        self.assertIn(blocked, groups["attention"])
        self.assertEqual(groups["needs_next"], [needs_next])

    def test_project_insight_requires_an_existing_project_folder(self):
        with patch.object(APP, "find_summary_codex_binary", return_value="codex"):
            result = APP.generate_project_insight({"path": "Z:/definitely-missing-project"})
        self.assertEqual(result["error"], "请先选择有效的项目文件夹")

    def test_control_state_prioritizes_blockers_and_missing_decisions(self):
        blocked = {"status": "active", "health": "on_track", "blocker": "Waiting for calibration", "objective": "Ship", "nextStep": "Test"}
        missing_next = {"status": "active", "health": "on_track", "objective": "Ship", "nextStep": ""}
        healthy = {"status": "active", "health": "on_track", "objective": "Ship", "nextStep": "Test"}
        self.assertEqual(APP.project_control_state(blocked)[0], "blocked")
        self.assertIn("calibration", APP.project_control_state(blocked)[4])
        self.assertEqual(APP.project_control_state(missing_next)[0], "on_track")
        self.assertIn("尚未设置下一步", APP.project_control_state(missing_next)[4])
        self.assertEqual(APP.project_control_state(healthy)[0], "on_track")

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

    def test_management_scope_surfaces_attention_and_blocked_projects(self):
        blocked = {"status": "active", "blocker": "Dependency unavailable", "objective": "Ship", "nextStep": "Wait"}
        attention = {"status": "active", "health": "attention", "objective": "Ship", "nextStep": "Review"}
        healthy = {"status": "active", "health": "on_track", "objective": "Ship", "nextStep": "Test"}
        self.assertTrue(APP.project_management_scope_matches(blocked, "blocked"))
        self.assertTrue(APP.project_management_scope_matches(blocked, "attention"))
        self.assertTrue(APP.project_management_scope_matches(attention, "attention"))
        self.assertFalse(APP.project_management_scope_matches(healthy, "attention"))

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

    def test_payload_resolves_tasks_saved_with_a_stable_project_id(self):
        tasks = [{"date": "2026-08-08", "title": "Validate", "status": "doing", "projectId": "stable-id"}]
        projects = [{"id": "current-id", "savedId": "stable-id", "name": "Denoising", "conversations": []}]
        payload = APP.build_daily_summary_payload(tasks, projects, "2026-08-08")
        self.assertEqual(payload["tasks"][0]["project"], "Denoising")

    def test_prompt_requires_specific_structured_output(self):
        prompt = APP.daily_summary_prompt({"date": "2026-08-08", "tasks": [], "codexActivities": []})
        self.assertIn('"overview"', prompt)
        self.assertIn('"completed"', prompt)
        self.assertIn("不要虚构完成情况", prompt)
        self.assertIn("下一步进化建议", prompt)

    def test_visible_prompt_is_readable_and_has_writeback_marker(self):
        prompt = APP.daily_summary_prompt({"date": "2026-08-08", "tasks": [{}, {}], "codexActivities": [{"userTurns": 3}]}, visible=True)
        self.assertIn("本次覆盖：3 个工作项 · 2 项计划任务 · 1 个 Codex 对话 · 3 次提问", prompt)
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
            {"date": "2026-08-08", "tasks": [{}], "codexActivities": []},
            "summary-thread",
        )
        self.assertEqual(result["overview"], "已完成检查。")
        self.assertEqual(result["nextFocus"], ["项目：增加回归验证"])
        self.assertEqual(result["sourceCounts"]["tasks"], 1)

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
