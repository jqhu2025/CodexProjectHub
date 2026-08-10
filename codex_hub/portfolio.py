"""Qt-independent portfolio capacity and activity-evidence rules."""

from datetime import datetime

from .management import (
    PROJECT_DECISION_FIELDS,
    PROJECT_HEALTH,
    PROJECT_PRIORITY,
    STATUS_TEXT,
    normalized_action_text,
    ordered_board_tasks,
    project_execution_alignment,
    project_governance_gaps,
    project_review_drift,
    task_is_archived,
    task_is_superseded_daily_record,
)
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


def _project_decision_route_key(project):
    """Build a stable-enough key for assigning one project to one decision queue."""
    references = project_reference_ids(project)
    if references:
        return "references", tuple(sorted(references))
    path = str((project or {}).get("path") or "").strip().casefold()
    if path:
        return "path", path
    name = str((project or {}).get("name") or "").strip().casefold()
    category = str((project or {}).get("category") or "").strip().casefold()
    if name or category:
        return "label", category, name
    return "object", id(project)


def route_project_decision_queues(ordered_queues):
    """Assign each project to the first applicable action queue and explain diversions.

    Queue items may be projects directly or mappings containing a ``project`` value.
    The caller defines management precedence through ``ordered_queues``.
    """
    queues = {}
    routed = {}
    routed_to = {}
    claimed_references = {}
    claimed_fallbacks = {}
    for queue_name, source_items in ordered_queues or []:
        accepted = []
        diverted = {}
        for item in source_items or []:
            project = (
                item.get("project")
                if isinstance(item, dict) and isinstance(item.get("project"), dict)
                else item
            )
            if not isinstance(project, dict):
                continue
            references = project_reference_ids(project)
            owner = next(
                (claimed_references[reference] for reference in references if reference in claimed_references),
                None,
            )
            fallback_key = None if references else _project_decision_route_key(project)
            if owner is None and fallback_key is not None:
                owner = claimed_fallbacks.get(fallback_key)
            if owner is not None:
                for reference in references:
                    claimed_references.setdefault(reference, owner)
                diverted[owner] = diverted.get(owner, 0) + 1
                continue
            if references:
                for reference in references:
                    claimed_references[reference] = queue_name
            else:
                claimed_fallbacks[fallback_key] = queue_name
            accepted.append(item)
        queues[queue_name] = accepted
        routed[queue_name] = sum(diverted.values())
        routed_to[queue_name] = diverted
    return {"queues": queues, "routed": routed, "routedTo": routed_to}


def primary_project_decision(project, routing):
    """Return the one routed management decision that owns a project, if any."""
    project = project or {}
    target_references = project_reference_ids(project)
    target_fallback = None if target_references else _project_decision_route_key(project)
    for queue_name, items in ((routing or {}).get("queues") or {}).items():
        for item in items or []:
            candidate = (
                item.get("project")
                if isinstance(item, dict) and isinstance(item.get("project"), dict)
                else item
            )
            if not isinstance(candidate, dict):
                continue
            candidate_references = project_reference_ids(candidate)
            matches = bool(target_references & candidate_references)
            if not target_references and not candidate_references:
                matches = target_fallback == _project_decision_route_key(candidate)
            if matches:
                return {"queue": str(queue_name or ""), "item": item}
    return None


def project_workbench_command(project, tasks, target_date, primary=None, now=None):
    """Resolve one project-level command and the evidence that justifies it.

    This intentionally consumes the already-routed portfolio decision.  A workbench
    therefore cannot ask the user to resolve a risk, calibrate direction, and review
    the same project at the same time.
    """
    project = project or {}
    evidence = project_review_evidence(project, tasks, target_date, now)
    primary = primary or {}
    route = str(primary.get("queue") or "")
    item = primary.get("item") or {}
    status = str(project.get("status") or "active")
    next_step = str(project.get("nextStep") or "").strip()
    blocker = str(project.get("blocker") or "").strip()
    health = _project_health_key(project)

    if status == "completed":
        command = {
            "key": "completed", "kind": "项目结论", "tone": "success",
            "title": "项目已完成，保留成果与决策证据",
            "reason": str(project.get("completionSummary") or "当前没有待处理的项目管理动作。"),
            "action": "", "actionLabel": "",
        }
    elif status in {"paused", "idea"}:
        state_label = STATUS_TEXT.get(status, "非活动")
        command = {
            "key": "inactive", "kind": "生命周期", "tone": "neutral",
            "title": f"项目当前为{state_label}",
            "reason": "资料和历史仍保留；需要继续时先重新确认目标、状态与下一步。",
            "action": "edit_decision", "actionLabel": "重新评估",
        }
    elif route == "attention":
        blocked = health == "blocked" or bool(blocker)
        command = {
            "key": "attention", "kind": "首要管理决策", "tone": "danger" if blocked else "warning",
            "title": "先解除当前阻塞" if blocked else "先校准风险与应对",
            "reason": blocker or "项目健康度已标记为需关注；请明确风险、责任动作与恢复条件。",
            "action": "resolve_blocker" if blocked else "edit_decision",
            "actionLabel": "处理阻塞" if blocked else "更新风险",
        }
    elif route == "alignment":
        live_titles = [
            str(task.get("title") or "未命名任务").strip()
            for task in (item.get("tasks") or [])
        ] if isinstance(item, dict) else []
        live_text = "、".join(live_titles[:2]) or "今日在制任务"
        declared = str((item or {}).get("declaredNextStep") or next_step).strip()
        command = {
            "key": "alignment", "kind": "首要管理决策", "tone": "primary",
            "title": "先确认实际执行方向",
            "reason": f"项目下一步“{declared}”与正在执行的“{live_text}”不一致。",
            "action": "calibrate_alignment", "actionLabel": "校准方向",
        }
    elif route == "lifecycle":
        lifecycle_state = (item or {}).get("state") if isinstance(item, dict) else {}
        command = {
            "key": "lifecycle", "kind": "首要管理决策", "tone": "neutral",
            "title": "确认项目继续推进还是暂缓",
            "reason": str((lifecycle_state or {}).get("reason") or "项目近期缺少新的执行或复核证据。"),
            "action": "calibrate_lifecycle", "actionLabel": "校准生命周期",
        }
    elif route == "needs_next":
        completed_step = str(project.get("lastCompletedNextStep") or "").strip()
        reason = (
            f"上一项“{completed_step}”已完成；现在需要明确新的可执行动作。"
            if completed_step else
            "当前没有可以直接开始的下一步，项目无法形成清晰的执行承诺。"
        )
        command = {
            "key": "needs_next", "kind": "首要管理决策", "tone": "primary",
            "title": "明确一个可以直接开始的下一步", "reason": reason,
            "action": "define_next_step", "actionLabel": "明确下一步",
        }
    elif route == "focus_commitment":
        command = {
            "key": "focus_commitment", "kind": "首要管理决策", "tone": "focus",
            "title": "把战略重点落地为今日承诺",
            "reason": f"下一步“{next_step}”已经明确，但尚未进入当前任务。",
            "action": "schedule_next_step", "actionLabel": "加入今日",
        }
    elif route == "review":
        gaps = project_governance_gaps(project)
        if gaps:
            title = "补全项目的必要信息"
            reason = "缺少：" + "、".join(PROJECT_DECISION_FIELDS.get(field, field) for field in gaps)
        else:
            changes = project_review_drift(project)
            labels = "、".join(change.get("label") or change.get("field") or "项目决策" for change in changes[:3])
            title = "确认真实发生的项目变化"
            reason = f"{labels}与上次记录不同。" if labels else "项目关键决策发生变化。"
        command = {
            "key": "review", "kind": "项目变化", "tone": "primary",
            "title": title, "reason": reason,
            "action": "confirm_review", "actionLabel": "查看变化",
        }
    elif evidence["doingCount"] or evidence["runningConversationCount"]:
        parts = []
        if evidence["doingCount"]:
            parts.append(f"{evidence['doingCount']} 项任务进行中")
        if evidence["runningConversationCount"]:
            parts.append(f"{evidence['runningConversationCount']} 个 Codex 对话运行中")
        command = {
            "key": "execute", "kind": "当前执行", "tone": "success",
            "title": "保持当前执行，优先完成在制工作",
            "reason": " · ".join(parts),
            "action": "continue_codex", "actionLabel": "继续执行",
        }
    elif next_step:
        command = {
            "key": "ready", "kind": "当前执行", "tone": "primary",
            "title": "把已明确的下一步转成今日承诺",
            "reason": f"下一步“{next_step}”尚未进入当前任务。",
            "action": "schedule_next_step", "actionLabel": "加入今日",
        }
    else:
        command = {
            "key": "idle", "kind": "项目状态", "tone": "neutral",
            "title": "当前没有可执行动作",
            "reason": "请补充项目目标与一个可以直接开始的下一步。",
            "action": "define_next_step", "actionLabel": "完善项目",
        }

    task_parts = []
    if evidence["taskCount"]:
        task_parts.append(
            f"今日 {evidence['taskCount']} 项 · {evidence['plannedCount']} 计划 / "
            f"{evidence['doingCount']} 进行 / {evidence['doneCount']} 完成"
        )
    else:
        task_parts.append("今日无关联任务")
    if evidence["runningConversationCount"]:
        task_parts.append(f"Codex {evidence['runningConversationCount']} 个运行中")
    age_days = (evidence.get("activity") or {}).get("ageDays")
    source = str((evidence.get("activity") or {}).get("source") or "")
    if age_days is None:
        task_parts.append("尚无执行证据")
    elif age_days == 0:
        task_parts.append(f"最近活动：今天{(' · ' + source) if source else ''}")
    elif age_days == 1:
        task_parts.append(f"最近活动：昨天{(' · ' + source) if source else ''}")
    else:
        task_parts.append(f"最近活动：{age_days} 天前{(' · ' + source) if source else ''}")
    command["evidence"] = evidence
    command["evidenceText"] = "  ·  ".join(task_parts)
    command["nextStep"] = next_step
    command["objective"] = str(project.get("objective") or "").strip()
    return command


def task_matches_project(task, project):
    project_id = str((task or {}).get("projectId") or "")
    return bool(project_id and project_id in project_reference_ids(project))


def find_open_project_next_step_task(tasks, project, title):
    """Return the single current work item matching a declared project action."""
    expected = normalized_action_text(title)
    if not expected:
        return None
    return next(
        (
            task for task in tasks or []
            if task_matches_project(task, project)
            and not task_is_archived(task)
            and not task_is_superseded_daily_record(task)
            and task.get("status", "planned") != "done"
            and normalized_action_text(task.get("title")) == expected
        ),
        None,
    )


def project_next_step_commitment_state(project, tasks):
    """Explain whether a declared project action has become current work."""
    project = project or {}
    if project.get("status", "active") != "active":
        return {"state": "inactive", "nextStep": "", "task": None, "activeTasks": [], "runningConversations": 0}
    next_step = str(project.get("nextStep") or "").strip()
    active_tasks = [
        task for task in tasks or []
        if task_matches_project(task, project)
        and not task_is_archived(task)
        and not task_is_superseded_daily_record(task)
        and task.get("status", "planned") != "done"
    ]
    running_conversations = sum(
        activity_state(conversation) == "running"
        for conversation in project.get("conversations") or []
    )
    if not next_step:
        state = "missing"
        matching_task = None
    else:
        matching_task = find_open_project_next_step_task(active_tasks, project, next_step)
        if matching_task is not None:
            state = "scheduled"
        elif active_tasks or running_conversations:
            state = "live_other"
        else:
            state = "ready"
    return {
        "state": state,
        "nextStep": next_step,
        "task": matching_task,
        "activeTasks": active_tasks,
        "runningConversations": running_conversations,
    }


def portfolio_focus_commitment_queue(projects, tasks):
    """Keep strategic-focus projects whose next-action commitment is incomplete."""
    return [
        {"project": project, **state}
        for project in projects or []
        if project.get("status", "active") == "active"
        and str(project.get("priority") or "normal") == "focus"
        for state in (project_next_step_commitment_state(project, tasks),)
        if state["state"] in {"missing", "ready"}
    ]


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


def portfolio_focus_guidance(state):
    """Explain the strategic selection decision without implying all live work must be promoted."""
    state = state or {}
    capacity = normalized_portfolio_focus_capacity(state.get("capacity"))
    strategic_count = len(state.get("strategic") or [])
    executing_count = len(state.get("executing") or [])
    outside_count = len(state.get("executionOutsideFocus") or [])
    remaining = max(0, int(state.get("remaining") or 0))
    over_by = max(0, int(state.get("overBy") or 0))
    if over_by:
        return f"重点组合超出容量 {over_by} 项"
    if outside_count and not strategic_count:
        return f"{executing_count} 项执行候选 · 最多选 {capacity} 项"
    if outside_count and remaining:
        return f"{outside_count} 项执行候选 · 还可选 {remaining} 项"
    if outside_count:
        return f"容量已满 · {outside_count} 项执行在重点外"
    if strategic_count:
        return "重点已落地" + (f" · 可增加 {remaining} 项" if remaining else "")
    return "尚未选择重点"


def portfolio_focus_change_impact(project, enabled, state):
    """Preview one deliberate focus change before it can cross capacity."""
    state = state or {}
    capacity = normalized_portfolio_focus_capacity(state.get("capacity"))
    current = len(state.get("strategic") or [])
    is_focus = _project_priority_key(project or {}) == "focus"
    requested = bool(enabled)
    delta = 1 if requested and not is_focus else -1 if not requested and is_focus else 0
    selected_after = max(0, current + delta)
    over_by = max(0, selected_after - capacity)
    return {
        "capacity": capacity,
        "selectedBefore": current,
        "selectedAfter": selected_after,
        "overBy": over_by,
        "changes": bool(delta),
        "requiresConfirmation": bool(delta > 0 and over_by),
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
        schedule_history = task.get("scheduleHistory") if isinstance(task.get("scheduleHistory"), list) else []
        candidates.extend(event.get("at") for event in schedule_history if isinstance(event, dict))
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


def project_review_evidence(project, tasks, target_date, now=None):
    """Summarize current execution evidence before a project review is confirmed."""
    today_tasks = [
        task for task in (tasks or [])
        if task_matches_project(task, project)
        and not task_is_archived(task)
        and not task_is_superseded_daily_record(task)
        and str(task.get("date") or "") == str(target_date or "")
    ]
    counts = {
        status: sum(task.get("status", "planned") == status for task in today_tasks)
        for status in ("planned", "doing", "done")
    }
    running_conversations = sum(
        activity_state(conversation) == "running"
        for conversation in (project or {}).get("conversations") or []
    )
    alignment = project_execution_alignment(project, tasks, target_date)
    if alignment is not None:
        alignment_state = "acknowledged" if alignment.get("acknowledged") else "divergent"
    elif counts["doing"] or running_conversations:
        alignment_state = "aligned"
    else:
        alignment_state = "idle"
    return {
        "taskCount": len(today_tasks),
        "plannedCount": counts["planned"],
        "doingCount": counts["doing"],
        "doneCount": counts["done"],
        "runningConversationCount": running_conversations,
        "alignmentState": alignment_state,
        "alignment": alignment,
        "activity": project_activity_evidence(project, tasks, now),
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
        result.append({
            "task": task,
            "project": project,
            "priority": priority,
            "boardPosition": position,
            "reason": reason,
        })
    return result


def wip_task_decisions(state, recommendations, projects):
    """Explain the role of every in-progress task in one WIP decision.

    The recommendation algorithm remains deliberately conservative and moves
    one task at a time.  This companion view makes the complete reasoning
    visible: active Codex work is protected, the first reduction is explicit,
    additional reductions are queued, and everything else has a concrete keep
    reason instead of appearing to be ignored.
    """
    state = state or {}
    recommendations = list(recommendations or [])
    protected_ids = {
        str(task.get("id") or "")
        for task in state.get("protected") or []
        if task.get("id")
    }
    recommendation_rank = {
        str((item.get("task") or {}).get("id") or ""): (index, item)
        for index, item in enumerate(recommendations, start=1)
        if (item.get("task") or {}).get("id")
    }
    project_index = {
        reference: project
        for project in projects or []
        for reference in project_reference_ids(project)
    }
    over_by = max(0, int(state.get("overBy") or 0))
    decisions = {}
    for task in state.get("doing") or []:
        task_id = str(task.get("id") or "")
        project = project_index.get(str(task.get("projectId") or ""))
        priority = str((project or {}).get("priority") or "normal")
        if priority not in PROJECT_PRIORITY:
            priority = "normal"
        priority_label = PROJECT_PRIORITY.get(priority, PROJECT_PRIORITY["normal"])
        if task_id in protected_ids:
            decision = {
                "action": "protected",
                "label": "运行保护",
                "reason": "关联的 Codex 对话仍在运行，避免中断正在执行的工作",
            }
        elif task_id in recommendation_rank:
            rank, recommendation = recommendation_rank[task_id]
            if rank == 1:
                action, label = "defer", "优先收敛"
                reason = str(recommendation.get("reason") or "当前是最合适的可逆收敛项")
            else:
                action, label = "queued", f"后续候选 {rank}"
                reason = f"若上一项处理后仍超载，再考虑本项；{recommendation.get('reason') or '排序次于当前建议'}"
            decision = {"action": action, "label": label, "reason": reason}
        elif over_by:
            if priority == "focus":
                reason = "所属项目是当前重点，本轮优先保留"
            else:
                reason = "优先级或看板顺序高于当前收敛候选，本轮建议保留"
            decision = {"action": "keep", "label": "建议保留", "reason": reason}
        else:
            decision = {"action": "keep", "label": "容量内", "reason": "当前在制任务未超过设定容量"}
        decisions[task_id] = {
            **decision,
            "priority": priority,
            "priorityLabel": priority_label,
        }
    return decisions
