"""Pure project and task management rules for Codex Project Hub.

This module intentionally has no Qt dependency.  It owns the vocabulary and
state-transition rules that must stay consistent across the dashboard,
editors, automatic Codex updates, and future integrations.
"""

import uuid
from datetime import datetime, timedelta


STATUS_TEXT = {"active": "进行中", "paused": "暂停", "idea": "想法库", "completed": "已完成"}
STATUS_COLOR = {"active": "#16803c", "paused": "#a15c00", "idea": "#7c3aed", "completed": "#2563eb"}
TASK_STATUS = {"planned": "计划", "doing": "进行中", "done": "已完成"}
TASK_COLORS = {"planned": "#7c3aed", "doing": "#2563eb", "done": "#16803c"}
TASK_EVENT_SOURCES = {
    "manual": "手动",
    "selector": "状态选择",
    "drag": "看板拖放",
    "editor": "任务编辑",
    "codex": "Codex 自动",
    "project": "项目下一步",
    "summary": "总结建议",
    "rollover": "自动延续",
    "undo": "撤销操作",
    "legacy": "历史记录",
}
TASK_SCHEDULE_SOURCES = {
    "editor": "任务编辑",
    "planning_review": "计划复核",
    "manual": "手动调整",
    "legacy": "历史记录",
}
PROJECT_PRIORITY = {"focus": "当前重点", "normal": "常规推进", "later": "稍后处理"}
PROJECT_REVIEW_CADENCE_DAYS = {"focus": 3, "normal": 7, "later": 14}
PROJECT_STAGE = {
    "discovery": "探索",
    "planning": "规划",
    "execution": "执行",
    "validation": "验证",
    "delivery": "交付",
    "completion": "收尾",
    "maintenance": "维护",
}
PROJECT_HEALTH = {"on_track": "正常", "attention": "需关注", "blocked": "阻塞"}
PROJECT_DECISION_FIELDS = {
    "name": "项目名称",
    "priority": "管理优先级",
    "status": "项目状态",
    "category": "项目分类",
    "stage": "当前阶段",
    "health": "项目健康度",
    "objective": "项目目标",
    "nextStep": "明确下一步",
    "blocker": "当前阻塞",
}
PROJECT_DECISION_SOURCES = {
    "manual": "手动决策",
    "editor": "项目编辑",
    "codex": "Codex 建议",
    "task_completion": "任务完成",
    "task_reopen": "任务重新打开",
    "undo": "撤销操作",
    "created": "建立项目",
    "category": "分类调整",
    "review": "状态复核",
    "alignment": "执行对齐",
    "archive": "项目归档",
    "restore": "项目恢复",
    "closeout": "项目收尾",
    "focus": "战略重点调整",
    "calibration": "活跃组合校准",
}
PROJECT_REVIEW_BASELINE_SOURCES = {"manual", "editor", "codex", "created"}
PROJECT_GOVERNANCE_FIELD_ORDER = ("objective", "nextStep", "blocker", "stage", "health")
PROJECT_BLOCKER_LIFECYCLE_FIELDS = (
    "blockedAt",
    "blockerUpdatedAt",
    "blockedAtEstimated",
    "lastResolvedBlocker",
    "lastBlockerResolvedAt",
)


def archive_project_layout(layout, project_id):
    """Add a project to the recoverable archive without touching its record."""
    updated = dict(layout or {})
    hidden = [str(value) for value in updated.get("hiddenProjectIds", []) if value]
    project_id = str(project_id or "")
    if not project_id or project_id in hidden:
        updated["hiddenProjectIds"] = hidden
        return updated, False
    hidden.append(project_id)
    updated["hiddenProjectIds"] = hidden
    return updated, True


def restore_project_layout(layout, project_id):
    """Remove a project from the archive while preserving category ordering."""
    updated = dict(layout or {})
    hidden = [str(value) for value in updated.get("hiddenProjectIds", []) if value]
    project_id = str(project_id or "")
    if not project_id or project_id not in hidden:
        updated["hiddenProjectIds"] = hidden
        return updated, False
    updated["hiddenProjectIds"] = [value for value in hidden if value != project_id]
    return updated, True


def task_is_archived(task):
    return bool(str((task or {}).get("archivedAt") or "").strip())


def task_is_superseded_daily_record(task):
    """Return True when a daily snapshot has already continued to a newer record.

    Rollover deliberately leaves the previous day in its original ``doing``
    state so daily history remains truthful.  That snapshot is evidence, not a
    second open work item, once ``carriedToTaskId`` points at its successor.
    """
    return bool(str((task or {}).get("carriedToTaskId") or "").strip())


def current_task_record(tasks, task):
    """Follow a rollover chain to its newest available daily record.

    Corrupt or cyclic links stop at the last trustworthy record instead of
    looping or guessing. The stored chain is never mutated.
    """
    if not isinstance(task, dict):
        return None
    records = {
        str(item.get("id") or ""): item
        for item in (tasks or [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    current = task
    visited = {str(task.get("id") or "")}
    while task_is_superseded_daily_record(current):
        successor_id = str(current.get("carriedToTaskId") or "")
        if not successor_id or successor_id in visited or successor_id not in records:
            break
        visited.add(successor_id)
        current = records[successor_id]
    return current


def active_task_records(tasks):
    return [task for task in (tasks or []) if isinstance(task, dict) and not task_is_archived(task)]


def archived_task_records(tasks):
    archived = [task for task in (tasks or []) if isinstance(task, dict) and task_is_archived(task)]
    return sorted(archived, key=lambda task: str(task.get("archivedAt") or ""), reverse=True)


def archive_task_record(task, occurred_at):
    """Move a task out of active views without deleting its audit history."""
    if not isinstance(task, dict) or task_is_archived(task):
        return False
    task["archivedAt"] = str(occurred_at or "")
    task["archivedFromStatus"] = task.get("status", "planned")
    task["updatedAt"] = str(occurred_at or task.get("updatedAt") or "")
    return True


def restore_task_record(task, occurred_at):
    """Restore an archived task while retaining evidence of the archive cycle."""
    if not isinstance(task, dict) or not task_is_archived(task):
        return False
    archived_at = str(task.pop("archivedAt", "") or "")
    task["lastArchivedAt"] = archived_at
    task["restoredAt"] = str(occurred_at or "")
    task["updatedAt"] = str(occurred_at or task.get("updatedAt") or "")
    task.pop("boardOrder", None)
    return True


def task_completion_outcome(task):
    """Return the current completion evidence only while a task is completed."""
    if not isinstance(task, dict) or task.get("status") != "done":
        return ""
    return str(task.get("completionNote") or "").strip()


def record_task_completion_outcome(task, outcome, occurred_at, source="manual"):
    """Store a completed task's outcome and retain every real outcome revision."""
    if not isinstance(task, dict) or task.get("status") != "done":
        return False
    text = str(outcome or "").strip()
    previous = str(task.get("completionNote") or "").strip()
    if normalized_decision_value(previous) == normalized_decision_value(text):
        return False
    history = task.get("completionHistory")
    if not isinstance(history, list):
        history = []
    history.append({
        "at": str(occurred_at or ""),
        "previous": previous,
        "text": text,
        "source": str(source or "manual"),
    })
    task["completionHistory"] = history[-40:]
    if text:
        task["completionNote"] = text
        task["completionRecordedAt"] = str(occurred_at or "")
    else:
        task.pop("completionNote", None)
        task.pop("completionRecordedAt", None)
    task["updatedAt"] = str(occurred_at or task.get("updatedAt") or "")
    return True


def clear_task_completion_outcome(task, occurred_at, source="reopen"):
    """Retire stale completion evidence when a completed task is reopened."""
    if not isinstance(task, dict):
        return False
    previous = str(task.get("completionNote") or "").strip()
    if not previous and not task.get("completionRecordedAt"):
        return False
    history = task.get("completionHistory")
    if not isinstance(history, list):
        history = []
    history.append({
        "at": str(occurred_at or ""),
        "previous": previous,
        "text": "",
        "source": str(source or "reopen"),
    })
    task["completionHistory"] = history[-40:]
    task.pop("completionNote", None)
    task.pop("completionRecordedAt", None)
    task["updatedAt"] = str(occurred_at or task.get("updatedAt") or "")
    return True


def task_completion_revisions(task):
    """Return outcome revisions newest-first, including a truthful legacy fallback."""
    if not isinstance(task, dict):
        return []
    history = task.get("completionHistory")
    revisions = [dict(item) for item in history or [] if isinstance(item, dict)] if isinstance(history, list) else []
    if not revisions:
        legacy = str(task.get("completionNote") or "").strip()
        if legacy:
            revisions = [{
                "at": str(task.get("completionRecordedAt") or task.get("updatedAt") or ""),
                "previous": "",
                "text": legacy,
                "source": "legacy",
            }]
    return sorted(revisions, key=lambda item: str(item.get("at") or ""), reverse=True)


def project_completion_outcome(project):
    """Return project-level completion evidence only while the project is completed."""
    if not isinstance(project, dict) or project.get("status") != "completed":
        return ""
    return str(project.get("completionSummary") or "").strip()


def record_project_completion_outcome(project, outcome, occurred_at, source="closeout", objective_snapshot=""):
    """Store a project's final outcome while retaining every real revision."""
    if not isinstance(project, dict) or project.get("status") != "completed":
        return False
    text = str(outcome or "").strip()
    if not text:
        return False
    previous = str(project.get("completionSummary") or "").strip()
    objective = normalized_decision_value(objective_snapshot or project.get("objective"))
    previous_objective = normalized_decision_value(project.get("completionObjectiveSnapshot"))
    if (
        normalized_decision_value(previous) == normalized_decision_value(text)
        and previous_objective == objective
    ):
        return False
    history = project.get("completionHistory")
    if not isinstance(history, list):
        history = []
    history.append({
        "at": str(occurred_at or ""),
        "previous": previous,
        "text": text,
        "source": str(source or "closeout"),
        "objective": objective,
        "accepted": bool(objective),
    })
    project["completionHistory"] = history[-40:]
    project["completionSummary"] = text
    if objective:
        project["completionObjectiveSnapshot"] = objective
        project["completionAcceptedAt"] = str(occurred_at or "")
    if not previous or not project.get("completedAt"):
        project["completedAt"] = str(occurred_at or "")
    return True


def clear_project_completion_outcome(project, occurred_at, source="reopen"):
    """Retire current project completion evidence without deleting its history."""
    if not isinstance(project, dict):
        return False
    previous = str(project.get("completionSummary") or "").strip()
    completed_at = str(project.get("completedAt") or "")
    if not previous and not completed_at:
        return False
    history = project.get("completionHistory")
    if not isinstance(history, list):
        history = []
    history.append({
        "at": str(occurred_at or ""),
        "previous": previous,
        "text": "",
        "source": str(source or "reopen"),
        "completedAt": completed_at,
        "objective": normalized_decision_value(project.get("completionObjectiveSnapshot")),
        "acceptedAt": str(project.get("completionAcceptedAt") or ""),
    })
    project["completionHistory"] = history[-40:]
    project.pop("completionSummary", None)
    project.pop("completedAt", None)
    project.pop("completionObjectiveSnapshot", None)
    project.pop("completionAcceptedAt", None)
    return True


def project_completion_revisions(project):
    """Return project outcome revisions newest-first with a legacy fallback."""
    if not isinstance(project, dict):
        return []
    history = project.get("completionHistory")
    revisions = [dict(item) for item in history or [] if isinstance(item, dict)] if isinstance(history, list) else []
    if not revisions:
        legacy = str(project.get("completionSummary") or "").strip()
        if legacy:
            revisions = [{
                "at": str(project.get("completedAt") or project.get("reviewedAt") or ""),
                "previous": "",
                "text": legacy,
                "source": "legacy",
            }]
    return sorted(revisions, key=lambda item: str(item.get("at") or ""), reverse=True)


def latest_project_completion_outcome(project):
    """Find the last non-empty closeout result, including after a reopen."""
    current = str((project or {}).get("completionSummary") or "").strip()
    if current:
        return current
    for revision in project_completion_revisions(project):
        text = str(revision.get("text") or "").strip()
        if text:
            return text
    return ""


def record_task_status_event(task, previous_status, status, occurred_at, source="manual"):
    """Append one real task status transition, avoiding no-op events."""
    if not isinstance(task, dict) or status not in TASK_STATUS:
        return False
    previous = previous_status if previous_status in TASK_STATUS else ""
    if previous == status:
        return False
    history = task.get("statusHistory")
    if not isinstance(history, list):
        history = []
    history.append({
        "at": str(occurred_at or ""),
        "from": previous,
        "to": status,
        "source": source if source in TASK_EVENT_SOURCES else "manual",
    })
    task["statusHistory"] = history[-80:]
    return True


def task_status_events(tasks):
    """Flatten stored task histories into a newest-first activity stream."""
    events = []
    for task in tasks or []:
        history = task.get("statusHistory") if isinstance(task.get("statusHistory"), list) else []
        if not history:
            fallback_source = (
                "codex" if task.get("autoStartedAt") else
                "rollover" if task.get("carriedFromTaskId") else
                "project" if task.get("origin") == "project_next_step" else
                "legacy"
            )
            history = [{
                "at": task.get("updatedAt") or task.get("createdAt") or "",
                "from": "",
                "to": task.get("status", "planned"),
                "source": fallback_source,
            }]
        for event in history:
            if event.get("to") not in TASK_STATUS:
                continue
            events.append({**event, "task": task})
    return sorted(events, key=lambda event: str(event.get("at") or ""), reverse=True)


def record_task_schedule_event(task, previous_date, target_date, occurred_at, source="manual"):
    """Record one real task-date change without inventing a status transition."""

    if not isinstance(task, dict):
        return False
    previous = str(previous_date or "").strip()
    target = str(target_date or "").strip()
    try:
        datetime.strptime(previous, "%Y-%m-%d")
        datetime.strptime(target, "%Y-%m-%d")
    except ValueError:
        return False
    if previous == target:
        return False
    history = task.get("scheduleHistory")
    if not isinstance(history, list):
        history = []
    history.append({
        "at": str(occurred_at or ""),
        "from": previous,
        "to": target,
        "source": source if source in TASK_SCHEDULE_SOURCES else "manual",
    })
    task["scheduleHistory"] = history[-80:]
    return True


def task_schedule_events(tasks):
    """Flatten explicit task-date changes into a newest-first audit stream."""

    events = []
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        history = task.get("scheduleHistory") if isinstance(task.get("scheduleHistory"), list) else []
        for event in history:
            if not isinstance(event, dict) or not event.get("from") or not event.get("to"):
                continue
            events.append({**event, "task": task})
    return sorted(events, key=lambda event: str(event.get("at") or ""), reverse=True)


def task_board_sort_key(task):
    """Keep deliberate board order ahead of the stable creation-time fallback."""
    value = (task or {}).get("boardOrder")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return 0, float(value), str((task or {}).get("createdAt") or ""), str((task or {}).get("id") or "")
    return 1, 0.0, str((task or {}).get("createdAt") or ""), str((task or {}).get("id") or "")


def ordered_board_tasks(tasks, target_date=None, status=None):
    selected = [
        task for task in (tasks or [])
        if not task_is_archived(task)
        and (target_date is None or str(task.get("date") or "") == str(target_date))
        and (status is None or task.get("status", "planned") == status)
    ]
    return sorted(selected, key=task_board_sort_key)


def reorder_task_board(tasks, task_id, target_status, target_index=None):
    """Move one task across or within Kanban columns and normalize both orders."""
    if target_status not in TASK_STATUS:
        return {"changed": False}
    task = next((item for item in (tasks or []) if str(item.get("id") or "") == str(task_id or "")), None)
    if task is None or task_is_archived(task) or task_is_superseded_daily_record(task):
        return {"changed": False}
    task_date = str(task.get("date") or "")
    previous_status = task.get("status", "planned")
    source = ordered_board_tasks(tasks, task_date, previous_status)
    source_ids = [str(item.get("id") or "") for item in source]
    try:
        previous_index = source_ids.index(str(task_id))
    except ValueError:
        previous_index = 0
    target_without_task = [
        item for item in ordered_board_tasks(tasks, task_date, target_status)
        if str(item.get("id") or "") != str(task_id)
    ]
    if target_index is None:
        target_index = len(target_without_task)
    try:
        target_index = int(target_index)
    except (TypeError, ValueError):
        target_index = len(target_without_task)
    target_index = max(0, min(target_index, len(target_without_task)))
    target_order = list(target_without_task)
    target_order.insert(target_index, task)
    new_target_ids = [str(item.get("id") or "") for item in target_order]
    changed = previous_status != target_status or new_target_ids != source_ids
    if not changed:
        return {
            "changed": False,
            "previousStatus": previous_status,
            "previousIndex": previous_index,
            "targetIndex": target_index,
        }
    if previous_status != target_status:
        source_remaining = [item for item in source if str(item.get("id") or "") != str(task_id)]
        for index, item in enumerate(source_remaining):
            item["boardOrder"] = index
    task["status"] = target_status
    for index, item in enumerate(target_order):
        item["boardOrder"] = index
    return {
        "changed": True,
        "previousStatus": previous_status,
        "previousIndex": previous_index,
        "targetStatus": target_status,
        "targetIndex": target_index,
    }


def overdue_planned_tasks(tasks, today=None):
    """Return unstarted plans from earlier valid dates without moving them."""

    target = str(today or datetime.now().date().isoformat())
    try:
        target_date = datetime.strptime(target, "%Y-%m-%d").date()
    except ValueError:
        return []
    overdue = []
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        if task_is_archived(task) or task_is_superseded_daily_record(task):
            continue
        if task.get("status", "planned") != "planned":
            continue
        try:
            task_date = datetime.strptime(str(task.get("date") or ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if task_date < target_date:
            overdue.append(task)
    return sorted(overdue, key=lambda task: (str(task.get("date") or ""), task_board_sort_key(task)))


def reschedule_task_date(tasks, task_id, target_date, occurred_at, source="planning_review"):
    """Move one planned task to a new date and preserve both board orders and audit."""

    target = str(target_date or "").strip()
    try:
        datetime.strptime(target, "%Y-%m-%d")
    except ValueError:
        return {"changed": False}
    task = next((item for item in (tasks or []) if str(item.get("id") or "") == str(task_id or "")), None)
    if (
        task is None
        or task_is_archived(task)
        or task_is_superseded_daily_record(task)
        or task.get("status", "planned") != "planned"
    ):
        return {"changed": False}
    previous = str(task.get("date") or "")
    if previous == target or not record_task_schedule_event(task, previous, target, occurred_at, source):
        return {"changed": False}

    source_board = [item for item in ordered_board_tasks(tasks, previous, "planned") if item is not task]
    target_board = [item for item in ordered_board_tasks(tasks, target, "planned") if item is not task]
    for index, item in enumerate(source_board):
        item["boardOrder"] = index
    task["date"] = target
    task["updatedAt"] = str(occurred_at or task.get("updatedAt") or "")
    target_board.append(task)
    for index, item in enumerate(target_board):
        item["boardOrder"] = index
    return {
        "changed": True,
        "previousDate": previous,
        "targetDate": target,
        "targetIndex": len(target_board) - 1,
    }


def rollover_in_progress_tasks(tasks, today=None):
    """Preserve each day's record and carry unfinished active work forward."""
    today = today or datetime.now().date().isoformat()
    result = [dict(task) for task in tasks]
    changed = False
    while True:
        source = next(
            (
                task for task in result
                if task.get("status") == "doing"
                and not task_is_archived(task)
                and str(task.get("date") or "") < today
                and not task.get("carriedToTaskId")
            ),
            None,
        )
        if source is None:
            break
        try:
            next_date = (datetime.strptime(source["date"], "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
        except (KeyError, TypeError, ValueError):
            source["date"] = today
            changed = True
            continue
        now = datetime.now().isoformat(timespec="seconds")
        carried = dict(source)
        carried["id"] = str(uuid.uuid4())
        carried["date"] = next_date
        carried["createdAt"] = now
        carried["updatedAt"] = now
        carried["statusHistory"] = []
        record_task_status_event(carried, None, "doing", now, "rollover")
        carried["carriedFromTaskId"] = source.get("id")
        carried["carriedFromDate"] = source.get("date")
        carried.pop("carriedToTaskId", None)
        carried.pop("carriedToDate", None)
        carried.pop("autoStartedAt", None)
        carried.pop("boardOrder", None)
        source["carriedToTaskId"] = carried["id"]
        source["carriedToDate"] = next_date
        source["carriedAt"] = now
        source["updatedAt"] = now
        result.append(carried)
        changed = True
    return result, changed


def normalized_decision_value(value):
    return " ".join(str(value or "").split())


def reconcile_project_blocker_lifecycle(current, project, occurred_at):
    """Mutate derived blocker timing metadata without resetting continuous age.

    The blocker text remains the human decision. Timing fields are derived from
    that decision so callers cannot accidentally create a blocked project with
    no reason or silently lose the start of an ongoing block.
    """
    if not isinstance(project, dict):
        return None
    current = current or {}
    previous = normalized_decision_value(current.get("blocker"))
    blocker = normalized_decision_value(project.get("blocker"))
    at = str(occurred_at or "")
    for field in ("lastResolvedBlocker", "lastBlockerResolvedAt"):
        if field in current and field not in project:
            project[field] = current.get(field)
    if blocker:
        project["blocker"] = blocker
        if previous:
            started_at = str(current.get("blockedAt") or "")
            project["blockedAt"] = started_at or at
            if started_at:
                if current.get("blockedAtEstimated"):
                    project["blockedAtEstimated"] = True
                else:
                    project.pop("blockedAtEstimated", None)
            else:
                project["blockedAtEstimated"] = True
            if normalized_decision_value(previous) != normalized_decision_value(blocker):
                project["blockerUpdatedAt"] = at
                return {"action": "updated", "previous": previous, "blocker": blocker, "at": at}
            if current.get("blockerUpdatedAt"):
                project["blockerUpdatedAt"] = current.get("blockerUpdatedAt")
            elif not started_at:
                project["blockerUpdatedAt"] = at
                return {"action": "confirmed", "previous": previous, "blocker": blocker, "at": at}
            return None
        project["blockedAt"] = at
        project["blockerUpdatedAt"] = at
        project.pop("blockedAtEstimated", None)
        return {"action": "started", "previous": "", "blocker": blocker, "at": at}
    project["blocker"] = ""
    for field in ("blockedAt", "blockerUpdatedAt", "blockedAtEstimated"):
        project.pop(field, None)
    if previous:
        project["lastResolvedBlocker"] = previous
        project["lastBlockerResolvedAt"] = at
        return {"action": "resolved", "previous": previous, "blocker": "", "at": at}
    return None


def project_blocker_age_seconds(project, now=None):
    """Return elapsed blocker age, or None when active blocker timing is unknown."""
    project = project or {}
    if not normalized_decision_value(project.get("blocker")):
        return None
    blocked_at = normalized_decision_value(project.get("blockedAt"))
    if not blocked_at:
        return None
    try:
        started = datetime.fromisoformat(blocked_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    current = now or datetime.now(tz=started.tzinfo)
    if isinstance(current, str):
        try:
            current = datetime.fromisoformat(current.replace("Z", "+00:00"))
        except ValueError:
            return None
    if started.tzinfo is not None and current.tzinfo is None:
        current = current.replace(tzinfo=started.tzinfo)
    elif started.tzinfo is None and current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return max(0, int((current - started).total_seconds()))


def project_blocker_duration_label(project, now=None):
    """Format blocker age for compact portfolio and workbench surfaces."""
    seconds = project_blocker_age_seconds(project, now)
    if seconds is None:
        return "时长未知"
    if seconds < 3600:
        return "不足 1 小时"
    if seconds < 86400:
        return f"{max(1, seconds // 3600)} 小时"
    return f"{max(1, seconds // 86400)} 天"


def project_governance_gaps(project):
    """Return only project-control fields that genuinely need a decision.

    Defaults that are already stored remain deliberate user decisions.  Active
    projects need a concrete next action; paused, idea, and completed projects
    do not.  A next action awaiting review is intentionally treated as missing
    so Codex can propose the successor without overwriting unrelated fields.
    """
    project = project or {}
    gaps = []
    if not normalized_decision_value(project.get("objective")):
        gaps.append("objective")
    if project.get("status", "active") == "active" and (
        not normalized_decision_value(project.get("nextStep"))
        or bool(project.get("nextStepReviewNeeded"))
    ):
        gaps.append("nextStep")
    if project.get("health") == "blocked" and not normalized_decision_value(project.get("blocker")):
        gaps.append("blocker")
    if project.get("stage") not in PROJECT_STAGE:
        gaps.append("stage")
    if project.get("health") not in PROJECT_HEALTH:
        gaps.append("health")
    return gaps


def project_change_establishes_review(project, source, has_changes=True):
    """Return True only when a complete project review can be claimed.

    Full editor/manual saves, reviewed Codex governance, and complete project
    creation may establish a baseline. Narrow portfolio actions such as focus,
    calibration, alignment, category moves, or undo remain audited decisions
    without pretending every governance field was reviewed.
    """
    return bool(
        has_changes
        and source in PROJECT_REVIEW_BASELINE_SOURCES
        and not project_governance_gaps(project)
    )


def merge_missing_project_insight(project, insight, allowed_fields=None):
    """Apply a Codex insight strictly to still-missing governance fields.

    The merge is deliberately conservative: a suggestion can fill a gap but
    never replace a non-empty human decision.  Callers can safely re-run this
    after a long background analysis because gaps are recalculated against the
    latest project state at apply time.
    """
    current = dict(project or {})
    suggestion = insight or {}
    gaps = project_governance_gaps(current)
    if allowed_fields is not None:
        allowed = {str(field) for field in allowed_fields}
        gaps = [field for field in gaps if field in allowed]
    applied = []
    for field in PROJECT_GOVERNANCE_FIELD_ORDER:
        if field not in gaps:
            continue
        value = suggestion.get(field)
        if field == "stage":
            if value not in PROJECT_STAGE:
                continue
        elif field == "health":
            if value not in PROJECT_HEALTH:
                continue
        else:
            value = normalized_decision_value(value)
            if not value:
                continue
        current[field] = value
        if field == "nextStep":
            current["nextStepReviewNeeded"] = False
        applied.append(field)
    return current, applied


def project_review_status(project, now=None):
    """Return (is_due, age_days, cadence_days) for a deliberate project review.

    Every active project needs one deliberate baseline review before a cadence
    can be truthful. Unreviewed projects enter a neutral review queue rather
    than masquerading as current risk. Once reviewed, cadence is derived from
    management priority and continues automatically.
    """
    project = project or {}
    priority = project.get("priority") if project.get("priority") in PROJECT_REVIEW_CADENCE_DAYS else "normal"
    cadence = PROJECT_REVIEW_CADENCE_DAYS[priority]
    if project.get("status", "active") != "active":
        return False, None, cadence
    reviewed_at = normalized_decision_value(project.get("reviewedAt"))
    if not reviewed_at:
        return True, None, cadence
    try:
        reviewed = datetime.fromisoformat(reviewed_at)
    except ValueError:
        return True, None, cadence
    current = now or datetime.now(tz=reviewed.tzinfo)
    if reviewed.tzinfo is not None and current.tzinfo is None:
        current = current.replace(tzinfo=reviewed.tzinfo)
    elif reviewed.tzinfo is None and current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    age_days = max(0, int((current - reviewed).total_seconds() // 86400))
    return age_days >= cadence, age_days, cadence


def display_project_decision_value(field, value):
    normalized = normalized_decision_value(value)
    if field == "priority":
        return PROJECT_PRIORITY.get(normalized, normalized or "未设置")
    if field == "status":
        return STATUS_TEXT.get(normalized, normalized or "未设置")
    if field == "stage":
        return PROJECT_STAGE.get(normalized, normalized or "未设置")
    if field == "health":
        return PROJECT_HEALTH.get(normalized, normalized or "未设置")
    if normalized:
        return normalized
    return "无" if field == "blocker" else "未设置"


def project_decision_changes(before, after):
    changes = []
    before = before or {}
    after = after or {}
    for field, label in PROJECT_DECISION_FIELDS.items():
        old_value = normalized_decision_value(before.get(field))
        # Decision callers may provide a full snapshot or a partial patch. An
        # omitted field means "unchanged"; an explicit empty value still means
        # "clear it". This is especially important for project identity.
        new_value = normalized_decision_value(after.get(field, before.get(field)))
        if old_value != new_value:
            changes.append({"field": field, "label": label, "before": old_value, "after": new_value})
    return changes


def build_project_decision_rollback(project, entry):
    """Prepare a selective rollback and report fields changed again since then."""
    requested = dict(project or {})
    affected = []
    conflicts = []
    for change in (entry or {}).get("changes") or []:
        field = change.get("field")
        if field not in PROJECT_DECISION_FIELDS:
            continue
        current_value = normalized_decision_value((project or {}).get(field))
        before_value = normalized_decision_value(change.get("before"))
        after_value = normalized_decision_value(change.get("after"))
        requested[field] = before_value
        if current_value == before_value:
            continue
        detail = {
            "field": field,
            "label": change.get("label") or PROJECT_DECISION_FIELDS[field],
            "current": current_value,
            "target": before_value,
        }
        affected.append(detail)
        if current_value != after_value:
            conflicts.append(detail)
    return requested, affected, conflicts


def build_project_decision_entry(project, before, after, source, occurred_at, entry_id=None):
    changes = project_decision_changes(before, after)
    if not changes:
        return None
    stable_project_id = (project or {}).get("savedId") or (project or {}).get("codexProjectId") or (project or {}).get("id")
    entry = {
        "id": entry_id or str(uuid.uuid4()),
        "projectId": stable_project_id,
        "projectName": str((after or {}).get("name") or (project or {}).get("name") or "未命名项目"),
        "at": occurred_at,
        "source": source if source in PROJECT_DECISION_SOURCES else "manual",
        "changes": changes,
    }
    blocker_change = next((change for change in changes if change.get("field") == "blocker"), None)
    if blocker_change:
        previous = normalized_decision_value(blocker_change.get("before"))
        blocker = normalized_decision_value(blocker_change.get("after"))
        if blocker and not previous:
            action, duration = "started", "不足 1 小时"
        elif blocker:
            action, duration = "updated", project_blocker_duration_label(after, occurred_at)
        else:
            action, duration = "resolved", project_blocker_duration_label(before, occurred_at)
        entry["blockerLifecycle"] = {
            "action": action,
            "blockedAt": str((after or {}).get("blockedAt") or (before or {}).get("blockedAt") or ""),
            "duration": duration,
        }
    return entry


def build_project_review_entry(project, occurred_at, entry_id=None):
    """Record an explicit review even when no project field changed."""
    stable_project_id = (project or {}).get("savedId") or (project or {}).get("codexProjectId") or (project or {}).get("id")
    if not stable_project_id:
        return None
    return {
        "id": entry_id or str(uuid.uuid4()),
        "projectId": stable_project_id,
        "projectName": str((project or {}).get("name") or "未命名项目"),
        "at": str(occurred_at or ""),
        "source": "review",
        "kind": "review",
        "changes": [],
        "snapshot": {
            "stage": (project or {}).get("stage"),
            "health": (project or {}).get("health"),
            "nextStep": normalized_decision_value((project or {}).get("nextStep")),
            "blocker": normalized_decision_value((project or {}).get("blocker")),
        },
    }


def build_project_alignment_entry(project, tasks, occurred_at, entry_id=None):
    """Audit a deliberate choice to keep the declared next step despite live work."""
    stable_project_id = (project or {}).get("savedId") or (project or {}).get("codexProjectId") or (project or {}).get("id")
    if not stable_project_id:
        return None
    task_titles = [normalized_decision_value((task or {}).get("title")) for task in tasks or []]
    task_titles = [title for title in task_titles if title]
    return {
        "id": entry_id or str(uuid.uuid4()),
        "projectId": stable_project_id,
        "projectName": str((project or {}).get("name") or "未命名项目"),
        "at": str(occurred_at or ""),
        "source": "alignment",
        "kind": "alignment",
        "changes": [],
        "snapshot": {
            "nextStep": normalized_decision_value((project or {}).get("nextStep")),
            "activeTasks": task_titles,
            "resolution": "keep",
        },
    }


def build_project_lifecycle_entry(project, action, occurred_at, entry_id=None):
    """Audit a recoverable project archive or restore operation."""
    if action not in {"archive", "restore"}:
        return None
    stable_project_id = (project or {}).get("savedId") or (project or {}).get("codexProjectId") or (project or {}).get("id")
    if not stable_project_id:
        return None
    return {
        "id": entry_id or str(uuid.uuid4()),
        "projectId": stable_project_id,
        "projectName": str((project or {}).get("name") or "未命名项目"),
        "at": str(occurred_at or ""),
        "source": action,
        "kind": "lifecycle",
        "action": action,
        "changes": [],
        "snapshot": {
            "category": normalized_decision_value((project or {}).get("category")),
            "status": normalized_decision_value((project or {}).get("status") or "active"),
            "stage": normalized_decision_value((project or {}).get("stage") or "execution"),
            "health": normalized_decision_value((project or {}).get("health") or "on_track"),
            "objective": normalized_decision_value((project or {}).get("objective")),
            "nextStep": normalized_decision_value((project or {}).get("nextStep")),
            "blocker": normalized_decision_value((project or {}).get("blocker")),
            "blockedAt": str((project or {}).get("blockedAt") or ""),
            "blockerUpdatedAt": str((project or {}).get("blockerUpdatedAt") or ""),
            "blockedAtEstimated": bool((project or {}).get("blockedAtEstimated")),
            "lastResolvedBlocker": normalized_decision_value((project or {}).get("lastResolvedBlocker")),
            "lastBlockerResolvedAt": str((project or {}).get("lastBlockerResolvedAt") or ""),
            "completionSummary": normalized_decision_value((project or {}).get("completionSummary")),
            "completedAt": str((project or {}).get("completedAt") or ""),
            "completionObjectiveSnapshot": normalized_decision_value((project or {}).get("completionObjectiveSnapshot")),
            "completionAcceptedAt": str((project or {}).get("completionAcceptedAt") or ""),
        },
    }


def build_project_closeout_entry(project, action, outcome, occurred_at, entry_id=None):
    """Audit project completion evidence separately from ordinary field changes."""
    if action not in {"complete", "revise", "reopen"}:
        return None
    stable_project_id = (project or {}).get("savedId") or (project or {}).get("codexProjectId") or (project or {}).get("id")
    if not stable_project_id:
        return None
    summary = normalized_decision_value(outcome)
    if action in {"complete", "revise"} and not summary:
        return None
    return {
        "id": entry_id or str(uuid.uuid4()),
        "projectId": stable_project_id,
        "projectName": str((project or {}).get("name") or "未命名项目"),
        "at": str(occurred_at or ""),
        "source": "closeout",
        "kind": "closeout",
        "action": action,
        "changes": [],
        "snapshot": {
            "outcome": summary,
            "completedAt": str((project or {}).get("completedAt") or occurred_at or ""),
            "objective": normalized_decision_value((project or {}).get("completionObjectiveSnapshot")),
            "acceptedAt": str((project or {}).get("completionAcceptedAt") or ""),
        },
    }


def compact_project_decision_value(field, value, limit=36):
    text = display_project_decision_value(field, value)
    return text if len(text) <= limit else text[: max(1, limit - 1)].rstrip() + "…"


def format_project_decision_summary(entry, max_changes=2):
    if (entry or {}).get("kind") == "review":
        snapshot = (entry or {}).get("snapshot") or {}
        stage = display_project_decision_value("stage", snapshot.get("stage"))
        health = display_project_decision_value("health", snapshot.get("health"))
        next_step = compact_project_decision_value("nextStep", snapshot.get("nextStep"), 30)
        return f"确认{stage}阶段 · {health} · 下一步：{next_step}"
    if (entry or {}).get("kind") == "alignment":
        snapshot = (entry or {}).get("snapshot") or {}
        next_step = compact_project_decision_value("nextStep", snapshot.get("nextStep"), 30)
        active = [normalized_decision_value(value) for value in snapshot.get("activeTasks") or []]
        active = [value for value in active if value]
        active_text = "、".join(active[:2]) or "未记录"
        if len(active) > 2:
            active_text += f" 等 {len(active)} 项"
        return f"确认保留下一步：{next_step} · 当前执行：{active_text}"
    if (entry or {}).get("kind") == "lifecycle":
        snapshot = (entry or {}).get("snapshot") or {}
        category = normalized_decision_value(snapshot.get("category")) or "未分类"
        if (entry or {}).get("action") == "restore":
            return f"从归档箱恢复 · 回到“{category}”分类"
        status = display_project_decision_value("status", snapshot.get("status"))
        stage = display_project_decision_value("stage", snapshot.get("stage"))
        blocker = compact_project_decision_value("blocker", snapshot.get("blocker"), 30)
        next_step = compact_project_decision_value("nextStep", snapshot.get("nextStep"), 30)
        completion = compact_project_decision_value("completionSummary", snapshot.get("completionSummary"), 42)
        if normalized_decision_value(snapshot.get("completionSummary")):
            context = f"成果：{completion}"
        else:
            if normalized_decision_value(snapshot.get("blocker")):
                duration = project_blocker_duration_label(snapshot, (entry or {}).get("at"))
                estimate = "（从确认起）" if snapshot.get("blockedAtEstimated") else ""
                context = f"阻塞 {duration}{estimate}：{blocker}"
            else:
                context = f"下一步：{next_step}"
        return f"归档项目 · {status} / {stage}阶段 · {context}"
    if (entry or {}).get("kind") == "closeout":
        snapshot = (entry or {}).get("snapshot") or {}
        outcome = compact_project_decision_value("completionSummary", snapshot.get("outcome"), 64)
        objective = compact_project_decision_value("objective", snapshot.get("objective"), 42)
        action = (entry or {}).get("action")
        if action == "reopen":
            return f"重新打开项目 · 原完成成果保留在历史：{outcome}"
        if action == "revise":
            return f"修订项目完成成果 · 验收目标：{objective} · 成果：{outcome}" if normalized_decision_value(snapshot.get("objective")) else f"修订项目完成成果：{outcome}"
        return f"完成项目 · 验收目标：{objective} · 成果：{outcome}" if normalized_decision_value(snapshot.get("objective")) else f"完成项目 · 最终成果：{outcome}"
    changes = (entry or {}).get("changes") or []
    parts = [
        f"{change.get('label') or PROJECT_DECISION_FIELDS.get(change.get('field'), '项目字段')}："
        f"{compact_project_decision_value(change.get('field'), change.get('before'))} → "
        f"{compact_project_decision_value(change.get('field'), change.get('after'))}"
        for change in changes[:max_changes]
    ]
    if len(changes) > max_changes:
        parts.append(f"另 {len(changes) - max_changes} 项")
    summary = "；".join(parts) if parts else "没有字段变化"
    blocker_lifecycle = (entry or {}).get("blockerLifecycle") or {}
    action = blocker_lifecycle.get("action")
    duration = str(blocker_lifecycle.get("duration") or "时长未知")
    if action == "started":
        summary += " · 阻塞计时开始"
    elif action == "updated":
        summary += f" · 阻塞已持续 {duration}，计时未重置"
    elif action == "resolved":
        summary += f" · 阻塞已解除，持续 {duration}"
    return summary


def format_project_decision_time(value, compact=False):
    try:
        point = datetime.fromisoformat(str(value or ""))
        return point.strftime("%m-%d %H:%M" if compact else "%Y-%m-%d %H:%M")
    except ValueError:
        return str(value or "时间未知")


def normalized_action_text(value):
    return " ".join(str(value or "").split()).casefold()


def project_execution_alignment(project, tasks, target_date):
    """Describe a real divergence between a project's declared and live next action.

    The result is intentionally neutral: a different live task can be valid.  A
    saved signature records that the user deliberately reviewed the exact pair
    of declared direction and live tasks, and becomes stale as soon as either
    side changes.
    """
    project = project or {}
    if project.get("status", "active") != "active":
        return None
    declared = str(project.get("nextStep") or "").strip()
    declared_key = normalized_action_text(declared)
    if not declared_key:
        return None
    references = {
        str(value)
        for value in (project.get("id"), project.get("savedId"), project.get("codexProjectId"))
        if value
    }
    live_tasks = [
        task for task in tasks or []
        if isinstance(task, dict)
        and not task_is_archived(task)
        and str(task.get("date") or "") == str(target_date or "")
        and task.get("status", "planned") == "doing"
        and str(task.get("projectId") or "") in references
    ]
    if not live_tasks or any(normalized_action_text(task.get("title")) == declared_key for task in live_tasks):
        return None
    task_parts = sorted(
        f"{str(task.get('id') or '')}:{normalized_action_text(task.get('title'))}"
        for task in live_tasks
    )
    signature = "|".join([str(target_date or ""), declared_key, *task_parts])
    return {
        "project": project,
        "tasks": live_tasks,
        "declaredNextStep": declared,
        "signature": signature,
        "acknowledged": str(project.get("executionAlignmentSignature") or "") == signature,
    }


def portfolio_execution_alignment_queue(projects, tasks, target_date):
    """Return only unreviewed execution-direction divergences."""
    queue = []
    for project in projects or []:
        alignment = project_execution_alignment(project, tasks, target_date)
        if alignment is not None and not alignment["acknowledged"]:
            queue.append(alignment)
    priority_order = {"focus": 0, "normal": 1, "later": 2}
    return sorted(
        queue,
        key=lambda item: (
            priority_order.get((item.get("project") or {}).get("priority"), 1),
            str((item.get("project") or {}).get("name") or "").casefold(),
        ),
    )


def project_next_step_completion_update(project, task, completed_at):
    if (task or {}).get("origin") != "project_next_step":
        return None
    completed_step = str((task or {}).get("projectNextStep") or (task or {}).get("title") or "").strip()
    if normalized_action_text((project or {}).get("nextStep")) != normalized_action_text(completed_step):
        return None
    update = {
        "lastCompletedNextStep": completed_step,
        "lastCompletedNextStepAt": completed_at,
        "nextStep": "",
        "nextStepReviewNeeded": True,
    }
    outcome = task_completion_outcome(task)
    if outcome:
        update["lastCompletedOutcome"] = outcome
        update["lastCompletedOutcomeAt"] = str((task or {}).get("completionRecordedAt") or completed_at)
    return update


def project_next_step_reopen_update(project, task):
    if (task or {}).get("origin") != "project_next_step":
        return None
    if (project or {}).get("status", "active") != "active":
        return None
    reopened_step = str((task or {}).get("projectNextStep") or (task or {}).get("title") or "").strip()
    if not reopened_step or normalized_decision_value((project or {}).get("nextStep")):
        return None
    if normalized_action_text((project or {}).get("lastCompletedNextStep")) != normalized_action_text(reopened_step):
        return None
    return {
        "nextStep": reopened_step,
        "nextStepReviewNeeded": False,
        "lastCompletedNextStep": "",
        "lastCompletedNextStepAt": "",
        "lastCompletedOutcome": "",
        "lastCompletedOutcomeAt": "",
    }


def normalize_project_management_decision(current, requested):
    """Keep project control fields coherent without overwriting active decisions."""
    current = current or {}
    normalized = dict(requested or {})
    notes = []
    status = normalized.get("status") if normalized.get("status") in STATUS_TEXT else current.get("status", "active")
    normalized["status"] = status
    blocker = normalized_decision_value(normalized.get("blocker"))
    normalized["blocker"] = blocker
    if status == "completed":
        completion_values = {
            "stage": "completion",
            "health": "on_track",
            "blocker": "",
            "nextStep": "",
            "nextStepReviewNeeded": False,
        }
        if any(normalized_decision_value(normalized.get(key)) != normalized_decision_value(value) for key, value in completion_values.items()):
            notes.append("已对齐完成状态：收尾阶段、无阻塞、无待执行下一步")
        normalized.update(completion_values)
    elif blocker and normalized.get("health") != "blocked":
        normalized["health"] = "blocked"
        notes.append("已根据阻塞原因同步项目健康度")
    return normalized, notes


def project_management_validation_error(data):
    data = data or {}
    if data.get("status", "active") != "completed" and data.get("health") == "blocked" and not normalized_decision_value(data.get("blocker")):
        return "项目标记为阻塞时，请写明具体阻塞原因。"
    return ""


def task_status_transition_allowed(task, target_status):
    return bool(
        task
        and not task_is_superseded_daily_record(task)
        and target_status in TASK_STATUS
        and task.get("status", "planned") != target_status
    )
