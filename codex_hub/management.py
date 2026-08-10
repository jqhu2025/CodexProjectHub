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
    "rollover": "自动延续",
    "undo": "撤销操作",
    "legacy": "历史记录",
}
PROJECT_PRIORITY = {"focus": "当前重点", "normal": "常规推进", "later": "稍后处理"}
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
}


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


def task_board_sort_key(task):
    """Keep deliberate board order ahead of the stable creation-time fallback."""
    value = (task or {}).get("boardOrder")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return 0, float(value), str((task or {}).get("createdAt") or ""), str((task or {}).get("id") or "")
    return 1, 0.0, str((task or {}).get("createdAt") or ""), str((task or {}).get("id") or "")


def ordered_board_tasks(tasks, target_date=None, status=None):
    selected = [
        task for task in (tasks or [])
        if (target_date is None or str(task.get("date") or "") == str(target_date))
        and (status is None or task.get("status", "planned") == status)
    ]
    return sorted(selected, key=task_board_sort_key)


def reorder_task_board(tasks, task_id, target_status, target_index=None):
    """Move one task across or within Kanban columns and normalize both orders."""
    if target_status not in TASK_STATUS:
        return {"changed": False}
    task = next((item for item in (tasks or []) if str(item.get("id") or "") == str(task_id or "")), None)
    if task is None:
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
        new_value = normalized_decision_value(after.get(field))
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
    return {
        "id": entry_id or str(uuid.uuid4()),
        "projectId": stable_project_id,
        "projectName": str((project or {}).get("name") or "未命名项目"),
        "at": occurred_at,
        "source": source if source in PROJECT_DECISION_SOURCES else "manual",
        "changes": changes,
    }


def compact_project_decision_value(field, value, limit=36):
    text = display_project_decision_value(field, value)
    return text if len(text) <= limit else text[: max(1, limit - 1)].rstrip() + "…"


def format_project_decision_summary(entry, max_changes=2):
    changes = (entry or {}).get("changes") or []
    parts = [
        f"{change.get('label') or PROJECT_DECISION_FIELDS.get(change.get('field'), '项目字段')}："
        f"{compact_project_decision_value(change.get('field'), change.get('before'))} → "
        f"{compact_project_decision_value(change.get('field'), change.get('after'))}"
        for change in changes[:max_changes]
    ]
    if len(changes) > max_changes:
        parts.append(f"另 {len(changes) - max_changes} 项")
    return "；".join(parts) if parts else "没有字段变化"


def format_project_decision_time(value, compact=False):
    try:
        point = datetime.fromisoformat(str(value or ""))
        return point.strftime("%m-%d %H:%M" if compact else "%Y-%m-%d %H:%M")
    except ValueError:
        return str(value or "时间未知")


def normalized_action_text(value):
    return " ".join(str(value or "").split()).casefold()


def project_next_step_completion_update(project, task, completed_at):
    if (task or {}).get("origin") != "project_next_step":
        return None
    completed_step = str((task or {}).get("projectNextStep") or (task or {}).get("title") or "").strip()
    if normalized_action_text((project or {}).get("nextStep")) != normalized_action_text(completed_step):
        return None
    return {
        "lastCompletedNextStep": completed_step,
        "lastCompletedNextStepAt": completed_at,
        "nextStep": "",
        "nextStepReviewNeeded": True,
    }


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
    return bool(task and target_status in TASK_STATUS and task.get("status", "planned") != target_status)
