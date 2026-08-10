"""Qt-independent catalog and ranking rules for global workspace navigation."""

from __future__ import annotations

import re
import unicodedata

from .management import PROJECT_STAGE, STATUS_TEXT, TASK_STATUS
from .runtime import activity_state


def _text(value):
    return str(value or "").strip()


def _normalized(value):
    value = unicodedata.normalize("NFKC", _text(value)).casefold()
    return " ".join(value.split())


def _project_reference(project):
    return _text(project.get("savedId") or project.get("id") or project.get("codexProjectId"))


def _project_name_for_task(task, project_names):
    project_id = _text(task.get("projectId"))
    return (
        project_names.get(project_id)
        or _text(task.get("projectNameSnapshot"))
        or _text(task.get("projectTitle"))
        or "未关联项目"
    )


def _conversation_title(conversation):
    label = _text(conversation.get("conversationLabel") or conversation.get("title"))
    if label:
        return label
    session_id = _text(conversation.get("sessionId"))
    return f"对话 {session_id[-6:]}" if session_id else "Codex 对话"


def _entry(kind, key, title, subtitle, keywords, payload, priority, order):
    search_text = _normalized(" ".join(_text(value) for value in (title, subtitle, *keywords)))
    return {
        "kind": kind,
        "key": key,
        "title": title,
        "subtitle": subtitle,
        "searchText": search_text,
        "payload": payload,
        "priority": priority,
        "order": order,
    }


def build_navigation_entries(projects, tasks, today=None):
    """Build one searchable catalog for projects, current tasks, and conversations."""

    entries = []
    project_names = {}
    order = 0
    seen_conversations = set()
    for project in projects or []:
        if not isinstance(project, dict):
            continue
        project_id = _project_reference(project) or f"project-{order}"
        name = _text(project.get("name")) or "未命名项目"
        for reference in (project.get("id"), project.get("savedId"), project.get("codexProjectId")):
            if _text(reference):
                project_names[_text(reference)] = name
        category = _text(project.get("category")) or "未分类"
        stage = PROJECT_STAGE.get(_text(project.get("stage")), _text(project.get("stage")))
        status = STATUS_TEXT.get(_text(project.get("status")), _text(project.get("status")))
        meta = [value for value in (category, stage, status) if value]
        subtitle = " · ".join(meta) or "项目"
        project_priority = 32 if project.get("priority") == "focus" else 42
        if project.get("status") == "completed":
            project_priority = 72
        entries.append(_entry(
            "project", f"project:{project_id}", name, subtitle,
            (
                project.get("objective"), project.get("nextStep"), project.get("blocker"),
                project.get("path"), project.get("health"), project.get("priority"),
            ),
            project, project_priority, order,
        ))
        order += 1

        for index, conversation in enumerate(project.get("conversations") or []):
            if not isinstance(conversation, dict):
                continue
            session_id = _text(conversation.get("sessionId"))
            conversation_key = session_id or f"{project_id}:{index}"
            if conversation_key in seen_conversations:
                continue
            seen_conversations.add(conversation_key)
            state = activity_state(conversation)
            state_label = {"running": "运行中", "completed": "已完成"}.get(state, "已关联")
            title = _conversation_title(conversation)
            subtitle = f"{name} · {state_label}"
            priority = 10 if state == "running" else 62
            entries.append(_entry(
                "conversation", f"conversation:{conversation_key}", title, subtitle,
                (conversation.get("summary"), name, category, state_label),
                conversation, priority, order,
            ))
            order += 1

    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        if _text(task.get("archivedAt")) or _text(task.get("carriedToTaskId")):
            continue
        task_id = _text(task.get("id")) or f"task-{order}"
        title = _text(task.get("title")) or "未命名任务"
        project_name = _project_name_for_task(task, project_names)
        task_date = _text(task.get("date"))
        status_key = _text(task.get("status")) or "planned"
        status = TASK_STATUS.get(status_key, status_key)
        subtitle = " · ".join(value for value in (project_name, task_date, status) if value)
        priority = {"doing": 20, "planned": 48, "done": 76}.get(status_key, 58)
        if today and task_date == _text(today):
            priority -= 3
        entries.append(_entry(
            "task", f"task:{task_id}", title, subtitle,
            (
                task.get("notes"), task.get("completionNote"), task.get("conversationTitle"),
                task.get("projectNameSnapshot"), task.get("category"),
            ),
            task, priority, order,
        ))
        order += 1
    return entries


def search_navigation_entries(entries, query="", limit=8):
    """Rank navigation results by title relevance, then management usefulness."""

    query_text = _normalized(query)
    candidates = [entry for entry in (entries or []) if isinstance(entry, dict)]
    if not query_text:
        ordered = sorted(candidates, key=lambda entry: (entry.get("priority", 99), entry.get("order", 0)))
        return ordered[:max(0, int(limit))]

    terms = [term for term in re.split(r"\s+", query_text) if term]
    ranked = []
    for entry in candidates:
        haystack = _normalized(entry.get("searchText"))
        if not all(term in haystack for term in terms):
            continue
        title = _normalized(entry.get("title"))
        if title == query_text:
            match_rank = 0
        elif title.startswith(query_text):
            match_rank = 1
        elif query_text in title:
            match_rank = 2
        elif all(term in title for term in terms):
            match_rank = 3
        else:
            match_rank = 4
        ranked.append((match_rank, entry.get("priority", 99), entry.get("order", 0), entry))
    ranked.sort(key=lambda item: item[:3])
    return [item[3] for item in ranked[:max(0, int(limit))]]
