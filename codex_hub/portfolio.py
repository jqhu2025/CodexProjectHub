"""Qt-independent portfolio capacity and activity-evidence rules."""

from datetime import datetime

from .management import PROJECT_HEALTH, PROJECT_PRIORITY, STATUS_TEXT, ordered_board_tasks, task_is_archived
from .runtime import activity_state


DEFAULT_PORTFOLIO_FOCUS_CAPACITY = 3
DEFAULT_PORTFOLIO_INACTIVITY_DAYS = 14
DEFAULT_TASK_WIP_LIMIT = 3


def normalized_portfolio_focus_capacity(value):
    try:
        capacity = int(value)
    except (TypeError, ValueError):
        capacity = DEFAULT_PORTFOLIO_FOCUS_CAPACITY
    return max(1, min(9, capacity))


def normalized_portfolio_inactivity_days(value):
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = DEFAULT_PORTFOLIO_INACTIVITY_DAYS
    return max(7, min(90, days))


def normalized_task_wip_limit(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_TASK_WIP_LIMIT
    return max(1, min(9, limit))


def project_reference_ids(project):
    """Return every stable/current ID that may be stored on a linked task."""
    return {
        str(value)
        for value in (
            (project or {}).get("id"),
            (project or {}).get("savedId"),
            (project or {}).get("codexProjectId"),
        )
        if value
    }


def task_matches_project(task, project):
    project_id = str((task or {}).get("projectId") or "")
    return bool(project_id and project_id in project_reference_ids(project))


def task_project_identity(task, project=None):
    """Return a truthful task-project label without guessing a broken link."""
    task = task or {}
    project = project or {}
    current_name = str(project.get("name") or "").strip()
    if current_name:
        return {"name": current_name, "state": "current"}
    snapshot = str(task.get("projectNameSnapshot") or "").strip()
    if snapshot:
        return {"name": f"{snapshot}（历史关联）", "state": "historical"}
    if str(task.get("projectId") or "").strip():
        return {"name": "历史项目（关联已失效）", "state": "orphan"}
    return {"name": "未关联项目", "state": "unlinked"}


def reconcile_task_project_snapshots(tasks, projects):
    """Backfill missing identity snapshots only when a unique live match exists."""
    changed = 0
    for task in tasks or []:
        matches = [project for project in projects or [] if task_matches_project(task, project)]
        if len(matches) != 1:
            continue
        project = matches[0]
        additions = {
            "projectNameSnapshot": str(project.get("name") or "").strip(),
            "projectCategorySnapshot": str(project.get("category") or "未分类").strip(),
        }
        for field, value in additions.items():
            if value and not str(task.get(field) or "").strip():
                task[field] = value
                changed += 1
    return changed


def reconcile_task_project_categories(tasks, projects):
    """Repair current taxonomy fields when one linked project resolves unambiguously."""
    changed = 0
    for task in tasks or []:
        matches = [project for project in projects or [] if task_matches_project(task, project)]
        if len(matches) != 1:
            continue
        category = str(matches[0].get("category") or "未分类").strip()
        if not category:
            continue
        if (
            str(task.get("category") or "").strip() == category
            and str(task.get("projectCategorySnapshot") or "").strip() == category
        ):
            continue
        task["category"] = category
        task["projectCategorySnapshot"] = category
        changed += 1
    return changed


def migrate_task_category_references(tasks, previous_category, next_category):
    """Rename one taxonomy label everywhere it is currently referenced by a task."""
    previous = str(previous_category or "").strip()
    replacement = str(next_category or "").strip()
    if not previous or not replacement or previous == replacement:
        return 0
    changed = 0
    for task in tasks or []:
        touched = False
        if str(task.get("category") or "").strip() == previous:
            task["category"] = replacement
            touched = True
        if str(task.get("projectCategorySnapshot") or "").strip() == previous:
            task["projectCategorySnapshot"] = replacement
            touched = True
        if touched:
            changed += 1
    return changed


def migrate_project_task_category_references(tasks, project, next_category):
    """Keep every task linked to one project inside the project's current taxonomy."""
    replacement = str(next_category or "").strip()
    if not replacement:
        return 0
    changed = 0
    for task in tasks or []:
        if not task_matches_project(task, project):
            continue
        if (
            str(task.get("category") or "").strip() == replacement
            and str(task.get("projectCategorySnapshot") or "").strip() == replacement
        ):
            continue
        task["category"] = replacement
        task["projectCategorySnapshot"] = replacement
        changed += 1
    return changed


def task_project_link_issues(tasks, projects):
    """Return live task records whose saved project reference no longer resolves."""
    known_references = {
        reference
        for project in projects or []
        for reference in project_reference_ids(project)
    }
    return [
        task for task in tasks or []
        if not task_is_archived(task)
        and str(task.get("projectId") or "").strip()
        and str(task.get("projectId")) not in known_references
    ]


def task_project_link_events(task):
    """Return newest-first task/project repair evidence."""
    events = [event for event in (task or {}).get("projectLinkHistory") or [] if isinstance(event, dict)]
    return sorted(events, key=lambda event: str(event.get("at") or ""), reverse=True)


def assign_task_project(task, project, occurred_at, source="manual_repair"):
    """Repair one task link without rewriting task activity or status history."""
    if not task or not project:
        return False
    stable_project_id = (project or {}).get("savedId") or (project or {}).get("codexProjectId") or (project or {}).get("id")
    if not stable_project_id or task_matches_project(task, project):
        return False
    previous_id = str(task.get("projectId") or "")
    previous_name = str(task.get("projectNameSnapshot") or "").strip()
    previous_category = str(task.get("projectCategorySnapshot") or task.get("category") or "").strip()
    project_name = str(project.get("name") or "未命名项目").strip()
    project_category = str(project.get("category") or "未分类").strip()
    task["projectId"] = stable_project_id
    task["projectNameSnapshot"] = project_name
    task["projectCategorySnapshot"] = project_category
    task["category"] = project_category
    history = task.setdefault("projectLinkHistory", [])
    history.append({
        "at": str(occurred_at or ""),
        "source": str(source or "manual_repair"),
        "fromProjectId": previous_id,
        "fromProjectName": previous_name,
        "fromProjectCategory": previous_category,
        "toProjectId": str(stable_project_id),
        "toProjectName": project_name,
        "toProjectCategory": project_category,
    })
    if len(history) > 100:
        task["projectLinkHistory"] = history[-100:]
    return True


def reconcile_task_project_links_from_conversations(tasks, projects, occurred_at, known_projects=None):
    """Repair only orphan links backed by one unique current Codex conversation."""
    project_by_session = {}
    for project in projects or []:
        for conversation in project.get("conversations") or []:
            session_id = str(conversation.get("sessionId") or "")
            if not session_id:
                continue
            project_by_session.setdefault(session_id, []).append(project)
    repaired = []
    for task in task_project_link_issues(tasks, known_projects if known_projects is not None else projects):
        candidates = project_by_session.get(str(task.get("sessionId") or ""), [])
        unique = {str((candidate or {}).get("id") or ""): candidate for candidate in candidates if (candidate or {}).get("id")}
        if len(unique) != 1:
            continue
        project = next(iter(unique.values()))
        if assign_task_project(task, project, occurred_at, "codex_conversation"):
            repaired.append(task)
    return repaired


def _project_priority_key(project):
    value = str((project or {}).get("priority") or "normal")
    return value if value in PROJECT_PRIORITY else "normal"


def _project_health_key(project):
    value = str((project or {}).get("health") or "on_track")
    return value if value in PROJECT_HEALTH else "on_track"


def project_live_work_state(project):
    """Return live execution evidence without conflating it with strategic priority."""
    if (project or {}).get("status", "active") != "active":
        status_text = STATUS_TEXT.get((project or {}).get("status"), "非活动")
        return False, f"项目状态为{status_text}，当前不执行", 0, 0
    active_tasks = int((project or {}).get("activeTaskCount") or 0)
    running_conversations = sum(
        activity_state(conversation) == "running"
        for conversation in (project or {}).get("conversations") or []
    )
    if active_tasks:
        reason = f"今日 {active_tasks} 项任务进行中"
        if running_conversations:
            reason += f"，{running_conversations} 个 Codex 对话运行中"
        return True, reason, active_tasks, running_conversations
    if running_conversations:
        return True, f"{running_conversations} 个 Codex 对话运行中", active_tasks, running_conversations
    return False, "当前没有进行中的任务或 Codex 对话", 0, 0


def portfolio_focus_capacity_state(projects, capacity=DEFAULT_PORTFOLIO_FOCUS_CAPACITY):
    """Separate declared strategic focus from work that happens to be live today."""
    capacity = normalized_portfolio_focus_capacity(capacity)
    active = [project for project in (projects or []) if (project or {}).get("status", "active") == "active"]
    strategic = [project for project in active if _project_priority_key(project) == "focus"]
    executing = [project for project in active if project_live_work_state(project)[0]]
    strategic_ids = {str(project.get("id") or project.get("savedId") or id(project)) for project in strategic}
    executing_ids = {str(project.get("id") or project.get("savedId") or id(project)) for project in executing}
    return {
        "capacity": capacity,
        "strategic": strategic,
        "executing": executing,
        "executionOutsideFocus": [
            project for project in executing
            if str(project.get("id") or project.get("savedId") or id(project)) not in strategic_ids
        ],
        "focusWithoutExecution": [
            project for project in strategic
            if str(project.get("id") or project.get("savedId") or id(project)) not in executing_ids
        ],
        "remaining": max(0, capacity - len(strategic)),
        "overBy": max(0, len(strategic) - capacity),
    }


def parsed_portfolio_evidence_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def project_activity_evidence(project, tasks, now=None):
    """Return the latest task, Codex, or deliberate-review evidence for one project."""
    evidence = []
    linked_tasks = [
        task for task in (tasks or [])
        if task_matches_project(task, project) and not task_is_archived(task)
    ]
    for task in linked_tasks:
        candidates = []
        history = task.get("statusHistory") if isinstance(task.get("statusHistory"), list) else []
        candidates.extend(event.get("at") for event in history if isinstance(event, dict))
        candidates.extend((task.get("updatedAt"), task.get("createdAt")))
        parsed = [parsed_portfolio_evidence_time(value) for value in candidates]
        parsed = [value for value in parsed if value is not None]
        if not parsed:
            fallback = parsed_portfolio_evidence_time(task.get("date"))
            if fallback is not None:
                parsed.append(fallback)
        if parsed:
            evidence.append((max(parsed), "任务记录"))
    conversations = list((project or {}).get("conversations") or [])
    for conversation in conversations:
        occurred_at = parsed_portfolio_evidence_time(conversation.get("at"))
        if occurred_at is not None:
            evidence.append((occurred_at, "Codex 对话"))
    reviewed_at = parsed_portfolio_evidence_time((project or {}).get("reviewedAt"))
    if reviewed_at is not None:
        evidence.append((reviewed_at, "人工复核"))
    latest_at, source = max(evidence, default=(None, ""), key=lambda item: item[0] or datetime.min)
    current = now or datetime.now()
    if current.tzinfo is not None:
        current = current.astimezone().replace(tzinfo=None)
    age_days = None if latest_at is None else max(0, int((current - latest_at).total_seconds() // 86400))
    return {
        "at": latest_at,
        "source": source,
        "ageDays": age_days,
        "taskCount": len(linked_tasks),
        "conversationCount": len(conversations),
    }


def project_lifecycle_calibration_state(project, tasks, now=None, inactivity_days=DEFAULT_PORTFOLIO_INACTIVITY_DAYS):
    """Identify neutral lifecycle debt without turning inactivity into a risk signal."""
    inactivity_days = normalized_portfolio_inactivity_days(inactivity_days)
    if (project or {}).get("status", "active") != "active":
        return {"due": False, "reason": "项目不在活跃组合", "threshold": inactivity_days}
    if _project_priority_key(project) == "focus":
        return {"due": False, "reason": "项目已明确列为战略重点", "threshold": inactivity_days}
    live, live_reason, _active_tasks, _running = project_live_work_state(project)
    if live:
        return {"due": False, "reason": live_reason, "threshold": inactivity_days}
    blocker = str((project or {}).get("blocker") or "").strip()
    if blocker or _project_health_key(project) in {"attention", "blocked"}:
        return {"due": False, "reason": "项目已进入风险或阻塞处置", "threshold": inactivity_days}
    evidence = project_activity_evidence(project, tasks, now)
    age_days = evidence["ageDays"]
    due = age_days is None or age_days >= inactivity_days
    if age_days is None:
        reason = "尚无任务、Codex 活动或人工复核记录"
    elif due:
        reason = f"已 {age_days} 天没有新的执行或复核记录"
    else:
        reason = f"最近证据来自{evidence['source']}，距今 {age_days} 天"
    return {**evidence, "due": due, "reason": reason, "threshold": inactivity_days}


def portfolio_lifecycle_calibration_queue(projects, tasks, now=None, inactivity_days=DEFAULT_PORTFOLIO_INACTIVITY_DAYS):
    queue = []
    for project in projects or []:
        state = project_lifecycle_calibration_state(project, tasks, now, inactivity_days)
        if state.get("due"):
            queue.append({"project": project, "state": state})
    return sorted(
        queue,
        key=lambda item: (
            0 if item["state"].get("ageDays") is None else 1,
            -(item["state"].get("ageDays") or 0),
            str((item.get("project") or {}).get("name") or "").casefold(),
        ),
    )


def task_wip_capacity_state(tasks, target_date, limit=DEFAULT_TASK_WIP_LIMIT, running_session_ids=None):
    """Describe current in-progress capacity without blocking legitimate state changes."""
    limit = normalized_task_wip_limit(limit)
    running_session_ids = {str(value) for value in (running_session_ids or set()) if value}
    doing = [
        task for task in (tasks or [])
        if not task_is_archived(task)
        and str(task.get("date") or "") == str(target_date or "")
        and task.get("status", "planned") == "doing"
    ]
    protected = [task for task in doing if str(task.get("sessionId") or "") in running_session_ids]
    return {
        "limit": limit,
        "doing": doing,
        "protected": protected,
        "count": len(doing),
        "remaining": max(0, limit - len(doing)),
        "overBy": max(0, len(doing) - limit),
    }


def wip_deferral_recommendations(tasks, projects, target_date, over_by, protected_task_ids=None):
    """Recommend reversible WIP reductions from explicit priority and board-order evidence."""
    try:
        needed = max(0, int(over_by))
    except (TypeError, ValueError):
        needed = 0
    if not needed:
        return []
    protected = {str(value) for value in (protected_task_ids or set()) if value}
    project_index = {
        reference: project
        for project in (projects or [])
        for reference in project_reference_ids(project)
    }
    ordered = ordered_board_tasks(tasks, target_date, "doing")
    priority_order = {"later": 0, "normal": 1, "focus": 2}
    candidates = []
    for position, task in enumerate(ordered):
        if str(task.get("id") or "") in protected:
            continue
        project = project_index.get(str(task.get("projectId") or ""))
        priority = str((project or {}).get("priority") or "normal")
        if priority not in PROJECT_PRIORITY:
            priority = "normal"
        candidates.append((priority_order[priority], -position, task, project, priority))
    candidates.sort(key=lambda item: (item[0], item[1], str(item[2].get("createdAt") or "")))
    result = []
    for _priority_rank, _position, task, project, priority in candidates[:needed]:
        if priority == "later":
            reason = "所属项目已设为“稍后处理”"
        elif project is None:
            reason = "未关联可识别项目，且看板顺序靠后"
        elif priority == "focus":
            reason = "看板顺序最低；仅在其他候选不足时建议"
        else:
            reason = "非战略重点，且看板顺序靠后"
        result.append({"task": task, "project": project, "reason": reason})
    return result
