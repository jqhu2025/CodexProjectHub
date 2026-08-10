import json
import mmap
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PyQt5.QtCore import QDate, QMimeData, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QDrag, QFont, QFontDatabase, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFrame, QGridLayout,
    QFileDialog, QGraphicsScene, QGraphicsView, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QShortcut, QSizePolicy, QStackedWidget, QStatusBar, QStyle, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from codex_hub.management import (
    PROJECT_DECISION_FIELDS,
    PROJECT_DECISION_SOURCES,
    PROJECT_BLOCKER_LIFECYCLE_FIELDS,
    PROJECT_HEALTH,
    PROJECT_PRIORITY,
    PROJECT_STAGE,
    STATUS_COLOR,
    STATUS_TEXT,
    TASK_COLORS,
    TASK_EVENT_SOURCES,
    TASK_SCHEDULE_SOURCES,
    TASK_STATUS,
    active_task_records,
    archive_task_record,
    archive_project_layout,
    archived_task_records,
    build_project_decision_entry,
    build_project_alignment_entry,
    build_project_decision_rollback,
    build_project_closeout_entry,
    build_project_lifecycle_entry,
    build_project_review_entry,
    clear_project_completion_outcome,
    clear_task_completion_outcome,
    compact_project_decision_value,
    current_task_record,
    display_project_decision_value,
    establish_project_review_baseline,
    format_project_decision_summary,
    format_project_decision_time,
    merge_missing_project_insight,
    latest_project_completion_outcome,
    normalize_project_management_decision,
    normalized_action_text,
    normalized_decision_value,
    ordered_board_tasks,
    overdue_planned_tasks,
    project_decision_changes,
    project_execution_alignment,
    project_governance_gaps,
    portfolio_execution_alignment_queue,
    project_review_status,
    project_review_phase,
    project_review_drift,
    project_review_trigger,
    project_review_overdue_days,
    project_management_validation_error,
    project_blocker_age_seconds,
    project_blocker_duration_label,
    project_completion_outcome,
    project_change_establishes_review,
    project_next_step_completion_update,
    project_next_step_reopen_update,
    record_task_completion_outcome,
    record_project_completion_outcome,
    record_task_status_event,
    record_task_schedule_event,
    reconcile_project_blocker_lifecycle,
    reorder_task_board,
    reschedule_task_date,
    rollover_in_progress_tasks,
    restore_project_layout,
    restore_task_record,
    task_status_events,
    task_schedule_events,
    task_status_transition_allowed,
    task_is_archived,
    task_is_superseded_daily_record,
    task_completion_outcome,
    task_completion_revisions,
    tasks_missing_completion_outcomes,
)
from codex_hub.navigation import build_navigation_entries, search_navigation_entries
from codex_hub.portfolio import (
    DEFAULT_PORTFOLIO_FOCUS_CAPACITY,
    DEFAULT_PORTFOLIO_INACTIVITY_DAYS,
    DEFAULT_TASK_WIP_LIMIT,
    normalized_portfolio_focus_capacity,
    normalized_portfolio_inactivity_days,
    normalized_task_wip_limit,
    find_open_project_next_step_task,
    migrate_task_category_references,
    migrate_project_task_category_references,
    portfolio_focus_commitment_queue,
    portfolio_focus_capacity_state,
    portfolio_focus_change_impact,
    portfolio_focus_guidance,
    portfolio_lifecycle_calibration_queue,
    project_activity_evidence,
    project_review_evidence,
    project_lifecycle_calibration_state,
    project_live_work_state,
    project_next_step_commitment_state,
    primary_project_decision,
    project_workbench_command,
    project_reference_ids,
    assign_task_project,
    reconcile_task_project_links_from_conversations,
    reconcile_task_project_snapshots,
    reconcile_task_project_categories,
    route_project_decision_queues,
    task_matches_project,
    task_project_identity,
    task_project_link_events,
    task_project_link_issues,
    task_wip_capacity_state,
    wip_deferral_recommendations,
    wip_task_decisions,
)
from codex_hub.runtime import activity_state, analyze_session_records, find_codex_binary as locate_codex_binary, read_user_thread_rows
from codex_hub.storage import consume_json_recovery_events, load_json, save_json
from codex_hub.usage import (
    local_codex_tokens_for_date as estimate_local_codex_tokens,
    read_codex_usage as query_codex_usage,
)

ROOT = Path(__file__).resolve().parent
PROJECTS_FILE = ROOT / "data" / "projects.json"
CATEGORIES_FILE = ROOT / "data" / "categories.json"
TASKS_FILE = ROOT / "data" / "today_tasks.json"
DAILY_SUMMARIES_FILE = ROOT / "data" / "daily_summaries.json"
PROJECT_DECISIONS_FILE = ROOT / "data" / "project_decisions.json"
SETTINGS_FILE = ROOT / "data" / "settings.json"
PROJECT_LAYOUT_FILE = ROOT / "data" / "project_layout.json"
CODEX_HOME = Path(os.environ.get("USERPROFILE", "")) / ".codex"
CODEX_SESSIONS = CODEX_HOME / "sessions"
CODEX_GLOBAL_STATE = CODEX_HOME / ".codex-global-state.json"
CODEX_SESSION_INDEX = CODEX_HOME / "session_index.jsonl"
DEFAULT_CATEGORIES = ["Product Development", "Research Lab", "Operations", "External Projects", "未分类"]
PROJECT_REVIEW_BATCH_SIZE = 5

STYLE = """
QMainWindow, QWidget { background: #f5f7fb; color: #172033; font-family: 'Segoe UI Variable Text', 'Microsoft YaHei UI'; font-size: 14px; }
QLabel { background: transparent; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #c3cfdd; border-radius: 4px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: #91a6be; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
QScrollBar::handle:horizontal { background: #c3cfdd; border-radius: 4px; min-width: 34px; }
QLineEdit, QTextEdit, QComboBox, QDateEdit { background: #ffffff; border: 1px solid #d5dee9; border-radius: 9px; padding: 8px 12px; color: #172033; selection-background-color: #dce9ff; font-size: 13px; }
QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QDateEdit:hover { border-color: #a7bbd3; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus { border: 1px solid #2563eb; background: #ffffff; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView { background: #ffffff; color: #172033; border: 1px solid #d5dee9; selection-background-color: #e8f0ff; }
QPushButton { border: 1px solid #d3dde8; border-radius: 9px; padding: 8px 13px; background: #ffffff; color: #34445c; font-size: 13px; font-weight: 550; }
QPushButton:hover { background: #f3f7fd; border-color: #9fb6d0; color: #174ea6; }
QPushButton:pressed { background: #e8f0fb; }
QPushButton:focus, QToolButton:focus { border: 1px solid #2474ff; }
QPushButton#primary { background: #2563eb; color: #ffffff; border: 1px solid #2563eb; border-radius: 9px; font-weight: 650; padding: 9px 17px; }
QPushButton#primary:hover { background: #1d4ed8; border-color: #1d4ed8; }
QPushButton#nav { text-align: left; background: transparent; border: 1px solid transparent; border-radius: 9px; color: #42526a; padding: 11px 12px; font-size: 14px; }
QPushButton#nav:hover { background: #eef3f9; color: #1d4ed8; }
QPushButton#nav[active='true'] { background: #e9f0ff; color: #1d4ed8; font-weight: 650; border: 1px solid #c8d8f4; border-left: 3px solid #2563eb; padding-left: 10px; }
QPushButton#categoryNav { text-align: left; background: transparent; border: 1px solid transparent; border-radius: 8px; color: #53647a; padding: 0; font-size: 13px; }
QPushButton#categoryNav:hover { background: #f0f4f9; color: #1d4ed8; }
QPushButton#categoryNav[active='true'] { background: #e9f0ff; border-color: #cbdaf1; color: #1d4ed8; font-weight: 650; padding: 0; }
QToolButton { color: #42526a; border-radius: 8px; }
QToolButton:hover { background: #edf2f8; }
QMenu { background: #ffffff; color: #26364c; border: 1px solid #d5dee9; border-radius: 9px; padding: 5px; }
QMenu::item { min-width: 124px; padding: 9px 13px; border-radius: 6px; }
QMenu::item:selected { background: #e8f0ff; color: #1d4ed8; }
QDialog { background: #f7f9fc; }
QStatusBar { background: #fafbfd; color: #607087; border-top: 1px solid #dbe3ee; font-size: 12px; }
"""


def daily_summary_thread_id():
    configured = str(os.environ.get("CODEX_HUB_SUMMARY_THREAD_ID") or "").strip()
    if configured:
        return configured
    settings = load_json(SETTINGS_FILE, {})
    return str(settings.get("dailySummaryThreadId") or "").strip() if isinstance(settings, dict) else ""


def portfolio_focus_capacity():
    settings = load_json(SETTINGS_FILE, {})
    value = settings.get("portfolioFocusCapacity") if isinstance(settings, dict) else None
    return normalized_portfolio_focus_capacity(value)


def save_portfolio_focus_capacity(value):
    settings = load_json(SETTINGS_FILE, {})
    if not isinstance(settings, dict):
        settings = {}
    settings["portfolioFocusCapacity"] = normalized_portfolio_focus_capacity(value)
    save_json(SETTINGS_FILE, settings)
    return settings["portfolioFocusCapacity"]


def portfolio_inactivity_days():
    settings = load_json(SETTINGS_FILE, {})
    value = settings.get("portfolioInactivityDays") if isinstance(settings, dict) else None
    return normalized_portfolio_inactivity_days(value)


def save_portfolio_inactivity_days(value):
    settings = load_json(SETTINGS_FILE, {})
    if not isinstance(settings, dict):
        settings = {}
    settings["portfolioInactivityDays"] = normalized_portfolio_inactivity_days(value)
    save_json(SETTINGS_FILE, settings)
    return settings["portfolioInactivityDays"]


def task_wip_limit():
    settings = load_json(SETTINGS_FILE, {})
    value = settings.get("taskWipLimit") if isinstance(settings, dict) else None
    return normalized_task_wip_limit(value)


def save_task_wip_limit(value):
    settings = load_json(SETTINGS_FILE, {})
    if not isinstance(settings, dict):
        settings = {}
    settings["taskWipLimit"] = normalized_task_wip_limit(value)
    save_json(SETTINGS_FILE, settings)
    return settings["taskWipLimit"]


def load_categories():
    stored = load_json(CATEGORIES_FILE, None)
    source = stored if isinstance(stored, list) else DEFAULT_CATEGORIES
    categories = []
    project_categories = [item.get("category") for item in load_json(PROJECTS_FILE, []) if isinstance(item, dict)]
    for value in [*source, *project_categories]:
        name = str(value or "").strip()
        if name and name != "全部" and name not in categories:
            categories.append(name)
    if "未分类" not in categories:
        categories.append("未分类")
    return ["全部", *categories]


def load_project_layout():
    data = load_json(PROJECT_LAYOUT_FILE, {})
    hidden = [str(value) for value in data.get("hiddenProjectIds", []) if value]
    orders = {
        str(category): [str(value) for value in values if value]
        for category, values in (data.get("categoryOrders") or {}).items()
        if isinstance(values, list)
    }
    return {"hiddenProjectIds": hidden, "categoryOrders": orders}


def storage_recovery_notice(events):
    """Build a concise, one-time status message for local data failures."""

    recovered_files = sorted({event.filename for event in events if event.recovered})
    unreadable_files = sorted({event.filename for event in events if not event.recovered})
    if unreadable_files:
        names = "、".join(unreadable_files[:3])
        suffix = f"等 {len(unreadable_files)} 个文件" if len(unreadable_files) > 3 else ""
        return f"本地数据无法读取：{names}{suffix}；原文件仍保留，请检查数据目录", 9000
    if recovered_files:
        names = "、".join(recovered_files[:3])
        suffix = f"等 {len(recovered_files)} 个文件" if len(recovered_files) > 3 else ""
        return f"已从本地安全副本恢复：{names}{suffix}", 7000
    return None


def normalized_path(value):
    path = str(value or "").replace("/", "\\")
    if path.startswith("\\\\?\\"):
        path = path[4:]
    return path.rstrip("\\").lower()


def project_display_name(saved, source_name, fallback=""):
    """Resolve the visible name without mistaking legacy saved data for an override."""
    saved = saved or {}
    override = normalized_decision_value(saved.get("nameOverride"))
    source = normalized_decision_value(source_name)
    stored = normalized_decision_value(saved.get("name"))
    return override or source or stored or normalized_decision_value(fallback) or "未命名项目"


def apply_project_display_name(target, project, requested_name):
    """Persist an explicit local alias while retaining Codex's source identity."""
    requested = normalized_decision_value(requested_name)
    if not requested:
        return False
    previous_name = normalized_decision_value((target or {}).get("name"))
    previous_override = normalized_decision_value((target or {}).get("nameOverride"))
    source_name = normalized_decision_value((project or {}).get("sourceName"))
    is_codex_project = bool((project or {}).get("codexProjectId") and source_name)
    target["name"] = requested
    if is_codex_project and requested.casefold() != source_name.casefold():
        target["nameOverride"] = requested
    else:
        target.pop("nameOverride", None)
    return previous_name != requested or previous_override != normalized_decision_value(target.get("nameOverride"))


def matched_project(projects, folder):
    target = normalized_path(folder)
    matches = []
    for item in projects:
        paths = item.get("rootPaths") or [item.get("path", "")]
        for path in paths:
            normalized = normalized_path(path)
            if normalized and target.startswith(normalized):
                matches.append((len(normalized), item))
    return max(matches, key=lambda value: value[0], default=(0, None))[1]


def codex_global_state():
    return load_json(CODEX_GLOBAL_STATE, {}, use_backup=False, report_failure=False)


def codex_display_names():
    names = {}
    try:
        with CODEX_SESSION_INDEX.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                thread_id, thread_name = record.get("id"), record.get("thread_name")
                if thread_id and thread_name:
                    names[thread_id] = str(thread_name).strip()
    except OSError:
        pass
    return names


def fluent_icon(glyph, color="#555555", size=16):
    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.TextAntialiasing)
    font = QFont("Segoe MDL2 Assets")
    font.setPixelSize(max(10, size - 1))
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(canvas.rect(), Qt.AlignCenter, glyph)
    painter.end()
    return QIcon(canvas)


def codex_sidebar_projects(saved_projects):
    state = codex_global_state()
    local_projects = state.get("local-projects") or {}
    order = [project_id for project_id in state.get("project-order", []) if project_id in local_projects]
    for project_id in local_projects:
        if project_id not in order:
            order.append(project_id)
    saved_by_path = {}
    for project in saved_projects:
        for path in project.get("rootPaths") or [project.get("path", "")]:
            normalized = normalized_path(path)
            if normalized:
                saved_by_path[normalized] = project
    projects = []
    for project_id in order:
        source = local_projects.get(project_id) or {}
        roots = [str(path) for path in source.get("rootPaths") or [] if path]
        if not roots:
            continue
        saved = next((saved_by_path.get(normalized_path(path)) for path in roots if normalized_path(path) in saved_by_path), None) or {}
        source_name = source.get("name") or Path(roots[0]).name
        projects.append({
            **saved,
            "id": project_id,
            "savedId": saved.get("id"),
            "codexProjectId": project_id,
            "name": project_display_name(saved, source_name, Path(roots[0]).name),
            "sourceName": source_name,
            "path": roots[0],
            "rootPaths": roots,
            "category": saved.get("category", "未分类"),
            "status": saved.get("status", "active"),
        })
    return projects


def visible_project_catalog(saved_projects, layout):
    projects = codex_sidebar_projects(saved_projects)
    codex_paths = {
        normalized_path(path)
        for project in projects
        for path in project.get("rootPaths") or [project.get("path", "")]
        if path
    }
    for saved in saved_projects:
        path = saved.get("path", "")
        if not saved.get("manualProject") or not path or normalized_path(path) in codex_paths:
            continue
        projects.append({
            **saved,
            "id": f"manual:{saved.get('id')}",
            "savedId": saved.get("id"),
            "codexProjectId": None,
            "name": saved.get("name") or Path(path).name,
            "sourceName": "",
            "path": path,
            "rootPaths": [path],
            "category": saved.get("category", "未分类"),
            "status": saved.get("status", "active"),
        })
    hidden = set(layout.get("hiddenProjectIds") or [])
    projects = [project for project in projects if project.get("id") not in hidden]
    base_positions = {project.get("id"): position for position, project in enumerate(projects)}
    category_orders = layout.get("categoryOrders") or {}

    def order_key(project):
        order = category_orders.get(project.get("category"), [])
        try:
            return order.index(project.get("id"))
        except ValueError:
            return len(order) + base_positions.get(project.get("id"), 0)

    projects.sort(key=order_key)
    return projects


def archived_project_catalog(saved_projects, layout):
    """Return recoverable projects hidden from the active portfolio."""
    archived_ids = set((layout or {}).get("hiddenProjectIds") or [])
    if not archived_ids:
        return []
    complete_layout = {
        **(layout or {}),
        "hiddenProjectIds": [],
    }
    return [
        project for project in visible_project_catalog(saved_projects, complete_layout)
        if project.get("id") in archived_ids
    ]


def sidebar_thread_project_map(projects):
    state = codex_global_state()
    valid_projects = {project.get("codexProjectId") for project in projects}
    result = {}
    for project_id, order in (state.get("sidebar-project-thread-orders") or {}).items():
        if project_id not in valid_projects:
            continue
        for thread_id in order.get("threadIds") or []:
            result[thread_id] = project_id
    return result


def codex_thread_project_map(projects, index):
    """Mirror Codex's sidebar, with a path-based fallback for projects omitted there."""
    result = sidebar_thread_project_map(projects)
    for thread_id, metadata in index.items():
        if thread_id in result:
            continue
        project = matched_project(projects, metadata.get("cwd"))
        if not project:
            continue
        result[thread_id] = project["id"]
    return result


def codex_thread_index():
    """Read only durable titles and paths; never writes Codex state."""
    try:
        databases = sorted(CODEX_HOME.glob("state_*.sqlite"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not databases:
            return {}
        rows = read_user_thread_rows(databases[0])
        display_names = codex_display_names()
        return {
            thread_id: {
                "cwd": cwd or "",
                "title": display_names.get(thread_id) or title or "",
                "updatedMs": updated_ms or 0,
                "preview": preview or "",
                "rolloutPath": rollout_path or "",
            }
            for thread_id, cwd, title, updated_ms, preview, rollout_path in rows
        }
    except (OSError, sqlite3.Error):
        return {}


def session_id_from_path(path):
    match = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})\.jsonl$", path.name, re.IGNORECASE)
    return match.group(1) if match else ""


def session_cwd(path):
    try:
        with path.open("r", encoding="utf-8") as file:
            for _ in range(3):
                record = json.loads(file.readline())
                payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                cwd = payload.get("cwd")
                if cwd:
                    return str(cwd)
    except (OSError, json.JSONDecodeError):
        pass
    return ""


_SESSION_TAIL_CACHE = {}


def tail_records(path, max_bytes=128 * 1024):
    try:
        stat = path.stat()
        cache_key = str(path)
        cached = _SESSION_TAIL_CACHE.get(cache_key)
        signature = (stat.st_mtime_ns, stat.st_size, max_bytes)
        if cached and cached[0] == signature:
            return cached[1]
        with path.open("rb") as file:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(max(0, size - max_bytes))
            text = file.read().decode("utf-8", errors="ignore")
        if size > max_bytes:
            text = text.split("\n", 1)[-1]
        records = []
        for line in text.splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        _SESSION_TAIL_CACHE[cache_key] = (signature, records)
        if len(_SESSION_TAIL_CACHE) > 512:
            oldest = next(iter(_SESSION_TAIL_CACHE))
            _SESSION_TAIL_CACHE.pop(oldest, None)
        return records
    except OSError:
        return []


def indexed_codex_sessions(projects, index, thread_projects):
    sessions = []
    project_index = {item.get("codexProjectId"): item for item in projects}
    for session_id, codex_project_id in thread_projects.items():
        metadata = index.get(session_id)
        if not metadata:
            continue
        project = project_index.get(codex_project_id) or matched_project(projects, metadata.get("cwd"))
        if not project:
            continue
        updated_ms = metadata.get("updatedMs") or 0
        try:
            at = datetime.fromtimestamp(updated_ms / 1000, timezone.utc).isoformat() if updated_ms else ""
        except (OSError, OverflowError, ValueError):
            at = ""
        sessions.append({
            "at": at,
            "event": "CodexThread",
            "state": "linked",
            "projectId": project["id"],
            "sessionId": session_id,
            "conversationLabel": metadata.get("title") or f"Codex 对话 {session_id[-6:]}",
            "summary": metadata.get("preview", "")[:180],
            "source": "codex-index",
        })
    return sessions


def recent_codex_sessions(projects, index=None, thread_projects=None):
    """Read only indexed user session logs; never scan the full sessions tree."""
    now = datetime.now(timezone.utc)
    index = index or codex_thread_index()
    thread_projects = thread_projects or {}
    allowed_ids = set(thread_projects) if thread_projects else None
    project_by_reference = {}
    for item in projects:
        if item.get("id"): project_by_reference[item["id"]] = item
        if item.get("codexProjectId"): project_by_reference[item["codexProjectId"]] = item
    sessions = []
    for session_id, metadata in index.items():
        if allowed_ids is not None and session_id not in allowed_ids:
            continue
        file = Path(metadata.get("rolloutPath") or "")
        if not file.is_file():
            continue
        try:
            modified = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc)
        except OSError:
            continue
        cwd = metadata.get("cwd") or session_cwd(file)
        project = project_by_reference.get(thread_projects.get(session_id)) or matched_project(projects, cwd)
        if not project:
            continue
        records = tail_records(file)
        analysis = analyze_session_records(records, modified, now)
        if not analysis["hasActivity"]:
            continue
        title = metadata.get("title") or f"Codex 对话 {session_id[-6:]}"
        sessions.append({
            "at": modified.isoformat(),
            "event": "CodexLocalSession",
            "state": analysis["state"],
            "projectId": project["id"],
            "sessionId": session_id,
            "conversationLabel": title,
            "summary": (analysis["lastPrompt"] or metadata.get("preview") or "Codex 对话已关联")[:180],
            "source": "local-session",
        })
    return sorted(sessions, key=lambda item: item.get("at", ""), reverse=True)


def local_codex_sessions(projects):
    index = codex_thread_index()
    thread_projects = codex_thread_project_map(projects, index)
    combined = {item["sessionId"]: item for item in indexed_codex_sessions(projects, index, thread_projects)}
    for live in recent_codex_sessions(projects, index, thread_projects):
        combined[live["sessionId"]] = {**combined.get(live["sessionId"], {}), **live}
    return sorted(combined.values(), key=lambda item: item.get("at", ""), reverse=True)


class SessionScanner(QThread):
    scanned = pyqtSignal(object)

    def __init__(self, projects):
        super().__init__()
        self.projects = [
            {
                "id": item.get("id"),
                "codexProjectId": item.get("codexProjectId"),
                "path": item.get("path", ""),
                "rootPaths": item.get("rootPaths") or [item.get("path", "")],
            }
            for item in projects
        ]

    def run(self):
        self.scanned.emit(local_codex_sessions(self.projects))


def find_codex_binary():
    return locate_codex_binary()


def find_summary_codex_binary():
    """Prefer the newest user-installed CLI for thread resume compatibility."""
    npm_root = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@openai" / "codex" / "node_modules"
    try:
        candidates = sorted(
            npm_root.glob("@openai/codex-win32-*/vendor/*/bin/codex.exe"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        candidates = []
    path_candidate = shutil.which("codex.exe") or shutil.which("codex")
    if path_candidate and Path(path_candidate).is_file():
        candidates.append(Path(path_candidate))
    return str(candidates[0]) if candidates else find_codex_binary()


def local_codex_tokens_for_date(date_value=None):
    return estimate_local_codex_tokens(CODEX_SESSIONS, date_value)


def read_codex_usage():
    return query_codex_usage(find_codex_binary(), CODEX_SESSIONS)


class UsageScanner(QThread):
    scanned = pyqtSignal(object)

    def run(self):
        self.scanned.emit(read_codex_usage())


def generate_project_insight(project, tasks=None, timeout=240):
        project = dict(project or {})
        tasks = [dict(task) for task in (tasks or [])]
        binary = find_summary_codex_binary()
        path = Path(str(project.get("path") or ""))
        if not binary:
            return {"error": "未找到 Codex 可执行程序"}
        if not path.is_dir():
            return {"error": "请先选择有效的项目文件夹"}
        conversations = []
        for conversation in project.get("conversations") or []:
            conversations.append({
                "title": conversation_name(conversation),
                "state": codex_state(conversation)[1],
                "summary": str(conversation.get("summary") or "").strip()[:240],
            })
        context = {
            "name": project.get("name") or path.name,
            "existingObjective": project.get("objective") or "",
            "existingSuccessCriteria": project.get("successCriteria") or "",
            "existingNextStep": project.get("nextStep") or "",
            "existingBlocker": project.get("blocker") or "",
            "currentStage": project_stage_key(project),
            "currentHealth": project_health_key(project),
            "recentTasks": [
                {
                    "title": task.get("title") or "未命名任务",
                    "status": TASK_STATUS.get(task.get("status", "planned"), "计划"),
                    "notes": str(task.get("notes") or "")[:240],
                    "completionOutcome": task_completion_outcome(task)[:360],
                }
                for task in tasks[-12:]
            ],
            "linkedCodexConversations": conversations[:12],
        }
        prompt = (
            "你是严谨的单人项目管理分析助手。请以只读方式检查当前项目目录，只读取高价值材料（例如 README、项目配置、"
            "入口文件、近期 git 状态与提交摘要），不要遍历大体积数据、构建产物或依赖目录，也不要修改任何文件。\n"
            "结合下面已有信息，生成可供用户确认的项目态势建议。不得把计划当成已完成结果，不得虚构阻塞。"
            "objective 用一句话说明最终交付或解决的问题；successCriteria 用一句话给出可验证的完成判据，"
            "没有足够证据时返回空字符串；nextStep 必须是一个可以立刻执行的具体动作；"
            "blocker 没有明确证据时返回空字符串；summary 用 1-2 句话说明判断依据。\n"
            f"stage 只能是 {list(PROJECT_STAGE)} 之一；health 只能是 {list(PROJECT_HEALTH)} 之一。\n\n"
            "已有项目信息：\n" + json.dumps(context, ensure_ascii=False, indent=2)
        )
        schema = {
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "successCriteria": {"type": "string"},
                "stage": {"type": "string", "enum": list(PROJECT_STAGE)},
                "health": {"type": "string", "enum": list(PROJECT_HEALTH)},
                "blocker": {"type": "string"},
                "nextStep": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["objective", "successCriteria", "stage", "health", "blocker", "nextStep", "summary"],
            "additionalProperties": False,
        }
        try:
            with tempfile.TemporaryDirectory(prefix="codex-hub-project-insight-") as folder:
                folder = Path(folder)
                schema_path = folder / "schema.json"
                output_path = folder / "result.json"
                schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
                command = [
                    binary, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
                    "--sandbox", "read-only", "--cd", str(path), "--output-schema", str(schema_path),
                    "--output-last-message", str(output_path), "-",
                ]
                result = subprocess.run(
                    command, input=prompt, text=True, encoding="utf-8", errors="replace",
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(path), timeout=timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode != 0:
                    lines = (result.stderr or result.stdout or "Codex 项目整理失败").strip().splitlines()
                    return {"error": " | ".join(lines[-4:])[:280]}
                raw = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else result.stdout.strip()
                if raw.startswith("```"):
                    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL)
                data = json.loads(raw)
                data["stage"] = data.get("stage") if data.get("stage") in PROJECT_STAGE else "execution"
                data["health"] = data.get("health") if data.get("health") in PROJECT_HEALTH else "on_track"
                for key in ("objective", "successCriteria", "blocker", "nextStep", "summary"):
                    data[key] = str(data.get(key) or "").strip()
                return data
        except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            return {"error": str(error)[:280]}


class ProjectInsightWorker(QThread):
    generated = pyqtSignal(object)

    def __init__(self, project, tasks=None, parent=None):
        super().__init__(parent)
        self.project = dict(project or {})
        self.tasks = [dict(task) for task in (tasks or [])]

    def run(self):
        self.generated.emit(generate_project_insight(self.project, self.tasks))


class PortfolioGovernanceWorker(QThread):
    """Analyze selected projects sequentially without blocking the Qt event loop."""

    progressed = pyqtSignal(int, int, str)
    generated = pyqtSignal(object)

    def __init__(self, projects, tasks=None, parent=None):
        super().__init__(parent)
        self.projects = [dict(project or {}) for project in (projects or [])]
        self.tasks = [dict(task or {}) for task in (tasks or [])]

    def run(self):
        results = []
        total = len(self.projects)
        for index, project in enumerate(self.projects, 1):
            if self.isInterruptionRequested():
                break
            name = str(project.get("name") or "未命名项目")
            self.progressed.emit(index - 1, total, f"正在分析：{name}")
            project_tasks = [
                task for task in self.tasks
                if not task_is_archived(task) and task_matches_project(task, project)
            ]
            insight = generate_project_insight(project, project_tasks)
            results.append({
                "projectId": project.get("id"),
                "projectName": name,
                "gaps": project_governance_gaps(project),
                "insight": insight,
            })
            self.progressed.emit(index, total, f"已完成：{name}")
        self.generated.emit(results)


class DailySummaryWorker(QThread):
    generated = pyqtSignal(object)

    def __init__(self, payload, projects=None, parent=None, visible=False):
        super().__init__(parent)
        self.payload = payload
        self.projects = [
            {
                key: project.get(key)
                for key in ("id", "codexProjectId", "name", "path", "rootPaths")
            }
            for project in (projects or [])
        ]
        self.visible = visible

    def run(self):
        self.payload["codexActivities"] = codex_activities_for_date(self.projects, self.payload["date"])
        thread_id = daily_summary_thread_id()
        if not thread_id:
            self.generated.emit({"error": "尚未配置固定的 Codex 每日总结任务"})
            return
        try:
            if self.visible:
                metadata = codex_thread_index().get(thread_id) or {}
                rollout_path = Path(metadata.get("rolloutPath") or "")
                if not metadata.get("title") or not rollout_path.is_file():
                    self.generated.emit({"error": "没有找到固定总结任务的本地会话记录"})
                    return
                baseline_size = rollout_path.stat().st_size
                from codex_hub.desktop_bridge import send_prompt_to_codex_thread

                send_prompt_to_codex_thread(
                    str(metadata["title"]),
                    daily_summary_prompt(self.payload, visible=True),
                )
                raw = wait_for_codex_thread_reply(rollout_path, baseline_size)
                self.generated.emit(parse_daily_summary_response(raw, self.payload, thread_id))
                return

            binary = find_summary_codex_binary()
            if not binary:
                self.generated.emit({"error": "未找到 Codex 可执行程序"})
                return
            with tempfile.TemporaryDirectory(prefix="codex-hub-summary-") as folder:
                folder = Path(folder)
                output_path = folder / "summary.json"
                command = [
                    binary, "exec", "resume", "--all", "--skip-git-repo-check", "--ignore-user-config",
                    "-o", str(output_path), thread_id, "-",
                ]
                result = subprocess.run(
                    command,
                    input=daily_summary_prompt(self.payload),
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(ROOT),
                    timeout=240,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode != 0:
                    lines = (result.stderr or result.stdout or "Codex 总结失败").strip().splitlines()
                    detail = " | ".join(lines[-4:])
                    self.generated.emit({"error": detail[:240]})
                    return
                raw = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else result.stdout.strip()
                self.generated.emit(parse_daily_summary_response(raw, self.payload, thread_id))
        except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            self.generated.emit({"error": str(error)[:240]})


def conversations_by_project(events):
    latest = {}
    for event in events:
        session_id = event.get("sessionId") or f"unknown:{event.get('projectId')}"
        key = (event["projectId"], session_id)
        if event.get("at", "") >= latest.get(key, {}).get("at", ""):
            latest[key] = event
    grouped = {}
    for (project_id, _session_id), event in latest.items():
        grouped.setdefault(project_id, []).append(event)
    for sessions in grouped.values():
        sessions.sort(key=lambda item: item.get("at", ""), reverse=True)
    return grouped


def event_time(activity):
    try:
        return datetime.fromisoformat(activity["at"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None


def codex_state(activity):
    state = activity_state(activity)
    if state == "running":
        return "running", "运行中", "#16803c"
    if state == "completed":
        return "completed", "已完成", "#2563eb"
    return "linked", "已关联", "#5f6368"


def project_display_state(project):
    """Return one consistent management state for a project across every view."""
    conversations = project.get("conversations") or []
    if any(codex_state(conversation)[0] == "running" for conversation in conversations):
        return "running", "运行中", "#087443", "#e8f7ef"
    if project.get("status") == "completed":
        return "completed", "已完成", "#2563eb", "#edf3ff"
    if conversations:
        return "linked", "已关联", "#526071", "#eef2f6"
    return "unlinked", "未关联", "#7a8798", "#f2f4f7"


def project_priority_key(project):
    value = str((project or {}).get("priority") or "normal")
    return value if value in PROJECT_PRIORITY else "normal"


def build_project_next_step_task(project, target_date, now, conversation=None, task_id=None):
    title = str((project or {}).get("nextStep") or "").strip()
    stable_project_id = (project or {}).get("savedId") or (project or {}).get("codexProjectId") or (project or {}).get("id")
    conversation = conversation or {}
    task = {
        "id": task_id or str(uuid.uuid4()),
        "title": title,
        "category": (project or {}).get("category") or "未分类",
        "projectId": stable_project_id,
        "projectNameSnapshot": str((project or {}).get("name") or "").strip(),
        "projectCategorySnapshot": str((project or {}).get("category") or "未分类").strip(),
        "sessionId": conversation.get("sessionId"),
        "conversationTitle": conversation_name(conversation) if conversation.get("sessionId") else "",
        "status": "planned",
        "date": target_date,
        "notes": "",
        "origin": "project_next_step",
        "projectNextStep": title,
        "createdAt": now,
        "updatedAt": now,
    }
    record_task_status_event(task, None, "planned", now, "project")
    return task


def open_project_tasks(tasks, project):
    return [
        task for task in (tasks or [])
        if task_matches_project(task, project)
        and not task_is_archived(task)
        and not task_is_superseded_daily_record(task)
        and task.get("status", "planned") != "done"
    ]


def project_strategy_execution_signals(project):
    """Keep deliberate strategic focus separate from evidence of work in progress."""
    if (project or {}).get("status", "active") != "active":
        status_text = STATUS_TEXT.get((project or {}).get("status"), "非活动")
        return {
            "strategic": False, "executing": False,
            "strategicReason": f"项目状态为{status_text}，不计入战略重点",
            "executionReason": f"项目状态为{status_text}，不计入实际推进",
            "executionColor": "#66758a", "executionBackground": "#eef2f6",
        }
    live, reason, _active_tasks, running_conversations = project_live_work_state(project)
    return {
        "strategic": project_priority_key(project) == "focus",
        "executing": live,
        "strategicReason": "已由你手动设为战略重点" if project_priority_key(project) == "focus" else "尚未设为战略重点",
        "executionReason": reason if live else "当前没有进行中的任务或 Codex 对话",
        "executionColor": "#087443" if running_conversations else "#1d4ed8",
        "executionBackground": "#e7f7ef" if running_conversations else "#e8f0ff",
    }


def project_focus_state(project):
    """Resolve the legacy combined focus/execute facet without conflating its labels."""
    signals = project_strategy_execution_signals(project)
    if signals["strategic"]:
        return True, "重点", "已手动设为战略重点", "#7c3aed", "#f1eaff"
    if signals["executing"]:
        return True, "推进中", signals["executionReason"], signals["executionColor"], signals["executionBackground"]
    return False, "", signals["executionReason"], "#66758a", "#eef2f6"


def project_stage_key(project):
    value = str((project or {}).get("stage") or "execution")
    return value if value in PROJECT_STAGE else "execution"


def project_health_key(project):
    value = str((project or {}).get("health") or "on_track")
    return value if value in PROJECT_HEALTH else "on_track"


def project_governance_gap_text(project):
    return "、".join(
        PROJECT_DECISION_FIELDS.get(field, field)
        for field in project_governance_gaps(project)
    )


def project_control_state(project):
    """Return the decision-facing project state and its most useful explanation."""
    if project.get("status") == "completed":
        return "completed", "已完成", "#2563eb", "#edf3ff", "项目已完成"
    if project.get("status") in {"paused", "idea"}:
        return "paused", STATUS_TEXT.get(project.get("status"), "暂缓"), "#7c3aed", "#f3edff", "当前不在主动推进"
    blocker = str(project.get("blocker") or "").strip()
    health = project_health_key(project)
    if health == "blocked" or blocker:
        reason = blocker or "项目已标记阻塞"
        duration = project_blocker_duration_label(project)
        if duration == "时长未知":
            reason += " · 开始时间未知"
        else:
            estimate = "（从最近确认起）" if project.get("blockedAtEstimated") else ""
            reason += f" · 已持续 {duration}{estimate}"
        return "blocked", "阻塞", "#b42318", "#fff0ee", reason
    if health == "attention" and bool(str(project.get("reviewedAt") or "").strip()):
        return "attention", "需关注", "#b54708", "#fff4e5", "已确认关注；请处理风险，并在状态变化后更新"
    if not str(project.get("nextStep") or "").strip():
        reason = "上一项下一步已完成，请明确后续动作" if project.get("nextStepReviewNeeded") else "尚未设置下一步"
        return "on_track", "正常", "#087443", "#e7f7ef", reason
    gap_text = project_governance_gap_text(project)
    if gap_text:
        return "review", "待补全", "#315f9b", "#edf4ff", f"复核前先补全：{gap_text}"
    if project_review_trigger(project) == "drift":
        drift = project_review_drift(project)
        labels = "、".join(change.get("label") or change.get("field") or "项目决策" for change in drift[:3])
        suffix = f"等 {len(drift)} 项" if len(drift) > 3 else ""
        return "review", "有变化", "#315f9b", "#edf4ff", f"{labels}{suffix}与上次记录不同"
    return "on_track", "正常", "#087443", "#e7f7ef", "按当前下一步推进"


def project_review_summary(project):
    reviewed_at = str((project or {}).get("reviewedAt") or "").strip()
    drift_count = len(project_review_drift(project))
    if reviewed_at:
        when = format_project_decision_time(reviewed_at, compact=True)
        if drift_count:
            return f"上次记录 {when} · {drift_count} 项关键变化待确认"
        return f"上次记录 {when} · 关键决策无变化"
    return "尚无变更基线 · 下次保存项目时自动建立"


def project_review_drift_presentation(project):
    """Describe real changes since the last comparable management baseline."""
    baseline = (project or {}).get("reviewBaseline")
    changes = project_review_drift(project)
    if not isinstance(baseline, dict):
        legacy = bool(str((project or {}).get("reviewedAt") or "").strip())
        return {
            "state": "baseline", "count": 0, "changes": [],
            "title": "尚无可比较的变更记录",
            "detail": "不需要单独确认；下次完整保存项目时会自动建立比较基线" if not legacy else "历史记录没有快照；下次完整保存项目时会自动建立",
        }
    if not changes:
        return {
            "state": "stable", "count": 0, "changes": [],
            "title": "关键决策无变化",
            "detail": "目标、验收标准、阶段、健康度、下一步和阻塞均与上次确认一致",
        }
    summaries = []
    for change in changes:
        before = compact_project_decision_value(change["field"], change["before"], 24)
        after = compact_project_decision_value(change["field"], change["after"], 24)
        summaries.append(f"{change['label']}：{before} → {after}")
    return {
        "state": "changed", "count": len(changes), "changes": changes,
        "title": f"自上次确认后 {len(changes)} 项关键变化",
        "detail": "；".join(summaries[:2]) + (f"；另 {len(summaries) - 2} 项" if len(summaries) > 2 else ""),
        "tooltip": "\n".join(summaries),
    }


PROJECT_COMMAND_TONE_COLORS = {
    "danger": ("#b42318", "#fff0ee"),
    "warning": ("#a15c00", "#fff4e5"),
    "primary": ("#1d4ed8", "#edf3ff"),
    "focus": ("#6d3fc0", "#f1eaff"),
    "success": ("#087443", "#e7f7ef"),
    "neutral": ("#526071", "#eef2f6"),
}


def project_command_row_presentation(project, command=None):
    """Keep project rows aligned with the workbench's one primary command."""
    stage_label = PROJECT_STAGE.get(project_stage_key(project), "执行")
    if not command:
        control_key, control_label, control_color, control_background, control_reason = project_control_state(project)
        next_step = str(project.get("nextStep") or "").strip()
        detail = (
            f"{stage_label} · {control_label}：{control_reason}"
            if control_key in {"blocked", "review", "attention"} else
            f"{stage_label} · {next_step or control_reason}"
        )
        return {
            "label": control_label, "detail": detail, "color": control_color,
            "background": control_background,
            "tooltip": f"阶段：{stage_label}\n健康度：{control_label}\n{control_reason}\n下一步：{next_step or '尚未设置'}",
        }
    key = str(command.get("key") or "")
    label = str(command.get("actionLabel") or "").strip() or {
        "completed": "已完成", "inactive": "待评估", "idle": "待完善",
    }.get(key, str(command.get("kind") or "当前状态"))
    title = str(command.get("title") or "当前项目").strip()
    reason = str(command.get("reason") or "").strip()
    detail = f"{stage_label} · {label}：{reason if key == 'attention' and reason else title}"
    color, background = PROJECT_COMMAND_TONE_COLORS.get(str(command.get("tone") or "neutral"), PROJECT_COMMAND_TONE_COLORS["neutral"])
    objective = str(command.get("objective") or "目标未明确")
    next_step = str(command.get("nextStep") or "下一步未明确")
    evidence = str(command.get("evidenceText") or "暂无执行证据")
    return {
        "label": label, "detail": detail, "color": color, "background": background,
        "tooltip": (
            f"首要动作：{title}\n判断依据：{reason or '当前状态无需额外说明'}\n"
            f"目标：{objective}\n下一步：{next_step}\n执行证据：{evidence}"
        ),
    }


def project_confirmation_counts(projects):
    """Count only missing essentials and comparable decision changes."""
    counts = {"governance": 0, "changes": 0, "total": 0}
    for project in projects or []:
        if not project_management_scope_matches(project, "review"):
            continue
        counts["total"] += 1
        if project_governance_gaps(project):
            counts["governance"] += 1
        else:
            counts["changes"] += 1
    return counts


def project_confirmation_caption(counts):
    """Name the event-driven queue by the actual work it contains."""
    counts = counts or {}
    total = int(counts.get("total") or 0)
    if total and int(counts.get("governance") or 0) == total:
        return "资料补全"
    if total and int(counts.get("changes") or 0) == total:
        return "变化确认"
    return "项目处理"


def project_baseline_batch_eligibility(project, today_tasks=None, today=None):
    """Allow batching only for a calm, complete first-baseline decision.

    Missing governance, an existing baseline, non-normal health, or live work
    that contradicts the saved next step all require deliberate one-by-one
    handling.  This keeps the convenience action from hiding a real decision.
    """
    project = project or {}
    if project.get("status", "active") != "active":
        return False, "项目当前不是进行中"
    if project_governance_gaps(project):
        return False, "管理资料尚未完整"
    if project_review_phase(project) != "baseline":
        return False, "已经建立过管理基线"
    if project_health_key(project) != "on_track":
        return False, "健康度需要逐项确认"
    date_key = today or QDate.currentDate().toString(Qt.ISODate)
    evidence = project_review_evidence(project, today_tasks or [], date_key)
    if evidence.get("alignmentState") == "divergent":
        return False, "实际执行方向需要先校准"
    return True, "可批量建立首次基线"


def project_baseline_batch_candidates(projects, today_tasks=None, today=None):
    """Return only projects that can truthfully share one baseline action."""
    return [
        project
        for project in projects or []
        if project_baseline_batch_eligibility(project, today_tasks, today)[0]
    ]


def project_confirmation_workload(projects, today_tasks=None, today=None):
    """Return only projects with a real event-driven review trigger."""
    queued = [
        project
        for project in projects or []
        if project_management_scope_matches(project, "review")
    ]
    return {
        "total": len(queued),
        "manual": queued,
        "manualCount": len(queued),
        "batch": [],
        "batchCount": 0,
    }


def project_review_urgency_summary(projects, now=None):
    """Calendar age is not urgency when no project decision changed."""
    return ""


def project_confirmation_priority_hint(projects):
    counts = project_confirmation_counts(projects)
    if counts["governance"]:
        return "缺项优先处理"
    if counts["changes"]:
        return "真实变化优先"
    return ""


def project_confirmation_sort_key(project):
    """Order missing essentials before larger comparable changes."""
    if project_governance_gaps(project):
        return 0, 0, project_management_sort_key(project)
    return 1, -len(project_review_drift(project)), project_management_sort_key(project)


def project_has_local_folder(project):
    """Require an explicit existing folder; an empty path must not mean the process CWD."""
    raw_path = str((project or {}).get("path") or "").strip()
    return bool(raw_path) and Path(raw_path).is_dir()


def project_confirmation_batch_summary(projects, include_routed=False):
    """Summarize review work; queue dialogs may include already-routed edge cases."""
    projects = list(projects or [])
    counts = project_confirmation_counts(projects)
    routed = max(0, len(projects) - counts["total"]) if include_routed else 0
    total = counts["total"] + routed
    if not total:
        return "本轮已完成"
    parts = []
    if counts["governance"]:
        parts.append(f"补全 {counts['governance']}")
    if counts["changes"]:
        parts.append(f"变化 {counts['changes']}")
    if routed:
        parts.append(f"状态确认 {routed}")
    return f"本轮剩余 {total} · " + " · ".join(parts)


def next_step_decision_batch_summary(projects):
    """Describe how the current next-step batch can be resolved."""
    projects = list(projects or [])
    if not projects:
        return "本轮已完成"
    codex_ready = sum(project_has_local_folder(project) for project in projects)
    manual = len(projects) - codex_ready
    parts = [f"本轮剩余 {len(projects)}"]
    if codex_ready:
        parts.append(f"Codex 可分析 {codex_ready}")
    if manual:
        parts.append(f"需手动补充 {manual}")
    return " · ".join(parts)


def lifecycle_calibration_batch_summary(items, tasks):
    """Show how much of a quiet-project batch is eligible to pause right now."""
    items = list(items or [])
    if not items:
        return "本轮已完成"
    protected = sum(
        bool(open_project_tasks(tasks, (item or {}).get("project") or {}))
        for item in items
    )
    pausable = len(items) - protected
    parts = [f"本轮剩余 {len(items)}"]
    if pausable:
        parts.append(f"可暂缓 {pausable}")
    if protected:
        parts.append(f"任务保护 {protected}")
    return " · ".join(parts)


def execution_alignment_batch_summary(alignments):
    """Expose task-choice complexity before the user enters an alignment batch."""
    alignments = list(alignments or [])
    if not alignments:
        return "本轮已完成"
    candidate_count = sum(len((item or {}).get("tasks") or []) for item in alignments)
    choice_count = sum(len((item or {}).get("tasks") or []) > 1 for item in alignments)
    parts = [f"本轮剩余 {len(alignments)}", f"候选任务 {candidate_count}"]
    if choice_count:
        parts.append(f"需选择 {choice_count}")
    return " · ".join(parts)


def project_management_scope_matches(project, scope):
    """Filter projects by decisions the user can act on, not by decorative metrics."""
    if scope == "focus":
        return project_focus_state(project)[0]
    if scope == "strategic_focus":
        return project_strategy_execution_signals(project)["strategic"]
    if scope == "executing":
        return project_strategy_execution_signals(project)["executing"]
    if scope == "needs_next":
        return project.get("status", "active") == "active" and not str(project.get("nextStep") or "").strip()
    if scope == "attention":
        blocker = str((project or {}).get("blocker") or "").strip()
        if (project or {}).get("status", "active") != "active":
            return False
        if project_health_key(project) == "blocked" or blocker:
            return True
        return project_health_key(project) == "attention" and bool(str((project or {}).get("reviewedAt") or "").strip())
    if scope == "review":
        return project_control_state(project)[0] == "review"
    if scope == "blocked":
        return project_control_state(project)[0] == "blocked"
    if scope == "paused":
        return project.get("status") in {"paused", "idea"}
    return True


PROJECT_DECISION_QUEUE_PRESENTATION = (
    ("attention", "风险处置", "\uE7BA", "#b42318", "#fff0ee", "处理已确认的风险与阻塞"),
    ("alignment", "执行校准", "\uE9D2", "#1d4ed8", "#edf3ff", "确认真实执行方向与项目下一步"),
    ("lifecycle", "生命周期", "\uE823", "#526071", "#eef2f6", "确认静默项目继续、暂缓或退出"),
    ("needs_next", "待定下一步", "\uE945", "#6d3fc0", "#f3edff", "为项目明确一个可执行下一步"),
    ("focus_commitment", "重点落地", "\uE735", "#7c3aed", "#f1eaff", "把战略重点的下一步落到任务板"),
    ("review", "项目变化", "\uE73E", "#315f9b", "#edf3ff", "补全必要资料或确认真实发生的关键变化"),
)


def project_decision_queue_counts(projects, routing):
    """Count the one primary management decision owned by each visible project."""
    counts = {queue_name: 0 for queue_name, *_rest in PROJECT_DECISION_QUEUE_PRESENTATION}
    for project in projects or []:
        primary = primary_project_decision(project, routing)
        queue_name = str((primary or {}).get("queue") or "")
        if queue_name in counts:
            counts[queue_name] += 1
    return counts


def project_decision_queue_summary(counts):
    parts = [
        f"{label} {int((counts or {}).get(queue_name) or 0)}"
        for queue_name, label, *_rest in PROJECT_DECISION_QUEUE_PRESENTATION
        if int((counts or {}).get(queue_name) or 0)
    ]
    return " · ".join(parts) if parts else "当前没有项目级管理待办"


def project_portfolio_overview(projects, routing, focus_capacity=None):
    """Build unambiguous cockpit counts from strategy, execution, risk, and decisions."""
    projects = list(projects or [])
    focus_state = portfolio_focus_capacity_state(projects, focus_capacity or DEFAULT_PORTFOLIO_FOCUS_CAPACITY)
    blocked_or_attention = sum(
        project_control_state(project)[0] in {"blocked", "attention"}
        for project in projects
    )
    decision_counts = project_decision_queue_counts(projects, routing)
    return {
        "total": len(projects),
        "strategic": len(focus_state["strategic"]),
        "focusCapacity": focus_state["capacity"],
        "executing": len(focus_state["executing"]),
        "executionOutsideFocus": len(focus_state["executionOutsideFocus"]),
        "focusWithoutExecution": len(focus_state["focusWithoutExecution"]),
        "focusAlignmentGap": len(focus_state["executionOutsideFocus"]) + len(focus_state["focusWithoutExecution"]),
        "focusGuidance": portfolio_focus_guidance(focus_state),
        "risk": blocked_or_attention,
        "decisionTotal": sum(decision_counts.values()),
        "decisionCounts": decision_counts,
    }


def project_portfolio_overview_text(metrics):
    parts = [
        f"{metrics['total']} 个项目",
        f"战略重点 {metrics['strategic']}/{metrics['focusCapacity']}",
        f"实际推进 {metrics['executing']}",
        f"风险/阻塞 {metrics['risk']}",
        f"管理待办 {metrics['decisionTotal']}",
    ]
    return "  ·  ".join(parts)


def workspace_view_signature(projects, tasks, time_bucket=None):
    """Fingerprint every visible workspace fact while keeping periodic refresh cheap."""
    bucket = str(time_bucket or datetime.now().strftime("%Y-%m-%dT%H"))
    dump_options = {
        "ensure_ascii": False,
        "sort_keys": True,
        "separators": (",", ":"),
        "default": str,
    }
    return (
        json.dumps(list(projects or []), **dump_options),
        json.dumps(list(tasks or []), **dump_options),
        bucket,
    )


def project_management_sort_key(project):
    control_order = {"blocked": 0, "attention": 1, "review": 2, "on_track": 3, "paused": 4, "completed": 5}
    signals = project_strategy_execution_signals(project)
    signal_order = (
        0 if signals["strategic"] else
        1 if signals["executing"] else
        3 if project_priority_key(project) == "later" else
        2
    )
    return (
        control_order.get(project_control_state(project)[0], 2),
        signal_order,
        0 if project.get("nextStep") else 1,
        str(project.get("name") or "").casefold(),
    )


def project_risk_priority_key(project, now=None):
    """Rank real blockers by known age, without fabricating urgency for unknown clocks."""
    state = project_control_state(project)[0]
    if state == "blocked":
        age_seconds = project_blocker_age_seconds(project, now)
        return (
            0,
            1 if age_seconds is None else 0,
            -(age_seconds or 0),
            project_management_sort_key(project),
        )
    return 1, 0, 0, project_management_sort_key(project)


def project_risk_batch_summary(projects, now=None):
    projects = list(projects or [])
    if not projects:
        return "当前风险队列已清空"
    blocked = [project for project in projects if project_control_state(project)[0] == "blocked"]
    attention_count = len(projects) - len(blocked)
    known = []
    for project in blocked:
        age_seconds = project_blocker_age_seconds(project, now)
        if age_seconds is not None:
            known.append((project, age_seconds))
    unknown_count = len(blocked) - len(known)
    parts = [f"待处置 {len(projects)}"]
    if blocked:
        parts.append(f"阻塞 {len(blocked)}")
    if attention_count:
        parts.append(f"需关注 {attention_count}")
    if known:
        oldest, _age = max(known, key=lambda item: item[1])
        duration = project_blocker_duration_label(oldest, now)
        estimate = "（起点估计）" if oldest.get("blockedAtEstimated") else ""
        parts.append(f"最长记录 {duration}{estimate}")
    if unknown_count:
        parts.append(f"时长待确认 {unknown_count}")
    return " · ".join(parts)


def portfolio_decision_groups(projects):
    ordered = sorted(projects or [], key=project_management_sort_key)
    return {
        "focus": [project for project in ordered if project_focus_state(project)[0]],
        "attention": sorted(
            [project for project in ordered if project_management_scope_matches(project, "attention")],
            key=project_risk_priority_key,
        ),
        "review": [project for project in ordered if project_management_scope_matches(project, "review")],
        "needs_next": [
            project for project in ordered
            if project_management_scope_matches(project, "needs_next")
        ],
    }


def portfolio_priority_decision(groups, capacity_state, alignments=None, lifecycle_items=None, wip_state=None, focus_commitments=None, overdue_tasks=None, completion_tasks=None):
    """Choose one calm, evidence-based management decision from competing queues."""
    groups = groups or {}
    capacity_state = capacity_state or {}
    alignments = list(alignments or [])
    lifecycle_items = list(lifecycle_items or [])
    wip_state = wip_state or {}
    focus_commitments = list(focus_commitments or [])
    overdue_tasks = list(overdue_tasks or [])
    completion_tasks = list(completion_tasks or [])

    def names_for(items, nested=False):
        projects = [(item.get("project") or {}) if nested else item for item in items]
        return [str(project.get("name") or "未命名项目") for project in projects]

    def preview(names, limit=3):
        text = "、".join(names[:limit])
        return f"{text} 等 {len(names)} 项" if len(names) > limit else text

    def finalize(decision):
        focus_capacity_count = int(capacity_state.get("overBy") or 0)
        if not focus_capacity_count:
            focus_capacity_count = len(capacity_state.get("executionOutsideFocus") or [])
        queue_counts = [
            ("attention", "风险/阻塞", len(groups.get("attention") or [])),
            ("task_wip", "WIP 超载", int(wip_state.get("overBy") or 0)),
            ("alignment", "执行校准", len(alignments)),
            ("completion_evidence", "待补成果", len(completion_tasks)),
            ("plan_backlog", "待安排计划", len(overdue_tasks)),
            ("needs_next", "待定下一步", len(groups.get("needs_next") or [])),
            ("focus_capacity", "重点校准", focus_capacity_count),
            ("focus_commitment", "重点落地", len(focus_commitments)),
            ("review", "项目变化", len(groups.get("review") or [])),
            ("lifecycle", "生命周期", len(lifecycle_items)),
        ]
        secondary_items = [
            {"scope": scope, "label": label, "count": count}
            for scope, label, count in queue_counts
            if count and scope != decision["scope"]
        ]
        full_secondary = " · ".join(
            f"{item['label']} {item['count']}" for item in secondary_items
        )
        visible_items = secondary_items[:3]
        compact_secondary = " · ".join(
            f"{item['label']} {item['count']}" for item in visible_items
        )
        if len(secondary_items) > len(visible_items):
            compact_secondary += f" · 另 {len(secondary_items) - len(visible_items)} 类"
        decision["secondaryItems"] = secondary_items
        decision["secondary"] = compact_secondary
        decision["secondaryFull"] = full_secondary
        return decision

    attention = list(groups.get("attention") or [])
    if attention:
        names = names_for(attention)
        blocked = sum(project_control_state(project)[0] == "blocked" for project in attention)
        detail = f"其中 {blocked} 项阻塞" if blocked else "已确认需要关注"
        return finalize({
            "scope": "attention", "count": len(attention), "title": "先处理风险与阻塞",
            "summary": f"{detail}：{preview(names)}", "names": names, "action": "进入处置",
            "outcome": "每个风险项目都已确认处置方向和可执行下一步",
        })

    wip_over_by = int(wip_state.get("overBy") or 0)
    if wip_over_by:
        tasks = list(wip_state.get("doing") or [])
        names = [str(task.get("title") or "未命名任务") for task in tasks]
        protected = len(wip_state.get("protected") or [])
        protected_text = f"，其中 {protected} 项由 Codex 运行保护" if protected else ""
        return finalize({
            "scope": "task_wip", "count": wip_over_by, "title": "收敛进行中任务",
            "summary": f"当前 {wip_state.get('count', len(tasks))}/{wip_state.get('limit', 0)}，超出容量 {wip_over_by} 项{protected_text}：{preview(names)}",
            "names": names, "action": "收敛并行",
            "outcome": f"进行中任务恢复至 {wip_state.get('limit', 0)} 项以内",
        })

    if alignments:
        names = names_for(alignments, nested=True)
        return finalize({
            "scope": "alignment", "count": len(alignments), "title": "校准实际执行方向",
            "summary": f"今日执行与项目已保存的下一步不一致：{preview(names)}",
            "names": names, "action": "逐项校准",
            "outcome": "每项实际工作都已对齐项目下一步，或明确保留原方向",
        })

    if completion_tasks:
        names = [str(task.get("title") or "未命名任务") for task in completion_tasks]
        return finalize({
            "scope": "completion_evidence", "count": len(completion_tasks), "title": "补齐任务完成成果",
            "summary": f"这些任务已结束，但日报和项目交接仍缺少可验证结果：{preview(names)}",
            "names": names, "action": "逐项补录",
            "outcome": "每项已完成任务都有可验证的成果记录",
        })

    if overdue_tasks:
        names = [str(task.get("title") or "未命名任务") for task in overdue_tasks]
        oldest = str(overdue_tasks[0].get("date") or "日期未知")
        return finalize({
            "scope": "plan_backlog", "count": len(overdue_tasks), "title": "重新安排历史计划",
            "summary": f"过去日期仍有未启动任务，最早来自 {oldest}：{preview(names)}",
            "names": names, "action": "逐项安排",
            "outcome": "每项历史计划都已重新安排、修订或明确保留",
        })

    needs_next = list(groups.get("needs_next") or [])
    if needs_next:
        names = names_for(needs_next)
        return finalize({
            "scope": "needs_next", "count": len(needs_next), "title": "明确项目下一步",
            "summary": f"这些活跃项目尚无可执行动作：{preview(names)}",
            "names": names, "action": "补齐决策",
            "outcome": "每个活跃项目都有一个明确、可执行的下一步",
        })

    over_by = int(capacity_state.get("overBy") or 0)
    outside_focus = list(capacity_state.get("executionOutsideFocus") or [])
    if over_by:
        names = names_for(capacity_state.get("strategic") or [])
        return finalize({
            "scope": "focus_capacity", "count": over_by, "title": "收敛战略重点",
            "summary": f"重点组合超出容量 {over_by} 项：{preview(names)}",
            "names": names, "action": "调整重点",
            "outcome": f"战略重点不超过 {capacity_state.get('capacity', 0)} 项容量",
        })
    if outside_focus:
        names = names_for(outside_focus)
        return finalize({
            "scope": "focus_capacity", "count": len(outside_focus), "title": "校准战略重点",
            "summary": f"{portfolio_focus_guidance(capacity_state)}：{preview(names)}",
            "names": names, "action": "调整重点",
            "outcome": "实际推进组合与已声明的战略重点保持一致",
        })

    if focus_commitments:
        names = names_for(focus_commitments, nested=True)
        return finalize({
            "scope": "focus_commitment", "count": len(focus_commitments), "title": "把战略重点落到任务板",
            "summary": f"已明确下一步，但尚未形成当前任务：{preview(names)}",
            "names": names, "action": "落实下一步",
            "outcome": "每个战略重点的下一步都已形成当前任务",
        })

    review = list(groups.get("review") or [])
    if review:
        names = names_for(review)
        return finalize({
            "scope": "review", "count": len(review), "title": "建立项目复核节奏",
            "summary": f"待建立或更新管理基线：{preview(names)}",
            "names": names, "action": "开始复核",
            "outcome": "缺项已补全，首次基线或到期复核已确认",
        })

    if lifecycle_items:
        names = names_for(lifecycle_items, nested=True)
        return finalize({
            "scope": "lifecycle", "count": len(lifecycle_items), "title": "校准活跃项目组合",
            "summary": f"长期静默项目需要确认继续或暂缓：{preview(names)}",
            "names": names, "action": "逐项确认",
            "outcome": "每个静默项目都已明确继续推进或暂缓",
        })
    return None


def matching_guided_project_item(project, items):
    """Return the latest plain or nested queue item for the same stable project."""
    references = project_reference_ids(project)
    if not references:
        return None
    for item in items or []:
        candidate = (
            item.get("project")
            if isinstance(item, dict) and isinstance(item.get("project"), dict)
            else item
        )
        if isinstance(candidate, dict) and project_reference_ids(candidate) & references:
            return item
    return None


def build_daily_summary_payload(tasks, projects, target_date, project_decisions=None):
    """Create a compact, factual source packet for the fixed Codex summary task."""
    project_index = {
        reference: project
        for project in projects
        for reference in project_reference_ids(project)
    }
    selected_tasks = []
    for task in tasks:
        if task_is_archived(task):
            continue
        if str(task.get("date") or "") != target_date:
            continue
        project = project_index.get(str(task.get("projectId") or ""), {})
        project_identity = task_project_identity(task, project)
        transitions = [
            {
                "at": str(event.get("at") or ""),
                "from": TASK_STATUS.get(event.get("from"), "新建"),
                "to": TASK_STATUS.get(event.get("to"), "更新"),
                "source": TASK_EVENT_SOURCES.get(event.get("source"), "手动"),
            }
            for event in reversed(task_status_events([task])[:8])
        ]
        schedule_changes = [
            {
                "at": str(event.get("at") or ""),
                "from": str(event.get("from") or ""),
                "to": str(event.get("to") or ""),
                "source": TASK_SCHEDULE_SOURCES.get(event.get("source"), "手动调整"),
            }
            for event in reversed(task_schedule_events([task])[:8])
        ]
        selected_tasks.append({
            "title": str(task.get("title") or "未命名任务"),
            "status": TASK_STATUS.get(task.get("status", "planned"), "计划"),
            "project": project_identity["name"],
            "projectLinkState": project_identity["state"],
            "notes": str(task.get("notes") or "").strip(),
            "completionOutcome": task_completion_outcome(task),
            "conversation": str(task.get("conversationTitle") or "").strip(),
            "statusTransitions": transitions,
            "scheduleChanges": schedule_changes,
        })

    local_timezone = datetime.now().astimezone().tzinfo
    activities = []
    for project in projects:
        for conversation in project.get("conversations") or []:
            point = event_time(conversation)
            if not point or point.astimezone(local_timezone).date().isoformat() != target_date:
                continue
            activities.append({
                "project": str(project.get("name") or "未命名项目"),
                "conversation": conversation_name(conversation),
                "state": codex_state(conversation)[1],
                "summary": str(conversation.get("summary") or "").strip(),
            })

    decisions = []
    for entry in project_decisions or []:
        if not isinstance(entry, dict):
            continue
        try:
            point = datetime.fromisoformat(str(entry.get("at") or "").replace("Z", "+00:00"))
            if point.tzinfo is not None:
                point = point.astimezone(local_timezone)
            if point.date().isoformat() != target_date:
                continue
        except ValueError:
            continue
        project = project_index.get(str(entry.get("projectId") or ""), {})
        kind = str(entry.get("kind") or "decision")
        decisions.append({
            "project": str(entry.get("projectName") or project.get("name") or "未命名项目"),
            "at": str(entry.get("at") or ""),
            "kind": {"review": "项目复核", "alignment": "执行方向确认", "lifecycle": "项目生命周期", "closeout": "项目收尾"}.get(kind, "项目决策"),
            "action": str(entry.get("action") or ""),
            "isCompletionEvidence": kind == "closeout" and entry.get("action") in {"complete", "revise"},
            "source": PROJECT_DECISION_SOURCES.get(entry.get("source"), "手动决策"),
            "summary": format_project_decision_summary(entry),
            "changes": [
                {
                    "field": str(change.get("label") or PROJECT_DECISION_FIELDS.get(change.get("field"), "项目字段")),
                    "before": display_project_decision_value(change.get("field"), change.get("before")),
                    "after": display_project_decision_value(change.get("field"), change.get("after")),
                }
                for change in entry.get("changes") or []
                if isinstance(change, dict)
            ],
        })
    decisions.sort(key=lambda item: item.get("at", ""))
    return {"date": target_date, "tasks": selected_tasks, "codexActivities": activities, "projectDecisions": decisions[-40:]}


def _reverse_jsonl_lines(path):
    """Yield JSONL lines newest-first without loading a rollout into memory."""
    with path.open("rb") as file:
        if not path.stat().st_size:
            return
        with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
            end = len(data)
            while end > 0:
                newline = data.rfind(b"\n", 0, end)
                start = newline + 1
                line = data[start:end].strip()
                end = newline if newline >= 0 else 0
                if line:
                    yield line


def _activity_excerpt(value, limit=180):
    text = " ".join(str(value or "").split())
    if not text or text.startswith(("<environment_context>", "<model_switch>", "<permissions", "<codex_delegation>")):
        return ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def codex_activities_for_date(projects, target_date, index=None, thread_projects=None):
    """Read actual per-day activity from indexed user rollouts, not card timestamps."""
    index = codex_thread_index() if index is None else index
    thread_projects = codex_thread_project_map(projects, index) if thread_projects is None else thread_projects
    projects_by_id = {}
    for project in projects:
        if project.get("id"):
            projects_by_id[str(project["id"])] = project
        if project.get("codexProjectId"):
            projects_by_id[str(project["codexProjectId"])] = project

    try:
        local_timezone = datetime.now().astimezone().tzinfo
        day_start = datetime.fromisoformat(target_date).replace(tzinfo=local_timezone)
    except ValueError:
        return []
    day_end = day_start + timedelta(days=1)
    excluded_thread = daily_summary_thread_id()
    activities = []

    for thread_id, metadata in index.items():
        if thread_id == excluded_thread:
            continue
        path = Path(metadata.get("rolloutPath") or "")
        if not path.is_file():
            continue
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, local_timezone) < day_start:
                continue
        except OSError:
            continue

        user_turns = 0
        highlights = []
        latest_result = ""
        first_at = ""
        last_at = ""
        try:
            for raw_line in _reverse_jsonl_lines(path):
                try:
                    record = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                timestamp = str(record.get("timestamp") or "")
                if not timestamp:
                    continue
                try:
                    point = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    if point.tzinfo is None:
                        point = point.replace(tzinfo=timezone.utc)
                    point = point.astimezone(local_timezone)
                except ValueError:
                    continue
                if point >= day_end:
                    continue
                if point < day_start:
                    break

                payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                if record.get("type") != "event_msg":
                    continue
                event_type = payload.get("type")
                if event_type not in {"user_message", "agent_message"}:
                    continue
                first_at = point.isoformat()
                if not last_at:
                    last_at = point.isoformat()
                if event_type == "user_message":
                    user_turns += 1
                    excerpt = _activity_excerpt(payload.get("message"))
                    if excerpt and len(highlights) < 5:
                        highlights.append(excerpt)
                elif not latest_result:
                    latest_result = _activity_excerpt(payload.get("message"), 260)
        except OSError:
            continue

        if not user_turns and not latest_result:
            continue
        project = projects_by_id.get(str(thread_projects.get(thread_id) or "")) or matched_project(projects, metadata.get("cwd"))
        fallback_name = Path(str(metadata.get("cwd") or "").replace("\\\\?\\", "")).name
        activities.append({
            "project": str((project or {}).get("name") or fallback_name or "未归类 Codex"),
            "conversation": str(metadata.get("title") or f"Codex 对话 {thread_id[-6:]}"),
            "userTurns": user_turns,
            "firstAt": first_at,
            "lastAt": last_at,
            "recentRequests": highlights,
            "latestResult": latest_result,
        })

    activities.sort(key=lambda item: item.get("lastAt", ""), reverse=True)
    return activities[:30]


def daily_summary_prompt(payload, visible=False):
    source = json.dumps(payload, ensure_ascii=False, indent=2)
    task_count = len(payload.get("tasks") or [])
    activity_count = len(payload.get("codexActivities") or [])
    decision_count = len(payload.get("projectDecisions") or [])
    turn_count = sum(int(item.get("userTurns") or 0) for item in payload.get("codexActivities") or [])
    work_item_count = task_count + activity_count + decision_count
    rules = (
        "你是固定的每日工作总结助手。请只根据下面提供的昨日记录总结，不要虚构完成情况。\n"
        f"本次共覆盖 {work_item_count} 个工作项：{task_count} 项昨日计划任务、{activity_count} 个实际活跃的 Codex 对话（{turn_count} 次用户提问）、{decision_count} 项项目管理决策。必须综合全部记录后再总结。\n"
        "要求：overview 用自然、简洁的 2-3 句话说明昨天主要做了什么和当前结果，不超过 180 个汉字；"
        "completed 列出已完成成果；inProgress 列出仍在推进的工作及当前落点；nextFocus 给出今天最值得继续的事项。\n"
        "任务中的 completionOutcome 是人工确认的实际完成成果，应作为 completed 的首要证据；notes 只是计划说明，不能单独证明工作已完成。"
        "已完成任务若没有 completionOutcome，只能谨慎描述状态，不得补造结果。\n"
        "任务中的 scheduleChanges 只表示计划日期经过人工调整，不代表任务已开始或完成；可以用于说明重新安排，但不能写入 completed。\n"
        "projectDecisions 是人工确认的项目管理活动，可用于说明方向、阶段、风险和下一步发生了什么变化。只有 kind 为‘项目收尾’且 isCompletionEvidence 为 true 的记录，才是整个项目完成的人工确认成果；普通复核、字段变更、归档和重新打开都不能写入 completed。\n"
        "每个数组最多 4 条，每条不超过 60 个汉字。不要在 overview 里重复逐条清单，不要堆叠模型参数。"
        "如果某一类没有证据，返回空数组。每条包含项目名和实际动作，避免‘推进项目’这类空话。\n"
        "nextFocus 不只是重复未完成项，要结合现状给出具体、可执行的下一步进化建议，例如更可靠的验证、拆分或决策动作。\n"
    )
    schema = '{"overview":"...","completed":["..."],"inProgress":["..."],"nextFocus":["..."]}'
    if visible:
        output = (
            f"先注明“本次覆盖：{work_item_count} 个工作项 · {task_count} 项计划任务 · {activity_count} 个 Codex 对话 · {decision_count} 项项目决策 · {turn_count} 次提问”，再用“工作概览 / 完成成果 / 仍在推进 / 下一步进化建议”四个简短部分输出便于阅读的中文总结。"
            "最后单独一行输出一个 Markdown HTML 注释，注释内部先写 CODEX_HUB_JSON:，再紧跟用于软件写回的 JSON 对象，结构必须是："
            f"{schema}。格式示例：<!-- CODEX_HUB_JSON: {schema} -->。不要在该注释后添加内容。\n\n"
        )
    else:
        output = f"仅返回 JSON 对象，不要 Markdown 代码围栏，结构必须是：{schema}。\n\n"
    return rules + output + "昨日记录：\n" + source


def parse_daily_summary_response(raw, payload, thread_id):
    """Normalize pure JSON and the visible Codex response marker into one record."""
    raw = str(raw or "").strip()
    marker = "CODEX_HUB_JSON:"
    if marker in raw:
        raw = raw.rsplit(marker, 1)[1].strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL)
    start = raw.find("{")
    if start < 0:
        raise json.JSONDecodeError("Codex 返回中缺少 JSON", raw, 0)
    data, _ = json.JSONDecoder().raw_decode(raw[start:])
    if not isinstance(data, dict):
        raise json.JSONDecodeError("Codex 返回的总结不是 JSON 对象", raw, start)
    data["overview"] = str(data.get("overview") or "").strip()
    for key in ("completed", "inProgress", "nextFocus"):
        values = data.get(key)
        data[key] = [str(item).strip() for item in values if str(item).strip()][:4] if isinstance(values, list) else []
    data.update({
        "date": payload["date"],
        "threadId": thread_id,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "sourceCounts": {
            "tasks": len(payload.get("tasks") or []),
            "codexActivities": len(payload.get("codexActivities") or []),
            "projectDecisions": len(payload.get("projectDecisions") or []),
            "codexTurns": sum(int(item.get("userTurns") or 0) for item in payload.get("codexActivities") or []),
        },
    })
    return data


def wait_for_codex_thread_reply(rollout_path, baseline_size, timeout=240):
    """Wait for the visible Codex turn appended after ``baseline_size``."""
    deadline = time.monotonic() + timeout
    position = int(baseline_size)
    pending = b""
    task_started = False
    final_message = ""
    while time.monotonic() < deadline:
        try:
            current_size = rollout_path.stat().st_size
            if current_size < position:
                position = 0
                pending = b""
            if current_size > position:
                with rollout_path.open("rb") as file:
                    file.seek(position)
                    pending += file.read()
                    position = file.tell()
                lines = pending.split(b"\n")
                pending = lines.pop()
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    kind = record.get("type")
                    item = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                    if kind == "event_msg" and item.get("type") == "task_started":
                        task_started = True
                    if not task_started:
                        continue
                    if kind == "event_msg" and item.get("type") == "agent_message":
                        final_message = str(item.get("message") or final_message)
                    elif kind == "response_item" and item.get("type") == "message" and item.get("role") == "assistant":
                        parts = item.get("content") if isinstance(item.get("content"), list) else []
                        text_parts = [str(part.get("text") or "") for part in parts if isinstance(part, dict)]
                        if any(text_parts):
                            final_message = "".join(text_parts)
                    elif kind == "event_msg" and item.get("type") == "task_complete":
                        final_message = str(item.get("last_agent_message") or final_message)
                        if final_message.strip():
                            return final_message.strip()
                        raise RuntimeError("Codex 已结束总结，但没有返回可读取的内容")
        except OSError:
            pass
        time.sleep(0.2)
    raise TimeoutError("等待 Codex 每日总结超时")


def compact_summary_text(text, limit=150):
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    sentence_end = max(value.rfind("。", 0, limit), value.rfind("；", 0, limit))
    if sentence_end >= max(8, limit // 3):
        return value[:sentence_end + 1]
    return value[: max(1, limit - 1)].rstrip("，,；;。 ") + "…"


def daily_summary_suggestion_draft(suggestion, projects, summary_date=""):
    """Build an editable task draft and link only one unambiguous project."""
    text = " ".join(str(suggestion or "").split())
    folded = text.casefold()
    candidates = [
        project for project in projects or []
        if project.get("status", "active") == "active"
        and str(project.get("name") or "").strip()
        and str(project.get("name") or "").strip().casefold() in folded
    ]
    prefix_candidates = [
        project for project in candidates
        if folded.startswith(str(project.get("name") or "").strip().casefold())
    ]
    project = None
    if prefix_candidates:
        project = max(prefix_candidates, key=lambda item: len(str(item.get("name") or "")))
    elif len(candidates) == 1:
        project = candidates[0]
    title = text
    if project is not None:
        name = str(project.get("name") or "").strip()
        if folded.startswith(name.casefold()):
            remainder = text[len(name):].lstrip(" \t：:-—·|›")
            if remainder:
                title = remainder
    source_date = str(summary_date or "").strip()
    source_label = f"{source_date} 每日总结" if source_date else "每日总结"
    draft = {
        "title": title,
        "status": "planned",
        "notes": f"来源：{source_label} · 下一步进化建议\n原建议：{text}",
        "origin": "daily_summary",
        "sourceSummaryDate": source_date,
        "sourceSuggestion": text,
    }
    return draft, project


def find_daily_summary_suggestion_task(tasks, summary_date, suggestion):
    """Prevent one review suggestion from silently creating duplicate work."""
    source_date = str(summary_date or "").strip()
    expected = normalized_action_text(suggestion)
    return next(
        (
            task for task in tasks or []
            if task.get("origin") == "daily_summary"
            and str(task.get("sourceSummaryDate") or "").strip() == source_date
            and normalized_action_text(task.get("sourceSuggestion")) == expected
            and not task_is_archived(task)
            and not task_is_superseded_daily_record(task)
        ),
        None,
    )


def relative_time(activity):
    point = event_time(activity) if activity else None
    if not point:
        return "尚未记录 Codex 活动"
    minutes = max(0, int((datetime.now(timezone.utc) - point).total_seconds() // 60))
    if minutes < 1:
        return "刚刚同步"
    if minutes < 60:
        return f"{minutes} 分钟前"
    if minutes < 1440:
        return f"{minutes // 60} 小时前"
    return f"{minutes // 1440} 天前"


def conversation_name(activity):
    label = (activity or {}).get("conversationLabel")
    if label:
        return label
    session_id = (activity or {}).get("sessionId")
    return f"对话 {session_id[-6:]}" if session_id else "Codex 对话"


class ProjectEditor(QDialog):
    def __init__(self, parent, project=None, categories=None):
        super().__init__(parent)
        self.project = project
        self.insight_worker = None
        self.insight_applied = False
        self.completion_summary = None
        self.completion_objective_snapshot = None
        self.completion_criteria_snapshot = None
        self.setWindowTitle("编辑项目" if project else "新建项目")
        self.setObjectName("projectEditor")
        self.setMinimumSize(720, 390)
        self.resize(760, 460)
        self.setStyleSheet(STYLE + """
            QDialog#projectEditor QLabel[fieldLabel='true'] { color: #4a586b; font-size: 12px; font-weight: 500; }
            QDialog#projectEditor QLineEdit, QDialog#projectEditor QComboBox { min-height: 24px; font-size: 13px; }
        """)
        item = project or {
            "name": "", "category": "未分类", "path": "", "status": "active", "priority": "normal",
            "stage": "planning", "health": "on_track", "blocker": "",
        }
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 24, 28, 22); layout.setSpacing(12)
        title = QLabel("编辑项目" if project else "新建项目")
        title.setStyleSheet("font-size: 24px; font-weight: 600; color: #172033;")
        layout.addWidget(title)
        subtitle = QLabel("只需填写名称、分类和文件夹；其他资料按需补充")
        subtitle.setStyleSheet("color: #718096; font-size: 12px;"); layout.addWidget(subtitle)
        self.fields = {}
        name = QLineEdit(item.get("name", "")); name.setFixedHeight(40); name.setPlaceholderText("例如：Desktop Analytics App"); name.setAccessibleName("项目名称"); self.fields["name"] = name
        self.source_name = normalized_decision_value(item.get("sourceName"))
        if self.source_name:
            name.setToolTip("这是项目中心的本地显示名，不会修改 Codex 中的项目来源或本地文件夹")
        category = QComboBox(); category.setFixedHeight(40); category.setAccessibleName("类别")
        for category_name in (categories or load_categories())[1:]: category.addItem(category_name, category_name)
        category.setCurrentIndex(max(0, category.findData(item.get("category", "未分类")))); self.fields["category"] = category
        path = QLineEdit(item.get("path", "")); path.setFixedHeight(40); path.setPlaceholderText("选择项目所在文件夹"); path.setAccessibleName("本地路径"); self.fields["path"] = path
        status = QComboBox(); status.setFixedHeight(40); status.setAccessibleName("项目状态")
        for key, label in STATUS_TEXT.items(): status.addItem(label, key)
        status.setCurrentIndex(max(0, status.findData(item.get("status", "active")))); self.fields["status"] = status
        priority = QComboBox(); priority.setFixedHeight(40); priority.setAccessibleName("管理优先级")
        for key, label in PROJECT_PRIORITY.items(): priority.addItem(label, key)
        priority.setCurrentIndex(max(0, priority.findData(project_priority_key(item)))); self.fields["priority"] = priority
        stage = QComboBox(); stage.setFixedHeight(40); stage.setAccessibleName("当前阶段")
        for key, label in PROJECT_STAGE.items(): stage.addItem(label, key)
        stage.setCurrentIndex(max(0, stage.findData(project_stage_key(item)))); self.fields["stage"] = stage
        health = QComboBox(); health.setFixedHeight(40); health.setAccessibleName("项目健康度")
        for key, label in PROJECT_HEALTH.items(): health.addItem(label, key)
        health.setCurrentIndex(max(0, health.findData(project_health_key(item)))); self.fields["health"] = health

        def field_label(text):
            label = QLabel(text); label.setProperty("fieldLabel", True); return label

        form = QGridLayout(); form.setHorizontalSpacing(10); form.setVerticalSpacing(6)
        for column in range(6): form.setColumnStretch(column, 1)
        form.addWidget(field_label("项目名称（本地显示）" if self.source_name else "项目名称"), 0, 0, 1, 6)
        name_holder = QWidget(); name_layout = QHBoxLayout(name_holder); name_layout.setContentsMargins(0, 0, 0, 0); name_layout.setSpacing(7); name_layout.addWidget(name, 1)
        self.restore_source_name = QPushButton("使用 Codex 原名"); self.restore_source_name.setFixedHeight(40)
        self.restore_source_name.setToolTip(f"恢复来源名称：{self.source_name}" if self.source_name else "")
        self.restore_source_name.clicked.connect(lambda: name.setText(self.source_name)); name_layout.addWidget(self.restore_source_name)
        def sync_source_name_action(value):
            differs = bool(self.source_name and normalized_decision_value(value).casefold() != self.source_name.casefold())
            self.restore_source_name.setVisible(differs)
        name.textChanged.connect(sync_source_name_action); sync_source_name_action(name.text())
        form.addWidget(name_holder, 1, 0, 1, 6)
        form.addWidget(field_label("类别"), 2, 0, 1, 6)
        form.addWidget(category, 3, 0, 1, 6)
        form.addWidget(field_label("本地路径"), 4, 0, 1, 6)
        path_holder = QWidget(); path_layout = QHBoxLayout(path_holder); path_layout.setContentsMargins(0, 0, 0, 0); path_layout.setSpacing(7); path_layout.addWidget(path, 1)
        browse = QPushButton("选择文件夹"); browse.setFixedHeight(40); browse.setIcon(fluent_icon("\uE838", size=15)); browse.setIconSize(QSize(15, 15)); browse.clicked.connect(self.choose_folder); path_layout.addWidget(browse)
        form.addWidget(path_holder, 5, 0, 1, 6)
        layout.addLayout(form)

        self.advanced_toggle = QPushButton("更多项目资料（可选）")
        self.advanced_toggle.setCheckable(True); self.advanced_toggle.setChecked(False); self.advanced_toggle.setFixedHeight(36)
        self.advanced_toggle.setIcon(fluent_icon("\uE70D", color="#526071", size=13)); self.advanced_toggle.setIconSize(QSize(13, 13))
        self.advanced_toggle.setStyleSheet("QPushButton { color: #526071; background: #f7f9fc; border: 1px solid #d9e2ec; border-radius: 8px; padding: 5px 10px; text-align: left; font-size: 12px; font-weight: 600; } QPushButton:hover { background: #eef3f8; }")
        self.advanced_toggle.toggled.connect(self.set_advanced_visible); layout.addWidget(self.advanced_toggle)

        self.advanced_panel = QFrame(); self.advanced_panel.setObjectName("advancedProjectFields")
        self.advanced_panel.setStyleSheet("QFrame#advancedProjectFields { background: #f8fafc; border: 1px solid #dfe6ef; border-radius: 10px; }")
        advanced_layout = QVBoxLayout(self.advanced_panel); advanced_layout.setContentsMargins(14, 12, 14, 12); advanced_layout.setSpacing(10)
        management = QGridLayout(); management.setHorizontalSpacing(10); management.setVerticalSpacing(6)
        management.addWidget(field_label("项目状态"), 0, 0); management.addWidget(field_label("管理优先级"), 0, 1)
        management.addWidget(status, 1, 0); management.addWidget(priority, 1, 1)
        management.addWidget(field_label("当前阶段"), 2, 0); management.addWidget(field_label("项目健康度"), 2, 1)
        management.addWidget(stage, 3, 0); management.addWidget(health, 3, 1)
        management.setColumnStretch(0, 1); management.setColumnStretch(1, 1); advanced_layout.addLayout(management)

        definition = QHBoxLayout(); definition.setSpacing(10)
        objective_box = QVBoxLayout(); objective_box.setSpacing(6); objective_box.addWidget(field_label("项目目标"))
        self.objective = QTextEdit(); self.objective.setFixedHeight(68); self.objective.setPlainText(str(item.get("objective") or ""))
        self.objective.setPlaceholderText("这个项目最终要交付或解决什么？")
        self.objective.setAccessibleName("项目目标"); objective_box.addWidget(self.objective); definition.addLayout(objective_box, 1)
        criteria_box = QVBoxLayout(); criteria_box.setSpacing(6); criteria_box.addWidget(field_label("验收标准（可逐步补充）"))
        self.success_criteria = QTextEdit(); self.success_criteria.setFixedHeight(68); self.success_criteria.setPlainText(str(item.get("successCriteria") or ""))
        self.success_criteria.setPlaceholderText("达到什么可验证结果时，项目可以结束？")
        self.success_criteria.setAccessibleName("项目验收标准"); criteria_box.addWidget(self.success_criteria); definition.addLayout(criteria_box, 1); advanced_layout.addLayout(definition)
        decision = QGridLayout(); decision.setHorizontalSpacing(10); decision.setVerticalSpacing(6)
        next_step_label = field_label("明确下一步"); decision.addWidget(next_step_label, 0, 0)
        blocker_label = field_label("当前阻塞"); decision.addWidget(blocker_label, 0, 1)
        self.next_step = QLineEdit(str(item.get("nextStep") or "")); self.next_step.setFixedHeight(40)
        self.next_step.setPlaceholderText("一个可以直接开始的具体动作")
        self.next_step.setAccessibleName("项目下一步"); decision.addWidget(self.next_step, 1, 0)
        self.blocker = QLineEdit(str(item.get("blocker") or "")); self.blocker.setFixedHeight(40)
        self.blocker.setPlaceholderText("没有阻塞可留空；有阻塞时写清具体原因")
        self.blocker.setAccessibleName("项目阻塞项"); decision.addWidget(self.blocker, 1, 1); advanced_layout.addLayout(decision)
        self.advanced_panel.hide(); layout.addWidget(self.advanced_panel)
        actions = QHBoxLayout(); actions.setContentsMargins(0, 10, 0, 0); actions.setSpacing(8)
        self.insight_button = QPushButton("Codex 自动整理"); self.insight_button.setFixedHeight(38); self.insight_button.setIcon(fluent_icon("\uE945", color="#1d4ed8", size=14)); self.insight_button.setIconSize(QSize(14, 14)); self.insight_button.clicked.connect(self.start_codex_insight); actions.addWidget(self.insight_button)
        self.insight_status = QLabel("选择文件夹后可让 Codex 填写项目态势"); self.insight_status.setMaximumWidth(280); self.insight_status.setStyleSheet("color: #748094; font-size: 11px;"); actions.addWidget(self.insight_status)
        actions.addStretch()
        cancel = QPushButton("取消"); cancel.setFixedHeight(38); cancel.clicked.connect(self.reject); actions.addWidget(cancel)
        save = QPushButton("保存项目"); save.setFixedHeight(38); save.setObjectName("primary"); save.clicked.connect(self.accept_project); actions.addWidget(save); layout.addLayout(actions)
        status.currentIndexChanged.connect(self.update_status_controls)
        self.update_status_controls()
        self.fields["name"].setFocus()

    def set_advanced_visible(self, visible):
        self.advanced_panel.setVisible(bool(visible))
        self.advanced_toggle.setText("收起项目资料" if visible else "更多项目资料（可选）")
        self.advanced_toggle.setIcon(fluent_icon("\uE70E" if visible else "\uE70D", color="#526071", size=13))
        self.resize(760, 720 if visible else 460)

    def update_status_controls(self):
        completed = self.fields["status"].currentData() == "completed"
        self.next_step.setEnabled(not completed); self.blocker.setEnabled(not completed)
        if completed:
            self.next_step.setToolTip("已完成项目不保留待执行下一步")
            self.blocker.setToolTip("已完成项目不保留当前阻塞")
        else:
            self.next_step.setToolTip(""); self.blocker.setToolTip("")

    def start_codex_insight(self):
        if self.insight_worker is not None:
            return
        path = Path(self.fields["path"].text().strip())
        if not path.is_dir():
            self.insight_status.setText("请先选择有效的项目文件夹")
            self.fields["path"].setFocus()
            return
        draft = {**(self.project or {}), **self.value()}
        if self.project:
            draft["conversations"] = self.project.get("conversations") or []
        tasks = [
            task for task in getattr(self.parent(), "today_tasks", [])
            if self.project and task_matches_project(task, self.project) and not task_is_archived(task)
        ]
        worker = ProjectInsightWorker(draft, tasks, self)
        worker.generated.connect(self.on_codex_insight)
        worker.finished.connect(lambda: self.finish_codex_insight(worker))
        self.insight_worker = worker
        self.insight_button.setEnabled(False); self.insight_button.setText("Codex 整理中…")
        self.insight_status.setText("正在只读分析目录、任务和对话")
        worker.start()

    def on_codex_insight(self, result):
        if result.get("error"):
            self.insight_status.setText("整理失败，稍后可重试")
            self.insight_status.setToolTip(str(result.get("error")))
            return
        if result.get("objective"): self.objective.setPlainText(result["objective"])
        if result.get("successCriteria"): self.success_criteria.setPlainText(result["successCriteria"])
        if result.get("nextStep"): self.next_step.setText(result["nextStep"])
        self.blocker.setText(result.get("blocker") or "")
        for field_name, key in (("stage", "stage"), ("health", "health")):
            field = self.fields[field_name]; index = field.findData(result.get(key))
            if index >= 0: field.setCurrentIndex(index)
        summary = str(result.get("summary") or "Codex 已生成建议")
        self.insight_applied = True
        self.insight_status.setText("已填入建议，请确认后保存")
        self.insight_status.setToolTip(summary)

    def finish_codex_insight(self, worker):
        if self.insight_worker is worker:
            self.insight_worker = None
        self.insight_button.setEnabled(True); self.insight_button.setText("Codex 自动整理")
        worker.deleteLater()

    def closeEvent(self, event):
        if self.insight_worker is not None:
            self.insight_status.setText("Codex 正在整理，请完成后再关闭")
            event.ignore(); return
        super().closeEvent(event)

    def reject(self):
        if self.insight_worker is not None:
            self.insight_status.setText("Codex 正在整理，请完成后再关闭")
            return
        super().reject()

    def choose_folder(self):
        start = self.fields.get("path").text().strip() or str(ROOT)
        folder = QFileDialog.getExistingDirectory(self, "选择项目文件夹", start)
        if folder:
            self.fields["path"].setText(folder)

    def accept_project(self):
        if not self.fields["name"].text().strip():
            self.fields["name"].setFocus(); QMessageBox.information(self, "项目名称为空", "请输入项目名称。")
            return
        if not self.fields["path"].text().strip():
            self.fields["path"].setFocus(); QMessageBox.information(self, "项目路径为空", "请选择项目所在文件夹。")
            return
        data = self.value()
        validation_error = project_management_validation_error(data)
        if validation_error:
            self.blocker.setFocus(); QMessageBox.information(self, "项目决策不完整", validation_error)
            return
        if (not self.project or self.project.get("status", "active") != "completed") and data.get("status") == "completed":
            pending = open_project_tasks(getattr(self.parent(), "today_tasks", []), self.project)
            initial = str((self.project or {}).get("lastCompletedOutcome") or "").strip() or latest_project_completion_outcome(self.project)
            closeout = ProjectCloseoutDialog(self, {**(self.project or {}), **data}, len(pending), initial)
            if closeout.exec_() != QDialog.Accepted:
                return
            self.completion_summary = closeout.value()
            self.completion_objective_snapshot = closeout.acceptance_objective()
            self.completion_criteria_snapshot = closeout.acceptance_criteria()
        self.accept()

    def value(self):
        data = {
            key: (control.currentData() if isinstance(control, QComboBox) else control.text().strip())
            for key, control in self.fields.items()
        }
        data["icon"] = (self.project or {}).get("icon", "")
        data["color"] = (self.project or {}).get("color", "#58d7f6")
        data["objective"] = self.objective.toPlainText().strip()
        data["successCriteria"] = self.success_criteria.toPlainText().strip()
        data["nextStep"] = self.next_step.text().strip()
        data["blocker"] = self.blocker.text().strip()
        if self.completion_summary is not None:
            data["completionSummary"] = self.completion_summary
            data["completionObjectiveSnapshot"] = self.completion_objective_snapshot or data["objective"]
            if self.completion_criteria_snapshot:
                data["completionCriteriaSnapshot"] = self.completion_criteria_snapshot
        return normalize_project_management_decision(self.project, data)[0]


class PortfolioGovernanceDialog(QDialog):
    """Reviewable batch completion for missing project-management decisions."""

    def __init__(self, parent, projects):
        super().__init__(parent)
        self.window = parent
        self.projects = list(projects or [])
        self.worker = None
        self.results = []
        self.candidate_checks = {}
        self.result_checks = {}
        self.setWindowTitle("Codex 项目治理")
        self.setObjectName("portfolioGovernanceDialog")
        self.setMinimumSize(780, 620)
        self.resize(860, 680)
        self.setStyleSheet(STYLE + """
            QDialog#portfolioGovernanceDialog { background: #f5f7fb; }
            QFrame#governanceHero { background: #ffffff; border: 1px solid #d9e3ef; border-radius: 14px; }
            QFrame#governanceRow { background: #ffffff; border: 1px solid #dce4ed; border-radius: 11px; }
            QFrame#governanceRow:hover { border-color: #b7c8dc; background: #fbfdff; }
            QCheckBox { color: #253247; font-size: 14px; font-weight: 650; spacing: 10px; }
            QCheckBox::indicator { width: 18px; height: 18px; }
        """)

        root = QVBoxLayout(self); root.setContentsMargins(24, 22, 24, 20); root.setSpacing(14)
        hero = QFrame(); hero.setObjectName("governanceHero")
        hero_layout = QHBoxLayout(hero); hero_layout.setContentsMargins(16, 14, 16, 14); hero_layout.setSpacing(12)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE945", color="#1d4ed8", size=21).pixmap(QSize(21, 21)))
        icon.setStyleSheet("background: #eaf1ff; border: none; border-radius: 11px;"); hero_layout.addWidget(icon)
        hero_text = QVBoxLayout(); hero_text.setSpacing(2)
        title = QLabel("Codex 项目治理"); title.setStyleSheet("color: #172033; font-size: 22px; font-weight: 720;"); hero_text.addWidget(title)
        subtitle = QLabel("只补齐缺失的目标或下一步；已有人工判断不会被覆盖，所有建议先审核再写入。")
        subtitle.setWordWrap(True); subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); hero_text.addWidget(subtitle)
        hero_layout.addLayout(hero_text, 1)
        self.hero_count = QLabel(); self.hero_count.setAlignment(Qt.AlignCenter); self.hero_count.setFixedHeight(32)
        self.hero_count.setStyleSheet("color: #1d4ed8; background: #edf3ff; border: none; border-radius: 8px; padding: 0 11px; font-size: 12px; font-weight: 700;")
        hero_layout.addWidget(self.hero_count); root.addWidget(hero)

        self.status = QLabel("选择本轮需要 Codex 只读分析的项目")
        self.status.setStyleSheet("color: #526071; font-size: 12px; font-weight: 600;"); root.addWidget(self.status)
        self.progress = QProgressBar(); self.progress.setFixedHeight(7); self.progress.setTextVisible(False)
        self.progress.setStyleSheet("QProgressBar { background: #dfe7f1; border: none; border-radius: 3px; } QProgressBar::chunk { background: #2563eb; border-radius: 3px; }")
        self.progress.hide(); root.addWidget(self.progress)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.rows_widget = QWidget(); self.rows_widget.setStyleSheet("background: transparent;")
        self.rows = QVBoxLayout(self.rows_widget); self.rows.setContentsMargins(0, 0, 5, 0); self.rows.setSpacing(8)
        scroll.setWidget(self.rows_widget); root.addWidget(scroll, 1)

        actions = QHBoxLayout(); actions.setSpacing(8)
        self.selection_caption = QLabel(); self.selection_caption.setStyleSheet("color: #748094; font-size: 11px;"); actions.addWidget(self.selection_caption)
        actions.addStretch()
        self.close_button = QPushButton("关闭"); self.close_button.setFixedHeight(38); self.close_button.clicked.connect(self.reject); actions.addWidget(self.close_button)
        self.start_button = QPushButton("开始智能补全"); self.start_button.setObjectName("primary"); self.start_button.setFixedHeight(38); self.start_button.clicked.connect(self.start_analysis); actions.addWidget(self.start_button)
        self.apply_button = QPushButton("应用所选建议"); self.apply_button.setObjectName("primary"); self.apply_button.setFixedHeight(38); self.apply_button.clicked.connect(self.apply_results); self.apply_button.hide(); actions.addWidget(self.apply_button)
        root.addLayout(actions)
        self.render_candidates()

    def clear_rows(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def render_candidates(self):
        self.clear_rows()
        self.candidate_checks = {}
        self.hero_count.setText(f"{len(self.projects)} 个缺项项目")
        for project in self.projects:
            gaps = project_governance_gaps(project)
            row = QFrame(); row.setObjectName("governanceRow"); row.setFixedHeight(68)
            row_layout = QHBoxLayout(row); row_layout.setContentsMargins(15, 8, 14, 8); row_layout.setSpacing(12)
            check = QCheckBox(str(project.get("name") or "未命名项目")); check.setChecked(True)
            check.stateChanged.connect(self.sync_selection); row_layout.addWidget(check, 1)
            gap_text = "、".join(PROJECT_DECISION_FIELDS.get(field, field) for field in gaps)
            gap = QLabel(f"待补：{gap_text}"); gap.setAlignment(Qt.AlignCenter); gap.setFixedHeight(27)
            gap.setStyleSheet("color: #8a5a00; background: #fff5dd; border: none; border-radius: 7px; padding: 0 9px; font-size: 11px; font-weight: 650;")
            row_layout.addWidget(gap)
            self.candidate_checks[str(project.get("id") or "")] = check
            self.rows.addWidget(row)
        self.rows.addStretch()
        self.sync_selection()

    def selected_projects(self):
        return [
            project for project in self.projects
            if self.candidate_checks.get(str(project.get("id") or ""))
            and self.candidate_checks[str(project.get("id") or "")].isChecked()
        ]

    def sync_selection(self):
        count = len(self.selected_projects())
        self.selection_caption.setText(f"已选择 {count} 项 · 逐个只读分析")
        self.start_button.setText(f"开始整理 {count} 项" if count else "请选择项目")
        self.start_button.setEnabled(count > 0 and self.worker is None)

    def start_analysis(self):
        selected = self.selected_projects()
        if not selected or self.worker is not None:
            return
        for check in self.candidate_checks.values():
            check.setEnabled(False)
        self.start_button.setEnabled(False); self.close_button.setEnabled(False)
        self.progress.setRange(0, len(selected)); self.progress.setValue(0); self.progress.show()
        self.status.setText("Codex 正在逐项读取项目目录；期间不会修改任何文件或项目判断。")
        worker = PortfolioGovernanceWorker(selected, self.window.today_tasks, self)
        worker.progressed.connect(self.on_progress)
        worker.generated.connect(self.on_generated)
        worker.finished.connect(lambda: self.finish_worker(worker))
        self.worker = worker
        worker.start()

    def on_progress(self, completed, total, message):
        self.progress.setRange(0, max(1, total)); self.progress.setValue(completed)
        self.status.setText(message)

    def on_generated(self, results):
        self.results = list(results or [])
        self.render_results()

    def render_results(self):
        self.clear_rows()
        self.result_checks = {}
        applicable = 0
        for index, result in enumerate(self.results):
            project = self.window.project_by_id(result.get("projectId"))
            insight = result.get("insight") or {}
            proposed, applied = merge_missing_project_insight(project, insight, result.get("gaps")) if project else ({}, [])
            error = str(insight.get("error") or "")
            changes = [change for change in project_decision_changes(project, proposed) if change.get("field") in applied] if project else []
            row = QFrame(); row.setObjectName("governanceRow"); row.setMinimumHeight(82)
            row_layout = QHBoxLayout(row); row_layout.setContentsMargins(15, 10, 14, 10); row_layout.setSpacing(12)
            check = QCheckBox(str(result.get("projectName") or "未命名项目")); check.setChecked(bool(changes)); check.setEnabled(bool(changes))
            check.stateChanged.connect(self.sync_result_selection)
            row_layout.addWidget(check, 0, Qt.AlignTop)
            text = QVBoxLayout(); text.setSpacing(3)
            if error:
                preview_text = f"整理失败：{compact_summary_text(error, 150)}"
                preview_color = "#b42318"
            elif changes:
                preview_text = "；".join(
                    f"{change.get('label')}：{display_project_decision_value(change.get('field'), change.get('after'))}"
                    for change in changes
                )
                preview_color = "#34445c"
                applicable += 1
            else:
                preview_text = "分析期间项目已补齐，或 Codex 未返回可用建议"
                preview_color = "#748094"
            preview = QLabel(preview_text); preview.setWordWrap(True); preview.setStyleSheet(f"color: {preview_color}; font-size: 12px;"); text.addWidget(preview)
            summary = compact_summary_text(insight.get("summary"), 180)
            if summary:
                basis = QLabel(f"判断依据：{summary}"); basis.setWordWrap(True); basis.setStyleSheet("color: #748094; font-size: 10px;"); text.addWidget(basis)
            row_layout.addLayout(text, 1)
            self.result_checks[index] = check
            self.rows.addWidget(row)
        self.rows.addStretch()
        self.hero_count.setText(f"{applicable} 项可应用")
        self.selection_caption.setText("建议已生成 · 勾选后写入项目决策记录")
        self.start_button.hide(); self.apply_button.show(); self.apply_button.setText(f"应用 {applicable} 项建议")
        self.apply_button.setEnabled(False)
        self.status.setText("整理完成。请审核建议；应用时仍会再次检查缺项，避免覆盖刚刚发生的人工修改。")

    def sync_result_selection(self):
        count = sum(check.isEnabled() and check.isChecked() for check in self.result_checks.values())
        self.apply_button.setText(f"应用 {count} 项建议" if count else "请选择建议")
        self.apply_button.setEnabled(count > 0 and self.worker is None)

    def finish_worker(self, worker):
        if self.worker is worker:
            self.worker = None
        worker.deleteLater()
        self.close_button.setEnabled(True)
        self.sync_result_selection()

    def apply_results(self):
        applied_projects = 0
        applied_fields = 0
        for index, result in enumerate(self.results):
            check = self.result_checks.get(index)
            if not check or not check.isEnabled() or not check.isChecked():
                continue
            project = self.window.project_by_id(result.get("projectId"))
            if not project:
                continue
            proposed, fields = merge_missing_project_insight(project, result.get("insight"), result.get("gaps"))
            if not fields:
                continue
            if self.window.update_project_management(project, proposed, notify=False, source="codex") is not None:
                applied_projects += 1
                applied_fields += len(fields)
        if applied_projects:
            self.window.statusBar().showMessage(
                f"Codex 已补齐 {applied_projects} 个项目的 {applied_fields} 项缺失信息，并写入决策记录",
                5000,
            )
            self.accept()
        else:
            self.status.setText("没有写入任何内容：所选缺项可能已经被人工补齐。")
            self.apply_button.setEnabled(False)

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("Codex 正在分析当前项目，请等待本轮完成后关闭。")
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("Codex 正在分析当前项目，请等待本轮完成后关闭。")
            event.ignore()
            return
        super().closeEvent(event)


class ElidedLabel(QLabel):
    def __init__(self, text=""):
        super().__init__(text)
        self.full_text = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def resizeEvent(self, event):
        shown = self.fontMetrics().elidedText(self.full_text, Qt.ElideRight, max(0, event.size().width()))
        self._applying_elision = True
        try:
            super().setText(shown)
        finally:
            self._applying_elision = False
        super().resizeEvent(event)

    def setText(self, text):
        if not getattr(self, "_applying_elision", False):
            self.full_text = str(text)
        display_text = self.full_text
        if self.width() > 0:
            display_text = self.fontMetrics().elidedText(self.full_text, Qt.ElideRight, self.width())
        self._applying_elision = True
        try:
            super().setText(display_text)
        finally:
            self._applying_elision = False


class ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit(); event.accept(); return
        super().keyPressEvent(event)


class SidebarCategoryButton(QPushButton):
    def __init__(self, category, count, active, handler):
        super().__init__()
        self.setObjectName("categoryNav")
        self.setProperty("active", active)
        self.setFixedHeight(36)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(f"项目分类 {category}，{count} 个项目")
        layout = QHBoxLayout(self); layout.setContentsMargins(14, 0, 10, 0); layout.setSpacing(8)
        title = ElidedLabel(category); title.setAttribute(Qt.WA_TransparentForMouseEvents)
        title.setStyleSheet(f"color: {'#1d4ed8' if active else '#53647a'}; border: none; background: transparent; font-size: 13px; font-weight: {'650' if active else '500'};")
        layout.addWidget(title, 1)
        badge = QLabel(str(count)); badge.setAttribute(Qt.WA_TransparentForMouseEvents); badge.setAlignment(Qt.AlignCenter); badge.setFixedSize(28, 22)
        badge.setStyleSheet(f"color: {'#1d4ed8' if active else '#64748b'}; background: {'#dce8ff' if active else '#eef2f6'}; border: none; border-radius: 7px; font-size: 11px; font-weight: 650;")
        layout.addWidget(badge)
        self.clicked.connect(handler)


class ConversationRow(QFrame):
    def __init__(self, conversation, window):
        super().__init__()
        self.conversation = conversation
        self.window = window
        self.setObjectName("conversationRow")
        self.setFixedHeight(50)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("在 Codex 中打开此对话")
        self.setAccessibleName(f"Codex 对话：{conversation_name(conversation)}")
        _state, label, color = codex_state(conversation)
        row_bg = "#edf9f3" if _state == "running" else "#ffffff"
        hover_bg = "#e4f6ed" if _state == "running" else "#f1f5fa"
        divider = "#a9ddc2" if _state == "running" else "#dce4ed"
        self.setStyleSheet(
            f"QFrame#conversationRow {{ background: {row_bg}; border: 1px solid {divider}; border-radius: 9px; }}"
            f"QFrame#conversationRow:hover {{ background: {hover_bg}; }}"
            "QFrame#conversationRow:focus { border: 1px solid #2474ff; }"
        )
        layout = QHBoxLayout(self); layout.setContentsMargins(14, 0, 13, 0); layout.setSpacing(12)
        thread_icon = QLabel(); thread_icon.setAttribute(Qt.WA_TransparentForMouseEvents); thread_icon.setFixedSize(26, 26); thread_icon.setAlignment(Qt.AlignCenter)
        thread_icon.setPixmap(fluent_icon("\uE8BD", color="#64748b", size=14).pixmap(QSize(14, 14))); thread_icon.setStyleSheet("background: #f1f5f9; border: none; border-radius: 7px;"); layout.addWidget(thread_icon)
        title = ElidedLabel(conversation_name(conversation)); title.setToolTip(conversation.get("summary") or conversation_name(conversation))
        title.setAttribute(Qt.WA_TransparentForMouseEvents)
        title.setStyleSheet("color: #26364c; font-size: 13px; font-weight: 600; border: none;"); layout.addWidget(title, 1)
        time_label = QLabel(relative_time(conversation)); time_label.setAttribute(Qt.WA_TransparentForMouseEvents); time_label.setFixedWidth(88); time_label.setStyleSheet("color: #748094; font-size: 11px; border: none;"); layout.addWidget(time_label)
        state_label = QLabel(f"● {label}"); state_label.setAttribute(Qt.WA_TransparentForMouseEvents); state_label.setFixedWidth(96); state_label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600; border: none;"); layout.addWidget(state_label)
        open_hint = QLabel(); open_hint.setAttribute(Qt.WA_TransparentForMouseEvents); open_hint.setFixedSize(16, 16); open_hint.setPixmap(fluent_icon("\uE76C", color="#718096", size=13).pixmap(QSize(13, 13))); open_hint.setAlignment(Qt.AlignCenter); layout.addWidget(open_hint)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.window.open_codex_conversation(self.conversation)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.window.open_codex_conversation(self.conversation); event.accept(); return
        super().keyPressEvent(event)


class ProjectDragHandle(QLabel):
    MIME_TYPE = "application/x-codex-project-id"

    def __init__(self, project_id):
        super().__init__()
        self.project_id = project_id
        self.press_position = None
        self.setFixedSize(20, 28)
        self.setAlignment(Qt.AlignCenter)
        self.setPixmap(fluent_icon("\uE76F", color="#8a8a8a", size=14).pixmap(QSize(14, 14)))
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("拖动调整项目顺序")
        self.setStyleSheet("border: none;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.press_position = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self.press_position is None:
            return
        if (event.pos() - self.press_position).manhattanLength() < QApplication.startDragDistance():
            return
        mime = QMimeData(); mime.setData(self.MIME_TYPE, self.project_id.encode("utf-8"))
        drag = QDrag(self); drag.setMimeData(mime); drag.exec_(Qt.MoveAction)
        self.setCursor(Qt.OpenHandCursor)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.OpenHandCursor)
        self.press_position = None
        super().mouseReleaseEvent(event)


class TaskDragHandle(QLabel):
    MIME_TYPE = "application/x-codex-task-id"

    def __init__(self, task):
        super().__init__()
        self.task_id = str((task or {}).get("id") or "")
        self.press_position = None
        self.setFixedSize(24, 26)
        self.setAlignment(Qt.AlignCenter)
        self.setPixmap(fluent_icon("\uE76F", color="#8794a6", size=14).pixmap(QSize(14, 14)))
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("拖动调整任务顺序；拖到其他列可同时改变状态")
        self.setAccessibleName(f"拖动任务 {(task or {}).get('title', '未命名任务')} 调整顺序或状态")
        self.setStyleSheet("border: none; background: transparent;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.task_id:
            self.press_position = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self.press_position is None or not self.task_id:
            return
        if (event.pos() - self.press_position).manhattanLength() < QApplication.startDragDistance():
            return
        mime = QMimeData(); mime.setData(self.MIME_TYPE, self.task_id.encode("utf-8"))
        drag = QDrag(self); drag.setMimeData(mime); drag.exec_(Qt.MoveAction)
        self.setCursor(Qt.OpenHandCursor)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.OpenHandCursor)
        self.press_position = None
        super().mouseReleaseEvent(event)


class TaskDropColumn(QFrame):
    def __init__(self, window, status):
        super().__init__()
        self.window = window
        self.status = status
        self.setAcceptDrops(True)
        self.setObjectName("taskColumn")
        self.setProperty("dropActive", False)
        self.current_drop_index = None

    def task_from_event(self, event):
        if not event.mimeData().hasFormat(TaskDragHandle.MIME_TYPE):
            return None
        try:
            task_id = bytes(event.mimeData().data(TaskDragHandle.MIME_TYPE)).decode("utf-8")
        except UnicodeDecodeError:
            return None
        return next((task for task in self.window.today_tasks if str(task.get("id") or "") == task_id), None)

    def set_drop_active(self, active):
        if bool(self.property("dropActive")) == bool(active):
            return
        self.setProperty("dropActive", bool(active))
        self.style().unpolish(self); self.style().polish(self)

    def drop_index(self, event, moving_task):
        moving_id = str((moving_task or {}).get("id") or "")
        cards = sorted(
            (
                card for card in self.children() if isinstance(card, TodayTaskCard)
                if card.task_id != moving_id
            ),
            key=lambda card: card.geometry().top(),
        )
        for index, card in enumerate(cards):
            if event.pos().y() < card.geometry().center().y():
                return index
        return len(cards)

    def update_drop_message(self, task, index):
        same_column = task.get("status", "planned") == self.status
        action = "调整为" if same_column else f"移至“{TASK_STATUS[self.status]}”并设为"
        self.window.statusBar().showMessage(f"松开后{action}第 {index + 1} 项")

    def dragEnterEvent(self, event):
        task = self.task_from_event(event)
        if task is None or self.status not in TASK_STATUS:
            event.ignore(); return
        self.set_drop_active(True)
        self.current_drop_index = self.drop_index(event, task)
        self.update_drop_message(task, self.current_drop_index)
        event.acceptProposedAction()

    def dragMoveEvent(self, event):
        task = self.task_from_event(event)
        if task is None or self.status not in TASK_STATUS:
            event.ignore()
            return
        index = self.drop_index(event, task)
        if index != self.current_drop_index:
            self.current_drop_index = index
            self.update_drop_message(task, index)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.set_drop_active(False)
        self.current_drop_index = None
        self.window.statusBar().clearMessage()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        task = self.task_from_event(event)
        target_index = self.drop_index(event, task) if task is not None else None
        self.set_drop_active(False)
        self.current_drop_index = None
        if task is None or self.status not in TASK_STATUS:
            event.ignore(); return
        event.acceptProposedAction()
        if not self.window.move_task_on_board(task.get("id"), self.status, target_index, source="drag"):
            self.window.statusBar().clearMessage()


class ProjectReorderContainer(QWidget):
    def __init__(self, window, category):
        super().__init__()
        self.window, self.category = window, category
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(ProjectDragHandle.MIME_TYPE):
            self.setStyleSheet("background: #edf4ff; border: 1px dashed #9fbbeb; border-radius: 10px;")
            self.window.statusBar().showMessage("拖到目标位置后松开，即可保存项目顺序")
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(ProjectDragHandle.MIME_TYPE):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")
        self.window.statusBar().clearMessage()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.setStyleSheet("")
        if self.window.search.text().strip():
            self.window.statusBar().showMessage("请先清除搜索内容，再调整项目顺序", 2500)
            return
        try:
            source_id = bytes(event.mimeData().data(ProjectDragHandle.MIME_TYPE)).decode("utf-8")
        except UnicodeDecodeError:
            return
        layout = self.layout()
        ids = [layout.itemAt(index).widget().project.get("id") for index in range(layout.count()) if isinstance(layout.itemAt(index).widget(), ProjectGroup)]
        if source_id not in ids:
            return
        target_index = len(ids)
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if isinstance(widget, ProjectGroup) and event.pos().y() < widget.geometry().center().y():
                target_index = ids.index(widget.project.get("id")); break
        source_index = ids.index(source_id); ids.pop(source_index)
        if source_index < target_index:
            target_index -= 1
        ids.insert(max(0, min(target_index, len(ids))), source_id)
        self.window.reorder_projects(self.category, ids)
        event.acceptProposedAction()


class ProjectMapRow(QFrame):
    def __init__(self, project, state_text, state_color, state_background, handler, command=None):
        super().__init__()
        self.handler = handler
        self.setObjectName("projectMapRow")
        self.setFixedHeight(56)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("打开项目；Codex 对话在项目内按行展开")
        conversations = list(project.get("conversations") or [])
        running_count = sum(codex_state(conversation)[0] == "running" for conversation in conversations)
        conversation_text = f"{len(conversations)} 个 Codex 对话" if conversations else "暂无 Codex 对话"
        if running_count:
            conversation_text += f" · {running_count} 个运行中"
        self.setAccessibleName(
            f"项目：{project.get('name') or '未命名项目'}，{conversation_text}，{state_text}；点击打开项目"
        )
        self.setStyleSheet(
            "QFrame#projectMapRow { background: #ffffff; border: 1px solid #e1e7ef; border-radius: 9px; }"
            "QFrame#projectMapRow:hover { background: #f5f8fc; border-color: #b8c8dc; }"
            "QFrame#projectMapRow:focus { border: 1px solid #2474ff; background: #e5f0ff; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 10, 0)
        layout.setSpacing(9)
        dot = QLabel()
        dot.setFixedSize(6, 6)
        dot.setToolTip(conversation_text)
        dot.setStyleSheet(f"background: {'#0f9f62' if running_count else state_color}; border: none; border-radius: 3px;")
        layout.addWidget(dot)
        text_box = QVBoxLayout(); text_box.setSpacing(1)
        name = ElidedLabel(project.get("name") or "未命名项目")
        name.setToolTip(project.get("name") or "未命名项目")
        name.setStyleSheet("color: #26364c; border: none; font-size: 13px; font-weight: 650;")
        text_box.addWidget(name)
        self.command_label = ElidedLabel(conversation_text)
        self.command_label.setToolTip(conversation_text)
        self.command_label.setStyleSheet("color: #718096; border: none; font-size: 10px;")
        text_box.addWidget(self.command_label)
        layout.addLayout(text_box, 1)
        state = QLabel(state_text)
        state.setAlignment(Qt.AlignCenter)
        state.setFixedSize(58, 24)
        state.setStyleSheet(
            f"color: {state_color}; background: {state_background}; border: none; "
            "border-radius: 12px; font-size: 11px; font-weight: 500;"
        )
        layout.addWidget(state)
        chevron = QLabel(); chevron.setFixedSize(16, 16); chevron.setPixmap(fluent_icon("\uE76C", color="#8794a6", size=13).pixmap(QSize(13, 13))); chevron.setAlignment(Qt.AlignCenter)
        layout.addWidget(chevron)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.handler:
            self.handler()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.handler:
            self.handler(); event.accept(); return
        super().keyPressEvent(event)


class ProjectMindMap(QGraphicsView):
    CATEGORY_COLORS = ["#2563eb"]
    CATEGORY_BACKGROUNDS = ["#edf3ff"]

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.map_scene = QGraphicsScene(self)
        self.setScene(self.map_scene)
        self.setFrameShape(QFrame.NoFrame)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setStyleSheet("QGraphicsView { background: transparent; border: none; } QScrollBar:horizontal, QScrollBar:vertical { background: transparent; }")
        self._last_viewport_width = 0

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.viewport().width()
        if abs(width - self._last_viewport_width) < 32:
            return
        self._last_viewport_width = width
        if getattr(self.window, "projects", None):
            QTimer.singleShot(0, lambda: self.update_map(self.window.shown(), self.window.categories))

    def add_connector(self, start_x, start_y, end_x, end_y, color, width=2):
        path = QPainterPath(); path.moveTo(start_x, start_y)
        midpoint = start_x + (end_x - start_x) * 0.5
        path.cubicTo(midpoint, start_y, midpoint, end_y, end_x, end_y)
        pen = QPen(QColor(color)); pen.setWidth(width); pen.setCapStyle(Qt.RoundCap)
        self.map_scene.addPath(path, pen)

    def add_node(self, text, x, y, width, height, style, handler=None, icon=None, tooltip=""):
        button = QPushButton(text); button.setFixedSize(width, height); button.setCursor(Qt.PointingHandCursor if handler else Qt.ArrowCursor)
        button.setStyleSheet(style)
        if icon:
            button.setIcon(icon); button.setIconSize(QSize(16, 16))
        if tooltip: button.setToolTip(tooltip)
        if handler: button.clicked.connect(handler)
        proxy = self.map_scene.addWidget(button); proxy.setPos(x, y)
        return button

    def update_map(self, projects, categories):
        self.map_scene.clear()
        groups = {}
        for project in projects:
            groups.setdefault(project.get("category") or "未分类", []).append(project)
        for items in groups.values():
            items.sort(key=project_management_sort_key)
        order = [category for category in categories if category != "全部" and category in groups]
        order += sorted(set(groups) - set(order))

        canvas_width = max(760, self.viewport().width() - 28)
        side_margin, column_gap = 16, 14
        columns = 3 if canvas_width >= 900 else 2
        card_width = int((canvas_width - side_margin * 2 - column_gap * (columns - 1)) / columns)

        column_heights = [8] * columns
        for category_index, category in enumerate(order):
            items = groups[category]
            color = self.CATEGORY_COLORS[category_index % len(self.CATEGORY_COLORS)]
            tint = self.CATEGORY_BACKGROUNDS[category_index % len(self.CATEGORY_BACKGROUNDS)]
            card_height = 66 + len(items) * 62
            column = min(range(columns), key=lambda index: column_heights[index])
            card_x = side_margin + column * (card_width + column_gap)
            card_y = column_heights[column]

            card = QFrame()
            card.setObjectName("mapCategoryCard")
            card.setFixedSize(card_width, card_height)
            card.setStyleSheet(
                "QFrame#mapCategoryCard { background: #ffffff; border: 1px solid #d9e2ec; border-radius: 12px; }"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.setSpacing(6)
            category_button = QPushButton(category)
            category_button.setCursor(Qt.PointingHandCursor)
            category_button.setToolTip(f"进入“{category}”分类管理项目")
            category_button.setFixedHeight(40)
            category_button.setStyleSheet(
                f"QPushButton {{ text-align: left; padding: 0 12px; color: {color}; background: {tint}; "
                "border: none; border-radius: 9px; font-size: 14px; font-weight: 700; }"
                "QPushButton:hover { background: #dfe9fb; }"
            )
            category_button.clicked.connect(lambda _checked=False, value=category: self.window.select_category(value))
            header = QHBoxLayout(); header.setContentsMargins(0, 0, 0, 0); header.setSpacing(8)
            header.addWidget(category_button, 1)
            count = QLabel(f"{len(items)} 项")
            count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            count.setFixedSize(44, 30)
            count.setStyleSheet("color: #718096; background: transparent; border: none; font-size: 11px; font-weight: 500;")
            header.addWidget(count)
            card_layout.addLayout(header)

            for project in items:
                _state, state_text, state_color, background = project_display_state(project)
                row = ProjectMapRow(
                    project, state_text, state_color, background,
                    lambda value=project: self.window.open_project_workspace(value),
                )
                card_layout.addWidget(row)
            card_layout.addStretch(1)
            proxy = self.map_scene.addWidget(card)
            proxy.setPos(card_x, card_y)
            column_heights[column] += card_height + 14

        scene_height = max(560, max(column_heights, default=560) + 12)
        self.map_scene.setSceneRect(0, 0, canvas_width, scene_height)


class ProjectGroup(QFrame):
    def __init__(self, project, window, command=None):
        super().__init__()
        self.project, self.window = project, window
        self.conversations = project.get("conversations") or []
        self.setObjectName("projectGroup")
        self.setStyleSheet("QFrame#projectGroup { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 11px; }")
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        header = QFrame(); header.setObjectName("projectHeader"); header.setFixedHeight(72); header.setStyleSheet("QFrame#projectHeader { background: #ffffff; border: none; border-radius: 10px; }")
        layout = QHBoxLayout(header); layout.setContentsMargins(12, 0, 12, 0); layout.setSpacing(10)
        layout.addWidget(ProjectDragHandle(project["id"]))
        self.toggle_button = QToolButton(); self.toggle_button.setFixedSize(32, 32); self.toggle_button.setAutoRaise(True); self.toggle_button.setToolTip("展开或收起 Codex 对话")
        self.toggle_button.setAccessibleName(f"展开或收起 {project['name']} 的 Codex 对话")
        self.toggle_button.setStyleSheet("QToolButton { border: none; border-radius: 7px; } QToolButton:hover, QToolButton:focus { background: #edf3fb; }")
        self.toggle_button.setEnabled(bool(self.conversations)); self.toggle_button.clicked.connect(self.toggle_details); layout.addWidget(self.toggle_button)
        name_box = QVBoxLayout(); name_box.setSpacing(2)
        name_row = QHBoxLayout(); name_row.setSpacing(6)
        name = ElidedLabel(project["name"]); name.setToolTip(project["name"]); name.setStyleSheet("font-size: 14px; font-weight: 680; color: #253247; border: none;"); name_row.addWidget(name, 1)
        name_box.addLayout(name_row)
        running_count = sum(codex_state(conversation)[0] == "running" for conversation in self.conversations)
        conversation_summary = f"{len(self.conversations)} 个 Codex 对话"
        if running_count:
            conversation_summary += f" · {running_count} 个运行中"
        conversation_detail = ElidedLabel(conversation_summary); conversation_detail.setToolTip(conversation_summary)
        conversation_detail.setStyleSheet("color: #718096; font-size: 10px; border: none;"); name_box.addWidget(conversation_detail)
        layout.addLayout(name_box, 1)
        self.setAccessibleName(f"{project.get('name') or '未命名项目'}；{conversation_summary}；可展开查看每个 Codex 对话")
        category_select = QComboBox(); category_select.setFixedSize(138, 34); category_select.addItems(window.categories[1:]); category_select.setCurrentText(project.get("category", "未分类")); category_select.setToolTip("调整项目分类"); category_select.setAccessibleName(f"{project['name']} 的项目分类")
        category_select.setStyleSheet("QComboBox { background: #f3f6fa; border: 1px solid transparent; border-radius: 8px; padding: 4px 10px; color: #526071; font-size: 12px; } QComboBox:hover, QComboBox:focus { background: #eef3f8; border-color: #cbd7e5; } QComboBox::drop-down { border: none; width: 22px; }")
        category_select.activated[str].connect(lambda category: window.change_project_category(project, category)); layout.addWidget(category_select)
        state_key, state_label, status_color, status_background = project_display_state(project)
        status_text = f"● {state_label}"
        count = QLabel(f"{len(self.conversations)} 个对话"); count.setFixedWidth(72); count.setAlignment(Qt.AlignRight | Qt.AlignVCenter); count.setStyleSheet("color: #748094; font-size: 11px; border: none;"); layout.addWidget(count)
        status = QLabel(status_text); status.setFixedSize(78, 28); status.setAlignment(Qt.AlignCenter); status.setStyleSheet(f"color: {status_color}; background: {status_background}; border-radius: 9px; padding: 4px 7px; font-size: 11px; font-weight: 650;"); layout.addWidget(status)
        continue_button = QPushButton("项目面板"); continue_button.setFixedSize(94, 34); continue_button.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); continue_button.setIconSize(QSize(14, 14)); continue_button.setToolTip("查看目标、下一步、任务和 Codex 对话")
        continue_button.setAccessibleName(f"打开项目面板 {project['name']}")
        continue_button.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c8d8f4; border-radius: 8px; padding: 4px 9px; font-size: 12px; font-weight: 650; } QPushButton:hover, QPushButton:focus { background: #dfe9fb; border-color: #9eb8e4; }")
        continue_button.clicked.connect(lambda: window.open_project_workspace(project)); layout.addWidget(continue_button)
        more = QToolButton(); more.setFixedSize(32, 32); more.setIcon(fluent_icon("\uE712", size=15)); more.setIconSize(QSize(15, 15)); more.setToolTip("更多项目操作")
        more.setAccessibleName(f"{project['name']} 的更多操作")
        more.setStyleSheet("QToolButton { border: none; border-radius: 7px; background: transparent; } QToolButton:hover, QToolButton:focus { background: #edf3fb; } QToolButton::menu-indicator { image: none; }")
        project_menu = QMenu(more)
        continue_action = project_menu.addAction(fluent_icon("\uE72A", color="#1d4ed8", size=14), "在 Codex 中继续"); continue_action.triggered.connect(lambda: window.continue_project(project))
        schedule_action = project_menu.addAction(fluent_icon("\uE787", color="#1d4ed8", size=14), "将下一步加入今日"); schedule_action.setEnabled(bool(str(project.get("nextStep") or "").strip())); schedule_action.triggered.connect(lambda: window.schedule_project_next_step(project))
        governance_action = project_menu.addAction(fluent_icon("\uE945", color="#1d4ed8", size=14), "Codex 补全缺项")
        governance_action.setEnabled(bool(project_governance_gaps(project)) and project_has_local_folder(project) and project.get("status", "active") != "completed")
        governance_action.triggered.connect(lambda: window.show_project_governance([project]))
        folder_action = project_menu.addAction(fluent_icon("\uE838", size=14), "打开文件夹"); folder_action.triggered.connect(lambda: window.open_folder(project))
        up_action = project_menu.addAction(fluent_icon("\uE74A", size=14), "向上移动"); up_action.triggered.connect(lambda: window.move_project(project, -1))
        down_action = project_menu.addAction(fluent_icon("\uE74B", size=14), "向下移动"); down_action.triggered.connect(lambda: window.move_project(project, 1))
        project_menu.addSeparator()
        edit_action = project_menu.addAction(fluent_icon("\uE70F", size=14), "编辑项目"); edit_action.triggered.connect(lambda: window.edit_project(project))
        delete_action = project_menu.addAction(fluent_icon("\uE7B8", color="#526071", size=14), "归档项目"); delete_action.triggered.connect(lambda: window.delete_project(project))
        more.setMenu(project_menu); more.setPopupMode(QToolButton.InstantPopup); layout.addWidget(more); root.addWidget(header)
        self.details = QFrame(); self.details.setObjectName("conversationDetails"); self.details.setStyleSheet("QFrame#conversationDetails { background: #f7f9fc; border: none; border-top: 1px solid #e3e9f0; border-radius: 0 0 10px 10px; }")
        detail_layout = QVBoxLayout(self.details); detail_layout.setContentsMargins(54, 8, 12, 10); detail_layout.setSpacing(6)
        for conversation in self.conversations:
            detail_layout.addWidget(ConversationRow(conversation, window))
        root.addWidget(self.details)
        default_open = state_key == "running"
        self.expanded = window.expansion_preferences.get(project["id"], default_open)
        self.apply_expansion()

    def toggle_details(self):
        if not self.conversations:
            return
        self.expanded = not self.expanded
        self.window.expansion_preferences[self.project["id"]] = self.expanded
        self.apply_expansion()

    def apply_expansion(self):
        self.details.setVisible(bool(self.conversations) and self.expanded)
        self.toggle_button.setArrowType(Qt.DownArrow if self.expanded and self.conversations else Qt.RightArrow)


class CategoryOrderDialog(QDialog):
    def __init__(self, parent, categories):
        super().__init__(parent)
        self.setWindowTitle("调整分类顺序")
        self.setMinimumSize(440, 430)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self); layout.setContentsMargins(26, 24, 26, 22); layout.setSpacing(11)
        title = QLabel("调整项目分类顺序"); title.setStyleSheet("font-size: 22px; font-weight: 600; color: #202124;"); layout.addWidget(title)
        hint = QLabel("按住分类并上下拖动。“全部”固定在首位，“未分类”固定在末位。")
        hint.setWordWrap(True); hint.setStyleSheet("color: #686868; font-size: 11px; margin-bottom: 4px;"); layout.addWidget(hint)
        self.category_list = QListWidget(); self.category_list.addItems(categories)
        self.category_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.category_list.setDefaultDropAction(Qt.MoveAction)
        self.category_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.category_list.setAccessibleName("项目分类顺序")
        self.category_list.setStyleSheet("QListWidget { background: #f7f9fc; border: 1px solid #dfe6ef; border-radius: 10px; padding: 7px; font-size: 13px; } QListWidget::item { background: #ffffff; border: 1px solid #e5eaf1; border-radius: 7px; padding: 11px 12px; margin: 3px; } QListWidget::item:selected { background: #eaf2ff; color: #1d4ed8; border-color: #9fbbeb; } QListWidget::item:hover { background: #f1f5fa; }")
        layout.addWidget(self.category_list, 1)
        if self.category_list.count(): self.category_list.setCurrentRow(0)
        move_actions = QHBoxLayout(); move_actions.setSpacing(7)
        up = QPushButton("上移"); up.setIcon(fluent_icon("\uE74A", size=14)); up.setIconSize(QSize(14, 14)); up.setFixedHeight(36); up.clicked.connect(lambda: self.move_selected(-1)); move_actions.addWidget(up)
        down = QPushButton("下移"); down.setIcon(fluent_icon("\uE74B", size=14)); down.setIconSize(QSize(14, 14)); down.setFixedHeight(36); down.clicked.connect(lambda: self.move_selected(1)); move_actions.addWidget(down)
        move_actions.addStretch(); layout.addLayout(move_actions)
        actions = QHBoxLayout(); actions.addStretch()
        cancel = QPushButton("取消"); cancel.setFixedHeight(38); cancel.clicked.connect(self.reject); actions.addWidget(cancel)
        save = QPushButton("保存顺序"); save.setFixedHeight(38); save.setObjectName("primary"); save.clicked.connect(self.accept); actions.addWidget(save); layout.addLayout(actions)

    def move_selected(self, offset):
        row = self.category_list.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= self.category_list.count():
            return
        item = self.category_list.takeItem(row)
        self.category_list.insertItem(target, item)
        self.category_list.setCurrentRow(target)

    def value(self):
        return [self.category_list.item(index).text() for index in range(self.category_list.count())]


class ArchivedProjectsDialog(QDialog):
    def __init__(self, parent, projects):
        super().__init__(parent)
        self.window = parent
        self.projects = list(projects or [])
        self.setWindowTitle("项目归档箱")
        self.setObjectName("archivedProjectsDialog")
        self.setMinimumSize(680, 440)
        self.resize(740, 500)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE7B8", color="#1d4ed8", size=20).pixmap(QSize(20, 20)))
        icon.setStyleSheet("background: #eaf1ff; border: 1px solid #c9d9f6; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("项目归档箱"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        hint = QLabel("归档只影响项目中心视图，不会删除本地文件或 Codex 对话；需要时可以随时恢复。")
        hint.setWordWrap(True); hint.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(hint); heading.addLayout(title_box, 1)
        self.count_label = QLabel(); self.count_label.setAlignment(Qt.AlignCenter); self.count_label.setFixedHeight(30)
        self.count_label.setStyleSheet("color: #315f9b; background: #edf3ff; border-radius: 8px; padding: 3px 10px; font-size: 11px; font-weight: 650;"); heading.addWidget(self.count_label)
        root.addLayout(heading)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.content = QWidget(); self.content.setStyleSheet("background: transparent;")
        self.rows = QVBoxLayout(self.content); self.rows.setContentsMargins(0, 0, 6, 0); self.rows.setSpacing(8)
        scroll.setWidget(self.content); root.addWidget(scroll, 1)

        actions = QHBoxLayout(); actions.addStretch()
        close = QPushButton("关闭"); close.setFixedHeight(38); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)
        self.render_rows()

    def render_rows(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.count_label.setText(f"{len(self.projects)} 个项目")
        if not self.projects:
            empty = QFrame(); empty.setObjectName("archiveEmpty"); empty.setMinimumHeight(220)
            empty.setStyleSheet("QFrame#archiveEmpty { background: #ffffff; border: 1px dashed #cbd5e1; border-radius: 12px; }")
            empty_layout = QVBoxLayout(empty); empty_layout.setAlignment(Qt.AlignCenter); empty_layout.setSpacing(8)
            empty_icon = QLabel(); empty_icon.setFixedSize(40, 40); empty_icon.setAlignment(Qt.AlignCenter)
            empty_icon.setPixmap(fluent_icon("\uE7B8", color="#7890aa", size=19).pixmap(QSize(19, 19))); empty_icon.setStyleSheet("background: #eef3f8; border-radius: 10px;"); empty_layout.addWidget(empty_icon, 0, Qt.AlignCenter)
            empty_title = QLabel("归档箱为空"); empty_title.setStyleSheet("color: #34445c; font-size: 15px; font-weight: 700;"); empty_layout.addWidget(empty_title, 0, Qt.AlignCenter)
            empty_hint = QLabel("从项目列表归档的项目会安全保存在这里"); empty_hint.setStyleSheet("color: #748094; font-size: 11px;"); empty_layout.addWidget(empty_hint, 0, Qt.AlignCenter)
            self.rows.addWidget(empty); self.rows.addStretch(); return
        for project in self.projects:
            row = QFrame(); row.setObjectName("archivedProjectRow"); row.setFixedHeight(76)
            row.setStyleSheet("QFrame#archivedProjectRow { background: #ffffff; border: 1px solid #dbe3ee; border-radius: 10px; }")
            row_layout = QHBoxLayout(row); row_layout.setContentsMargins(14, 8, 10, 8); row_layout.setSpacing(12)
            project_icon = QLabel(); project_icon.setFixedSize(34, 34); project_icon.setAlignment(Qt.AlignCenter)
            project_icon.setPixmap(fluent_icon("\uE8B7", color="#526f93", size=17).pixmap(QSize(17, 17))); project_icon.setStyleSheet("background: #f0f4f8; border-radius: 9px;"); row_layout.addWidget(project_icon)
            text = QVBoxLayout(); text.setSpacing(2)
            name = ElidedLabel(project.get("name") or "未命名项目"); name.setStyleSheet("color: #253247; font-size: 14px; font-weight: 680;"); text.addWidget(name)
            origin = "Codex 同步项目" if project.get("codexProjectId") else "本地手建项目"
            lifecycle = [entry for entry in self.window.project_decisions_for(project) if entry.get("kind") == "lifecycle"]
            archive_events = [entry for entry in lifecycle if entry.get("action") == "archive"]
            latest_archive = archive_events[0] if archive_events else None
            archive_text = f"{format_project_decision_time(latest_archive.get('at'), compact=True)} 归档" if latest_archive else "历史归档 · 时间未记录"
            cycle_text = f"  ·  已归档 {len(archive_events)} 次" if len(archive_events) > 1 else ""
            meta = QLabel(f"{project.get('category', '未分类')}  ·  {origin}  ·  {archive_text}{cycle_text}"); meta.setStyleSheet("color: #748094; font-size: 11px;"); text.addWidget(meta); row_layout.addLayout(text, 1)
            audit = QToolButton(); audit.setFixedSize(34, 34); audit.setIcon(fluent_icon("\uE81C", color="#315f9b", size=14)); audit.setIconSize(QSize(14, 14)); audit.setToolTip("查看项目决策与归档记录")
            audit.setAccessibleName(f"查看归档项目 {project.get('name', '')} 的完整记录"); audit.clicked.connect(lambda _checked=False, value=project: self.window.show_project_decision_history(value, read_only=True)); row_layout.addWidget(audit)
            restore = QPushButton("恢复项目"); restore.setFixedSize(92, 36); restore.setIcon(fluent_icon("\uE72C", color="#1d4ed8", size=13)); restore.setIconSize(QSize(13, 13))
            restore.setToolTip("恢复到原分类和原有排序"); restore.clicked.connect(lambda _checked=False, value=project: self.restore_project(value)); row_layout.addWidget(restore)
            self.rows.addWidget(row)
        self.rows.addStretch()

    def restore_project(self, project):
        if self.window.restore_project(project):
            self.projects = [item for item in self.projects if item.get("id") != project.get("id")]
            self.render_rows()


def task_editor_project_choices(projects, task=None):
    """Hide completed projects from new work while preserving historical task links."""
    existing_reference = str((task or {}).get("projectId") or "")
    return [
        project for project in projects or []
        if project.get("status", "active") != "completed"
        or existing_reference in project_reference_ids(project)
    ]


class TaskEditor(QDialog):
    def __init__(self, parent, projects, task=None, default_date=None, default_status=None, default_project_id=None, draft=None):
        super().__init__(parent)
        self.projects = task_editor_project_choices(projects, task)
        self.task = dict(task or draft or {})
        self.codex_requested = False
        self.setWindowTitle("编辑每日任务" if task else "新建每日任务")
        self.setObjectName("taskEditor"); self.setMinimumWidth(660)
        self.setStyleSheet(STYLE + """
            QDialog#taskEditor QLabel { font-size: 12px; color: #303030; }
            QDialog#taskEditor QLineEdit, QDialog#taskEditor QTextEdit, QDialog#taskEditor QComboBox,
            QDialog#taskEditor QDateEdit { font-size: 12px; }
            QDialog#taskEditor QPushButton { min-height: 20px; font-size: 12px; padding-left: 14px; padding-right: 14px; }
        """)
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 24, 28, 24); layout.setSpacing(11)
        title = QLabel("编辑每日任务" if task else "新建每日任务"); title.setStyleSheet("font-size: 24px; font-weight: 600; color: #202124;"); layout.addWidget(title)
        subtitle = QLabel("选择准确的项目层级，再安排当天要完成的工作")
        subtitle.setStyleSheet("font-size: 11px; color: #707070; margin-bottom: 5px;"); layout.addWidget(subtitle)
        task_content_label = QLabel("每日任务内容"); task_content_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #303030;"); layout.addWidget(task_content_label)
        self.title_field = QLineEdit(self.task.get("title", "")); self.title_field.setPlaceholderText("今天具体要完成什么？"); self.title_field.setFixedHeight(40); layout.addWidget(self.title_field)
        self.title_field.setAccessibleName("每日任务内容")
        layout.addWidget(QLabel("计划日期"))
        schedule = QHBoxLayout(); schedule.setSpacing(10)
        task_date = QDate.fromString(self.task.get("date") or default_date or QDate.currentDate().toString(Qt.ISODate), Qt.ISODate)
        self.date_field = QDateEdit(task_date if task_date.isValid() else QDate.currentDate()); self.date_field.setCalendarPopup(True); self.date_field.setDisplayFormat("yyyy年MM月dd日"); self.date_field.setFixedHeight(38); self.date_field.setAccessibleName("计划日期"); schedule.addWidget(self.date_field, 1); layout.addLayout(schedule)
        relation_title = QLabel("关联层级")
        relation_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #303030; margin-top: 4px;"); layout.addWidget(relation_title)
        relation = QFrame(); relation.setObjectName("taskRelation")
        relation.setStyleSheet("QFrame#taskRelation { background: #f7f9fc; border: 1px solid #e2e7ef; border-radius: 11px; } QFrame#taskRelation QLabel { background: transparent; border: none; }")
        relation_layout = QHBoxLayout(relation); relation_layout.setContentsMargins(14, 12, 14, 13); relation_layout.setSpacing(12)
        categories = [value for value in getattr(parent, "categories", []) if value != "全部"]
        for project in self.projects:
            category = project.get("category") or "未分类"
            if category not in categories: categories.append(category)
        current_project_id = self.task.get("projectId") or default_project_id
        current_project = next(
            (item for item in self.projects if str(current_project_id or "") in project_reference_ids(item)),
            None,
        )
        if current_project:
            current_project_id = current_project.get("id")
        current_category = (current_project or {}).get("category") or self.task.get("category")
        if current_category and current_category not in categories:
            categories.append(current_category)
        self.unresolved_project_id = current_project_id if current_project is None and current_project_id else None
        self.unresolved_project_name = str(self.task.get("projectNameSnapshot") or "").strip()
        self.unresolved_category = current_category
        self.category_field = QComboBox(); self.project_field = QComboBox(); self.conversation_field = QComboBox()
        for category in categories: self.category_field.addItem(category, category)
        if current_category:
            index = self.category_field.findData(current_category)
            if index >= 0: self.category_field.setCurrentIndex(index)
        for number, caption, field in (("1", "项目分类", self.category_field), ("2", "项目", self.project_field), ("3", "Codex 对话", self.conversation_field)):
            column = QVBoxLayout(); column.setSpacing(7)
            step_label = QLabel(f"{number}  {caption}"); step_label.setStyleSheet("color: #59616c; font-size: 11px; font-weight: 600;"); column.addWidget(step_label)
            field.setFixedHeight(38); field.setAccessibleName(caption); column.addWidget(field); relation_layout.addLayout(column, 1)
        layout.addWidget(relation)
        auto_hint = QLabel("关联具体对话后，检测到 Codex 开始处理时会自动转为“进行中”；不关联则由你手动调整状态。")
        auto_hint.setWordWrap(True); auto_hint.setStyleSheet("color: #64748b; font-size: 11px; padding: 0 3px 3px;"); layout.addWidget(auto_hint)
        self.preferred_project_id = current_project_id
        self.preferred_session_id = self.task.get("sessionId")
        self.category_field.currentIndexChanged.connect(self.load_projects)
        self.project_field.currentIndexChanged.connect(self.load_conversations)
        self.load_projects()
        self.status_field = QComboBox(); self.status_field.setAccessibleName("当前阶段")
        for status, label in TASK_STATUS.items(): self.status_field.addItem(label, status)
        status_index = self.status_field.findData(self.task.get("status") or default_status or "planned"); self.status_field.setCurrentIndex(max(0, status_index)); self.status_field.hide()
        layout.addWidget(QLabel("备注（可选）")); self.notes_field = QTextEdit(self.task.get("notes", "")); self.notes_field.setFixedHeight(76); self.notes_field.setAccessibleName("任务备注"); self.notes_field.setPlaceholderText("补充交付标准或关键提醒…"); layout.addWidget(self.notes_field)
        self.outcome_frame = QFrame(); self.outcome_frame.setObjectName("taskOutcomeEditor")
        self.outcome_frame.setStyleSheet("QFrame#taskOutcomeEditor { background: #eef8f2; border: 1px solid #c8e5d3; border-radius: 11px; } QFrame#taskOutcomeEditor QLabel { background: transparent; border: none; }")
        outcome_layout = QVBoxLayout(self.outcome_frame); outcome_layout.setContentsMargins(14, 11, 14, 13); outcome_layout.setSpacing(6)
        outcome_title = QLabel("完成成果"); outcome_title.setStyleSheet("color: #116b3b; font-size: 13px; font-weight: 700;"); outcome_layout.addWidget(outcome_title)
        outcome_hint = QLabel("写下可验证的结果，不重复任务名称；这会进入项目交接与每日总结。")
        outcome_hint.setWordWrap(True); outcome_hint.setStyleSheet("color: #547363; font-size: 11px;"); outcome_layout.addWidget(outcome_hint)
        self.outcome_field = QTextEdit(task_completion_outcome(self.task)); self.outcome_field.setFixedHeight(76); self.outcome_field.setAccessibleName("完成成果")
        self.outcome_field.setPlaceholderText("例如：完成 3 组对照实验，确认方案 B 在高噪声条件下更稳定。")
        outcome_layout.addWidget(self.outcome_field); layout.addWidget(self.outcome_frame)
        self.status_field.currentIndexChanged.connect(self.update_outcome_visibility)
        self.update_outcome_visibility()
        actions = QHBoxLayout(); actions.setSpacing(8); actions.setContentsMargins(0, 4, 0, 0); actions.addStretch()
        cancel = QPushButton("取消"); cancel.setFixedHeight(38); cancel.clicked.connect(self.reject); actions.addWidget(cancel)
        codex = QPushButton("在 Codex 中规划"); codex.setFixedHeight(38); codex.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); codex.setIconSize(QSize(14, 14)); codex.setToolTip("保存任务，复制规划提示并打开关联对话"); codex.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf4ff; border: none; font-weight: 600; } QPushButton:hover { background: #dfeaff; }"); codex.clicked.connect(self.accept_with_codex); actions.addWidget(codex)
        save = QPushButton("保存任务"); save.setFixedHeight(38); save.setObjectName("primary"); save.clicked.connect(self.accept_task); actions.addWidget(save); layout.addLayout(actions)
        self.title_field.setFocus()

    def load_projects(self):
        selected = self.project_field.currentData() if self.project_field.count() else self.preferred_project_id
        category = self.category_field.currentData()
        self.project_field.blockSignals(True); self.project_field.clear()
        self.project_field.addItem("不关联项目", None)
        if self.unresolved_project_id and category == self.unresolved_category:
            historical_name = self.unresolved_project_name or "历史项目（关联已失效）"
            self.project_field.addItem(f"{historical_name} · 历史关联", self.unresolved_project_id)
        for project in self.projects:
            if (project.get("category") or "未分类") == category:
                self.project_field.addItem(project.get("name", "未命名项目"), project.get("id"))
        if selected:
            index = self.project_field.findData(selected)
            if index >= 0: self.project_field.setCurrentIndex(index)
        self.project_field.blockSignals(False)
        self.load_conversations()

    def load_conversations(self):
        selected = self.conversation_field.currentData() if self.conversation_field.count() else self.preferred_session_id
        self.conversation_field.clear(); self.conversation_field.addItem("不关联对话", None)
        project_id = self.project_field.currentData()
        project = next((item for item in self.projects if item.get("id") == project_id), None)
        if project is None and project_id == self.unresolved_project_id and self.preferred_session_id:
            historical_title = str(self.task.get("conversationTitle") or "历史对话").strip()
            self.conversation_field.addItem(f"{historical_title} · 历史关联", self.preferred_session_id)
        for conversation in (project or {}).get("conversations", []):
            self.conversation_field.addItem(conversation_name(conversation), conversation.get("sessionId"))
        if selected:
            index = self.conversation_field.findData(selected)
            if index >= 0: self.conversation_field.setCurrentIndex(index)

    def accept_with_codex(self):
        if not self.conversation_field.currentData():
            QMessageBox.information(self, "请选择对话", "先选择一个 Codex 对话，才能在其中继续规划。")
            return
        self.codex_requested = True
        self.accept_task()

    def accept_task(self):
        if not self.title_field.text().strip():
            QMessageBox.information(self, "任务名称为空", "请输入一个清晰的任务名称。")
            return
        self.accept()

    def update_outcome_visibility(self):
        self.outcome_frame.setVisible(self.status_field.currentData() == "done")

    def value(self):
        selected_project_id = self.project_field.currentData()
        project = next((item for item in self.projects if item.get("id") == selected_project_id), None)
        if project is not None:
            project_id = project.get("savedId") or project.get("codexProjectId") or project.get("id")
            project_name_snapshot = str(project.get("name") or "").strip()
            project_category_snapshot = str(project.get("category") or "未分类").strip()
        elif selected_project_id == self.unresolved_project_id:
            project_id = selected_project_id
            project_name_snapshot = self.unresolved_project_name
            project_category_snapshot = str(self.task.get("projectCategorySnapshot") or self.task.get("category") or "未分类").strip()
        else:
            project_id = None
            project_name_snapshot = ""
            project_category_snapshot = ""
        session_id = self.conversation_field.currentData()
        if selected_project_id == self.unresolved_project_id and session_id == self.preferred_session_id:
            conversation_title = str(self.task.get("conversationTitle") or "").strip()
        else:
            conversation_title = self.conversation_field.currentText() if session_id else ""
        return {
            "title": self.title_field.text().strip(),
            "category": self.category_field.currentData(),
            "projectId": project_id,
            "projectNameSnapshot": project_name_snapshot,
            "projectCategorySnapshot": project_category_snapshot,
            "sessionId": session_id,
            "conversationTitle": conversation_title,
            "status": self.status_field.currentData(),
            "date": self.date_field.date().toString(Qt.ISODate),
            "notes": self.notes_field.toPlainText().strip(),
            "completionNote": self.outcome_field.toPlainText().strip(),
        }


class TaskLinkRepairDialog(QDialog):
    """Review orphan task links without guessing project identity."""
    def __init__(self, parent, issues, projects):
        super().__init__(parent)
        self.issues = list(issues or [])
        self.projects = sorted(
            projects or [],
            key=lambda project: (
                bool(project.get("_archived")),
                str(project.get("category") or "未分类").casefold(),
                str(project.get("name") or "").casefold(),
            ),
        )
        self.selectors = {}
        self.setWindowTitle("修复任务项目关联")
        self.setObjectName("taskLinkRepairDialog")
        self.setMinimumSize(780, 380)
        self.resize(840, min(680, max(400, 225 + min(len(self.issues), 6) * 86)))
        self.setStyleSheet(STYLE + """
            QDialog#taskLinkRepairDialog { background: #f5f7fb; }
            QFrame#taskLinkRepairRow { background: #ffffff; border: 1px solid #dce4ed; border-radius: 10px; }
            QFrame#taskLinkRepairRow:hover { border-color: #a9bfd8; }
        """)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(12)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE71B", color="#315f9b", size=20).pixmap(QSize(20, 20)))
        icon.setStyleSheet("background: #e8eff7; border: 1px solid #cbd9e8; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        eyebrow = QLabel("DATA INTEGRITY"); eyebrow.setStyleSheet("color: #315f9b; font-size: 10px; font-weight: 750; letter-spacing: 1px;"); title_box.addWidget(eyebrow)
        title = QLabel("修复任务项目关联"); title.setStyleSheet("color: #172033; font-size: 22px; font-weight: 720;"); title_box.addWidget(title)
        subtitle = QLabel("这些任务仍保留原内容和状态，但项目 ID 已失效。请只在确认归属后重新关联；未选择的任务保持不变。")
        subtitle.setWordWrap(True); subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box, 1)
        self.selection_count = QLabel(); self.selection_count.setAlignment(Qt.AlignCenter); self.selection_count.setFixedHeight(30)
        self.selection_count.setStyleSheet("color: #315f9b; background: #e8eff7; border-radius: 8px; padding: 3px 10px; font-size: 11px; font-weight: 700;"); heading.addWidget(self.selection_count)
        root.addLayout(heading)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget(); content.setStyleSheet("background: transparent;")
        rows = QVBoxLayout(content); rows.setContentsMargins(0, 0, 6, 0); rows.setSpacing(8)
        for task in self.issues:
            row = QFrame(); row.setObjectName("taskLinkRepairRow"); row.setMinimumHeight(78)
            row_layout = QHBoxLayout(row); row_layout.setContentsMargins(14, 10, 12, 10); row_layout.setSpacing(14)
            text = QVBoxLayout(); text.setSpacing(3)
            task_title = ElidedLabel(str(task.get("title") or "未命名任务")); task_title.setStyleSheet("color: #253247; font-size: 14px; font-weight: 680; border: none;"); text.addWidget(task_title)
            task_date = QDate.fromString(str(task.get("date") or ""), Qt.ISODate)
            date_text = task_date.toString("yyyy年MM月dd日") if task_date.isValid() else str(task.get("date") or "日期未知")
            historical = str(task.get("projectNameSnapshot") or "历史项目").strip()
            conversation = str(task.get("conversationTitle") or "未保留对话标题").strip()
            meta = ElidedLabel(f"{date_text}  ·  原关联：{historical}  ·  Codex：{conversation}"); meta.setStyleSheet("color: #748094; font-size: 11px; border: none;"); text.addWidget(meta); row_layout.addLayout(text, 1)
            selector = QComboBox(); selector.setFixedSize(330, 40); selector.setAccessibleName(f"为任务 {task.get('title') or '未命名任务'} 选择项目")
            selector.addItem("选择确认后的项目…", None)
            for project in self.projects:
                category = str(project.get("category") or "未分类")
                suffix = " · 已归档" if project.get("_archived") else ""
                selector.addItem(f"{category}  ›  {project.get('name') or '未命名项目'}{suffix}", project.get("id"))
            selector.currentIndexChanged.connect(self.sync_selection); row_layout.addWidget(selector)
            self.selectors[str(task.get("id") or "")] = selector; rows.addWidget(row)
        rows.addStretch(); scroll.setWidget(content); root.addWidget(scroll, 1)

        actions = QHBoxLayout(); actions.setSpacing(8)
        note = QLabel("修复只更新项目归属与快照，不改变任务状态、日期和执行记录。")
        note.setStyleSheet("color: #748094; font-size: 11px;"); actions.addWidget(note); actions.addStretch()
        close = QPushButton("稍后处理"); close.setFixedHeight(38); close.clicked.connect(self.reject); actions.addWidget(close)
        self.apply_button = QPushButton("保存确认的关联"); self.apply_button.setObjectName("primary"); self.apply_button.setFixedHeight(38); self.apply_button.clicked.connect(self.accept); actions.addWidget(self.apply_button)
        root.addLayout(actions); self.sync_selection()

    def sync_selection(self):
        selected = sum(selector.currentData() is not None for selector in self.selectors.values())
        self.selection_count.setText(f"已选择 {selected} / {len(self.issues)}")
        self.apply_button.setEnabled(selected > 0)

    def value(self):
        return [
            (task_id, selector.currentData())
            for task_id, selector in self.selectors.items()
            if selector.currentData() is not None
        ]


class TaskOutcomeDialog(QDialog):
    def __init__(self, parent, task):
        super().__init__(parent)
        self.setWindowTitle("记录完成成果")
        self.setObjectName("taskOutcomeDialog")
        self.setMinimumWidth(560)
        self.setStyleSheet(STYLE + """
            QDialog#taskOutcomeDialog QLabel { color: #26364c; }
            QDialog#taskOutcomeDialog QTextEdit { font-size: 13px; line-height: 1.45; }
            QDialog#taskOutcomeDialog QPushButton { min-height: 20px; }
        """)
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 24, 28, 24); layout.setSpacing(12)
        eyebrow = QLabel("完成闭环"); eyebrow.setStyleSheet("color: #16803c; font-size: 11px; font-weight: 700;"); layout.addWidget(eyebrow)
        title = QLabel("记录完成成果"); title.setStyleSheet("font-size: 23px; font-weight: 700; color: #172033;"); layout.addWidget(title)
        task_name = QLabel(str((task or {}).get("title") or "未命名任务")); task_name.setWordWrap(True)
        task_name.setStyleSheet("font-size: 14px; font-weight: 650; color: #34445c; background: #eef3f8; border-radius: 9px; padding: 10px 12px;"); layout.addWidget(task_name)
        hint = QLabel("用一到两句话写下可验证的结果或关键结论。该内容会进入每日回顾，并在项目下一步完成时成为交接证据。")
        hint.setWordWrap(True); hint.setStyleSheet("color: #66758a; font-size: 12px;"); layout.addWidget(hint)
        self.outcome_field = QTextEdit(task_completion_outcome(task)); self.outcome_field.setFixedHeight(108)
        self.outcome_field.setPlaceholderText("例如：完成新版导出流程并通过 12 项回归检查，未发现阻断问题。")
        self.outcome_field.setAccessibleName("完成成果"); layout.addWidget(self.outcome_field)
        actions = QHBoxLayout(); actions.setSpacing(8); actions.addStretch()
        cancel = QPushButton("取消"); cancel.clicked.connect(self.reject); actions.addWidget(cancel)
        save = QPushButton("保存成果"); save.setObjectName("primary"); save.clicked.connect(self.accept_outcome); actions.addWidget(save)
        layout.addLayout(actions); self.outcome_field.setFocus()

    def accept_outcome(self):
        if not self.value():
            QMessageBox.information(self, "还没有成果", "请写下实际完成的结果；如果任务尚未完成，可先将它移回“进行中”。")
            return
        self.accept()

    def value(self):
        return self.outcome_field.toPlainText().strip()


class ProjectCloseoutDialog(QDialog):
    """Capture project-level delivery evidence without turning closeout into a form."""
    def __init__(self, parent, project, pending_count=0, initial_outcome=""):
        super().__init__(parent)
        self.project = project or {}
        self.objective_snapshot = str(
            self.project.get("completionObjectiveSnapshot") or self.project.get("objective") or ""
        ).strip()
        self.criteria_snapshot = str(
            self.project.get("completionCriteriaSnapshot") or self.project.get("successCriteria") or ""
        ).strip()
        existing = project_completion_outcome(self.project)
        self.editing = bool(existing)
        self.setWindowTitle("项目收尾记录" if self.editing else "确认项目完成")
        self.setObjectName("projectCloseoutDialog")
        self.setMinimumWidth(650)
        self.resize(680, 570 if pending_count else 530)
        self.setStyleSheet(STYLE + """
            QDialog#projectCloseoutDialog { background: #f7f9fc; }
            QDialog#projectCloseoutDialog QTextEdit { background: #ffffff; border: 1px solid #cbd7e6; border-radius: 10px; padding: 10px; font-size: 13px; line-height: 1.5; }
            QDialog#projectCloseoutDialog QTextEdit:focus { border: 2px solid #2563eb; padding: 9px; }
        """)
        root = QVBoxLayout(self); root.setContentsMargins(30, 26, 30, 24); root.setSpacing(13)

        heading = QHBoxLayout(); heading.setSpacing(12)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=21).pixmap(QSize(21, 21)))
        icon.setStyleSheet("background: #e8f7ef; border: 1px solid #b9dfc8; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        eyebrow = QLabel("PROJECT CLOSEOUT"); eyebrow.setStyleSheet("color: #16803c; font-size: 10px; font-weight: 750; letter-spacing: 1px;"); title_box.addWidget(eyebrow)
        title = QLabel("修订完成成果" if self.editing else "确认项目完成"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        heading.addLayout(title_box, 1); root.addLayout(heading)

        project_name = QLabel(str(self.project.get("name") or "未命名项目")); project_name.setWordWrap(True)
        project_name.setStyleSheet("color: #34445c; background: #eef3f8; border: 1px solid #dce5ef; border-radius: 9px; padding: 10px 12px; font-size: 14px; font-weight: 650;"); root.addWidget(project_name)
        objective_frame = QFrame(); objective_frame.setObjectName("closeoutObjective")
        objective_frame.setStyleSheet("QFrame#closeoutObjective { background: #f1f6ff; border: 1px solid #cfdbef; border-radius: 10px; } QFrame#closeoutObjective QLabel { background: transparent; border: none; }")
        objective_layout = QVBoxLayout(objective_frame); objective_layout.setContentsMargins(12, 9, 12, 10); objective_layout.setSpacing(3)
        objective_title = QLabel("验收依据 · 项目目标"); objective_title.setStyleSheet("color: #315f9b; font-size: 10px; font-weight: 750;"); objective_layout.addWidget(objective_title)
        objective_text = QLabel(self.objective_snapshot or "尚未明确项目目标")
        objective_text.setWordWrap(True); objective_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        objective_text.setStyleSheet(f"color: {'#34445c' if self.objective_snapshot else '#9a5b00'}; font-size: 12px; font-weight: 600;"); objective_layout.addWidget(objective_text)
        criteria_title = QLabel("完成判据 · 验收标准"); criteria_title.setStyleSheet("color: #315f9b; font-size: 10px; font-weight: 750; margin-top: 4px;"); objective_layout.addWidget(criteria_title)
        criteria_text = QLabel(self.criteria_snapshot or "尚未单独定义验收标准；本次将按项目目标与完成成果进行验收")
        criteria_text.setWordWrap(True); criteria_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        criteria_text.setStyleSheet(f"color: {'#34445c' if self.criteria_snapshot else '#8a6a2d'}; font-size: 12px; font-weight: 600;"); objective_layout.addWidget(criteria_text)
        root.addWidget(objective_frame)
        hint = QLabel("对照目标与验收标准，写下整个项目最终交付了什么、用什么证据验证。这里记录的是项目成果，不是最近完成的一项任务。")
        hint.setWordWrap(True); hint.setStyleSheet("color: #5f6f84; font-size: 12px;"); root.addWidget(hint)

        if pending_count:
            warning = QLabel(f"仍有 {pending_count} 项未完成任务。完成项目不会改写这些任务，它们会继续保留，便于逐项确认或重新归类。")
            warning.setWordWrap(True); warning.setStyleSheet("color: #8a5800; background: #fff8e8; border: 1px solid #ead7a4; border-radius: 9px; padding: 9px 11px; font-size: 11px;"); root.addWidget(warning)

        initial = existing or str(initial_outcome or "").strip()
        self.outcome_field = QTextEdit(initial); self.outcome_field.setFixedHeight(112)
        self.outcome_field.setPlaceholderText("例如：交付可复现的分析流程并通过三组数据验证，核心结论已写入报告，未遗留阻断问题。")
        self.outcome_field.setAccessibleName("项目完成成果"); root.addWidget(self.outcome_field)

        basis = "项目目标与验收标准" if self.criteria_snapshot else "项目目标"
        acceptance_text = f"我已核对{basis}，确认当前成果足以完成项目"
        if pending_count:
            acceptance_text = f"我已核对{basis}与未完成任务，确认当前成果仍足以完成项目"
        self.acceptance = QCheckBox(acceptance_text)
        self.acceptance.setAccessibleName("确认项目验收")
        self.acceptance.setStyleSheet("QCheckBox { color: #34445c; background: #ffffff; border: 1px solid #d5deea; border-radius: 9px; padding: 9px 11px; font-size: 12px; font-weight: 600; } QCheckBox::indicator { width: 17px; height: 17px; }")
        root.addWidget(self.acceptance)

        footer = QHBoxLayout(); footer.setSpacing(8)
        evidence = QLabel("保存后会写入项目档案与每日总结；重新打开项目也不会删除这次成果。")
        evidence.setWordWrap(True); evidence.setStyleSheet("color: #718096; font-size: 10px;"); footer.addWidget(evidence, 1)
        cancel = QPushButton("取消"); cancel.setFixedHeight(38); cancel.clicked.connect(self.reject); footer.addWidget(cancel)
        save = QPushButton("保存成果" if self.editing else "确认完成"); save.setObjectName("primary"); save.setFixedHeight(38); save.clicked.connect(self.accept_outcome); footer.addWidget(save)
        root.addLayout(footer); self.outcome_field.setFocus()

    def accept_outcome(self):
        if not self.objective_snapshot:
            QMessageBox.information(self, "项目目标缺失", "请先返回项目面板明确项目目标，再进行完成验收。")
            return
        if not self.value():
            QMessageBox.information(self, "还没有项目成果", "请写下项目最终交付或验证的结果；如果还没有形成结果，可以先保持“进行中”。")
            return
        if not self.acceptance.isChecked():
            QMessageBox.information(self, "尚未确认验收", "请核对项目目标与完成成果，并勾选验收确认。")
            return
        self.accept()

    def value(self):
        return self.outcome_field.toPlainText().strip()

    def acceptance_objective(self):
        return self.objective_snapshot if self.acceptance.isChecked() else ""

    def acceptance_criteria(self):
        return self.criteria_snapshot if self.acceptance.isChecked() else ""


class TodayTaskCard(QFrame):
    def __init__(self, task, window):
        super().__init__()
        self.task_id = str((task or {}).get("id") or "")
        historical_snapshot = task_is_superseded_daily_record(task)
        self.setObjectName("todayTaskCard")
        status_key = task.get("status", "planned")
        project = window.project_by_id(task.get("projectId")); project_name = task_project_identity(task, project)["name"]
        conversation = window.conversation_by_id(task.get("sessionId")); conversation_title = conversation_name(conversation) if conversation else task.get("conversationTitle") or ""
        conversation_state = codex_state(conversation)[0] if conversation else None
        accent = TASK_COLORS.get(status_key, "#64748b")
        self.setStyleSheet(f"QFrame#todayTaskCard {{ background: #ffffff; border: 1px solid #d9e2ec; border-left: 3px solid {accent}; border-radius: 10px; }} QFrame#todayTaskCard:hover {{ background: #fbfdff; border-color: #9eb4ce; border-left-color: {accent}; }}")
        root = QVBoxLayout(self); root.setContentsMargins(12, 10, 10, 9); root.setSpacing(6)
        headline = QHBoxLayout(); headline.setSpacing(8)
        title = ElidedLabel(task.get("title") or "未命名任务"); title.setToolTip(task.get("title") or "未命名任务"); title.setStyleSheet("font-size: 14px; font-weight: 680; color: #253247; border: none;"); headline.addWidget(title, 1)
        if historical_snapshot:
            snapshot = QLabel("已延续")
            snapshot.setToolTip(f"该日状态已延续至 {task.get('carriedToDate') or '后续日期'}，请在最新记录中继续管理")
            snapshot.setStyleSheet("color: #526071; background: #eef2f6; border: none; border-radius: 7px; padding: 3px 7px; font-size: 10px; font-weight: 650;")
            headline.addWidget(snapshot, 0, Qt.AlignTop)
        else:
            headline.addWidget(TaskDragHandle(task), 0, Qt.AlignTop)
        root.addLayout(headline)
        meta_row = QHBoxLayout(); meta_row.setSpacing(7)
        identity = project_name
        if conversation_title:
            identity = f"{identity}  ·  {conversation_title}"
        meta = ElidedLabel(identity); meta.setToolTip(identity); meta.setStyleSheet("color: #66758a; font-size: 11px; border: none;"); meta_row.addWidget(meta, 1)
        if conversation_state == "running":
            live = QLabel("● Codex 运行中"); live.setStyleSheet("color: #087443; background: #e3f6ec; border: 1px solid #b6e1c9; border-radius: 8px; padding: 3px 7px; font-size: 10px; font-weight: 700;"); meta_row.addWidget(live)
        root.addLayout(meta_row)
        if task.get("notes"):
            notes = ElidedLabel(task["notes"].replace("\n", " ")); notes.setStyleSheet("color: #526071; font-size: 11px; border: none;"); root.addWidget(notes)
        completion_outcome = task_completion_outcome(task)
        actions = QHBoxLayout(); actions.setSpacing(6)
        actions.addStretch()
        if historical_snapshot:
            current = QPushButton("查看当前")
            current.setFixedSize(88, 30); current.setIcon(fluent_icon("\uE72A", color="#315f9b", size=13)); current.setIconSize(QSize(13, 13))
            current.setToolTip("跳转到这项工作的最新每日记录")
            current.setStyleSheet("QPushButton { color: #315f9b; background: #edf4ff; border: 1px solid #cfdaeb; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 650; } QPushButton:hover { background: #e2ebfa; }")
            current.clicked.connect(lambda: window.open_current_task_record(task)); actions.addWidget(current)
        elif task.get("sessionId"):
            open_codex = QPushButton("打开 Codex")
            open_codex.setFixedSize(96, 30)
            open_codex.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14))
            open_codex.setIconSize(QSize(14, 14))
            open_codex.setToolTip("打开关联的 Codex 对话")
            open_codex.setAccessibleName(f"打开任务 {task.get('title', '')} 的 Codex 对话")
            open_codex.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c7d7f2; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 650; } QPushButton:hover { background: #dfe9fb; border-color: #9db7e4; }")
            open_codex.clicked.connect(lambda: window.open_task_conversation(task))
            actions.addWidget(open_codex)
        elif status_key == "planned":
            begin = QPushButton("开始")
            begin.setFixedSize(72, 30); begin.setIcon(fluent_icon("\uE768", color="#1d4ed8", size=13)); begin.setIconSize(QSize(13, 13))
            begin.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c7d7f2; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 650; } QPushButton:hover { background: #dfe9fb; border-color: #9db7e4; }")
            begin.clicked.connect(lambda: window.set_task_status(task["id"], "doing", source="manual")); actions.addWidget(begin)
        if not historical_snapshot and status_key == "doing":
            finish = QPushButton("完成")
            finish.setFixedSize(72, 30); finish.setIcon(fluent_icon("\uE73E", color="#087443", size=13)); finish.setIconSize(QSize(13, 13))
            finish.setStyleSheet("QPushButton { color: #087443; background: #e9f8f0; border: 1px solid #b9dfc8; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 650; } QPushButton:hover { background: #dff2e7; border-color: #88cda4; }")
            finish.clicked.connect(lambda: window.set_task_status(task["id"], "done", source="manual")); actions.addWidget(finish)
        more = QToolButton(); more.setFixedSize(32, 30); more.setIcon(fluent_icon("\uE712", size=14)); more.setIconSize(QSize(14, 14)); more.setToolTip("更多操作")
        more.setAccessibleName(f"任务 {task.get('title', '')} 的更多操作")
        more.setStyleSheet("QToolButton { border: none; border-radius: 7px; background: transparent; } QToolButton:hover { background: #eaf1fa; } QToolButton::menu-indicator { image: none; }")
        menu = QMenu(more)
        if historical_snapshot:
            current_action = menu.addAction(fluent_icon("\uE72A", color="#315f9b", size=14), "查看当前任务")
            current_action.triggered.connect(lambda: window.open_current_task_record(task))
        else:
            edit_action = menu.addAction(fluent_icon("\uE70F", size=14), "编辑任务")
            edit_action.triggered.connect(lambda: window.edit_today_task(task))
            if status_key == "done":
                reopen_action = menu.addAction(fluent_icon("\uE7A7", color="#315f9b", size=14), "重新打开")
                reopen_action.triggered.connect(lambda: window.set_task_status(task["id"], "doing", source="manual"))
            elif status_key == "planned":
                begin_action = menu.addAction(fluent_icon("\uE768", color="#1d4ed8", size=14), "移到进行中")
                begin_action.triggered.connect(lambda: window.set_task_status(task["id"], "doing", source="manual"))
        audit_action = menu.addAction(fluent_icon("\uE81C", color="#315f9b", size=14), "任务记录")
        audit_action.triggered.connect(lambda: window.show_task_audit(task))
        if status_key == "done" and not historical_snapshot:
            outcome_action = menu.addAction(fluent_icon("\uE73E", color="#16803c", size=14), "编辑完成成果" if completion_outcome else "记录完成成果")
            outcome_action.triggered.connect(lambda: window.edit_task_outcome(task))
        menu.addSeparator()
        delete_action = menu.addAction(fluent_icon("\uE74D", color="#526071", size=14), "移到任务回收站")
        delete_action.triggered.connect(lambda: window.delete_today_task(task))
        more.setMenu(menu); more.setPopupMode(QToolButton.InstantPopup); actions.addWidget(more)
        root.addLayout(actions)


class TaskAuditDialog(QDialog):
    OUTCOME_SOURCES = {
        "task_editor": "任务编辑",
        "outcome_editor": "成果编辑",
        "reopen": "任务重新打开",
        "legacy": "历史导入",
        "manual": "手动记录",
    }

    def __init__(self, parent, task):
        super().__init__(parent)
        self.window = parent
        self.task = task or {}
        self.setWindowTitle("任务档案")
        self.setObjectName("taskAuditDialog")
        self.setMinimumSize(760, 560)
        self.resize(840, 640)
        self.setStyleSheet(STYLE + """
            QDialog#taskAuditDialog { background: #f5f7fb; }
            QFrame#auditSection { background: #ffffff; border: 1px solid #dce4ee; border-radius: 11px; }
            QFrame#auditEvent { background: #f8fafc; border: 1px solid #e5eaf0; border-radius: 8px; }
        """)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(12)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE81C", color="#1d4ed8", size=20).pixmap(QSize(20, 20)))
        icon.setStyleSheet("background: #eaf1ff; border: 1px solid #c9d9f6; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        eyebrow = QLabel("TASK RECORD"); eyebrow.setStyleSheet("color: #2563eb; font-size: 10px; font-weight: 750; letter-spacing: 1px;"); title_box.addWidget(eyebrow)
        title = QLabel(str(self.task.get("title") or "未命名任务")); title.setWordWrap(True)
        title.setStyleSheet("color: #172033; font-size: 22px; font-weight: 720;"); title_box.addWidget(title)
        project = self.window.project_by_id(self.task.get("projectId")); project_name = task_project_identity(self.task, project)["name"]
        conversation = self.window.conversation_by_id(self.task.get("sessionId"))
        conversation_title = conversation_name(conversation) if conversation else self.task.get("conversationTitle") or "未关联 Codex"
        task_date = QDate.fromString(str(self.task.get("date") or ""), Qt.ISODate)
        date_text = task_date.toString("yyyy年MM月dd日") if task_date.isValid() else str(self.task.get("date") or "日期未知")
        meta = QLabel(f"{date_text}  ·  {project_name}  ·  {conversation_title}"); meta.setWordWrap(True)
        meta.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(meta); heading.addLayout(title_box, 1)
        status = str(self.task.get("status") or "planned"); color = TASK_COLORS.get(status, "#64748b")
        tint = {"planned": "#f3edff", "doing": "#eaf2ff", "done": "#e8f7ef"}.get(status, "#eef2f6")
        if task_is_archived(self.task):
            archived = QLabel("已归档"); archived.setAlignment(Qt.AlignCenter); archived.setFixedSize(64, 30)
            archived.setToolTip(f"{format_project_decision_time(self.task.get('archivedAt'))} 移到任务回收站")
            archived.setStyleSheet("color: #526071; background: #eef2f6; border: 1px solid #cbd5e1; border-radius: 9px; font-size: 11px; font-weight: 650;"); heading.addWidget(archived, 0, Qt.AlignTop)
        state = QLabel(TASK_STATUS.get(status, status)); state.setAlignment(Qt.AlignCenter); state.setFixedSize(76, 30)
        state.setStyleSheet(f"color: {color}; background: {tint}; border: 1px solid {color}; border-radius: 9px; font-size: 12px; font-weight: 700;"); heading.addWidget(state, 0, Qt.AlignTop)
        root.addLayout(heading)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget(); content.setStyleSheet("background: transparent;")
        body = QVBoxLayout(content); body.setContentsMargins(0, 0, 6, 0); body.setSpacing(11)

        notes = str(self.task.get("notes") or "").strip()
        self._add_text_section(body, "计划说明", notes or "没有补充计划说明", "\uE70B", "#315f9b", notes != "")

        revisions = task_completion_revisions(self.task)
        current_outcome = task_completion_outcome(self.task)
        historical_outcome = next((str(item.get("text") or item.get("previous") or "").strip() for item in revisions if str(item.get("text") or item.get("previous") or "").strip()), "")
        if current_outcome:
            outcome_title, outcome_text, outcome_color = "完成成果", current_outcome, "#16803c"
        elif historical_outcome:
            outcome_title, outcome_text, outcome_color = "历史完成成果（任务已重新打开）", historical_outcome, "#64748b"
        else:
            outcome_title, outcome_text, outcome_color = "完成成果", "尚未记录完成成果", "#748094"
        self._add_text_section(body, outcome_title, outcome_text, "\uE73E", outcome_color, bool(current_outcome or historical_outcome))

        events = task_status_events([self.task])[:30]
        event_section, event_layout = self._section("状态流转", "\uE8A7", "#2563eb")
        for event in events:
            before = TASK_STATUS.get(event.get("from"), "建立任务")
            after = TASK_STATUS.get(event.get("to"), "更新")
            event_color = TASK_COLORS.get(event.get("to"), "#64748b")
            self._add_event_row(
                event_layout,
                f"{before}  →  {after}",
                f"{TASK_EVENT_SOURCES.get(event.get('source'), '手动')}  ·  {format_project_decision_time(event.get('at'))}",
                event_color,
            )
        body.addWidget(event_section)

        schedule_events = task_schedule_events([self.task])[:30]
        if schedule_events:
            schedule_section, schedule_layout = self._section("计划日期调整", "\uE787", "#9a6700")
            for event in schedule_events:
                previous = QDate.fromString(str(event.get("from") or ""), Qt.ISODate)
                target = QDate.fromString(str(event.get("to") or ""), Qt.ISODate)
                previous_text = previous.toString("yyyy年MM月dd日") if previous.isValid() else str(event.get("from") or "日期未知")
                target_text = target.toString("yyyy年MM月dd日") if target.isValid() else str(event.get("to") or "日期未知")
                source = TASK_SCHEDULE_SOURCES.get(str(event.get("source") or ""), "手动调整")
                self._add_event_row(
                    schedule_layout,
                    f"{previous_text}  →  {target_text}",
                    f"{source}  ·  {format_project_decision_time(event.get('at'))}",
                    "#9a6700",
                )
            body.addWidget(schedule_section)

        link_events = task_project_link_events(self.task)
        if link_events:
            link_section, link_layout = self._section("项目关联修复", "\uE71B", "#315f9b")
            source_labels = {"codex_conversation": "Codex 对话自动恢复", "manual_repair": "人工确认"}
            for event in link_events[:30]:
                previous = str(event.get("fromProjectName") or "历史项目").strip()
                current = str(event.get("toProjectName") or "未命名项目").strip()
                source = source_labels.get(str(event.get("source") or ""), "关联修复")
                self._add_event_row(
                    link_layout,
                    f"{previous}  →  {current}",
                    f"{source}  ·  {format_project_decision_time(event.get('at'))}",
                    "#315f9b",
                )
            body.addWidget(link_section)

        revision_section, revision_layout = self._section("成果修订", "\uE70F", "#7c3aed")
        if not revisions:
            empty = QLabel("尚无成果修订记录"); empty.setStyleSheet("color: #748094; font-size: 12px; padding: 6px 2px;"); revision_layout.addWidget(empty)
        else:
            for revision in revisions[:30]:
                current = str(revision.get("text") or "").strip()
                previous = str(revision.get("previous") or "").strip()
                if current and previous:
                    label, detail, revision_color = "更新完成成果", current, "#7c3aed"
                elif current:
                    label, detail, revision_color = "记录完成成果", current, "#16803c"
                else:
                    label, detail, revision_color = "任务重新打开，原成果转为历史", previous or "原成果已退役", "#64748b"
                source = self.OUTCOME_SOURCES.get(str(revision.get("source") or ""), "手动记录")
                self._add_event_row(revision_layout, label, f"{source}  ·  {format_project_decision_time(revision.get('at'))}\n{detail}", revision_color)
        body.addWidget(revision_section); body.addStretch(); scroll.setWidget(content); root.addWidget(scroll, 1)

        actions = QHBoxLayout(); actions.setSpacing(8)
        if self.task.get("sessionId"):
            open_codex = QPushButton("打开 Codex 对话"); open_codex.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); open_codex.setIconSize(QSize(14, 14))
            open_codex.clicked.connect(lambda: self.window.open_task_conversation(self.task)); actions.addWidget(open_codex)
        actions.addStretch(); close = QPushButton("关闭"); close.setFixedHeight(38); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)

    def _section(self, title_text, glyph, color):
        section = QFrame(); section.setObjectName("auditSection")
        layout = QVBoxLayout(section); layout.setContentsMargins(15, 12, 15, 14); layout.setSpacing(8)
        heading = QHBoxLayout(); heading.setSpacing(8)
        icon = QLabel(); icon.setFixedSize(20, 20); icon.setPixmap(fluent_icon(glyph, color=color, size=14).pixmap(QSize(14, 14))); icon.setAlignment(Qt.AlignCenter); heading.addWidget(icon)
        title = QLabel(title_text); title.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 700;"); heading.addWidget(title); heading.addStretch(); layout.addLayout(heading)
        return section, layout

    def _add_text_section(self, parent_layout, title, text, glyph, color, has_value):
        section, layout = self._section(title, glyph, color)
        value = QLabel(text); value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value.setStyleSheet(f"color: {'#34445c' if has_value else '#748094'}; font-size: 13px; line-height: 1.45; padding: 2px;")
        layout.addWidget(value); parent_layout.addWidget(section)

    def _add_event_row(self, parent_layout, title_text, meta_text, color):
        row = QFrame(); row.setObjectName("auditEvent")
        layout = QHBoxLayout(row); layout.setContentsMargins(11, 8, 11, 8); layout.setSpacing(10)
        dot = QLabel(); dot.setFixedSize(8, 8); dot.setStyleSheet(f"background: {color}; border-radius: 4px;"); layout.addWidget(dot, 0, Qt.AlignTop | Qt.AlignHCenter)
        text = QVBoxLayout(); text.setSpacing(2)
        title = QLabel(title_text); title.setStyleSheet("color: #26364c; font-size: 12px; font-weight: 650;"); text.addWidget(title)
        meta = QLabel(meta_text); meta.setWordWrap(True); meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        meta.setStyleSheet("color: #66758a; font-size: 11px;"); text.addWidget(meta); layout.addLayout(text, 1)
        parent_layout.addWidget(row)


class TaskHistoryRow(QFrame):
    def __init__(self, task, window):
        super().__init__()
        status = task.get("status", "planned")
        color = TASK_COLORS.get(status, "#64748b")
        tint = {"planned": "#f3edff", "doing": "#eaf2ff", "done": "#e8f7ef"}.get(status, "#eef2f6")
        self.setObjectName("taskHistoryRow")
        self.setFixedHeight(66)
        self.setStyleSheet("QFrame#taskHistoryRow { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 9px; }")
        layout = QHBoxLayout(self); layout.setContentsMargins(13, 8, 12, 8); layout.setSpacing(10)
        dot = QLabel(); dot.setFixedSize(7, 7); dot.setStyleSheet(f"background: {color}; border-radius: 3px;"); layout.addWidget(dot)
        content = QVBoxLayout(); content.setSpacing(2)
        title = ElidedLabel(task.get("title") or "未命名任务"); title.setStyleSheet("color: #202b3c; font-size: 13px; font-weight: 600; border: none;"); content.addWidget(title)
        project = window.project_by_id(task.get("projectId")); project_name = task_project_identity(task, project)["name"]
        carry_text = ""
        if task.get("carriedFromTaskId"):
            carry_text = f" · 延续自 {task.get('carriedFromDate', '前一天')}"
        elif task.get("carriedToTaskId"):
            carry_text = f" · 已延续至 {task.get('carriedToDate', '下一天')}"
        latest_events = task_status_events([task])
        event_text = ""
        if latest_events:
            latest = latest_events[0]
            try:
                event_time_text = datetime.fromisoformat(str(latest.get("at") or "")).strftime("%H:%M")
            except ValueError:
                event_time_text = "—"
            event_text = f" · {TASK_EVENT_SOURCES.get(latest.get('source'), '手动')} {event_time_text}"
        meta = QLabel(f"{project_name}{carry_text}{event_text}"); meta.setStyleSheet("color: #718096; font-size: 11px; border: none;"); content.addWidget(meta)
        layout.addLayout(content, 1)
        if task_completion_revisions(task):
            evidence = QLabel("有成果记录"); evidence.setAlignment(Qt.AlignCenter); evidence.setFixedSize(72, 24)
            evidence.setToolTip("该任务保留了完成成果或成果修订记录")
            evidence.setStyleSheet("color: #16803c; background: #e8f7ef; border: none; border-radius: 7px; font-size: 10px; font-weight: 650;"); layout.addWidget(evidence)
        state = QLabel(TASK_STATUS.get(status, status)); state.setAlignment(Qt.AlignCenter); state.setFixedSize(62, 26)
        state.setStyleSheet(f"color: {color}; background: {tint}; border: none; border-radius: 8px; font-size: 11px; font-weight: 600;"); layout.addWidget(state)
        view = QToolButton(); view.setFixedSize(30, 30); view.setIcon(fluent_icon("\uE81C", color="#315f9b", size=14)); view.setIconSize(QSize(14, 14)); view.setToolTip("查看完整任务记录")
        view.setAccessibleName(f"查看任务 {task.get('title', '')} 的完整记录"); view.clicked.connect(lambda: window.show_task_audit(task)); layout.addWidget(view)


class TaskHistoryDialog(QDialog):
    def __init__(self, parent, tasks, selected_date=None):
        super().__init__(parent)
        self.window = parent
        self.tasks = tasks
        self.setWindowTitle("每日任务记录")
        self.setObjectName("taskHistoryDialog")
        self.setMinimumSize(820, 590)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self); layout.setContentsMargins(26, 22, 26, 22); layout.setSpacing(12)
        title_row = QHBoxLayout(); title_row.setSpacing(10)
        icon = QLabel(); icon.setFixedSize(28, 28); icon.setPixmap(fluent_icon("\uE81C", color="#2563eb", size=22).pixmap(QSize(22, 22))); icon.setAlignment(Qt.AlignCenter); title_row.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(1)
        title = QLabel("每日任务记录"); title.setStyleSheet("font-size: 22px; font-weight: 600; color: #172033;"); title_box.addWidget(title)
        subtitle = QLabel("保留每天的计划、进行中和已完成状态；进行中自动延续，未启动计划进入重新安排队列")
        subtitle.setStyleSheet("color: #718096; font-size: 11px;"); title_box.addWidget(subtitle); title_row.addLayout(title_box); title_row.addStretch(); layout.addLayout(title_row)

        filters = QHBoxLayout(); filters.setSpacing(8)
        date_label = QLabel("记录日期"); date_label.setStyleSheet("color: #4a586b; font-size: 12px; font-weight: 500;"); filters.addWidget(date_label)
        self.date_field = QComboBox(); self.date_field.setFixedSize(180, 38); self.date_field.setAccessibleName("任务记录日期")
        dates = sorted({str(task.get("date")) for task in tasks if task.get("date")}, reverse=True)
        if not dates: dates = [QDate.currentDate().toString(Qt.ISODate)]
        for date_value in dates:
            date = QDate.fromString(date_value, Qt.ISODate)
            self.date_field.addItem(date.toString("yyyy年MM月dd日") if date.isValid() else date_value, date_value)
        preferred = selected_date or QDate.currentDate().toString(Qt.ISODate)
        preferred_index = self.date_field.findData(preferred)
        if preferred_index >= 0: self.date_field.setCurrentIndex(preferred_index)
        self.date_field.currentIndexChanged.connect(self.render_records); filters.addWidget(self.date_field)
        filters.addStretch()
        self.summary = QLabel(); self.summary.setStyleSheet("color: #65758b; font-size: 12px;"); filters.addWidget(self.summary); layout.addLayout(filters)

        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setStyleSheet("QScrollArea { background: #f7f9fc; border: 1px solid #dfe6ef; border-radius: 11px; }")
        self.records_widget = QWidget(); self.records_widget.setStyleSheet("background: #f7f9fc;")
        self.records_layout = QVBoxLayout(self.records_widget); self.records_layout.setContentsMargins(10, 10, 10, 10); self.records_layout.setSpacing(7)
        self.scroll.setWidget(self.records_widget)

        layout.addWidget(self.scroll, 1)
        actions = QHBoxLayout(); actions.addStretch()
        close = QPushButton("关闭"); close.setFixedHeight(38); close.clicked.connect(self.reject); actions.addWidget(close)
        open_date = QPushButton("查看当天"); open_date.setFixedHeight(38); open_date.setObjectName("primary"); open_date.clicked.connect(self.open_selected_date); actions.addWidget(open_date); layout.addLayout(actions)
        self.render_records()

    def render_records(self):
        while self.records_layout.count():
            item = self.records_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        selected = self.date_field.currentData()
        records = sorted(
            [task for task in self.tasks if task.get("date") == selected],
            key=lambda task: (task.get("createdAt", ""), task.get("updatedAt", "")),
        )
        counts = {status: sum(task.get("status", "planned") == status for task in records) for status in TASK_STATUS}
        outcome_count = sum(bool(task_completion_revisions(task)) for task in records)
        self.summary.setText(f"{len(records)} 项 · {counts['planned']} 计划 · {counts['doing']} 进行中 · {counts['done']} 已完成 · {outcome_count} 项有成果记录")
        if not records:
            empty = QLabel("当天没有任务记录"); empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #7b8798; padding: 70px; font-size: 12px;"); self.records_layout.addWidget(empty)
        else:
            for task in records: self.records_layout.addWidget(TaskHistoryRow(task, self.window))
        self.records_layout.addStretch()

    def open_selected_date(self):
        date = QDate.fromString(self.date_field.currentData() or "", Qt.ISODate)
        if date.isValid() and hasattr(self.window, "board_date_field"):
            self.window.board_date_field.setDate(date)
        self.accept()


class TaskArchiveDialog(QDialog):
    def __init__(self, parent, tasks):
        super().__init__(parent)
        self.window = parent
        self.tasks = list(archived_task_records(tasks))
        self.setWindowTitle("任务回收站")
        self.setObjectName("taskArchiveDialog")
        self.setMinimumSize(720, 500)
        self.resize(780, 560)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE74D", color="#1d4ed8", size=19).pixmap(QSize(19, 19)))
        icon.setStyleSheet("background: #eaf1ff; border: 1px solid #c9d9f6; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("任务回收站"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        hint = QLabel("移除的任务不会进入看板、项目负载或每日总结，但原状态和变更历史会完整保留。")
        hint.setWordWrap(True); hint.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(hint); heading.addLayout(title_box, 1)
        self.count_label = QLabel(); self.count_label.setAlignment(Qt.AlignCenter); self.count_label.setFixedHeight(30)
        self.count_label.setStyleSheet("color: #315f9b; background: #edf3ff; border-radius: 8px; padding: 3px 10px; font-size: 11px; font-weight: 650;"); heading.addWidget(self.count_label); root.addLayout(heading)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget(); content.setStyleSheet("background: transparent;")
        self.rows = QVBoxLayout(content); self.rows.setContentsMargins(0, 0, 6, 0); self.rows.setSpacing(8)
        scroll.setWidget(content); root.addWidget(scroll, 1)
        actions = QHBoxLayout(); actions.addStretch(); close = QPushButton("关闭"); close.setFixedHeight(38); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)
        self.render_rows()

    def render_rows(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.count_label.setText(f"{len(self.tasks)} 项任务")
        if not self.tasks:
            empty = QFrame(); empty.setObjectName("taskArchiveEmpty"); empty.setMinimumHeight(240)
            empty.setStyleSheet("QFrame#taskArchiveEmpty { background: #ffffff; border: 1px dashed #cbd5e1; border-radius: 12px; }")
            empty_layout = QVBoxLayout(empty); empty_layout.setAlignment(Qt.AlignCenter); empty_layout.setSpacing(8)
            empty_title = QLabel("回收站为空"); empty_title.setStyleSheet("color: #34445c; font-size: 15px; font-weight: 700;"); empty_layout.addWidget(empty_title, 0, Qt.AlignCenter)
            empty_hint = QLabel("从今日看板移除的任务会安全保存在这里"); empty_hint.setStyleSheet("color: #748094; font-size: 11px;"); empty_layout.addWidget(empty_hint, 0, Qt.AlignCenter)
            self.rows.addWidget(empty); self.rows.addStretch(); return
        for task in self.tasks:
            status = task.get("status", "planned"); accent = TASK_COLORS.get(status, "#64748b")
            row = QFrame(); row.setObjectName("archivedTaskRow"); row.setFixedHeight(76)
            row.setStyleSheet("QFrame#archivedTaskRow { background: #ffffff; border: 1px solid #dbe3ee; border-radius: 10px; }")
            row_layout = QHBoxLayout(row); row_layout.setContentsMargins(14, 8, 10, 8); row_layout.setSpacing(12)
            dot = QLabel(); dot.setFixedSize(8, 8); dot.setStyleSheet(f"background: {accent}; border-radius: 4px;"); row_layout.addWidget(dot)
            text = QVBoxLayout(); text.setSpacing(3)
            name = ElidedLabel(task.get("title") or "未命名任务"); name.setStyleSheet("color: #253247; font-size: 14px; font-weight: 680;"); text.addWidget(name)
            project = self.window.project_by_id(task.get("projectId")); project_name = task_project_identity(task, project)["name"]
            task_date = QDate.fromString(str(task.get("date") or ""), Qt.ISODate)
            date_text = task_date.toString("yyyy年MM月dd日") if task_date.isValid() else str(task.get("date") or "日期未知")
            archived_at = format_project_decision_time(task.get("archivedAt"), compact=True)
            meta = QLabel(f"{date_text}  ·  {project_name}  ·  {TASK_STATUS.get(status, '计划')}  ·  {archived_at} 移除")
            meta.setStyleSheet("color: #748094; font-size: 11px;"); text.addWidget(meta); row_layout.addLayout(text, 1)
            audit = QToolButton(); audit.setFixedSize(34, 34); audit.setIcon(fluent_icon("\uE81C", color="#315f9b", size=14)); audit.setIconSize(QSize(14, 14)); audit.setToolTip("查看任务记录")
            audit.setAccessibleName(f"查看已移除任务 {task.get('title', '')} 的记录"); audit.clicked.connect(lambda _checked=False, value=task: self.window.show_task_audit(value)); row_layout.addWidget(audit)
            restore = QPushButton("恢复任务"); restore.setFixedSize(92, 36); restore.setIcon(fluent_icon("\uE72C", color="#1d4ed8", size=13)); restore.setIconSize(QSize(13, 13))
            restore.setToolTip("恢复到原日期与原状态，并放在对应看板列末端"); restore.clicked.connect(lambda _checked=False, value=task: self.restore_task(value)); row_layout.addWidget(restore)
            self.rows.addWidget(row)
        self.rows.addStretch()

    def restore_task(self, task):
        if self.window.restore_archived_task(task):
            self.tasks = [item for item in self.tasks if item.get("id") != task.get("id")]
            self.render_rows()


class DailySummaryDialog(QDialog):
    def __init__(self, parent, summary):
        super().__init__(parent)
        self.window = parent
        self.summary = summary
        self.suggestion_buttons = []
        self.setWindowTitle("昨日工作总结")
        self.setObjectName("dailySummaryDialog")
        self.setMinimumSize(780, 560)
        self.resize(840, 620)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(40, 40); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE81C", color="#1d4ed8", size=20).pixmap(QSize(20, 20)))
        icon.setStyleSheet("background: #eaf1ff; border: 1px solid #c9d9f6; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("昨日工作总结"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        source_counts = summary.get("sourceCounts") if isinstance(summary.get("sourceCounts"), dict) else {}
        task_count = int(source_counts.get("tasks") or 0)
        activity_count = int(source_counts.get("codexActivities") or 0)
        decision_count = int(source_counts.get("projectDecisions") or 0)
        turn_count = int(source_counts.get("codexTurns") or 0)
        work_item_count = task_count + activity_count + decision_count
        subtitle = QLabel(f"{summary.get('date', '')} · 覆盖 {work_item_count} 个工作项：{task_count} 项计划任务、{activity_count} 个 Codex 对话、{decision_count} 项项目决策、{turn_count} 次提问")
        subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box, 1)
        generated = QLabel("已写回工作台"); generated.setAlignment(Qt.AlignCenter); generated.setFixedHeight(28)
        generated.setStyleSheet("color: #087443; background: #e7f7ef; border-radius: 8px; padding: 2px 9px; font-size: 11px; font-weight: 650;"); heading.addWidget(generated)
        root.addLayout(heading)

        overview = QFrame(); overview.setObjectName("summaryOverview")
        overview.setStyleSheet("QFrame#summaryOverview { background: #f6f9ff; border: 1px solid #d7e3f6; border-left: 4px solid #2563eb; border-radius: 11px; }")
        overview_layout = QVBoxLayout(overview); overview_layout.setContentsMargins(15, 12, 15, 13); overview_layout.setSpacing(5)
        overview_title = QLabel("工作概览"); overview_title.setStyleSheet("color: #1d4ed8; font-size: 12px; font-weight: 700;"); overview_layout.addWidget(overview_title)
        overview_text = QLabel(summary.get("overview") or "昨天没有足够的记录可总结。")
        overview_text.setWordWrap(True); overview_text.setStyleSheet("color: #34445c; font-size: 13px;"); overview_layout.addWidget(overview_text); root.addWidget(overview)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget(); content.setStyleSheet("background: transparent;"); content_layout = QVBoxLayout(content); content_layout.setContentsMargins(0, 0, 6, 0); content_layout.setSpacing(10)
        sections = (("完成成果", "completed", "#16803c", "#f3fbf7"), ("仍在推进", "inProgress", "#2563eb", "#f4f7ff"), ("下一步进化建议", "nextFocus", "#7c3aed", "#faf7ff"))
        for title_text, key, color, background in sections:
            card = QFrame(); card.setObjectName("summarySection"); card.setStyleSheet(f"QFrame#summarySection {{ background: {background}; border: 1px solid #dfe6ef; border-radius: 10px; }}")
            card_layout = QVBoxLayout(card); card_layout.setContentsMargins(15, 11, 15, 13); card_layout.setSpacing(7)
            section_title = QLabel(title_text); section_title.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 700;"); card_layout.addWidget(section_title)
            items = [str(item).strip() for item in summary.get(key) or [] if str(item).strip()]
            if not items:
                empty = QLabel("没有明确记录"); empty.setStyleSheet("color: #748094; font-size: 12px;"); card_layout.addWidget(empty)
            else:
                for number, item in enumerate(items, 1):
                    row = QHBoxLayout(); row.setSpacing(9)
                    index = QLabel(str(number)); index.setAlignment(Qt.AlignCenter); index.setFixedSize(24, 24)
                    index.setStyleSheet(f"color: {color}; background: #ffffff; border: 1px solid #dbe3ee; border-radius: 7px; font-size: 11px; font-weight: 700;"); row.addWidget(index)
                    text = QLabel(item); text.setWordWrap(True); text.setStyleSheet("color: #42526a; font-size: 12px;"); row.addWidget(text, 1)
                    if key == "nextFocus":
                        plan = QPushButton(); plan.setFixedSize(116, 32); plan.setAccessibleName(f"把建议加入今日计划：{item}")
                        plan.clicked.connect(lambda _checked=False, value=item, button=plan: self.plan_suggestion(value, button))
                        self.update_suggestion_button(plan, item); self.suggestion_buttons.append(plan); row.addWidget(plan)
                    card_layout.addLayout(row)
            content_layout.addWidget(card)
        content_layout.addStretch(); scroll.setWidget(content); root.addWidget(scroll, 1)

        actions = QHBoxLayout(); actions.setSpacing(8)
        open_thread = QPushButton("打开总结对话"); open_thread.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); open_thread.setIconSize(QSize(14, 14)); open_thread.clicked.connect(parent.open_daily_summary_thread); actions.addWidget(open_thread)
        regenerate = QPushButton("重新生成"); regenerate.setIcon(fluent_icon("\uE72C", color="#1d4ed8", size=13)); regenerate.setIconSize(QSize(13, 13)); regenerate.clicked.connect(self.regenerate); actions.addWidget(regenerate)
        actions.addStretch(); close = QPushButton("关闭"); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)

    def regenerate(self):
        self.accept()
        self.window.start_daily_summary(force=True)

    def update_suggestion_button(self, button, suggestion):
        task = find_daily_summary_suggestion_task(
            getattr(self.window, "today_tasks", []), self.summary.get("date"), suggestion
        )
        if task is not None:
            status = TASK_STATUS.get(task.get("status", "planned"), "计划")
            button.setText(f"已加入 · {status}"); button.setEnabled(False)
            button.setToolTip(f"已在 {task.get('date') or '任务记录'} 中建立；不会重复创建")
            button.setStyleSheet("QPushButton:disabled { color: #087443; background: #e7f7ef; border: 1px solid #c5e5d3; border-radius: 8px; font-size: 10px; font-weight: 680; }")
        else:
            button.setText("＋ 加入今日计划"); button.setEnabled(True)
            button.setToolTip("打开任务编辑器确认项目、Codex 对话和任务文字后再保存")
            button.setStyleSheet("QPushButton { color: #6d3fc0; background: #ffffff; border: 1px solid #d7c6f3; border-radius: 8px; font-size: 10px; font-weight: 680; } QPushButton:hover, QPushButton:focus { background: #f1eaff; border-color: #a987df; }")

    def plan_suggestion(self, suggestion, button):
        task = self.window.plan_daily_summary_suggestion(self.summary, suggestion)
        if task is not None:
            self.update_suggestion_button(button, suggestion)


class ProjectDecisionHistoryDialog(QDialog):
    def __init__(self, parent, project, entries, allow_rollback=True):
        super().__init__(parent)
        self.window = getattr(parent, "window", parent)
        self.project = project
        self.allow_rollback = allow_rollback
        self.rolled_back = False
        self.setWindowTitle(f"项目决策记录 · {project.get('name', '未命名项目')}")
        self.setObjectName("projectDecisionHistory")
        self.setMinimumSize(780, 560)
        self.resize(820, 620)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self); root.setContentsMargins(26, 22, 26, 20); root.setSpacing(13)
        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(38, 38); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE81C", color="#1d4ed8", size=19).pixmap(QSize(19, 19))); icon.setStyleSheet("background: #eaf1ff; border-radius: 10px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("项目决策记录"); title.setStyleSheet("color: #172033; font-size: 22px; font-weight: 720;"); title_box.addWidget(title)
        subtitle = QLabel(f"{project.get('name', '未命名项目')}  ·  {len(entries)} 条决策、复核与生命周期记录")
        subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box); heading.addStretch(); root.addLayout(heading)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: #f7f9fc; border: 1px solid #dbe3ee; border-radius: 11px; }")
        content = QWidget(); content.setObjectName("decisionHistoryContent"); content.setStyleSheet("QWidget#decisionHistoryContent { background: #f7f9fc; }")
        rows = QVBoxLayout(content); rows.setContentsMargins(10, 10, 10, 10); rows.setSpacing(8)
        if not entries:
            empty = QLabel("暂无项目决策、复核或生命周期记录\n旧版归档可能没有时间记录；后续操作会在这里形成可审计历史")
            empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #748094; font-size: 12px; padding: 80px 20px;"); rows.addWidget(empty)
        for entry in entries:
            card = QFrame(); card.setObjectName("decisionHistoryCard"); card.setStyleSheet("QFrame#decisionHistoryCard { background: #ffffff; border: 1px solid #dce4ed; border-radius: 10px; }")
            card_layout = QVBoxLayout(card); card_layout.setContentsMargins(14, 11, 14, 12); card_layout.setSpacing(7)
            header = QHBoxLayout(); header.setSpacing(8)
            timestamp = QLabel(format_project_decision_time(entry.get("at"))); timestamp.setStyleSheet("color: #34445c; font-size: 12px; font-weight: 650;"); header.addWidget(timestamp)
            header.addStretch()
            source_text = PROJECT_DECISION_SOURCES.get(entry.get("source"), "手动决策")
            source_color, source_background = "#315f9b", "#eaf2ff"
            if entry.get("kind") == "closeout":
                source_color, source_background = {
                    "complete": ("#17623b", "#e8f7ef"),
                    "revise": ("#6d35b5", "#f2eaff"),
                    "reopen": ("#526071", "#eef2f6"),
                }.get(entry.get("action"), (source_color, source_background))
            source = QLabel(source_text); source.setAlignment(Qt.AlignCenter); source.setStyleSheet(f"color: {source_color}; background: {source_background}; border: none; border-radius: 7px; padding: 4px 8px; font-size: 10px; font-weight: 650;"); header.addWidget(source)
            if entry.get("changes") and self.allow_rollback:
                rollback = QPushButton("恢复到变更前"); rollback.setFixedHeight(30); rollback.setIcon(fluent_icon("\uE7A7", color="#526071", size=12)); rollback.setIconSize(QSize(12, 12))
                rollback.setToolTip("仅恢复这条记录中发生变化的字段，并保留一条新的回滚记录")
                rollback.clicked.connect(lambda _checked=False, value=entry: self.rollback_entry(value)); header.addWidget(rollback)
            card_layout.addLayout(header)
            if entry.get("kind") in {"review", "alignment", "lifecycle", "closeout"}:
                review_line = QLabel(format_project_decision_summary(entry)); review_line.setWordWrap(True)
                review_line.setStyleSheet("color: #526071; background: #f7f9fc; border: none; border-radius: 7px; padding: 7px 9px; font-size: 12px;"); card_layout.addWidget(review_line)
                if entry.get("kind") == "closeout":
                    snapshot = entry.get("snapshot") or {}
                    criteria = str(snapshot.get("criteria") or "").strip()
                    if criteria:
                        criteria_line = QLabel(f"验收标准 · {criteria}"); criteria_line.setWordWrap(True); criteria_line.setTextInteractionFlags(Qt.TextSelectableByMouse)
                        criteria_line.setStyleSheet("color: #315f9b; background: #f1f6ff; border: none; border-radius: 7px; padding: 6px 9px; font-size: 11px; font-weight: 600;"); card_layout.addWidget(criteria_line)
                    outcome = str(snapshot.get("outcome") or "").strip()
                    if outcome:
                        outcome_line = QLabel(outcome); outcome_line.setWordWrap(True); outcome_line.setTextInteractionFlags(Qt.TextSelectableByMouse)
                        outcome_accent = {"complete": "#7db694", "revise": "#a982d6", "reopen": "#9aa7b6"}.get(entry.get("action"), "#7db694")
                        outcome_line.setStyleSheet(f"color: #30455f; border-left: 3px solid {outcome_accent}; padding: 4px 9px; font-size: 12px;"); card_layout.addWidget(outcome_line)
            blocker_lifecycle = entry.get("blockerLifecycle") or {}
            if blocker_lifecycle:
                blocker_action = blocker_lifecycle.get("action")
                blocker_duration = str(blocker_lifecycle.get("duration") or "时长未知")
                lifecycle_text = {
                    "started": "阻塞计时从这次决策开始",
                    "updated": f"阻塞说明已更新 · 已持续 {blocker_duration} · 计时未重置",
                    "resolved": f"阻塞已解除 · 本次持续 {blocker_duration}",
                }.get(blocker_action, "阻塞状态已更新")
                lifecycle_line = QLabel(lifecycle_text); lifecycle_line.setWordWrap(True)
                lifecycle_color = "#17623b" if blocker_action == "resolved" else "#8f2f27"
                lifecycle_background = "#edf8f2" if blocker_action == "resolved" else "#fff4f1"
                lifecycle_line.setStyleSheet(f"color: {lifecycle_color}; background: {lifecycle_background}; border: none; border-radius: 7px; padding: 6px 9px; font-size: 11px; font-weight: 650;"); card_layout.addWidget(lifecycle_line)
            for change in entry.get("changes") or []:
                field = change.get("field")
                before = display_project_decision_value(field, change.get("before"))
                after = display_project_decision_value(field, change.get("after"))
                line = QLabel(f"{change.get('label') or PROJECT_DECISION_FIELDS.get(field, '项目字段')}：  {before}  →  {after}")
                line.setWordWrap(True); line.setTextInteractionFlags(Qt.TextSelectableByMouse); line.setStyleSheet("color: #526071; font-size: 12px; padding: 2px 0;"); card_layout.addWidget(line)
            rows.addWidget(card)
        rows.addStretch(); scroll.setWidget(content); root.addWidget(scroll, 1)
        actions = QHBoxLayout(); actions.addStretch(); close = QPushButton("关闭"); close.setFixedHeight(36); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)

    def rollback_entry(self, entry):
        requested, affected, conflicts = build_project_decision_rollback(self.project, entry)
        if not affected:
            QMessageBox.information(self, "无需恢复", "当前项目已经与这条记录变更前的值一致。")
            return
        preview = []
        for detail in affected[:5]:
            current = display_project_decision_value(detail["field"], detail["current"])
            target = display_project_decision_value(detail["field"], detail["target"])
            preview.append(f"• {detail['label']}：{current} → {target}")
        if len(affected) > 5:
            preview.append(f"• 另 {len(affected) - 5} 项")
        notes = ["将只恢复这条记录涉及的字段：", *preview]
        if conflicts:
            labels = "、".join(detail["label"] for detail in conflicts)
            notes.extend(["", f"注意：{labels} 在此后又发生过变化，本次恢复会覆盖这些字段的当前值。"])
        pending = open_project_tasks(self.window.today_tasks, self.project) if requested.get("status") == "completed" else []
        if pending:
            notes.extend(["", f"项目仍关联 {len(pending)} 项未完成任务；恢复项目状态不会改写这些任务。"])
        notes.extend(["", "回滚完成后会新增一条“撤销操作”记录，历史不会被删除。是否继续？"])
        answer = QMessageBox.question(
            self,
            "恢复项目决策",
            "\n".join(notes),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes and self.window.rollback_project_decision(self.project, entry):
            self.rolled_back = True
            self.accept()


class TaskWipDialog(QDialog):
    """Make in-progress capacity visible and let the user deliberately reduce it."""
    def __init__(self, parent, target_date):
        super().__init__(parent)
        self.window = parent
        self.target_date = str(target_date or "")
        self.setWindowTitle("进行中容量")
        self.setObjectName("taskWipDialog")
        self.setMinimumSize(760, 560)
        self.resize(840, 680)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE9D2", color="#1d4ed8", size=21).pixmap(QSize(21, 21)))
        icon.setStyleSheet("background: #eaf1ff; border: 1px solid #cad9ef; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("控制今日在制任务"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        subtitle = QLabel("WIP 容量是软性提醒：不会阻止任务启动，也不会自动改变任何任务状态")
        subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box, 1)
        self.limit_button = QPushButton(); self.limit_button.setFixedHeight(36)
        self.limit_button.setIcon(fluent_icon("\uE70F", color="#1d4ed8", size=13)); self.limit_button.setIconSize(QSize(13, 13))
        self.limit_button.setToolTip("调整允许同时处于进行中的任务数量"); self.limit_button.clicked.connect(self.change_limit); heading.addWidget(self.limit_button)
        root.addLayout(heading)

        self.summary = QFrame(); self.summary.setObjectName("taskWipSummary")
        summary_layout = QHBoxLayout(self.summary); summary_layout.setContentsMargins(18, 13, 18, 13); summary_layout.setSpacing(22)
        self.count_metric = self.metric_widget("进行中", "0", "#1d4ed8"); summary_layout.addWidget(self.count_metric[0], 1)
        divider = QFrame(); divider.setFrameShape(QFrame.VLine); divider.setStyleSheet("color: #dfe6ef;"); summary_layout.addWidget(divider)
        self.limit_metric = self.metric_widget("容量", "0", "#315f9b"); summary_layout.addWidget(self.limit_metric[0], 1)
        divider = QFrame(); divider.setFrameShape(QFrame.VLine); divider.setStyleSheet("color: #dfe6ef;"); summary_layout.addWidget(divider)
        self.judgement_metric = self.metric_widget("执行判断", "待计算", "#087443"); summary_layout.addWidget(self.judgement_metric[0], 2)
        root.addWidget(self.summary)

        self.guidance = QFrame(); self.guidance.setObjectName("taskWipGuidance")
        guidance_layout = QHBoxLayout(self.guidance); guidance_layout.setContentsMargins(11, 8, 10, 8); guidance_layout.setSpacing(9)
        self.guidance_icon = QLabel(); self.guidance_icon.setFixedSize(26, 26); self.guidance_icon.setAlignment(Qt.AlignCenter); guidance_layout.addWidget(self.guidance_icon)
        self.guidance_text = QLabel(); self.guidance_text.setWordWrap(True); self.guidance_text.setStyleSheet("color: #526071; font-size: 11px;"); guidance_layout.addWidget(self.guidance_text, 1)
        self.recommend_button = QPushButton("移回计划"); self.recommend_button.setFixedHeight(32); self.recommend_button.setIcon(fluent_icon("\uE72A", color="#b54708", size=13)); self.recommend_button.setIconSize(QSize(13, 13)); self.recommend_button.clicked.connect(self.apply_recommendation); guidance_layout.addWidget(self.recommend_button)
        root.addWidget(self.guidance)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: #f7f9fc; border: 1px solid #dbe3ee; border-radius: 11px; }")
        self.rows_widget = QWidget(); self.rows_widget.setObjectName("taskWipRows"); self.rows_widget.setStyleSheet("QWidget#taskWipRows { background: #f7f9fc; }")
        self.rows_layout = QVBoxLayout(self.rows_widget); self.rows_layout.setContentsMargins(10, 10, 10, 10); self.rows_layout.setSpacing(7)
        scroll.setWidget(self.rows_widget); root.addWidget(scroll, 1)
        actions = QHBoxLayout(); actions.setSpacing(9)
        self.undo_feedback = QLabel(); self.undo_feedback.setStyleSheet("color: #526071; font-size: 11px;"); self.undo_feedback.hide(); actions.addWidget(self.undo_feedback, 1)
        actions.addStretch(1)
        self.undo_wip_button = QPushButton("撤销刚才收敛"); self.undo_wip_button.setFixedHeight(36)
        self.undo_wip_button.setIcon(fluent_icon("\uE7A7", color="#1d4ed8", size=13)); self.undo_wip_button.setIconSize(QSize(13, 13))
        self.undo_wip_button.setToolTip("将刚刚移回计划的任务恢复为进行中"); self.undo_wip_button.setAccessibleName("撤销刚才的 WIP 收敛")
        self.undo_wip_button.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #bfd1ef; border-radius: 8px; padding: 5px 11px; font-size: 11px; font-weight: 700; } QPushButton:hover, QPushButton:focus { background: #dfe9fb; border-color: #8eace0; }")
        self.undo_wip_button.clicked.connect(self.undo_last_wip_change); self.undo_wip_button.hide(); actions.addWidget(self.undo_wip_button)
        self.undo_wip_timer = QTimer(self); self.undo_wip_timer.setSingleShot(True); self.undo_wip_timer.timeout.connect(self.expire_wip_undo)
        close = QPushButton("完成"); close.setObjectName("primary"); close.setFixedHeight(38); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)
        self.render_state()

    @staticmethod
    def metric_widget(caption, value, color):
        frame = QWidget(); layout = QVBoxLayout(frame); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(1)
        value_label = QLabel(value); value_label.setStyleSheet(f"color: {color}; font-size: 21px; font-weight: 760;"); layout.addWidget(value_label)
        caption_label = QLabel(caption); caption_label.setStyleSheet("color: #748094; font-size: 10px; font-weight: 600;"); layout.addWidget(caption_label)
        return frame, value_label, caption_label

    def clear_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0); widget = item.widget()
            if widget is not None:
                widget.hide(); widget.setParent(None); widget.deleteLater()

    def render_state(self):
        self.clear_rows()
        state = self.window.task_wip_state(self.target_date)
        self.limit_button.setText(f"WIP 容量 {state['limit']}")
        self.count_metric[1].setText(str(state["count"])); self.limit_metric[1].setText(str(state["limit"]))
        if state["overBy"]:
            judgement = f"超出 {state['overBy']} 项"
            color, background, border = "#b54708", "#fff8ed", "#efd7b4"
        elif state["count"]:
            judgement = f"尚可增加 {state['remaining']} 项"
            color, background, border = "#087443", "#eef9f3", "#c8e7d6"
        else:
            judgement = "当前无在制任务"
            color, background, border = "#66758a", "#f5f7fa", "#d8e1eb"
        self.judgement_metric[1].setText(judgement); self.judgement_metric[1].setStyleSheet(f"color: {color}; font-size: 16px; font-weight: 720;")
        self.summary.setStyleSheet(f"QFrame#taskWipSummary {{ background: {background}; border: 1px solid {border}; border-radius: 12px; }} QFrame#taskWipSummary QLabel {{ background: transparent; border: none; }}")
        protected_ids = {str(task.get("id") or "") for task in state["protected"]}
        self.recommendations = wip_deferral_recommendations(
            self.window.today_tasks,
            self.window.projects,
            self.target_date,
            state["overBy"],
            protected_ids,
        )
        self.task_decisions = wip_task_decisions(state, self.recommendations, self.window.projects)
        primary_recommendation = self.recommendations[0] if self.recommendations else None
        if state["overBy"] and primary_recommendation:
            task = primary_recommendation["task"]
            remaining = max(0, state["overBy"] - 1)
            remaining_text = f"执行后仍需再收敛 {remaining} 项" if remaining else "执行后即可恢复容量"
            self.guidance_text.setText(
                f"建议收敛“{task.get('title') or '未命名任务'}”。依据：{primary_recommendation['reason']}。"
                f"影响：任务回到计划并保留全部记录；{remaining_text}。"
                "规则：先保护运行中的 Codex，再按项目优先级和你的看板顺序判断。"
            )
            self.guidance_icon.setPixmap(fluent_icon("\uE8EF", color="#b54708", size=15).pixmap(QSize(15, 15)))
            self.guidance_icon.setStyleSheet("background: #f8e7cd; border-radius: 7px;")
            self.guidance.setStyleSheet("QFrame#taskWipGuidance { background: #fff8ed; border: 1px solid #efd7b4; border-radius: 9px; }")
            self.recommend_button.setVisible(True)
            self.recommend_button.setToolTip(f"移回计划：{task.get('title') or '未命名任务'}")
            self.recommend_button.setStyleSheet("QPushButton { color: #9a3412; background: #ffffff; border: 1px solid #e7bd82; border-radius: 8px; padding: 4px 10px; font-size: 11px; font-weight: 700; } QPushButton:hover, QPushButton:focus { background: #fff3df; border-color: #c98b36; }")
        elif state["overBy"]:
            self.guidance_text.setText("当前超载任务均由 Codex 运行保护，暂不建议移回计划；可等待运行结束，或主动调整 WIP 容量。运行保护始终高于项目优先级和看板顺序。")
            self.guidance_icon.setPixmap(fluent_icon("\uE7BA", color="#b54708", size=15).pixmap(QSize(15, 15)))
            self.guidance_icon.setStyleSheet("background: #f8e7cd; border-radius: 7px;")
            self.guidance.setStyleSheet("QFrame#taskWipGuidance { background: #fff8ed; border: 1px solid #efd7b4; border-radius: 9px; }")
            self.recommend_button.setVisible(False)
        else:
            self.guidance_text.setText("当前并行量在容量内。正在运行的 Codex 任务会继续受到保护，不会被建议移回计划。")
            self.guidance_icon.setPixmap(fluent_icon("\uE73E", color="#087443", size=15).pixmap(QSize(15, 15)))
            self.guidance_icon.setStyleSheet("background: #e7f7ef; border-radius: 7px;")
            self.guidance.setStyleSheet("QFrame#taskWipGuidance { background: #f3f8f5; border: 1px solid #d7e8de; border-radius: 9px; }")
            self.recommend_button.setVisible(False)
        recommended_id = str((primary_recommendation or {}).get("task", {}).get("id") or "")
        recommended_reason = str((primary_recommendation or {}).get("reason") or "")
        if not state["doing"]:
            empty = QLabel("当前没有进行中的任务"); empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #748094; padding: 70px; font-size: 13px;"); self.rows_layout.addWidget(empty)
        for task in state["doing"]:
            task_id = str(task.get("id") or "")
            decision = dict(self.task_decisions.get(task_id) or {})
            if task_id == recommended_id and recommended_reason:
                decision["reason"] = recommended_reason
            self.rows_layout.addWidget(self.task_row(task, decision))
        self.rows_layout.addStretch()

    def task_row(self, task, decision):
        action = str((decision or {}).get("action") or "keep")
        protected = action == "protected"
        recommended = action == "defer"
        queued = action == "queued"
        decision_reason = str((decision or {}).get("reason") or "当前在制任务")
        row = QFrame(); row.setObjectName("taskWipRow")
        accent = "#10a361" if protected else ("#d97706" if recommended or queued else "#2563eb")
        row.setStyleSheet(f"QFrame#taskWipRow {{ background: #ffffff; border: 1px solid #dfe6ef; border-left: 4px solid {accent}; border-radius: 10px; }} QFrame#taskWipRow QLabel {{ background: transparent; border: none; }}")
        layout = QHBoxLayout(row); layout.setContentsMargins(14, 10, 10, 10); layout.setSpacing(11)
        text = QVBoxLayout(); text.setSpacing(3)
        title = ElidedLabel(task.get("title") or "未命名任务"); title.setToolTip(task.get("title") or "未命名任务"); title.setStyleSheet("color: #253247; font-size: 14px; font-weight: 700;"); text.addWidget(title)
        project = self.window.project_by_id(task.get("projectId")) or {}
        meta_text = f"{task_project_identity(task, project)['name']}  ·  {task.get('conversationTitle') or '未关联 Codex 对话'}"
        meta = ElidedLabel(meta_text); meta.setToolTip(meta_text); meta.setStyleSheet("color: #66758a; font-size: 11px;"); text.addWidget(meta)
        basis_text = f"管理依据 · {(decision or {}).get('priorityLabel') or '常规推进'} · {decision_reason}"
        basis = ElidedLabel(basis_text); basis.setToolTip(basis_text)
        basis.setStyleSheet(f"color: {accent}; font-size: 10px; font-weight: 600;"); text.addWidget(basis); layout.addLayout(text, 1)
        state_text = str((decision or {}).get("label") or "建议保留")
        state = QLabel(state_text); state.setAlignment(Qt.AlignCenter); state.setFixedSize(88 if queued else 78, 26)
        state_style = "color: #087443; background: #e7f7ef;" if protected else ("color: #9a3412; background: #fff1dc;" if recommended or queued else "color: #1d4ed8; background: #e8f0ff;")
        state.setStyleSheet(state_style + " border-radius: 8px; font-size: 10px; font-weight: 650;")
        state.setToolTip(decision_reason)
        layout.addWidget(state)
        if task.get("sessionId"):
            open_codex = QToolButton(); open_codex.setFixedSize(34, 34); open_codex.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); open_codex.setIconSize(QSize(14, 14)); open_codex.setToolTip("打开关联的 Codex 对话")
            open_codex.clicked.connect(lambda _checked=False, value=task: self.open_codex_task(value)); layout.addWidget(open_codex)
        defer = QPushButton("运行保护" if protected else "移回计划"); defer.setFixedSize(90, 34); defer.setEnabled(not protected)
        defer.setToolTip("Codex 正在执行，不能移回计划" if protected else f"{decision_reason}。仍可由你决定移回计划；全部历史记录会保留")
        if protected:
            defer.setStyleSheet("QPushButton:disabled { color: #708097; background: #eef2f6; border: 1px solid #d8e1eb; border-radius: 8px; font-size: 11px; font-weight: 650; }")
        elif recommended:
            defer.setStyleSheet("QPushButton { color: #9a3412; background: #fff8ed; border: 1px solid #e7bd82; border-radius: 8px; font-size: 11px; font-weight: 700; } QPushButton:hover, QPushButton:focus { background: #fff1dc; border-color: #c98b36; }")
        defer.clicked.connect(lambda _checked=False, value=task: self.defer_task(value)); layout.addWidget(defer)
        return row

    def change_limit(self):
        current = task_wip_limit()
        value, accepted = QInputDialog.getInt(self, "调整 WIP 容量", "最多同时进行多少项任务？", current, 1, 9, 1)
        if accepted:
            self.window.update_task_wip_limit(value); self.render_state()

    def defer_task(self, task):
        if self.window.defer_task_from_wip(task):
            state = self.window.task_wip_state(self.target_date)
            title = str(task.get("title") or "未命名任务")
            self.undo_feedback.setText(f"已收敛“{title}” · 当前 {state['count']}/{state['limit']}，全部记录已保留")
            self.undo_feedback.setToolTip(self.undo_feedback.text()); self.undo_feedback.show()
            self.undo_wip_button.show()
            # The main window owns the authoritative undo snapshot for eight seconds.
            # Hide this modal-local affordance slightly earlier so it cannot outlive that snapshot.
            self.undo_wip_timer.start(7500)
            self.render_state()

    def expire_wip_undo(self):
        self.undo_wip_button.hide()
        if self.undo_feedback.isVisible():
            self.undo_feedback.setText("最近一次收敛已记录在任务历史中")

    def undo_last_wip_change(self):
        self.undo_wip_timer.stop(); self.undo_wip_button.hide()
        self.window.undo_last_task_transition()
        self.undo_feedback.setText("已撤销收敛，任务恢复为进行中"); self.undo_feedback.show()
        self.render_state()

    def apply_recommendation(self):
        recommendation = self.recommendations[0] if getattr(self, "recommendations", None) else None
        if recommendation:
            self.defer_task(recommendation["task"])

    def open_codex_task(self, task):
        conversation = self.window.conversation_by_id(task.get("sessionId"))
        if conversation is not None:
            self.window.open_codex_conversation(conversation)


class PlanningBacklogDialog(QDialog):
    """Review unstarted plans from past dates without silently moving them."""

    def __init__(self, parent):
        super().__init__(parent)
        self.window = parent
        self.today = QDate.currentDate()
        self.setWindowTitle("历史计划重新安排")
        self.setObjectName("planningBacklogDialog")
        self.setMinimumSize(760, 520)
        self.resize(820, 620)
        self.setStyleSheet(STYLE + """
            QDialog#planningBacklogDialog { background: #f5f7fb; }
            QFrame#planningBacklogHero { background: #fffaf0; border: 1px solid #ead7ad; border-radius: 13px; }
            QFrame#planningBacklogRow { background: #ffffff; border: 1px solid #dce4ee; border-left: 4px solid #d69e2e; border-radius: 10px; }
            QFrame#planningBacklogRow:hover { border-color: #d4b56d; background: #fffdf8; }
        """)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE787", color="#9a6700", size=21).pixmap(QSize(21, 21)))
        icon.setStyleSheet("background: #f7ebcf; border: 1px solid #ead7ad; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("重新安排未启动的历史计划"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        subtitle = QLabel("过去日期中的计划不会被自动改期；逐项确认后移到今天，并保留原日期记录")
        subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box, 1)
        self.count = QLabel(); self.count.setAlignment(Qt.AlignCenter); self.count.setFixedHeight(30)
        self.count.setStyleSheet("color: #8a5b00; background: #fff4d8; border: 1px solid #ead7ad; border-radius: 8px; padding: 2px 10px; font-size: 11px; font-weight: 700;"); heading.addWidget(self.count)
        root.addLayout(heading)

        hero = QFrame(); hero.setObjectName("planningBacklogHero")
        hero_layout = QHBoxLayout(hero); hero_layout.setContentsMargins(14, 10, 14, 10); hero_layout.setSpacing(9)
        hero_icon = QLabel(); hero_icon.setFixedSize(26, 26); hero_icon.setAlignment(Qt.AlignCenter); hero_icon.setPixmap(fluent_icon("\uE7BA", color="#9a6700", size=14).pixmap(QSize(14, 14))); hero_layout.addWidget(hero_icon)
        guidance = QLabel("这不是逾期告警，而是一次计划真实性复核：仍值得做的移到今天，不再需要的可打开编辑或移入回收站。")
        guidance.setWordWrap(True); guidance.setStyleSheet("color: #6f5218; font-size: 11px;"); hero_layout.addWidget(guidance, 1); root.addWidget(hero)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: #f7f9fc; border: 1px solid #dbe3ee; border-radius: 11px; }")
        self.rows_widget = QWidget(); self.rows_widget.setObjectName("planningBacklogRows"); self.rows_widget.setStyleSheet("QWidget#planningBacklogRows { background: #f7f9fc; }")
        self.rows_layout = QVBoxLayout(self.rows_widget); self.rows_layout.setContentsMargins(10, 10, 10, 10); self.rows_layout.setSpacing(7)
        scroll.setWidget(self.rows_widget); root.addWidget(scroll, 1)
        actions = QHBoxLayout()
        self.undo_move = QPushButton("撤销上次改期"); self.undo_move.setFixedHeight(38); self.undo_move.setIcon(fluent_icon("\uE7A7", color="#315f9b", size=13)); self.undo_move.setIconSize(QSize(13, 13))
        self.undo_move.setToolTip("仅在任务尚未发生其他变化时恢复原计划日期"); self.undo_move.clicked.connect(self.undo_last_move); self.undo_move.hide(); actions.addWidget(self.undo_move)
        self.undo_move_timer = QTimer(self); self.undo_move_timer.setSingleShot(True); self.undo_move_timer.timeout.connect(self.undo_move.hide)
        actions.addStretch(); close = QPushButton("完成"); close.setObjectName("primary"); close.setFixedHeight(38); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)
        self.render_tasks()

    def render_tasks(self):
        MainWindow._clear_layout(self.rows_layout)
        tasks = self.window.planning_backlog()
        self.count.setText(f"{len(tasks)} 项待安排")
        if not tasks:
            empty = QWidget(); empty_layout = QVBoxLayout(empty); empty_layout.setAlignment(Qt.AlignCenter)
            icon = QLabel(); icon.setAlignment(Qt.AlignCenter); icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=28).pixmap(QSize(28, 28))); empty_layout.addWidget(icon)
            text = QLabel("历史计划已经处理完毕"); text.setAlignment(Qt.AlignCenter); text.setStyleSheet("color: #34445c; font-size: 14px; font-weight: 650; margin-top: 8px;"); empty_layout.addWidget(text)
            detail = QLabel("今天的任务板只保留经过确认的计划"); detail.setAlignment(Qt.AlignCenter); detail.setStyleSheet("color: #748094; font-size: 11px;"); empty_layout.addWidget(detail)
            self.rows_layout.addWidget(empty, 1); return
        for task in tasks:
            self.rows_layout.addWidget(self.task_row(task))
        self.rows_layout.addStretch()

    def task_row(self, task):
        row = QFrame(); row.setObjectName("planningBacklogRow"); row.setMinimumHeight(74)
        layout = QHBoxLayout(row); layout.setContentsMargins(14, 10, 10, 10); layout.setSpacing(11)
        text = QVBoxLayout(); text.setSpacing(3)
        title = ElidedLabel(str(task.get("title") or "未命名任务")); title.setToolTip(str(task.get("title") or "")); title.setStyleSheet("color: #253247; font-size: 14px; font-weight: 700;"); text.addWidget(title)
        project = self.window.project_by_id(task.get("projectId")) or {}
        original = QDate.fromString(str(task.get("date") or ""), Qt.ISODate)
        original_text = original.toString("yyyy年MM月dd日") if original.isValid() else str(task.get("date") or "日期未知")
        age = original.daysTo(self.today) if original.isValid() else 0
        meta_text = f"{task_project_identity(task, project)['name']}  ·  原计划 {original_text}" + (f"  ·  已过去 {age} 天" if age > 0 else "")
        meta = ElidedLabel(meta_text); meta.setToolTip(meta_text); meta.setStyleSheet("color: #66758a; font-size: 10px;"); text.addWidget(meta)
        notes = ElidedLabel(str(task.get("notes") or "尚无计划说明")); notes.setToolTip(str(task.get("notes") or "")); notes.setStyleSheet("color: #7a8798; font-size: 10px;"); text.addWidget(notes); layout.addLayout(text, 1)
        view = QToolButton(); view.setFixedSize(34, 34); view.setIcon(fluent_icon("\uE81C", color="#315f9b", size=14)); view.setIconSize(QSize(14, 14)); view.setToolTip("查看任务档案")
        view.clicked.connect(lambda _checked=False, value=task: self.window.show_task_audit(value)); layout.addWidget(view)
        edit = QPushButton("编辑"); edit.setFixedSize(64, 34); edit.setToolTip("调整任务内容、状态、项目或日期")
        edit.clicked.connect(lambda _checked=False, value=task: self.edit_task(value)); layout.addWidget(edit)
        move = QPushButton("移到今天"); move.setFixedSize(94, 34); move.setIcon(fluent_icon("\uE72A", color="#8a5b00", size=13)); move.setIconSize(QSize(13, 13))
        move.setStyleSheet("QPushButton { color: #8a5b00; background: #fff8e8; border: 1px solid #dfc581; border-radius: 8px; font-size: 11px; font-weight: 700; } QPushButton:hover, QPushButton:focus { background: #fff1cd; border-color: #c79c3a; }")
        move.clicked.connect(lambda _checked=False, value=task: self.move_to_today(value)); layout.addWidget(move)
        return row

    def move_to_today(self, task):
        if self.window.reschedule_planned_task(task, self.today.toString(Qt.ISODate)):
            self.undo_move.show(); self.undo_move_timer.start(8000)
            self.render_tasks()

    def undo_last_move(self):
        self.undo_move_timer.stop(); self.undo_move.hide()
        self.window.undo_last_task_transition()
        self.render_tasks()

    def edit_task(self, task):
        self.window.edit_today_task(task)
        self.render_tasks()


class TaskCompletionEvidenceDialog(QDialog):
    """Close the gap between a completed status and a verifiable result."""

    def __init__(self, parent):
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("任务完成成果待补录")
        self.setObjectName("completionEvidenceDialog")
        self.setMinimumSize(760, 520)
        self.resize(820, 620)
        self.setStyleSheet(STYLE + """
            QDialog#completionEvidenceDialog { background: #f5f7fb; }
            QFrame#completionEvidenceHero { background: #f3faf7; border: 1px solid #c9e3d6; border-radius: 13px; }
            QFrame#completionEvidenceRow { background: #ffffff; border: 1px solid #dce4ee; border-left: 4px solid #2f8f68; border-radius: 10px; }
            QFrame#completionEvidenceRow:hover { border-color: #a8d2be; background: #fbfefc; }
        """)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE73E", color="#176b4d", size=21).pixmap(QSize(21, 21)))
        icon.setStyleSheet("background: #e2f3ea; border: 1px solid #c9e3d6; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("补齐已完成任务的实际成果"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        subtitle = QLabel("完成状态保留不变；补充一句交付、结果或验证，日报与项目交接才会把它作为成果引用")
        subtitle.setWordWrap(True); subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box, 1)
        self.count = QLabel(); self.count.setAlignment(Qt.AlignCenter); self.count.setFixedHeight(30)
        self.count.setStyleSheet("color: #176b4d; background: #e8f6ef; border: 1px solid #c9e3d6; border-radius: 8px; padding: 2px 10px; font-size: 11px; font-weight: 700;"); heading.addWidget(self.count)
        root.addLayout(heading)

        hero = QFrame(); hero.setObjectName("completionEvidenceHero")
        hero_layout = QHBoxLayout(hero); hero_layout.setContentsMargins(14, 10, 14, 10); hero_layout.setSpacing(9)
        hero_icon = QLabel(); hero_icon.setFixedSize(26, 26); hero_icon.setAlignment(Qt.AlignCenter)
        hero_icon.setPixmap(fluent_icon("\uE946", color="#176b4d", size=14).pixmap(QSize(14, 14))); hero_layout.addWidget(hero_icon)
        guidance = QLabel("系统不会替你编造成果。请记录已经发生的结果；如果任务其实尚未结束，可打开编辑并恢复为进行中。")
        guidance.setWordWrap(True); guidance.setStyleSheet("color: #365f4e; font-size: 11px;"); hero_layout.addWidget(guidance, 1); root.addWidget(hero)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: #f7f9fc; border: 1px solid #dbe3ee; border-radius: 11px; }")
        self.rows_widget = QWidget(); self.rows_widget.setObjectName("completionEvidenceRows")
        self.rows_widget.setStyleSheet("QWidget#completionEvidenceRows { background: #f7f9fc; }")
        self.rows_layout = QVBoxLayout(self.rows_widget); self.rows_layout.setContentsMargins(10, 10, 10, 10); self.rows_layout.setSpacing(7)
        scroll.setWidget(self.rows_widget); root.addWidget(scroll, 1)
        actions = QHBoxLayout(); actions.addStretch()
        close = QPushButton("完成"); close.setObjectName("primary"); close.setFixedHeight(38); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)
        self.render_tasks()

    def render_tasks(self):
        MainWindow._clear_layout(self.rows_layout)
        tasks = self.window.completion_evidence_queue()
        self.count.setText(f"{len(tasks)} 项待补录")
        if not tasks:
            empty = QWidget(); empty_layout = QVBoxLayout(empty); empty_layout.setAlignment(Qt.AlignCenter)
            icon = QLabel(); icon.setAlignment(Qt.AlignCenter); icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=28).pixmap(QSize(28, 28))); empty_layout.addWidget(icon)
            text = QLabel("完成成果已经补齐"); text.setAlignment(Qt.AlignCenter); text.setStyleSheet("color: #34445c; font-size: 14px; font-weight: 650; margin-top: 8px;"); empty_layout.addWidget(text)
            detail = QLabel("日报和项目交接可以引用这些人工确认的结果"); detail.setAlignment(Qt.AlignCenter); detail.setStyleSheet("color: #748094; font-size: 11px;"); empty_layout.addWidget(detail)
            self.rows_layout.addWidget(empty, 1); return
        for task in tasks:
            self.rows_layout.addWidget(self.task_row(task))
        self.rows_layout.addStretch()

    def task_row(self, task):
        row = QFrame(); row.setObjectName("completionEvidenceRow"); row.setMinimumHeight(74)
        layout = QHBoxLayout(row); layout.setContentsMargins(14, 10, 10, 10); layout.setSpacing(11)
        text = QVBoxLayout(); text.setSpacing(3)
        title_text = str(task.get("title") or "未命名任务")
        title = ElidedLabel(title_text); title.setToolTip(title_text); title.setStyleSheet("color: #253247; font-size: 14px; font-weight: 700;"); text.addWidget(title)
        project = self.window.project_by_id(task.get("projectId")) or {}
        task_date = QDate.fromString(str(task.get("date") or ""), Qt.ISODate)
        date_text = task_date.toString("yyyy年MM月dd日") if task_date.isValid() else str(task.get("date") or "日期未知")
        meta_text = f"{task_project_identity(task, project)['name']}  ·  完成日期 {date_text}"
        meta = ElidedLabel(meta_text); meta.setToolTip(meta_text); meta.setStyleSheet("color: #66758a; font-size: 10px;"); text.addWidget(meta)
        notes_text = str(task.get("notes") or "尚无计划说明").replace("\n", " ")
        notes = ElidedLabel(f"原计划 · {notes_text}"); notes.setToolTip(notes_text); notes.setStyleSheet("color: #7a8798; font-size: 10px;"); text.addWidget(notes); layout.addLayout(text, 1)
        view = QToolButton(); view.setFixedSize(34, 34); view.setIcon(fluent_icon("\uE81C", color="#315f9b", size=14)); view.setIconSize(QSize(14, 14)); view.setToolTip("查看任务档案")
        view.clicked.connect(lambda _checked=False, value=task: self.window.show_task_audit(value)); layout.addWidget(view)
        edit = QPushButton("编辑任务"); edit.setFixedSize(76, 34); edit.setToolTip("任务若尚未结束，可恢复为计划或进行中")
        edit.clicked.connect(lambda _checked=False, value=task: self.edit_task(value)); layout.addWidget(edit)
        record = QPushButton("记录成果"); record.setFixedSize(94, 34); record.setIcon(fluent_icon("\uE73E", color="#176b4d", size=13)); record.setIconSize(QSize(13, 13))
        record.setStyleSheet("QPushButton { color: #176b4d; background: #eef9f3; border: 1px solid #abd6c1; border-radius: 8px; font-size: 11px; font-weight: 700; } QPushButton:hover, QPushButton:focus { background: #e1f3e9; border-color: #79bc9d; }")
        record.clicked.connect(lambda _checked=False, value=task: self.record_outcome(value)); layout.addWidget(record)
        return row

    def record_outcome(self, task):
        if self.window.edit_task_outcome(task):
            self.render_tasks()

    def edit_task(self, task):
        self.window.edit_today_task(task)
        self.render_tasks()


class LifecycleCalibrationDialog(QDialog):
    """Review quiet active projects one at a time without auto-pausing anything."""
    def __init__(self, parent, queue_items):
        super().__init__(parent)
        self.window = parent
        self.pending = list(queue_items or [])
        self.processed_count = 0
        self.deferred_count = 0
        self.setWindowTitle("活跃组合校准")
        self.setObjectName("lifecycleCalibrationDialog")
        self.setMinimumSize(740, 520)
        self.resize(800, 580)
        self.setStyleSheet(STYLE + "QDialog#lifecycleCalibrationDialog QLabel[sectionLabel='true'] { color: #66758a; font-size: 11px; font-weight: 650; }")
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE823", color="#315f9b", size=21).pixmap(QSize(21, 21)))
        icon.setStyleSheet("background: #eaf2ff; border: 1px solid #cad9ef; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("校准真正的活跃项目组合"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        self.subtitle = QLabel("逐项确认静默项目仍应推进还是暂缓；静默只触发复核，不代表风险")
        self.subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(self.subtitle); heading.addLayout(title_box, 1)
        self.threshold_button = QPushButton(); self.threshold_button.setFixedHeight(36)
        self.threshold_button.setIcon(fluent_icon("\uE70F", color="#315f9b", size=13)); self.threshold_button.setIconSize(QSize(13, 13))
        self.threshold_button.setToolTip("调整多久没有执行证据后进入组合校准"); self.threshold_button.clicked.connect(self.change_threshold); heading.addWidget(self.threshold_button)
        self.counter = QLabel(); self.counter.setFixedHeight(28); self.counter.setAlignment(Qt.AlignCenter)
        self.counter.setStyleSheet("color: #315f9b; background: #eaf2ff; border-radius: 8px; padding: 2px 10px; font-size: 11px; font-weight: 650;"); heading.addWidget(self.counter)
        root.addLayout(heading)

        self.card = QFrame(); self.card.setObjectName("lifecycleCalibrationCard")
        self.card.setStyleSheet("QFrame#lifecycleCalibrationCard { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 13px; } QFrame#lifecycleCalibrationCard QLabel { background: transparent; border: none; }")
        self.card_layout = QVBoxLayout(self.card); self.card_layout.setContentsMargins(20, 18, 20, 20); self.card_layout.setSpacing(12); root.addWidget(self.card, 1)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); self.feedback.setStyleSheet("color: #66758a; font-size: 11px;"); root.addWidget(self.feedback)

        actions = QHBoxLayout(); actions.setSpacing(8)
        close = QPushButton("关闭"); close.clicked.connect(self.reject); actions.addWidget(close); actions.addStretch()
        self.open_button = QPushButton("打开项目面板"); self.open_button.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); self.open_button.setIconSize(QSize(14, 14))
        self.open_button.setToolTip("查看完整项目资料；关闭项目面板后返回本轮生命周期校准")
        self.open_button.setAccessibleName("查看当前项目详情并返回生命周期校准队列")
        self.open_button.clicked.connect(self.open_current); actions.addWidget(self.open_button)
        self.defer_button = QPushButton("稍后处理"); self.defer_button.clicked.connect(self.defer_current); actions.addWidget(self.defer_button)
        self.pause_button = QPushButton("暂缓项目"); self.pause_button.clicked.connect(self.pause_current); actions.addWidget(self.pause_button)
        self.keep_button = QPushButton("确认继续活跃"); self.keep_button.setObjectName("primary"); self.keep_button.setIcon(fluent_icon("\uE73E", color="#ffffff", size=14)); self.keep_button.setIconSize(QSize(14, 14)); self.keep_button.clicked.connect(self.keep_current); actions.addWidget(self.keep_button)
        root.addLayout(actions); self.render_current()

    def clear_card(self):
        def clear(layout):
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget(); child = item.layout()
                if widget is not None:
                    widget.hide(); widget.setParent(None); widget.deleteLater()
                elif child is not None:
                    clear(child); child.deleteLater()
        clear(self.card_layout)

    def current_item(self):
        return self.pending[0] if self.pending else None

    def render_current(self):
        self.clear_card()
        remaining = len(self.pending); total = self.processed_count + self.deferred_count + remaining
        batch_summary = lifecycle_calibration_batch_summary(self.pending, self.window.today_tasks)
        self.subtitle.setText(f"{batch_summary}；静默不等于风险" if remaining else batch_summary)
        batch_explanation = (
            f"{batch_summary}\n"
            "可暂缓：当前没有未完成任务，可选择暂缓项目\n"
            "任务保护：仍有未完成任务，暂缓操作保持禁用\n"
            "静默只触发人工复核，不会自动标记风险或改变状态"
        )
        self.subtitle.setToolTip(batch_explanation)
        self.subtitle.setAccessibleName(f"生命周期校准批次。{batch_summary}。静默不等于风险")
        self.threshold_button.setText(f"静默阈值 {portfolio_inactivity_days()} 天")
        self.counter.setText(f"{self.processed_count + self.deferred_count + 1} / {total}" if remaining else f"已处理 {self.processed_count}")
        for button in (self.open_button, self.defer_button, self.pause_button): button.setVisible(bool(remaining))
        self.keep_button.setText("确认继续活跃" if remaining else "关闭")
        if not remaining:
            done_icon = QLabel(); done_icon.setFixedSize(56, 56); done_icon.setAlignment(Qt.AlignCenter)
            done_icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=29).pixmap(QSize(29, 29))); done_icon.setStyleSheet("background: #e8f7ef; border-radius: 16px;")
            self.card_layout.addStretch(); self.card_layout.addWidget(done_icon, 0, Qt.AlignCenter)
            title = QLabel("本轮活跃组合校准已完成"); title.setAlignment(Qt.AlignCenter); title.setStyleSheet("color: #172033; font-size: 20px; font-weight: 720;"); self.card_layout.addWidget(title)
            detail = QLabel(f"已确认 {self.processed_count} 个项目" + (f"，另有 {self.deferred_count} 个留待稍后处理" if self.deferred_count else ""))
            detail.setAlignment(Qt.AlignCenter); detail.setWordWrap(True); detail.setStyleSheet("color: #66758a; font-size: 12px;"); self.card_layout.addWidget(detail); self.card_layout.addStretch()
            self.feedback.setText("已确认项目建立新的复核时间；暂缓项目保留全部资料和 Codex 对话。")
            self.feedback.setStyleSheet("color: #087443; background: #e8f7ef; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
            return

        item = self.current_item(); project = item.get("project") or {}
        state = project_lifecycle_calibration_state(project, self.window.today_tasks, inactivity_days=portfolio_inactivity_days())
        item["state"] = state
        name_row = QHBoxLayout(); name_row.setSpacing(9)
        name = QLabel(project.get("name") or "未命名项目"); name.setWordWrap(True); name.setStyleSheet("color: #172033; font-size: 20px; font-weight: 720;"); name_row.addWidget(name, 1)
        category = QLabel(project.get("category") or "未分类"); category.setAlignment(Qt.AlignCenter)
        category.setStyleSheet("color: #315f9b; background: #edf3ff; border-radius: 8px; padding: 5px 9px; font-size: 10px; font-weight: 650;"); name_row.addWidget(category); self.card_layout.addLayout(name_row)
        reason = QLabel(f"进入校准 · {state.get('reason') or '近期没有执行证据'}"); reason.setWordWrap(True)
        reason.setStyleSheet("color: #315f9b; background: #edf4ff; border-radius: 8px; padding: 8px 10px; font-size: 11px; font-weight: 600;"); self.card_layout.addWidget(reason)

        latest = state.get("at")
        latest_text = latest.strftime("%Y-%m-%d %H:%M") if isinstance(latest, datetime) else "尚无记录"
        metrics = QHBoxLayout(); metrics.setSpacing(9)
        for caption, value in (
            ("最近证据", f"{latest_text} · {state.get('source') or '无来源'}"),
            ("任务记录", f"{state.get('taskCount') or 0} 项"),
            ("Codex 对话", f"{state.get('conversationCount') or 0} 个"),
        ):
            frame = QFrame(); frame.setObjectName("calibrationMetric"); frame.setStyleSheet("QFrame#calibrationMetric { background: #f7f9fc; border: 1px solid #e0e7ef; border-radius: 9px; }")
            metric_layout = QVBoxLayout(frame); metric_layout.setContentsMargins(11, 8, 11, 9); metric_layout.setSpacing(2)
            label = QLabel(caption); label.setProperty("sectionLabel", True); metric_layout.addWidget(label)
            value_label = ElidedLabel(value); value_label.setToolTip(value); value_label.setStyleSheet("color: #34445c; font-size: 12px; font-weight: 650;"); metric_layout.addWidget(value_label); metrics.addWidget(frame, 2 if caption == "最近证据" else 1)
        self.card_layout.addLayout(metrics)

        for caption, value, fallback in (
            ("项目目标", project.get("objective"), "尚未明确项目目标"),
            ("当前下一步", project.get("nextStep"), "尚未设置下一步"),
        ):
            label = QLabel(caption); label.setProperty("sectionLabel", True); self.card_layout.addWidget(label)
            text = QLabel(str(value or fallback)); text.setWordWrap(True); text.setStyleSheet("color: #34445c; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 9px; padding: 9px 11px; font-size: 12px;"); self.card_layout.addWidget(text)

        open_tasks = open_project_tasks(self.window.today_tasks, project)
        self.pause_button.setEnabled(not open_tasks)
        self.pause_button.setToolTip("请先处理未完成任务，再暂缓项目" if open_tasks else "将项目状态改为暂缓并调整为稍后处理；资料不会删除")
        if open_tasks:
            self.feedback.setText(f"此项目仍有 {len(open_tasks)} 项未完成任务，因此暂缓按钮已禁用；可先打开项目面板处理任务，或确认继续活跃。")
        else:
            self.feedback.setText("“确认继续活跃”会留下人工复核记录；“暂缓项目”只改变管理状态，不归档、不删除文件或 Codex 对话。")
        self.feedback.setStyleSheet("color: #66758a; font-size: 11px;")

    def change_threshold(self):
        current = portfolio_inactivity_days()
        value, accepted = QInputDialog.getInt(self, "调整静默阈值", "多少天没有执行或复核证据后进入校准？", current, 7, 90, 1)
        if not accepted:
            return
        self.window.update_portfolio_inactivity_days(value)
        provider = getattr(self.window, "actionable_lifecycle_calibration_queue", None)
        self.pending = provider() if callable(provider) else self.window.lifecycle_calibration_queue()
        self.processed_count = 0; self.deferred_count = 0; self.render_current()

    def open_current(self):
        item = self.current_item()
        if not item: return
        project = item.get("project") or {}
        references = project_reference_ids(project)
        self.window.open_project_workspace(project)
        queue_provider = getattr(self.window, "actionable_lifecycle_calibration_queue", None)
        if not callable(queue_provider):
            queue_provider = getattr(self.window, "lifecycle_calibration_queue", None)
        if callable(queue_provider) and references:
            refreshed = matching_guided_project_item(project, queue_provider())
            if refreshed is None:
                self.pending.pop(0); self.processed_count += 1
            else:
                self.pending[0] = refreshed
        self.render_current()

    def defer_current(self):
        if not self.pending: return
        self.pending.pop(0); self.deferred_count += 1; self.render_current()

    def keep_current(self):
        item = self.current_item()
        if not item:
            self.accept(); return
        if not self.window.record_project_review(item.get("project") or {}):
            self.feedback.setText("没有成功写入复核记录，请保留当前项目并稍后重试。"); return
        self.pending.pop(0); self.processed_count += 1; self.render_current()

    def pause_current(self):
        item = self.current_item()
        if not item: return
        project = item.get("project") or {}
        if open_project_tasks(self.window.today_tasks, project):
            self.render_current(); return
        if not self.window.pause_project_from_calibration(project):
            self.feedback.setText("没有成功暂缓项目，请确认项目仍然存在。"); return
        self.pending.pop(0); self.processed_count += 1; self.render_current()


class FocusCapacityDialog(QDialog):
    """Manage a small strategic focus set without hiding live execution evidence."""
    def __init__(self, parent):
        super().__init__(parent)
        self.window = parent
        self.view_mode = None
        self.setWindowTitle("重点容量")
        self.setObjectName("focusCapacityDialog")
        self.setMinimumSize(780, 580)
        self.resize(860, 700)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE945", color="#6d3fc0", size=21).pixmap(QSize(21, 21)))
        icon.setStyleSheet("background: #f1eaff; border: 1px solid #d9c9f6; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("校准战略重点与真实执行"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        subtitle = QLabel("重点由你决定；实际推进来自今日进行中任务和运行中的 Codex 对话")
        subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box, 1)
        self.capacity_button = QPushButton(); self.capacity_button.setFixedHeight(36)
        self.capacity_button.setIcon(fluent_icon("\uE70F", color="#6d3fc0", size=13)); self.capacity_button.setIconSize(QSize(13, 13))
        self.capacity_button.setToolTip("调整同时保留的战略重点数量"); self.capacity_button.clicked.connect(self.change_capacity); heading.addWidget(self.capacity_button)
        root.addLayout(heading)

        self.summary = QFrame(); self.summary.setObjectName("focusCapacitySummary")
        self.summary.setStyleSheet("QFrame#focusCapacitySummary { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 12px; } QFrame#focusCapacitySummary QLabel { background: transparent; border: none; }")
        summary_layout = QHBoxLayout(self.summary); summary_layout.setContentsMargins(18, 13, 18, 13); summary_layout.setSpacing(22)
        self.focus_metric = self.metric_widget("战略重点", "0", "#6d3fc0"); summary_layout.addWidget(self.focus_metric[0], 1)
        divider = QFrame(); divider.setFrameShape(QFrame.VLine); divider.setStyleSheet("color: #dfe6ef;"); summary_layout.addWidget(divider)
        self.execution_metric = self.metric_widget("实际推进", "0", "#087443"); summary_layout.addWidget(self.execution_metric[0], 1)
        divider = QFrame(); divider.setFrameShape(QFrame.VLine); divider.setStyleSheet("color: #dfe6ef;"); summary_layout.addWidget(divider)
        self.alignment_metric = self.metric_widget("组合判断", "待校准", "#315f9b"); summary_layout.addWidget(self.alignment_metric[0], 2)
        root.addWidget(self.summary)

        hint_frame = QFrame(); hint_frame.setObjectName("focusScopeBar")
        hint_frame.setStyleSheet("QFrame#focusScopeBar { background: #f3f6fa; border: 1px solid #e0e7ef; border-radius: 9px; } QFrame#focusScopeBar QLabel { background: transparent; border: none; }")
        hint_layout = QHBoxLayout(hint_frame); hint_layout.setContentsMargins(11, 7, 9, 7); hint_layout.setSpacing(10)
        hint = QLabel("先比较项目目标、健康度、下一步和执行证据，再选择不超过容量的战略重点。重点不等于正在忙。")
        hint.setWordWrap(True); hint.setStyleSheet("color: #526071; font-size: 11px;"); hint_layout.addWidget(hint, 1)
        self.scope_selector = QComboBox(); self.scope_selector.setFixedSize(156, 34)
        self.scope_selector.setToolTip("切换实际推进、已选重点或全部活跃项目")
        self.scope_selector.currentIndexChanged.connect(self.change_scope); hint_layout.addWidget(self.scope_selector)
        root.addWidget(hint_frame)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: #f7f9fc; border: 1px solid #dbe3ee; border-radius: 11px; }")
        self.rows_widget = QWidget(); self.rows_widget.setObjectName("focusRows"); self.rows_widget.setStyleSheet("QWidget#focusRows { background: #f7f9fc; }")
        self.rows_layout = QVBoxLayout(self.rows_widget); self.rows_layout.setContentsMargins(10, 10, 10, 10); self.rows_layout.setSpacing(7)
        scroll.setWidget(self.rows_widget); root.addWidget(scroll, 1)

        actions = QHBoxLayout(); actions.addStretch()
        close = QPushButton("完成"); close.setObjectName("primary"); close.setFixedHeight(38); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)
        self.render_state()

    @staticmethod
    def metric_widget(caption, value, color):
        frame = QWidget(); layout = QVBoxLayout(frame); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(1)
        value_label = QLabel(value); value_label.setStyleSheet(f"color: {color}; font-size: 21px; font-weight: 760;"); layout.addWidget(value_label)
        caption_label = QLabel(caption); caption_label.setStyleSheet("color: #748094; font-size: 10px; font-weight: 600;"); layout.addWidget(caption_label)
        return frame, value_label, caption_label

    def clear_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide(); widget.setParent(None); widget.deleteLater()

    def render_state(self):
        self.clear_rows()
        capacity = portfolio_focus_capacity()
        state = portfolio_focus_capacity_state(self.window.projects, capacity)
        self.focus_state = state
        strategic_count = len(state["strategic"]); execution_count = len(state["executing"])
        active = [project for project in self.window.projects if project.get("status", "active") == "active"]
        if self.view_mode not in {"executing", "strategic", "all"}:
            self.view_mode = "executing" if state["executing"] else "all"
        scope_options = (
            (f"实际推进  {execution_count}", "executing"),
            (f"战略重点  {strategic_count}", "strategic"),
            (f"全部活跃  {len(active)}", "all"),
        )
        self.scope_selector.blockSignals(True)
        self.scope_selector.clear()
        for label, value in scope_options:
            self.scope_selector.addItem(label, value)
        self.scope_selector.setCurrentIndex(max(0, self.scope_selector.findData(self.view_mode)))
        self.scope_selector.blockSignals(False)
        self.scope_selector.setAccessibleName(f"重点校准视图：{self.scope_selector.currentText()}")
        provider = getattr(self.window, "actionable_focus_commitment_queue", None)
        commitment_due = provider() if callable(provider) else portfolio_focus_commitment_queue(state["strategic"], self.window.today_tasks)
        self.capacity_button.setText(f"重点容量 {capacity}")
        self.focus_metric[1].setText(f"{strategic_count} / {capacity}")
        self.execution_metric[1].setText(str(execution_count))
        if state["overBy"]:
            alignment = f"超出容量 {state['overBy']} 项"
            color, background = "#b54708", "#fff8ed"
        elif state["executionOutsideFocus"]:
            alignment = portfolio_focus_guidance(state)
            color, background = "#315f9b", "#edf4ff"
        elif commitment_due:
            alignment = f"{len(commitment_due)} 项重点下一步待落地"
            color, background = "#b54708", "#fff8ed"
        elif strategic_count:
            alignment = "重点已落地" + (f" · 可增加 {state['remaining']} 项" if state["remaining"] else "")
            color, background = "#087443", "#e8f7ef"
        else:
            alignment = "尚未选择重点"
            color, background = "#66758a", "#eef2f6"
        self.alignment_metric[1].setText(alignment)
        self.alignment_metric[1].setStyleSheet(f"color: {color}; font-size: 16px; font-weight: 720;")
        self.summary.setStyleSheet(f"QFrame#focusCapacitySummary {{ background: {background}; border: 1px solid #d8e1eb; border-radius: 12px; }} QFrame#focusCapacitySummary QLabel {{ background: transparent; border: none; }}")

        if self.view_mode == "executing":
            shown = list(state["executing"])
            empty_text = "当前没有实际推进项目；可切换到“全部活跃”选择未来重点"
        elif self.view_mode == "strategic":
            shown = list(state["strategic"])
            empty_text = "尚未选择战略重点；可切换到“实际推进”或“全部活跃”"
        else:
            shown = list(active)
            empty_text = "当前没有活跃项目"
        shown.sort(key=lambda project: (
            0 if project_priority_key(project) == "focus" else 1,
            0 if project_live_work_state(project)[0] else 1,
            str(project.get("name") or "").casefold(),
        ))
        if not shown:
            empty = QLabel(empty_text); empty.setWordWrap(True); empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #748094; padding: 70px; font-size: 13px;")
            self.rows_layout.addWidget(empty)
        for project in shown:
            self.rows_layout.addWidget(self.project_row(project))
        self.rows_layout.addStretch()

    def project_row(self, project):
        is_focus = project_priority_key(project) == "focus"
        live, live_reason, task_count, running_count = project_live_work_state(project)
        commitment = project_next_step_commitment_state(project, self.window.today_tasks)
        row = QFrame(); row.setObjectName("focusProjectRow")
        row.setMinimumHeight(90)
        accent = "#7c3aed" if is_focus else "#10a361" if live else "#d5dee9"
        row.setStyleSheet(f"QFrame#focusProjectRow {{ background: #ffffff; border: 1px solid #dfe6ef; border-left: 4px solid {accent}; border-radius: 10px; }} QFrame#focusProjectRow QLabel {{ background: transparent; border: none; }}")
        layout = QHBoxLayout(row); layout.setContentsMargins(14, 8, 10, 8); layout.setSpacing(9)
        text = QVBoxLayout(); text.setSpacing(2)
        name = ElidedLabel(project.get("name") or "未命名项目"); name.setToolTip(project.get("name") or "未命名项目"); name.setStyleSheet("color: #253247; font-size: 14px; font-weight: 700;"); text.addWidget(name)
        stage = PROJECT_STAGE.get(project_stage_key(project), "阶段未设置")
        health = PROJECT_HEALTH.get(project_health_key(project), "健康度未设置")
        meta = ElidedLabel(f"{project.get('category') or '未分类'}  ·  {stage}  ·  {health}")
        meta.setToolTip(meta.text()); meta.setStyleSheet("color: #66758a; font-size: 10px;"); text.addWidget(meta)
        objective = str(project.get("objective") or "尚未明确项目目标")
        objective_line = ElidedLabel(f"目标 · {objective}"); objective_line.setToolTip(objective)
        objective_line.setStyleSheet("color: #40536d; font-size: 10px; font-weight: 550;"); text.addWidget(objective_line)
        next_step = commitment.get("nextStep") or "尚未明确下一步"
        next_line = ElidedLabel(f"下一步 · {next_step}"); next_line.setToolTip(next_step)
        next_line.setStyleSheet("color: #40536d; font-size: 10px; font-weight: 550;"); text.addWidget(next_line); layout.addLayout(text, 1)
        if live:
            evidence_parts = []
            if task_count:
                evidence_parts.append(f"任务 {task_count}")
            if running_count:
                evidence_parts.append(f"Codex {running_count}")
            execution = QLabel(" · ".join(evidence_parts) or "实际推进"); execution.setAlignment(Qt.AlignCenter); execution.setMinimumWidth(86); execution.setFixedHeight(26)
            execution.setToolTip(live_reason)
            execution.setStyleSheet("color: #087443; background: #e7f7ef; border-radius: 8px; font-size: 10px; font-weight: 650;"); layout.addWidget(execution)
        row.setAccessibleName(
            f"{project.get('name') or '未命名项目'}；目标：{objective}；下一步：{next_step}；"
            f"{live_reason if live else '当前没有实际推进'}；{'战略重点' if is_focus else '尚未设为重点'}"
        )
        if is_focus:
            commitment_styles = {
                "scheduled": ("下一步已落地", "#087443", "#e7f7ef"),
                "live_other": ("已有在制工作", "#315f9b", "#e7eef7"),
                "ready": ("下一步待落地", "#9a3412", "#fff1dc"),
                "missing": ("缺少下一步", "#b42318", "#fff0ee"),
            }
            label, color, background = commitment_styles.get(commitment["state"], ("待确认", "#66758a", "#eef2f6"))
            commitment_badge = QLabel(label); commitment_badge.setAlignment(Qt.AlignCenter); commitment_badge.setFixedSize(88, 26)
            commitment_badge.setStyleSheet(f"color: {color}; background: {background}; border-radius: 8px; font-size: 10px; font-weight: 650;"); layout.addWidget(commitment_badge)
            if commitment["state"] in {"ready", "missing"}:
                commit = QPushButton("加入今日计划" if commitment["state"] == "ready" else "补齐下一步"); commit.setFixedSize(96, 34)
                commit.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c9d8f4; border-radius: 8px; font-size: 11px; font-weight: 680; } QPushButton:hover, QPushButton:focus { background: #ffffff; border-color: #6d93df; }")
                if commitment["state"] == "ready":
                    commit.setToolTip("把这个战略重点已经确认的下一步加入今日计划")
                    commit.clicked.connect(lambda _checked=False, value=project: self.commit_project(value))
                else:
                    commit.setToolTip("打开项目面板，先明确一个可执行的下一步")
                    commit.clicked.connect(lambda _checked=False, value=project: self.open_project_for_next_step(value))
                layout.addWidget(commit)
        impact = portfolio_focus_change_impact(project, not is_focus, getattr(self, "focus_state", {}))
        action = QPushButton("移出重点" if is_focus else "设为重点"); action.setFixedSize(92, 34)
        if not is_focus:
            action.setStyleSheet("QPushButton { color: #6d3fc0; background: #f7f2ff; border: 1px solid #d7c6f3; border-radius: 8px; font-size: 11px; font-weight: 650; } QPushButton:hover { background: #eee4ff; border-color: #ab87df; }")
            if impact["requiresConfirmation"]:
                action.setToolTip(f"当前重点容量已满；继续会变为 {impact['selectedAfter']} / {impact['capacity']}，需要再次确认")
            else:
                action.setToolTip(f"设为重点后占用 {impact['selectedAfter']} / {impact['capacity']} 个重点名额")
        else:
            action.setToolTip(f"移出后保留 {impact['selectedAfter']} / {impact['capacity']} 个战略重点；不会停止实际工作")
        action.clicked.connect(lambda _checked=False, value=project, enabled=not is_focus: self.set_focus(value, enabled)); layout.addWidget(action)
        return row

    def commit_project(self, project):
        task = self.window.schedule_project_next_step(project)
        if task is not None:
            self.render_state()
        return task

    def open_project_for_next_step(self, project):
        self.window.open_project_workspace(project)
        self.render_state()

    def set_focus(self, project, enabled):
        state = portfolio_focus_capacity_state(self.window.projects, portfolio_focus_capacity())
        impact = portfolio_focus_change_impact(project, enabled, state)
        if impact["requiresConfirmation"]:
            answer = QMessageBox.question(
                self,
                "重点容量已满",
                f"当前战略重点为 {impact['selectedBefore']} / {impact['capacity']}。\n\n"
                f"继续把“{project.get('name') or '未命名项目'}”设为重点后，将变为 "
                f"{impact['selectedAfter']} / {impact['capacity']}，超出容量 {impact['overBy']} 项。\n\n"
                "系统不会自动移出其他重点，并会在主页持续提示收敛。是否仍要继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        if self.window.set_project_focus_priority(project, enabled):
            self.render_state()

    def change_scope(self, _index=None):
        value = self.scope_selector.currentData()
        if value in {"executing", "strategic", "all"} and value != self.view_mode:
            self.view_mode = value
            self.render_state()

    def change_capacity(self):
        current = portfolio_focus_capacity()
        value, accepted = QInputDialog.getInt(self, "调整重点容量", "同时保留多少个战略重点？", current, 1, 9, 1)
        if accepted:
            self.window.update_portfolio_focus_capacity(value)
            self.render_state()


class PortfolioRiskDialog(QDialog):
    """A ranked risk queue that returns from each project workbench without losing context."""
    def __init__(self, parent, projects):
        super().__init__(parent)
        self.window = parent
        self.projects = sorted(list(projects or []), key=project_risk_priority_key)
        self.setWindowTitle("风险与阻塞处置")
        self.setObjectName("portfolioRiskDialog")
        self.setMinimumSize(760, 520)
        self.resize(820, 610)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self); root.setContentsMargins(27, 24, 27, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(40, 40); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE7BA", color="#b54708", size=20).pixmap(QSize(20, 20)))
        icon.setStyleSheet("background: #fff1db; border: 1px solid #ebcfaa; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("风险与阻塞处置"); title.setStyleSheet("color: #172033; font-size: 22px; font-weight: 720;"); title_box.addWidget(title)
        self.subtitle = QLabel(); self.subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(self.subtitle); heading.addLayout(title_box, 1)
        self.count_badge = QLabel(); self.count_badge.setAlignment(Qt.AlignCenter); self.count_badge.setFixedHeight(29)
        self.count_badge.setStyleSheet("color: #9a3412; background: #fff5e8; border: 1px solid #edcfaa; border-radius: 8px; padding: 3px 10px; font-size: 11px; font-weight: 700;"); heading.addWidget(self.count_badge)
        root.addLayout(heading)

        guidance = QLabel("阻塞项目优先；已知时长按持续最久排序。时长未知只标记待确认，不推测风险年龄。")
        guidance.setWordWrap(True); guidance.setStyleSheet("color: #7a4b12; background: #fff9ef; border: 1px solid #eddabb; border-radius: 9px; padding: 8px 10px; font-size: 11px;"); root.addWidget(guidance)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: #f7f9fc; border: 1px solid #dbe3ee; border-radius: 11px; }")
        self.rows_widget = QWidget(); self.rows_widget.setObjectName("riskQueueRows"); self.rows_widget.setStyleSheet("QWidget#riskQueueRows { background: #f7f9fc; }")
        self.rows_layout = QVBoxLayout(self.rows_widget); self.rows_layout.setContentsMargins(10, 10, 10, 10); self.rows_layout.setSpacing(8)
        scroll.setWidget(self.rows_widget); root.addWidget(scroll, 1)

        footer = QHBoxLayout(); footer.setSpacing(9)
        self.feedback = QLabel("打开项目面板完成处置；关闭面板后会自动刷新并回到剩余风险队列。")
        self.feedback.setWordWrap(True); self.feedback.setStyleSheet("color: #66758a; font-size: 11px;"); footer.addWidget(self.feedback, 1)
        close = QPushButton("关闭"); close.clicked.connect(self.accept); footer.addWidget(close); root.addLayout(footer)
        self.render_state()

    def clear_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide(); widget.setParent(None); widget.deleteLater()

    def render_state(self):
        self.clear_rows()
        self.projects = sorted(self.projects, key=project_risk_priority_key)
        summary = project_risk_batch_summary(self.projects)
        self.subtitle.setText(summary)
        self.subtitle.setToolTip(summary)
        self.count_badge.setText(f"{len(self.projects)} 项")
        if not self.projects:
            self.count_badge.setStyleSheet("color: #087443; background: #e9f8f0; border: 1px solid #bfe3cf; border-radius: 8px; padding: 3px 10px; font-size: 11px; font-weight: 700;")
            empty = QFrame(); empty.setObjectName("riskQueueEmpty"); empty.setMinimumHeight(250)
            empty.setStyleSheet("QFrame#riskQueueEmpty { background: #ffffff; border: 1px dashed #cbd8e5; border-radius: 11px; }")
            layout = QVBoxLayout(empty); layout.setAlignment(Qt.AlignCenter); layout.setSpacing(8)
            icon = QLabel(); icon.setFixedSize(52, 52); icon.setAlignment(Qt.AlignCenter); icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=26).pixmap(QSize(26, 26))); icon.setStyleSheet("background: #e8f7ef; border-radius: 14px;"); layout.addWidget(icon, 0, Qt.AlignCenter)
            title = QLabel("当前风险队列已清空"); title.setAlignment(Qt.AlignCenter); title.setStyleSheet("color: #172033; font-size: 18px; font-weight: 700;"); layout.addWidget(title)
            detail = QLabel("已解决或校准的项目会继续保留完整决策历史。")
            detail.setAlignment(Qt.AlignCenter); detail.setStyleSheet("color: #66758a; font-size: 11px;"); layout.addWidget(detail)
            self.rows_layout.addWidget(empty); self.feedback.setText("风险状态已同步到主页。")
            return

        self.count_badge.setStyleSheet("color: #9a3412; background: #fff5e8; border: 1px solid #edcfaa; border-radius: 8px; padding: 3px 10px; font-size: 11px; font-weight: 700;")

        for index, project in enumerate(self.projects, start=1):
            state, state_text, color, background, reason = project_control_state(project)
            row = QFrame(); row.setObjectName("riskQueueRow"); row.setMinimumHeight(92)
            row.setStyleSheet(f"QFrame#riskQueueRow {{ background: #ffffff; border: 1px solid #dbe3ee; border-left: 4px solid {color}; border-radius: 10px; }} QFrame#riskQueueRow QLabel {{ background: transparent; border: none; }}")
            row_layout = QHBoxLayout(row); row_layout.setContentsMargins(12, 10, 10, 10); row_layout.setSpacing(11)
            rank = QLabel(str(index)); rank.setFixedSize(28, 28); rank.setAlignment(Qt.AlignCenter); rank.setStyleSheet(f"color: {color}; background: {background}; border-radius: 8px; font-size: 11px; font-weight: 750;"); row_layout.addWidget(rank)
            body = QVBoxLayout(); body.setSpacing(4)
            headline = QHBoxLayout(); headline.setSpacing(8)
            name = QLabel(str(project.get("name") or "未命名项目")); name.setStyleSheet("color: #172033; font-size: 14px; font-weight: 700;"); headline.addWidget(name, 1)
            category = QLabel(str(project.get("category") or "未分类")); category.setStyleSheet("color: #66758a; background: #f1f4f8; border-radius: 7px; padding: 3px 7px; font-size: 9px; font-weight: 650;"); headline.addWidget(category)
            badge = QLabel(state_text); badge.setStyleSheet(f"color: {color}; background: {background}; border-radius: 7px; padding: 3px 7px; font-size: 9px; font-weight: 700;"); headline.addWidget(badge); body.addLayout(headline)
            reason_label = ElidedLabel(reason); reason_label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600;"); reason_label.setToolTip(reason); body.addWidget(reason_label)
            next_step = str(project.get("nextStep") or "尚未明确下一步")
            next_label = ElidedLabel(f"下一步 · {next_step}"); next_label.setStyleSheet("color: #66758a; font-size: 10px;"); next_label.setToolTip(next_step); body.addWidget(next_label); row_layout.addLayout(body, 1)
            open_button = QPushButton("打开处置"); open_button.setFixedHeight(32); open_button.setIcon(fluent_icon("\uE72A", color=color, size=13)); open_button.setIconSize(QSize(13, 13)); open_button.setStyleSheet(f"QPushButton {{ color: {color}; background: #ffffff; border: 1px solid #d4dee9; border-radius: 8px; padding: 4px 9px; font-size: 10px; font-weight: 700; }} QPushButton:hover, QPushButton:focus {{ background: {background}; border-color: {color}; }}")
            open_button.clicked.connect(lambda _checked=False, value=project: self.open_project(value)); row_layout.addWidget(open_button)
            row.setAccessibleName(f"风险队列第 {index} 项，{project.get('name') or '未命名项目'}，{state_text}。{reason}。下一步：{next_step}")
            self.rows_layout.addWidget(row)
        self.rows_layout.addStretch()

    def open_project(self, project):
        self.window.open_project_workspace(project)
        provider = getattr(self.window, "risk_response_queue", None)
        if callable(provider):
            self.projects = list(provider() or [])
        self.render_state()


class PortfolioReviewDialog(QDialog):
    """A deliberate review flow with a guarded first-baseline batch action."""
    def __init__(self, parent, projects, total_count=None, purpose="review"):
        super().__init__(parent)
        self.window = parent
        self.purpose = purpose
        self.pending = list(projects or [])
        self.portfolio_total = max(len(self.pending), int(total_count or len(self.pending)))
        self.reviewed_count = 0
        next_step_mode = purpose == "next_step"
        self.setWindowTitle("明确项目下一步" if next_step_mode else "处理项目变化")
        self.setObjectName("portfolioReviewDialog")
        self.setMinimumSize(720, 560)
        self.resize(780, 620)
        self.setStyleSheet(STYLE + """
            QDialog#portfolioReviewDialog QLabel[sectionLabel='true'] { color: #66758a; font-size: 11px; font-weight: 650; }
        """)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(40, 40); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE73E", color="#1d4ed8", size=20).pixmap(QSize(20, 20)))
        icon.setStyleSheet("background: #eaf1ff; border: 1px solid #c9d9f6; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("逐项明确可执行下一步" if next_step_mode else "处理必要信息与真实变化"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        self.subtitle = QLabel("一次只决定一个项目，保存后自动进入下一项" if next_step_mode else "只有缺少必要信息或关键决策发生变化时才会出现在这里")
        self.subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(self.subtitle); heading.addLayout(title_box, 1)
        self.counter = QLabel(); self.counter.setAlignment(Qt.AlignCenter); self.counter.setFixedHeight(28)
        self.counter.setStyleSheet("color: #315f9b; background: #eaf2ff; border-radius: 8px; padding: 2px 10px; font-size: 11px; font-weight: 650;"); heading.addWidget(self.counter)
        root.addLayout(heading)

        self.review_card = QFrame(); self.review_card.setObjectName("portfolioReviewCard")
        self.review_card.setStyleSheet("QFrame#portfolioReviewCard { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 13px; } QFrame#portfolioReviewCard QLabel { background: transparent; border: none; }")
        self.card_layout = QVBoxLayout(self.review_card); self.card_layout.setContentsMargins(20, 18, 20, 20); self.card_layout.setSpacing(12)
        root.addWidget(self.review_card, 1)

        self.feedback = QLabel(); self.feedback.setWordWrap(True); self.feedback.setStyleSheet("color: #66758a; font-size: 11px;"); root.addWidget(self.feedback)
        actions = QHBoxLayout(); actions.setSpacing(8)
        close = QPushButton("关闭"); close.clicked.connect(self.reject); actions.addWidget(close)
        actions.addStretch()
        self.open_button = QPushButton("打开项目面板"); self.open_button.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); self.open_button.setIconSize(QSize(14, 14))
        self.open_button.setToolTip("查看完整项目资料；关闭项目面板后返回本轮确认")
        self.open_button.setAccessibleName("查看当前项目详情并返回项目确认队列")
        self.open_button.clicked.connect(self.open_current); actions.addWidget(self.open_button)
        self.skip_button = QPushButton("稍后处理"); self.skip_button.clicked.connect(self.skip_current); actions.addWidget(self.skip_button)
        self.recover_button = QPushButton("已恢复正常"); self.recover_button.setIcon(fluent_icon("\uE73E", color="#087443", size=14)); self.recover_button.setIconSize(QSize(14, 14))
        self.recover_button.setToolTip("将历史需关注状态校准为正常，并建立本次复核基线"); self.recover_button.setAccessibleName("确认项目已经恢复正常")
        self.recover_button.setStyleSheet("QPushButton { color: #087443; background: #eef9f3; border: 1px solid #b9dfca; border-radius: 8px; padding: 5px 11px; font-size: 11px; font-weight: 700; } QPushButton:hover, QPushButton:focus { background: #e2f4ea; border-color: #78bd98; }")
        self.recover_button.clicked.connect(self.recover_current); self.recover_button.hide(); actions.addWidget(self.recover_button)
        self.confirm_button = QPushButton("确认变化"); self.confirm_button.setObjectName("primary"); self.confirm_button.setIcon(fluent_icon("\uE73E", color="#ffffff", size=14)); self.confirm_button.setIconSize(QSize(14, 14)); self.confirm_button.clicked.connect(self.confirm_current); actions.addWidget(self.confirm_button)
        root.addLayout(actions)
        self.render_current()

    def clear_card(self):
        def clear_layout(layout):
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                child_layout = item.layout()
                if widget is not None:
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()
                elif child_layout is not None:
                    clear_layout(child_layout)
                    child_layout.deleteLater()
        clear_layout(self.card_layout)

    def current_project(self):
        return self.pending[0] if self.pending else None

    def render_current(self):
        self.clear_card()
        next_step_mode = getattr(self, "purpose", "review") == "next_step"
        remaining = len(self.pending)
        total = self.reviewed_count + remaining
        batch_summary = next_step_decision_batch_summary(self.pending) if next_step_mode else project_confirmation_batch_summary(self.pending, include_routed=True)
        priority_hint = "先形成一个可直接开始的动作" if next_step_mode and remaining else project_confirmation_priority_hint(self.pending)
        if remaining and not next_step_mode and not priority_hint:
            priority_hint = "逐项确认现状"
        self.subtitle.setText(f"{batch_summary}；{priority_hint}" if remaining and priority_hint else batch_summary)
        batch_explanation = (
            f"{batch_summary}\n"
            "Codex 可分析：已关联有效本地目录，可读取资料并生成可审核建议\n"
            "需手动补充：本地目录不可用，请在项目面板填写下一步\n"
            "保存后自动进入本轮下一项；不会自动替你确认建议"
            if next_step_mode else
            f"{batch_summary}\n"
            "补全：目标、阶段、健康度或下一步尚不完整\n"
            "变化：当前关键决策与上次保存的记录不同\n"
            "没有真实变化的项目不会出现在这里"
        )
        self.subtitle.setToolTip(batch_explanation)
        self.subtitle.setAccessibleName(
            f"{'下一步决策' if next_step_mode else '项目确认'}批次。{batch_summary}。{priority_hint}"
            if priority_hint else f"{'下一步决策' if next_step_mode else '项目确认'}批次。{batch_summary}"
        )
        self.counter.setText(
            f"{self.reviewed_count + 1} / {total} · {'总待决策' if next_step_mode else '总待确认'} {self.portfolio_total}"
            if remaining else f"本轮完成 {self.reviewed_count}"
        )
        self.open_button.setVisible(bool(remaining)); self.skip_button.setVisible(bool(remaining)); self.skip_button.setEnabled(remaining > 1); self.recover_button.hide()
        self.confirm_button.setText("确认变化" if remaining and not next_step_mode else "确认现状" if remaining else "关闭")
        if not remaining:
            done_icon = QLabel(); done_icon.setFixedSize(54, 54); done_icon.setAlignment(Qt.AlignCenter)
            done_icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=28).pixmap(QSize(28, 28))); done_icon.setStyleSheet("background: #e8f7ef; border-radius: 15px;")
            self.card_layout.addStretch(); self.card_layout.addWidget(done_icon, 0, Qt.AlignCenter)
            done = QLabel("本轮下一步决策已完成" if next_step_mode else "本轮项目确认已完成"); done.setAlignment(Qt.AlignCenter); done.setStyleSheet("color: #172033; font-size: 20px; font-weight: 720;"); self.card_layout.addWidget(done)
            remaining_total = max(0, self.portfolio_total - self.reviewed_count)
            detail_text = (
                f"本轮已处理 {self.reviewed_count} 个项目；仍有 {remaining_total} 个待{'决策' if next_step_mode else '确认'}，可稍后继续"
                if remaining_total else
                (f"已为 {self.reviewed_count} 个项目明确可执行下一步" if next_step_mode else f"已处理 {self.reviewed_count} 个项目的必要信息或真实变化")
            )
            detail = QLabel(detail_text)
            detail.setAlignment(Qt.AlignCenter); detail.setWordWrap(True); detail.setStyleSheet("color: #66758a; font-size: 12px;"); self.card_layout.addWidget(detail)
            feedback = (
                "主页待定数量已同步更新；继续处理时会自动进入下一批。" if remaining_total else "本轮项目都已有明确下一步。"
            ) if next_step_mode else (
                "项目变化数量已同步更新；继续处理时会自动进入下一批。" if remaining_total else "本轮项目变化已经全部处理。"
            )
            self.card_layout.addStretch(); self.feedback.setText(feedback)
            self.feedback.setStyleSheet("color: #087443; background: #e8f7ef; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
            return

        project = self.current_project()
        gaps = project_governance_gaps(project)
        gap_text = project_governance_gap_text(project)
        has_project_folder = project_has_local_folder(project)
        legacy_attention = project_health_key(project) == "attention" and not str(project.get("reviewedAt") or "").strip()
        today = QDate.currentDate().toString(Qt.ISODate)
        review_evidence = project_review_evidence(project, self.window.today_tasks, today)
        alignment_pending = not next_step_mode and review_evidence["alignmentState"] == "divergent"
        if next_step_mode:
            self.confirm_button.setText("Codex 建议下一步" if has_project_folder else "打开项目补充")
            self.confirm_button.setIcon(fluent_icon("\uE945" if has_project_folder else "\uE72A", color="#ffffff", size=14))
            self.confirm_button.setToolTip(
                "只读分析项目目录，生成可审核的下一步建议；确认保存后才会写入"
                if has_project_folder else
                "当前没有有效项目目录，请在项目面板中手动填写下一步"
            )
        elif gaps:
            self.confirm_button.setText("Codex 补全缺项" if has_project_folder else "打开项目补全")
            self.confirm_button.setIcon(fluent_icon("\uE945" if has_project_folder else "\uE72A", color="#ffffff", size=14))
            self.confirm_button.setToolTip(
                "只读分析项目目录，审核建议后写入并建立复核基线"
                if has_project_folder else
                "当前没有有效项目文件夹，请在项目面板中手动补齐"
            )
        elif alignment_pending:
            self.confirm_button.setText("先校准执行方向")
            self.confirm_button.setIcon(fluent_icon("\uE8A7", color="#ffffff", size=14))
            self.confirm_button.setToolTip("今日实际执行与已保存下一步不同；请先确认哪一个应作为项目方向")
        elif legacy_attention:
            self.confirm_button.setText("仍需关注")
            self.confirm_button.setIcon(fluent_icon("\uE7BA", color="#ffffff", size=14))
            self.confirm_button.setToolTip("确认风险仍然存在，并把需关注状态写入本次复核记录")
            self.recover_button.show()
        else:
            self.confirm_button.setText("确认变化")
            self.confirm_button.setIcon(fluent_icon("\uE73E", color="#ffffff", size=14))
            self.confirm_button.setToolTip("核对真实变化，并把当前关键决策保存为新的比较记录")
        if next_step_mode:
            review_reason = "当前没有可执行下一步"
        elif gaps:
            review_reason = f"缺少：{gap_text}"
        else:
            drift = project_review_drift(project)
            labels = "、".join(change.get("label") or change.get("field") or "项目决策" for change in drift[:3])
            review_reason = f"{labels}与上次记录不同" if labels else "项目关键决策发生变化"
        name_row = QHBoxLayout(); name_row.setSpacing(9)
        name = QLabel(project.get("name") or "未命名项目"); name.setWordWrap(True); name.setStyleSheet("color: #172033; font-size: 20px; font-weight: 720;"); name_row.addWidget(name, 1)
        priority = QLabel(PROJECT_PRIORITY.get(project_priority_key(project), "常规推进")); priority.setAlignment(Qt.AlignCenter)
        priority.setStyleSheet("color: #1d4ed8; background: #edf3ff; border-radius: 8px; padding: 5px 9px; font-size: 10px; font-weight: 650;"); name_row.addWidget(priority)
        self.card_layout.addLayout(name_row)
        reason_caption = "等待决策" if next_step_mode else "必要信息待补全" if gaps else "关键变化待确认"
        reason = QLabel(f"{reason_caption} · {review_reason}"); reason.setWordWrap(True)
        reason.setStyleSheet("color: #315f9b; background: #edf4ff; border-radius: 8px; padding: 8px 10px; font-size: 11px; font-weight: 600;"); self.card_layout.addWidget(reason)

        metrics = QHBoxLayout(); metrics.setSpacing(9)
        metric_values = (
            (
                ("所属分类", project.get("category") or "未分类"),
                ("当前阶段", PROJECT_STAGE.get(project.get("stage"), "尚未设置")),
                ("健康度", PROJECT_HEALTH.get(project.get("health"), "尚未设置")),
            ) if next_step_mode else (
                ("当前阶段", PROJECT_STAGE.get(project.get("stage"), "尚未设置")),
                ("健康度", PROJECT_HEALTH.get(project.get("health"), "尚未设置")),
                ("变更记录", "待必要信息完整后建立" if gaps else project_review_summary(project)),
            )
        )
        for caption, value in metric_values:
            metric = QFrame(); metric.setObjectName("reviewMetric"); metric.setStyleSheet("QFrame#reviewMetric { background: #f7f9fc; border: 1px solid #e0e7ef; border-radius: 9px; }")
            metric_layout = QVBoxLayout(metric); metric_layout.setContentsMargins(11, 8, 11, 9); metric_layout.setSpacing(2)
            label = QLabel(caption); label.setProperty("sectionLabel", True); metric_layout.addWidget(label)
            text = ElidedLabel(value); text.setToolTip(value); text.setStyleSheet("color: #34445c; font-size: 12px; font-weight: 650;"); metric_layout.addWidget(text); metrics.addWidget(metric, 1)
        self.card_layout.addLayout(metrics)

        if not next_step_mode:
            drift = project_review_drift_presentation(project)
            drift_palette = {
                "changed": ("#9a5b00", "#fff8e8", "#ead7a4", "\uE7BA"),
                "stable": ("#087443", "#eef8f2", "#c8e5d3", "\uE73E"),
                "baseline": ("#315f9b", "#f1f6ff", "#cfdbef", "\uE81C"),
            }
            drift_color, drift_background, drift_border, drift_glyph = drift_palette[drift["state"]]
            drift_frame = QFrame(); drift_frame.setObjectName("reviewDrift")
            drift_frame.setStyleSheet(f"QFrame#reviewDrift {{ background: {drift_background}; border: 1px solid {drift_border}; border-radius: 9px; }} QFrame#reviewDrift QLabel {{ background: transparent; border: none; }}")
            drift_layout = QHBoxLayout(drift_frame); drift_layout.setContentsMargins(10, 7, 10, 7); drift_layout.setSpacing(9)
            drift_icon = QLabel(); drift_icon.setFixedSize(28, 28); drift_icon.setAlignment(Qt.AlignCenter)
            drift_icon.setPixmap(fluent_icon(drift_glyph, color=drift_color, size=14).pixmap(QSize(14, 14))); drift_icon.setStyleSheet("background: #ffffff; border-radius: 8px;"); drift_layout.addWidget(drift_icon)
            drift_text = QVBoxLayout(); drift_text.setSpacing(1)
            drift_title = QLabel(drift["title"]); drift_title.setStyleSheet(f"color: {drift_color}; font-size: 11px; font-weight: 700;"); drift_text.addWidget(drift_title)
            drift_detail = ElidedLabel(drift["detail"]); drift_detail.setStyleSheet("color: #5f6f84; font-size: 10px;"); drift_detail.setToolTip(drift.get("tooltip") or drift["detail"]); drift_text.addWidget(drift_detail); drift_layout.addLayout(drift_text, 1)
            drift_frame.setToolTip(drift.get("tooltip") or drift["detail"])
            drift_frame.setAccessibleName(f"复核变化：{drift['title']}。{drift['detail']}")
            self.card_layout.addWidget(drift_frame)

        evidence_frame = QFrame(); evidence_frame.setObjectName("reviewEvidence")
        evidence_frame.setStyleSheet("QFrame#reviewEvidence { background: #f6f9fd; border: 1px solid #d9e4f0; border-radius: 9px; } QFrame#reviewEvidence QLabel { background: transparent; border: none; }")
        evidence_layout = QHBoxLayout(evidence_frame); evidence_layout.setContentsMargins(11, 8, 10, 8); evidence_layout.setSpacing(9)
        evidence_icon = QLabel(); evidence_icon.setFixedSize(28, 28); evidence_icon.setAlignment(Qt.AlignCenter)
        evidence_icon.setPixmap(fluent_icon("\uE9D9", color="#315f9b", size=15).pixmap(QSize(15, 15))); evidence_icon.setStyleSheet("background: #e7eef7; border-radius: 8px;"); evidence_layout.addWidget(evidence_icon)
        evidence_text = QVBoxLayout(); evidence_text.setSpacing(1)
        evidence_title = QLabel("实时执行证据"); evidence_title.setStyleSheet("color: #315f9b; font-size: 11px; font-weight: 700;"); evidence_text.addWidget(evidence_title)
        activity = review_evidence["activity"]
        age_days = activity.get("ageDays")
        if age_days is None:
            recent = "暂无历史活动"
        elif age_days == 0:
            recent = f"今天 · {activity.get('source') or '活动记录'}"
        elif age_days == 1:
            recent = f"昨天 · {activity.get('source') or '活动记录'}"
        else:
            recent = f"{age_days} 天前 · {activity.get('source') or '活动记录'}"
        evidence_detail_text = (
            f"今日 {review_evidence['taskCount']} 项（计划 {review_evidence['plannedCount']} / 进行 {review_evidence['doingCount']} / 完成 {review_evidence['doneCount']}）"
            f"  ·  Codex {review_evidence['runningConversationCount']} 运行  ·  最近活动 {recent}"
        )
        evidence_detail = ElidedLabel(evidence_detail_text); evidence_detail.setToolTip(evidence_detail_text); evidence_detail.setStyleSheet("color: #66758a; font-size: 10px;"); evidence_text.addWidget(evidence_detail); evidence_layout.addLayout(evidence_text, 1)
        alignment_labels = {
            "divergent": ("执行方向待校准", "#9a3412", "#fff1dc"),
            "acknowledged": ("执行差异已确认", "#315f9b", "#e7eef7"),
            "aligned": ("执行方向一致", "#087443", "#e7f7ef"),
            "idle": ("暂无在制任务", "#66758a", "#eef2f6"),
        }
        alignment_text, alignment_color, alignment_background = alignment_labels[review_evidence["alignmentState"]]
        alignment_badge = QLabel(alignment_text); alignment_badge.setAlignment(Qt.AlignCenter); alignment_badge.setFixedHeight(26)
        alignment_badge.setStyleSheet(f"color: {alignment_color}; background: {alignment_background}; border-radius: 8px; padding: 2px 9px; font-size: 10px; font-weight: 650;"); evidence_layout.addWidget(alignment_badge)
        self.card_layout.addWidget(evidence_frame)

        definition_row = QHBoxLayout(); definition_row.setSpacing(9)
        for caption, value, fallback in (
            ("项目目标", project.get("objective"), "尚未明确项目目标"),
            ("验收标准", project.get("successCriteria"), "尚未单独定义验收标准"),
        ):
            box = QFrame(); box.setObjectName("reviewDefinition")
            box.setStyleSheet("QFrame#reviewDefinition { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 9px; } QFrame#reviewDefinition QLabel { background: transparent; border: none; }")
            box_layout = QVBoxLayout(box); box_layout.setContentsMargins(10, 7, 10, 8); box_layout.setSpacing(2)
            label = QLabel(caption); label.setProperty("sectionLabel", True); box_layout.addWidget(label)
            value_text = str(value or fallback); text = ElidedLabel(value_text); text.setToolTip(value_text)
            text.setStyleSheet("color: #34445c; font-size: 11px; font-weight: 600;"); box_layout.addWidget(text); definition_row.addWidget(box, 1)
        self.card_layout.addLayout(definition_row)
        next_label = QLabel("当前下一步"); next_label.setProperty("sectionLabel", True); self.card_layout.addWidget(next_label)
        next_value = str(project.get("nextStep") or "尚未设置下一步")
        next_text = QLabel(next_value); next_text.setWordWrap(True); next_text.setToolTip(next_value)
        next_text.setStyleSheet("color: #34445c; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 9px; padding: 8px 10px; font-size: 11px;"); self.card_layout.addWidget(next_text)

        if next_step_mode:
            self.feedback.setText(
                "Codex 会读取项目目录并给出可审核建议；只有你在建议窗口中确认后才会写入。"
                if has_project_folder else
                "此项目没有可用的本地目录，请打开项目面板手动填写一个可以直接开始的动作。"
            )
            self.feedback.setStyleSheet("color: #315f9b; background: #edf4ff; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
        elif gaps:
            self.feedback.setText(
                "Codex 将只读检查项目目录并给出缺项建议；你审核并应用后才会写入。"
                if has_project_folder else
                "当前未关联有效项目文件夹，请打开项目面板手动补齐必要信息。"
            )
            self.feedback.setStyleSheet("color: #315f9b; background: #edf4ff; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
        elif alignment_pending:
            self.feedback.setText("今日实际执行与项目已保存的下一步不同；请先校准执行方向，再建立或刷新复核基线。")
            self.feedback.setStyleSheet("color: #9a3412; background: #fff3e6; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
        elif legacy_attention:
            self.feedback.setText("这是一次健康度校准：风险仍在请选择“仍需关注”；风险已解除请选择“已恢复正常”。两种选择都会保留决策记录并建立复核基线。")
            self.feedback.setStyleSheet("color: #8a5a00; background: #fff7e6; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
        else:
            self.feedback.setText("这里只有真实变化需要确认；确认后会更新比较记录，没有变化时不会产生周期性待办。")
            self.feedback.setStyleSheet("color: #66758a; font-size: 11px;")

    def skip_current(self):
        if len(self.pending) <= 1:
            return
        self.pending.append(self.pending.pop(0))
        self.render_current()

    def confirm_baseline_batch(self):
        candidates = project_baseline_batch_candidates(
            self.pending,
            self.window.today_tasks,
            QDate.currentDate().toString(Qt.ISODate),
        )
        if len(candidates) < 2:
            self.feedback.setText("当前不足 2 个安全可合并的首次基线，请继续逐项确认。")
            return
        names = "\n".join(f"• {project.get('name') or '未命名项目'}" for project in candidates)
        message = (
            f"将为以下 {len(candidates)} 个项目建立首次管理基线：\n\n{names}\n\n"
            "系统会保存当前目标、验收标准、阶段、健康度、下一步和阻塞状态，"
            "并按项目优先级启动 3 / 7 / 14 天复核周期。\n\n"
            "此操作不会修改项目内容；风险、缺项和执行方向冲突项目不在本次范围内。"
        )
        answer = QMessageBox.question(
            self,
            "批量建立首次基线",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        result = self.window.record_project_review_batch(candidates)
        if not result or not result.get("count"):
            self.feedback.setText("批量确认没有写入；项目状态可能刚刚发生变化，请重新检查。")
            self.feedback.setStyleSheet("color: #b42318; background: #fff0ee; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
            return
        confirmed = {str(value) for value in result.get("projectIds") or []}
        self.pending = [
            project for project in self.pending
            if not (project_reference_ids(project) & confirmed)
        ]
        self.reviewed_count += int(result.get("count") or 0)
        self.last_batch_result = result
        self.render_current()
        self.feedback.setText(f"已为 {result['count']} 个项目建立首次基线并写入审计记录；如有误，可立即撤销本次批量确认。")
        self.feedback.setStyleSheet("color: #087443; background: #e8f7ef; border-radius: 8px; padding: 7px 9px; font-size: 11px;")

    def undo_last_batch(self):
        if not self.last_batch_result:
            return
        restored = self.window.undo_project_review_batch(self.last_batch_result)
        if not restored:
            self.feedback.setText("未能撤销：这些项目的基线在批量确认后已经发生变化。")
            self.feedback.setStyleSheet("color: #b42318; background: #fff0ee; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
            return
        existing_refs = set().union(*(project_reference_ids(project) for project in self.pending)) if self.pending else set()
        for project in reversed(restored):
            if not (project_reference_ids(project) & existing_refs):
                self.pending.insert(0, project)
                existing_refs.update(project_reference_ids(project))
        self.reviewed_count = max(0, self.reviewed_count - len(restored))
        self.last_batch_result = None
        self.render_current()
        self.feedback.setText(f"已撤销 {len(restored)} 个项目的本次批量基线；项目资料保持不变。")
        self.feedback.setStyleSheet("color: #526071; background: #f1f4f8; border-radius: 8px; padding: 7px 9px; font-size: 11px;")

    def open_current(self):
        project = self.current_project()
        if project is None:
            return
        references = project_reference_ids(project)
        self.window.open_project_workspace(project)
        provider_name = "next_step_decision_queue" if getattr(self, "purpose", "review") == "next_step" else "portfolio_review_queue"
        queue_provider = getattr(self.window, provider_name, None)
        if callable(queue_provider) and references:
            refreshed = matching_guided_project_item(project, queue_provider())
            if refreshed is None:
                self.pending.pop(0)
                self.reviewed_count += 1
            else:
                self.pending[0] = refreshed
        else:
            project_lookup = getattr(self.window, "project_by_id", None)
            if callable(project_lookup) and references:
                refreshed = next(
                    (
                        candidate
                        for reference in references
                        for candidate in (project_lookup(reference),)
                        if candidate is not None
                    ),
                    project,
                )
                self.pending[0] = refreshed
        self.render_current()

    def recover_current(self):
        project = self.current_project()
        if project is None:
            return
        data = {
            "priority": project_priority_key(project),
            "stage": project_stage_key(project),
            "health": "on_track",
            "status": project.get("status", "active"),
            "category": project.get("category", "未分类"),
            "objective": project.get("objective", ""),
            "successCriteria": project.get("successCriteria", ""),
            "nextStep": project.get("nextStep", ""),
            "blocker": "",
        }
        if self.window.update_project_management(project, data, notify=False, source="review_resolution") is None:
            self.feedback.setText("没有成功写入健康度校准，请保留当前项目并稍后重试。")
            self.feedback.setStyleSheet("color: #b42318; background: #fff0ee; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
            return
        self.pending.pop(0)
        self.reviewed_count += 1
        self.render_current()

    def confirm_current(self):
        project = self.current_project()
        if project is None:
            self.accept(); return
        if getattr(self, "purpose", "review") == "next_step":
            if project_has_local_folder(project):
                self.window.show_project_governance([project])
            else:
                self.window.open_project_workspace(project)
            references = project_reference_ids(project)
            queue_provider = getattr(self.window, "next_step_decision_queue", None)
            refreshed = matching_guided_project_item(project, queue_provider()) if callable(queue_provider) and references else project
            if refreshed is None:
                self.pending.pop(0)
                self.reviewed_count += 1
            else:
                self.pending[0] = refreshed
            self.render_current()
            return
        if project_governance_gaps(project):
            self.accept()
            if project_has_local_folder(project):
                self.window.show_project_governance([project])
            else:
                self.window.open_project_workspace(project)
            return
        today = QDate.currentDate().toString(Qt.ISODate)
        evidence = project_review_evidence(project, self.window.today_tasks, today)
        if evidence["alignmentState"] == "divergent":
            self.accept()
            ExecutionAlignmentDialog(self.window, [evidence["alignment"]]).exec_()
            return
        if not self.window.record_project_review(project):
            self.feedback.setText("没有成功写入复核记录，请保留当前项目并稍后重试。")
            self.feedback.setStyleSheet("color: #b42318; background: #fff0ee; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
            return
        self.pending.pop(0)
        self.reviewed_count += 1
        self.render_current()


class ExecutionAlignmentDialog(QDialog):
    """Reconcile declared project direction with work that is actually in progress."""
    def __init__(self, parent, alignments):
        super().__init__(parent)
        self.window = parent
        self.pending = list(alignments or [])
        self.processed_count = 0
        self.skipped_count = 0
        self.setWindowTitle("执行方向校准")
        self.setObjectName("executionAlignmentDialog")
        self.setMinimumSize(740, 500)
        self.resize(800, 550)
        self.setStyleSheet(STYLE + """
            QDialog#executionAlignmentDialog QLabel[sectionLabel='true'] { color: #66758a; font-size: 11px; font-weight: 650; }
            QFrame#alignmentDirection { background: #f8fafc; border: 1px solid #dfe6ef; border-radius: 11px; }
        """)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE8A7", color="#1d4ed8", size=21).pixmap(QSize(21, 21)))
        icon.setStyleSheet("background: #eaf1ff; border: 1px solid #c9d9f6; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("校准项目方向与真实执行"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        self.subtitle = QLabel("逐项确认正在做的工作是否应成为项目下一步；系统不会自动覆盖你的决策")
        self.subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(self.subtitle); heading.addLayout(title_box, 1)
        self.counter = QLabel(); self.counter.setAlignment(Qt.AlignCenter); self.counter.setFixedHeight(28)
        self.counter.setStyleSheet("color: #315f9b; background: #eaf2ff; border-radius: 8px; padding: 2px 10px; font-size: 11px; font-weight: 650;"); heading.addWidget(self.counter)
        root.addLayout(heading)

        self.card = QFrame(); self.card.setObjectName("alignmentCard")
        self.card.setStyleSheet("QFrame#alignmentCard { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 13px; } QFrame#alignmentCard QLabel { background: transparent; border: none; }")
        self.card_layout = QVBoxLayout(self.card); self.card_layout.setContentsMargins(20, 18, 20, 20); self.card_layout.setSpacing(12); root.addWidget(self.card, 1)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); self.feedback.setStyleSheet("color: #66758a; font-size: 11px;"); root.addWidget(self.feedback)

        actions = QHBoxLayout(); actions.setSpacing(8)
        close = QPushButton("关闭"); close.clicked.connect(self.reject); actions.addWidget(close); actions.addStretch()
        self.open_button = QPushButton("打开项目面板"); self.open_button.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); self.open_button.setIconSize(QSize(14, 14))
        self.open_button.setToolTip("查看完整项目资料；关闭项目面板后返回本轮执行方向校准")
        self.open_button.setAccessibleName("查看当前项目详情并返回执行方向校准队列")
        self.open_button.clicked.connect(self.open_current); actions.addWidget(self.open_button)
        self.defer_button = QPushButton("稍后处理"); self.defer_button.clicked.connect(self.defer_current); actions.addWidget(self.defer_button)
        self.keep_button = QPushButton("保留原下一步"); self.keep_button.clicked.connect(self.keep_current); actions.addWidget(self.keep_button)
        self.adopt_button = QPushButton("采用正在执行的任务"); self.adopt_button.setObjectName("primary"); self.adopt_button.setIcon(fluent_icon("\uE73E", color="#ffffff", size=14)); self.adopt_button.setIconSize(QSize(14, 14)); self.adopt_button.clicked.connect(self.adopt_current); actions.addWidget(self.adopt_button)
        root.addLayout(actions); self.render_current()

    def clear_card(self):
        def clear_layout(layout):
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                child_layout = item.layout()
                if widget is not None:
                    widget.hide(); widget.setParent(None); widget.deleteLater()
                elif child_layout is not None:
                    clear_layout(child_layout); child_layout.deleteLater()
        clear_layout(self.card_layout)

    def current_alignment(self):
        return self.pending[0] if self.pending else None

    def render_current(self):
        self.clear_card(); remaining = len(self.pending); total = self.processed_count + self.skipped_count + remaining
        batch_summary = execution_alignment_batch_summary(self.pending)
        self.subtitle.setText(f"{batch_summary}；不会自动覆盖决策" if remaining else batch_summary)
        batch_explanation = (
            f"{batch_summary}\n"
            "候选任务：与项目已声明下一步不同的进行中任务\n"
            "需选择：存在多个候选任务，需要先选择要采用的方向\n"
            "系统只展示差异，不会自动覆盖项目下一步"
        )
        self.subtitle.setToolTip(batch_explanation)
        self.subtitle.setAccessibleName(f"执行方向校准批次。{batch_summary}。不会自动覆盖项目决策")
        self.counter.setText(f"{self.processed_count + self.skipped_count + 1} / {total}" if remaining else f"已处理 {self.processed_count}")
        for button in (self.open_button, self.defer_button, self.keep_button): button.setVisible(bool(remaining))
        self.adopt_button.setText("采用正在执行的任务" if remaining else "关闭")
        if not remaining:
            icon = QLabel(); icon.setFixedSize(56, 56); icon.setAlignment(Qt.AlignCenter)
            icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=29).pixmap(QSize(29, 29))); icon.setStyleSheet("background: #e8f7ef; border-radius: 16px;")
            self.card_layout.addStretch(); self.card_layout.addWidget(icon, 0, Qt.AlignCenter)
            title = QLabel("本轮执行方向校准已完成"); title.setAlignment(Qt.AlignCenter); title.setStyleSheet("color: #172033; font-size: 20px; font-weight: 720;"); self.card_layout.addWidget(title)
            detail = QLabel(f"已确认 {self.processed_count} 个项目" + (f"，另有 {self.skipped_count} 个留待稍后处理" if self.skipped_count else ""))
            detail.setAlignment(Qt.AlignCenter); detail.setWordWrap(True); detail.setStyleSheet("color: #66758a; font-size: 12px;"); self.card_layout.addWidget(detail)
            self.card_layout.addStretch(); self.feedback.setText("已确认的选择已写入项目决策记录；未处理项目仍会留在主页。")
            self.feedback.setStyleSheet("color: #087443; background: #e8f7ef; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
            return

        alignment = self.current_alignment(); project = alignment.get("project") or {}; tasks = alignment.get("tasks") or []
        name_row = QHBoxLayout(); name_row.setSpacing(9)
        name = QLabel(project.get("name") or "未命名项目"); name.setWordWrap(True); name.setStyleSheet("color: #172033; font-size: 20px; font-weight: 720;"); name_row.addWidget(name, 1)
        category = QLabel(project.get("category") or "未分类"); category.setAlignment(Qt.AlignCenter)
        category.setStyleSheet("color: #315f9b; background: #edf3ff; border-radius: 8px; padding: 5px 9px; font-size: 10px; font-weight: 650;"); name_row.addWidget(category); self.card_layout.addLayout(name_row)
        reason = QLabel("今日已有任务进入“进行中”，但它与项目档案中的“明确下一步”不同。两者都可能合理，请确认项目层面的真实方向。")
        reason.setWordWrap(True); reason.setStyleSheet("color: #315f9b; background: #edf4ff; border-radius: 8px; padding: 8px 10px; font-size: 11px; font-weight: 600;"); self.card_layout.addWidget(reason)

        directions = QHBoxLayout(); directions.setSpacing(10)
        declared = QFrame(); declared.setObjectName("alignmentDirection"); declared_layout = QVBoxLayout(declared); declared_layout.setContentsMargins(13, 11, 13, 13); declared_layout.setSpacing(6)
        declared_label = QLabel("项目档案中的下一步"); declared_label.setProperty("sectionLabel", True); declared_layout.addWidget(declared_label)
        declared_text = QLabel(alignment.get("declaredNextStep") or "未设置"); declared_text.setWordWrap(True); declared_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        declared_text.setStyleSheet("color: #34445c; font-size: 13px; font-weight: 650;"); declared_layout.addWidget(declared_text); declared_layout.addStretch(); directions.addWidget(declared, 1)

        live = QFrame(); live.setObjectName("alignmentDirection"); live_layout = QVBoxLayout(live); live_layout.setContentsMargins(13, 11, 13, 13); live_layout.setSpacing(6)
        live_label = QLabel("今日正在执行"); live_label.setProperty("sectionLabel", True); live_layout.addWidget(live_label)
        self.task_field = QComboBox(); self.task_field.setFixedHeight(38); self.task_field.setAccessibleName("选择要采用的进行中任务")
        for task in tasks: self.task_field.addItem(str(task.get("title") or "未命名任务"), str(task.get("id") or ""))
        live_layout.addWidget(self.task_field)
        selected = tasks[0] if tasks else {}
        self.live_task_meta = QLabel(str(selected.get("conversationTitle") or "未关联 Codex 对话")); self.live_task_meta.setWordWrap(True); self.live_task_meta.setStyleSheet("color: #748094; font-size: 10px;"); live_layout.addWidget(self.live_task_meta)
        self.task_field.currentIndexChanged.connect(self.update_live_task_meta); directions.addWidget(live, 1)
        self.card_layout.addLayout(directions)
        self.feedback.setText("“采用”会更新项目下一步并留下字段变更记录；“保留”只确认当前差异是有意安排，不改动任务或项目方向。")
        self.feedback.setStyleSheet("color: #66758a; font-size: 11px;")

    def selected_task(self):
        alignment = self.current_alignment() or {}
        task_id = str(self.task_field.currentData() or "") if hasattr(self, "task_field") else ""
        return next((task for task in alignment.get("tasks") or [] if str(task.get("id") or "") == task_id), None)

    def update_live_task_meta(self):
        task = self.selected_task() or {}
        if hasattr(self, "live_task_meta"):
            self.live_task_meta.setText(str(task.get("conversationTitle") or "未关联 Codex 对话"))

    def open_current(self):
        alignment = self.current_alignment()
        if not alignment: return
        project = alignment.get("project") or {}
        references = project_reference_ids(project)
        self.window.open_project_workspace(project)
        queue_provider = getattr(self.window, "actionable_execution_alignment_queue", None)
        if not callable(queue_provider):
            queue_provider = getattr(self.window, "execution_alignment_queue", None)
        if callable(queue_provider) and references:
            refreshed = matching_guided_project_item(project, queue_provider())
            if refreshed is None:
                self.pending.pop(0); self.processed_count += 1
            else:
                self.pending[0] = refreshed
        self.render_current()

    def defer_current(self):
        if not self.pending: return
        self.pending.pop(0); self.skipped_count += 1; self.render_current()

    def keep_current(self):
        alignment = self.current_alignment()
        if not alignment: return
        if not self.window.acknowledge_execution_alignment(alignment):
            self.feedback.setText("当前执行方向已发生变化，请关闭后重新打开校准队列。")
            self.feedback.setStyleSheet("color: #b42318; background: #fff0ee; border-radius: 8px; padding: 7px 9px; font-size: 11px;"); return
        self.pending.pop(0); self.processed_count += 1; self.render_current()

    def adopt_current(self):
        alignment = self.current_alignment()
        if not alignment:
            self.accept(); return
        task = self.selected_task()
        if task is None or not self.window.adopt_execution_alignment(alignment, task):
            self.feedback.setText("没有成功更新项目下一步，请确认项目和任务仍然存在。")
            self.feedback.setStyleSheet("color: #b42318; background: #fff0ee; border-radius: 8px; padding: 7px 9px; font-size: 11px;"); return
        self.pending.pop(0); self.processed_count += 1; self.render_current()


class BlockerResolutionDialog(QDialog):
    """Capture the evidence that closes a blocker without turning it into a form."""
    def __init__(self, parent, project):
        super().__init__(parent)
        self.project = project or {}
        self.setWindowTitle("解除项目阻塞")
        self.setObjectName("blockerResolutionDialog")
        self.setMinimumSize(600, 360)
        self.resize(640, 390)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self); root.setContentsMargins(26, 23, 26, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(40, 40); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=21).pixmap(QSize(21, 21)))
        icon.setStyleSheet("background: #e8f7ef; border: 1px solid #c2e6d1; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("确认阻塞已经解除"); title.setStyleSheet("color: #172033; font-size: 21px; font-weight: 720;"); title_box.addWidget(title)
        subtitle = QLabel("保留原始原因、持续时长和解决说明，形成完整风险闭环")
        subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box, 1); root.addLayout(heading)

        evidence = QFrame(); evidence.setObjectName("blockerResolutionEvidence")
        evidence.setStyleSheet("QFrame#blockerResolutionEvidence { background: #fff8f5; border: 1px solid #efd1ca; border-radius: 11px; } QFrame#blockerResolutionEvidence QLabel { background: transparent; border: none; }")
        evidence_layout = QVBoxLayout(evidence); evidence_layout.setContentsMargins(14, 11, 14, 12); evidence_layout.setSpacing(4)
        evidence_label = QLabel("当前阻塞"); evidence_label.setStyleSheet("color: #9a3d32; font-size: 10px; font-weight: 700;"); evidence_layout.addWidget(evidence_label)
        blocker = QLabel(str(self.project.get("blocker") or "仅标记为阻塞")); blocker.setWordWrap(True); blocker.setTextInteractionFlags(Qt.TextSelectableByMouse)
        blocker.setStyleSheet("color: #552a26; font-size: 13px; font-weight: 650;"); evidence_layout.addWidget(blocker)
        duration = project_blocker_duration_label(self.project)
        timing = " · 起始时间为估计值" if self.project.get("blockedAtEstimated") else ""
        age = QLabel(f"已持续 {duration}{timing}"); age.setStyleSheet("color: #7f5a55; font-size: 10px;"); evidence_layout.addWidget(age); root.addWidget(evidence)

        label = QLabel("解决说明"); label.setStyleSheet("color: #4a586b; font-size: 12px; font-weight: 650;"); root.addWidget(label)
        self.resolution = QTextEdit(); self.resolution.setFixedHeight(82)
        self.resolution.setPlaceholderText("例如：依赖数据已到位并通过校验；替代方案已确认可用")
        self.resolution.setAccessibleName("阻塞解决说明"); root.addWidget(self.resolution)
        self.feedback = QLabel("请写一句可验证的解决事实；这段文字会进入项目决策历史。")
        self.feedback.setWordWrap(True); self.feedback.setStyleSheet("color: #66758a; font-size: 11px;"); root.addWidget(self.feedback)

        actions = QHBoxLayout(); actions.setSpacing(8); actions.addStretch()
        cancel = QPushButton("取消"); cancel.clicked.connect(self.reject); actions.addWidget(cancel)
        confirm = QPushButton("确认已解决"); confirm.setObjectName("primary"); confirm.setIcon(fluent_icon("\uE73E", color="#ffffff", size=14)); confirm.setIconSize(QSize(14, 14)); confirm.clicked.connect(self.confirm); actions.addWidget(confirm); root.addLayout(actions)

    def value(self):
        return " ".join(self.resolution.toPlainText().split())

    def confirm(self):
        if not self.value():
            self.feedback.setText("请先填写阻塞如何解除，不能只清除风险状态。")
            self.feedback.setStyleSheet("color: #b42318; background: #fff0ee; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
            self.resolution.setFocus()
            return
        self.accept()


class ProjectWorkbenchDialog(QDialog):
    def __init__(self, parent, project):
        super().__init__(parent)
        self.window = parent
        self.project = project
        self.setWindowTitle(f"项目面板 · {project.get('name', '未命名项目')}")
        self.setObjectName("projectWorkbench")
        self.setMinimumSize(900, 650)
        self.resize(980, 740)
        self.setStyleSheet(STYLE + """
            QDialog#projectWorkbench QLabel[sectionTitle='true'] { color: #253247; font-size: 14px; font-weight: 700; }
            QDialog#projectWorkbench QLabel[fieldLabel='true'] { color: #66758a; font-size: 11px; font-weight: 600; }
        """)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(12)
        icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE8B7", color="#1d4ed8", size=21).pixmap(QSize(21, 21)))
        icon.setStyleSheet("background: #eaf1ff; border: 1px solid #c9d9f6; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel(project.get("name") or "未命名项目"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        conversations = project.get("conversations") or []
        running_conversations = sum(codex_state(conversation)[0] == "running" for conversation in conversations)
        subtitle = QLabel(f"{project.get('category', '未分类')}  ·  {len(conversations)} 个 Codex 对话")
        subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box, 1)
        control_key, control_text, control_color, control_background, control_reason = project_control_state(project)
        self.control_badge = QLabel(control_text); self.control_badge.setAlignment(Qt.AlignCenter); self.control_badge.setFixedSize(64, 30); self.control_badge.setToolTip(control_reason)
        self.control_badge.setStyleSheet(f"color: {control_color}; background: {control_background}; border-radius: 9px; font-size: 11px; font-weight: 650;"); heading.addWidget(self.control_badge)
        _state, state_text, state_color, state_background = project_display_state(project)
        live_text = f"● {running_conversations} 个对话运行中" if running_conversations else f"● {state_text}"
        self.project_state_badge = QLabel(live_text); self.project_state_badge.setAlignment(Qt.AlignCenter); self.project_state_badge.setFixedSize(112 if running_conversations else 78, 30)
        self.project_state_badge.setStyleSheet(f"color: {state_color}; background: {state_background}; border-radius: 9px; font-size: 11px; font-weight: 650;"); heading.addWidget(self.project_state_badge)
        self.control_badge.setVisible(control_key in {"blocked", "attention", "review"} and control_text != state_text)
        continue_button = QPushButton("继续 Codex"); continue_button.setObjectName("primary"); continue_button.setFixedHeight(38)
        continue_button.setIcon(fluent_icon("\uE72A", color="#ffffff", size=15)); continue_button.setIconSize(QSize(15, 15)); continue_button.clicked.connect(self.continue_in_codex); heading.addWidget(continue_button)
        root.addLayout(heading)

        self.command_card = QFrame(); self.command_card.setObjectName("projectCommandCard"); self.command_card.setFixedHeight(82)
        command_layout = QHBoxLayout(self.command_card); command_layout.setContentsMargins(14, 10, 12, 10); command_layout.setSpacing(10)
        self.command_icon = QLabel(); self.command_icon.setFixedSize(34, 34); self.command_icon.setAlignment(Qt.AlignCenter); command_layout.addWidget(self.command_icon)
        command_body = QVBoxLayout(); command_body.setSpacing(1)
        self.command_kind = QLabel(); self.command_kind.setStyleSheet("font-size: 10px; font-weight: 720; letter-spacing: 0.4px;"); command_body.addWidget(self.command_kind)
        self.command_title = ElidedLabel(); self.command_title.setStyleSheet("color: #172033; font-size: 14px; font-weight: 720;"); command_body.addWidget(self.command_title)
        self.command_reason = ElidedLabel(); self.command_reason.setStyleSheet("color: #526071; font-size: 10px;"); command_body.addWidget(self.command_reason)
        command_layout.addLayout(command_body, 1)
        self.command_action = QPushButton(); self.command_action.setFixedSize(122, 38); self.command_action.clicked.connect(self.run_primary_command); command_layout.addWidget(self.command_action, 0, Qt.AlignVCenter)
        root.addWidget(self.command_card)

        management = QFrame(); management.setObjectName("managementCard")
        management.setStyleSheet("QFrame#managementCard { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 12px; }")
        management_layout = QVBoxLayout(management); management_layout.setContentsMargins(18, 12, 18, 13); management_layout.setSpacing(10)
        management_head = QHBoxLayout(); management_head.setSpacing(9)
        management_title = QLabel("项目资料"); management_title.setProperty("sectionTitle", True); management_head.addWidget(management_title)
        next_step_summary = str(project.get("nextStep") or "尚未设置下一步")
        self.project_context_summary = ElidedLabel(f"下一步 · {next_step_summary}")
        self.project_context_summary.setToolTip(f"目标：{project.get('objective') or '尚未明确'}\n下一步：{next_step_summary}")
        self.project_context_summary.setStyleSheet("color: #66758a; font-size: 10px; border: none;"); management_head.addWidget(self.project_context_summary, 1)
        self.review_meta = QLabel(project_review_summary(project))
        initial_drift = project_review_drift_presentation(project)
        self.review_meta.setToolTip(initial_drift.get("tooltip") or initial_drift["detail"])
        self.review_meta.setStyleSheet("color: #9a5b00; font-size: 10px; font-weight: 650;"); self.review_meta.setVisible(initial_drift["state"] == "changed"); management_head.addWidget(self.review_meta)
        self.management_toggle = QPushButton("编辑"); self.management_toggle.setFixedHeight(32); self.management_toggle.setCheckable(True)
        self.management_toggle.setIcon(fluent_icon("\uE70F", color="#315f9b", size=13)); self.management_toggle.setIconSize(QSize(13, 13)); self.management_toggle.clicked.connect(self.toggle_management_details); management_head.addWidget(self.management_toggle)
        review_button = QPushButton("确认变化"); review_button.setFixedHeight(32); review_button.setIcon(fluent_icon("\uE73E", color="#1d4ed8", size=13)); review_button.setIconSize(QSize(13, 13))
        review_button.setToolTip("核对与上次记录不同的关键决策；没有变化时不会显示")
        review_button.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c8d8f4; border-radius: 8px; padding: 4px 9px; font-size: 11px; font-weight: 650; } QPushButton:hover, QPushButton:focus { background: #dfe9fb; border-color: #9eb8e4; }")
        review_button.clicked.connect(self.confirm_current_state); review_button.setVisible(project_review_trigger(project) == "drift"); management_head.addWidget(review_button); management_layout.addLayout(management_head)
        self.management_body = QWidget(); management_body_layout = QVBoxLayout(self.management_body); management_body_layout.setContentsMargins(0, 2, 0, 0); management_body_layout.setSpacing(10)
        meta = QHBoxLayout(); meta.setSpacing(10)
        self.priority_field = QComboBox(); self.status_field = QComboBox(); self.category_field = QComboBox(); self.stage_field = QComboBox(); self.health_field = QComboBox()
        for key, label in PROJECT_PRIORITY.items(): self.priority_field.addItem(label, key)
        self.priority_field.setCurrentIndex(max(0, self.priority_field.findData(project_priority_key(project))))
        for key, label in STATUS_TEXT.items(): self.status_field.addItem(label, key)
        self.status_field.setCurrentIndex(max(0, self.status_field.findData(project.get("status", "active"))))
        for category in parent.categories[1:]: self.category_field.addItem(category, category)
        self.category_field.setCurrentIndex(max(0, self.category_field.findData(project.get("category", "未分类"))))
        for key, label in PROJECT_STAGE.items(): self.stage_field.addItem(label, key)
        self.stage_field.setCurrentIndex(max(0, self.stage_field.findData(project_stage_key(project))))
        for key, label in PROJECT_HEALTH.items(): self.health_field.addItem(label, key)
        self.health_field.setCurrentIndex(max(0, self.health_field.findData(project_health_key(project))))
        for label_text, field in (("管理优先级", self.priority_field), ("项目状态", self.status_field), ("项目分类", self.category_field), ("当前阶段", self.stage_field), ("项目健康度", self.health_field)):
            column = QVBoxLayout(); column.setSpacing(5); label = QLabel(label_text); label.setProperty("fieldLabel", True); column.addWidget(label)
            field.setFixedHeight(38); field.setAccessibleName(label_text); column.addWidget(field); meta.addLayout(column, 1)
        management_body_layout.addLayout(meta)
        definition_row = QHBoxLayout(); definition_row.setSpacing(9)
        objective_box = QVBoxLayout(); objective_box.setSpacing(5); objective_label = QLabel("项目目标"); objective_label.setProperty("fieldLabel", True); objective_box.addWidget(objective_label)
        self.objective_field = QTextEdit(); self.objective_field.setFixedHeight(66); self.objective_field.setPlainText(str(project.get("objective") or ""))
        self.objective_field.setPlaceholderText("这个项目最终要交付或解决什么？"); objective_box.addWidget(self.objective_field); definition_row.addLayout(objective_box, 1)
        criteria_box = QVBoxLayout(); criteria_box.setSpacing(5); criteria_label = QLabel("验收标准"); criteria_label.setProperty("fieldLabel", True); criteria_box.addWidget(criteria_label)
        self.success_criteria_field = QTextEdit(); self.success_criteria_field.setFixedHeight(66); self.success_criteria_field.setPlainText(str(project.get("successCriteria") or ""))
        self.success_criteria_field.setPlaceholderText("达到什么可验证结果时可以结束？"); criteria_box.addWidget(self.success_criteria_field); definition_row.addLayout(criteria_box, 1)
        management_body_layout.addLayout(definition_row)
        next_row = QHBoxLayout(); next_row.setSpacing(9)
        next_box = QVBoxLayout(); next_box.setSpacing(5); next_label = QLabel("明确下一步"); next_label.setProperty("fieldLabel", True); next_box.addWidget(next_label)
        self.next_step_field = QLineEdit(str(project.get("nextStep") or "")); self.next_step_field.setFixedHeight(40); self.next_step_field.setPlaceholderText("一个可以直接开始的具体动作"); next_box.addWidget(self.next_step_field); next_row.addLayout(next_box, 1)
        self.next_step_field.setCursorPosition(0)
        blocker_box = QVBoxLayout(); blocker_box.setSpacing(5); blocker_label = QLabel("当前阻塞"); blocker_label.setProperty("fieldLabel", True); blocker_box.addWidget(blocker_label)
        self.blocker_field = QLineEdit(str(project.get("blocker") or "")); self.blocker_field.setFixedHeight(40); self.blocker_field.setPlaceholderText("没有阻塞可留空"); blocker_box.addWidget(self.blocker_field); next_row.addLayout(blocker_box, 1)
        self.blocker_field.setCursorPosition(0)
        self.schedule_button = QPushButton("加入今日"); self.schedule_button.setFixedHeight(40); self.schedule_button.setIcon(fluent_icon("\uE787", color="#1d4ed8", size=14)); self.schedule_button.setIconSize(QSize(14, 14)); self.schedule_button.setToolTip("把当前项目下一步直接加入今日任务，并保留项目关联"); self.schedule_button.clicked.connect(self.schedule_next_step); next_row.addWidget(self.schedule_button, 0, Qt.AlignBottom)
        save = QPushButton("保存项目决策"); save.setFixedHeight(40); save.setIcon(fluent_icon("\uE74E", color="#1d4ed8", size=14)); save.setIconSize(QSize(14, 14)); save.clicked.connect(lambda: self.save_changes()); next_row.addWidget(save, 0, Qt.AlignBottom)
        management_body_layout.addLayout(next_row)
        self.blocker_strip = QFrame(); self.blocker_strip.setObjectName("projectBlockerStrip")
        self.blocker_strip.setStyleSheet("QFrame#projectBlockerStrip { background: #fff4f1; border: 1px solid #efc7c0; border-radius: 9px; } QFrame#projectBlockerStrip QLabel { border: none; background: transparent; }")
        blocker_strip_layout = QHBoxLayout(self.blocker_strip); blocker_strip_layout.setContentsMargins(11, 7, 8, 7); blocker_strip_layout.setSpacing(8)
        blocker_icon = QLabel(); blocker_icon.setFixedSize(18, 18); blocker_icon.setPixmap(fluent_icon("\uE7BA", color="#b42318", size=14).pixmap(QSize(14, 14))); blocker_strip_layout.addWidget(blocker_icon)
        self.blocker_summary = ElidedLabel(); self.blocker_summary.setStyleSheet("color: #8f2f27; font-size: 11px; font-weight: 600;"); blocker_strip_layout.addWidget(self.blocker_summary, 1)
        resolve_blocker = QPushButton("标记已解决"); resolve_blocker.setFixedHeight(28); resolve_blocker.setIcon(fluent_icon("\uE73E", color="#16803c", size=12)); resolve_blocker.setIconSize(QSize(12, 12))
        resolve_blocker.setToolTip("清除当前阻塞并恢复正常健康度；操作会进入项目决策记录")
        resolve_blocker.setStyleSheet("QPushButton { color: #17623b; background: #ffffff; border: 1px solid #b9d9c6; border-radius: 7px; padding: 3px 8px; font-size: 10px; font-weight: 650; } QPushButton:hover { background: #f3fbf6; border-color: #7fbe98; }")
        resolve_blocker.clicked.connect(self.resolve_blocker); blocker_strip_layout.addWidget(resolve_blocker)
        management_body_layout.addWidget(self.blocker_strip); self.render_blocker_strip()
        self.outcome_strip = QFrame(); self.outcome_strip.setObjectName("projectOutcomeStrip")
        outcome_layout = QHBoxLayout(self.outcome_strip); outcome_layout.setContentsMargins(11, 7, 8, 7); outcome_layout.setSpacing(8)
        self.outcome_icon = QLabel(); self.outcome_icon.setFixedSize(18, 18); outcome_layout.addWidget(self.outcome_icon)
        self.outcome_title = QLabel(); self.outcome_title.setStyleSheet("font-size: 11px; font-weight: 700;"); outcome_layout.addWidget(self.outcome_title)
        self.outcome_text = ElidedLabel(); self.outcome_text.setStyleSheet("font-size: 11px;"); outcome_layout.addWidget(self.outcome_text, 1)
        self.outcome_edit = QPushButton("编辑成果"); self.outcome_edit.setFixedHeight(28); self.outcome_edit.setIcon(fluent_icon("\uE70F", color="#17623b", size=12)); self.outcome_edit.setIconSize(QSize(12, 12))
        self.outcome_edit.setStyleSheet("QPushButton { color: #17623b; background: #ffffff; border: 1px solid #b9d9c6; border-radius: 7px; padding: 3px 8px; font-size: 10px; font-weight: 650; } QPushButton:hover { background: #f7fbf8; border-color: #7fbe98; }")
        self.outcome_edit.clicked.connect(self.edit_project_closeout); outcome_layout.addWidget(self.outcome_edit)
        management_body_layout.addWidget(self.outcome_strip); self.render_project_outcome()
        management_layout.addWidget(self.management_body)
        self.management_body.setVisible(False)
        root.addWidget(management)

        self.decision_history_frame = ClickableFrame(); self.decision_history_frame.setObjectName("decisionHistoryStrip"); self.decision_history_frame.setFixedHeight(52)
        self.decision_history_frame.setAccessibleName("查看项目决策记录"); self.decision_history_frame.setToolTip("查看这个项目的目标、验收标准、阶段、健康度和下一步等真实变更")
        self.decision_history_frame.setStyleSheet("QFrame#decisionHistoryStrip { background: #f8fafc; border: 1px solid #dbe3ee; border-radius: 10px; } QFrame#decisionHistoryStrip:hover, QFrame#decisionHistoryStrip:focus { background: #f1f6fd; border-color: #a9bfdf; }")
        decision_layout = QHBoxLayout(self.decision_history_frame); decision_layout.setContentsMargins(13, 6, 12, 6); decision_layout.setSpacing(10)
        decision_icon = QLabel(); decision_icon.setFixedSize(32, 32); decision_icon.setAlignment(Qt.AlignCenter); decision_icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        decision_icon.setPixmap(fluent_icon("\uE81C", color="#1d4ed8", size=16).pixmap(QSize(16, 16))); decision_icon.setStyleSheet("background: #eaf1ff; border: none; border-radius: 8px;"); decision_layout.addWidget(decision_icon)
        decision_text = QVBoxLayout(); decision_text.setSpacing(1)
        decision_caption = QLabel("最近决策"); decision_caption.setAttribute(Qt.WA_TransparentForMouseEvents); decision_caption.setStyleSheet("color: #253247; font-size: 11px; font-weight: 700;"); decision_text.addWidget(decision_caption)
        self.decision_history_summary = ElidedLabel(); self.decision_history_summary.setAttribute(Qt.WA_TransparentForMouseEvents); self.decision_history_summary.setStyleSheet("color: #66758a; font-size: 11px;"); decision_text.addWidget(self.decision_history_summary); decision_layout.addLayout(decision_text, 1)
        self.decision_history_count = QLabel(); self.decision_history_count.setAttribute(Qt.WA_TransparentForMouseEvents); self.decision_history_count.setAlignment(Qt.AlignCenter); self.decision_history_count.setStyleSheet("color: #315f9b; background: #eaf2ff; border: none; border-radius: 7px; padding: 4px 8px; font-size: 10px; font-weight: 650;"); decision_layout.addWidget(self.decision_history_count)
        decision_chevron = QLabel(); decision_chevron.setFixedSize(18, 18); decision_chevron.setAlignment(Qt.AlignCenter); decision_chevron.setAttribute(Qt.WA_TransparentForMouseEvents); decision_chevron.setPixmap(fluent_icon("\uE76C", color="#7a8798", size=13).pixmap(QSize(13, 13))); decision_layout.addWidget(decision_chevron)
        self.decision_history_frame.clicked.connect(self.show_decision_history); root.addWidget(self.decision_history_frame)

        self.activity_panel = QWidget(); lower = QHBoxLayout(self.activity_panel); lower.setContentsMargins(0, 0, 0, 0); lower.setSpacing(12)
        tasks_card = QFrame(); tasks_card.setObjectName("projectTasksCard"); tasks_card.setStyleSheet("QFrame#projectTasksCard { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 12px; }")
        tasks_layout = QVBoxLayout(tasks_card); tasks_layout.setContentsMargins(16, 14, 16, 14); tasks_layout.setSpacing(8)
        task_head = QHBoxLayout(); task_title = QLabel("今日任务"); task_title.setProperty("sectionTitle", True); task_head.addWidget(task_title); task_head.addStretch()
        self.add_task_button = QPushButton("新建关联任务"); self.add_task_button.setFixedHeight(32); self.add_task_button.setIcon(fluent_icon("\uE710", color="#1d4ed8", size=13)); self.add_task_button.setIconSize(QSize(13, 13)); self.add_task_button.clicked.connect(self.new_task); task_head.addWidget(self.add_task_button); tasks_layout.addLayout(task_head)
        self.project_tasks = QVBoxLayout(); self.project_tasks.setSpacing(6); tasks_layout.addLayout(self.project_tasks); tasks_layout.addStretch(); lower.addWidget(tasks_card, 1)

        conversations_card = QFrame(); conversations_card.setObjectName("projectConversationsCard"); conversations_card.setStyleSheet("QFrame#projectConversationsCard { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 12px; }")
        conversations_layout = QVBoxLayout(conversations_card); conversations_layout.setContentsMargins(16, 14, 16, 14); conversations_layout.setSpacing(8)
        conversations = project.get("conversations") or []
        conversation_title = QLabel(f"Codex 对话  {len(conversations)}"); conversation_title.setProperty("sectionTitle", True); conversations_layout.addWidget(conversation_title)
        if conversations:
            for conversation in conversations[:6]: conversations_layout.addWidget(ConversationRow(conversation, parent))
        else:
            empty = QLabel("尚未关联 Codex 对话\n点击“在 Codex 中继续”可复制完整项目上下文")
            empty.setWordWrap(True); empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #748094; background: #f7f9fc; border: 1px dashed #cbd5e1; border-radius: 9px; padding: 28px 12px; font-size: 11px;"); conversations_layout.addWidget(empty)
        conversations_layout.addStretch(); lower.addWidget(conversations_card, 1)
        root.addWidget(self.activity_panel, 1)

        actions = QHBoxLayout(); actions.setSpacing(8); actions.addStretch()
        more = QToolButton(); more.setFixedSize(36, 36); more.setIcon(fluent_icon("\uE712", color="#526071", size=15)); more.setIconSize(QSize(15, 15)); more.setAccessibleName("更多项目工具")
        more.setStyleSheet("QToolButton { background: #ffffff; border: 1px solid #d5dee9; border-radius: 9px; } QToolButton:hover, QToolButton:focus { background: #f1f5fa; border-color: #9fb6d0; }")
        more_menu = QMenu(more)
        full_edit_action = more_menu.addAction(fluent_icon("\uE70F", size=14), "完整编辑")
        full_edit_action.triggered.connect(self.full_edit)
        folder_action = more_menu.addAction(fluent_icon("\uE838", size=14), "打开项目文件夹")
        folder_action.setEnabled(bool(str(project.get("path") or "").strip())); folder_action.triggered.connect(lambda: parent.open_folder(project))
        more.setMenu(more_menu); more.setPopupMode(QToolButton.InstantPopup); actions.addWidget(more)
        close = QPushButton("关闭"); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)
        self.status_field.currentIndexChanged.connect(self.update_completion_controls)
        self.update_completion_controls()
        self.render_tasks()
        self.render_decision_history()
        self.refresh_command_state()

    def toggle_management_details(self, checked=False):
        self.set_management_expanded(bool(checked))

    def set_management_expanded(self, expanded, focus=None):
        expanded = bool(expanded)
        self.management_toggle.blockSignals(True)
        self.management_toggle.setChecked(expanded)
        self.management_toggle.setText("收起" if expanded else "编辑")
        self.management_toggle.setIcon(
            fluent_icon("\uE72B" if expanded else "\uE70F", color="#315f9b", size=13)
        )
        self.management_toggle.blockSignals(False)
        self.management_body.setVisible(expanded)
        self.activity_panel.setVisible(not expanded)
        if expanded and focus is not None:
            QTimer.singleShot(0, focus.setFocus)

    def refresh_command_state(self):
        routing = self.window.project_decision_routing()
        primary = primary_project_decision(self.project, routing)
        provider = getattr(self.window, "project_command_for", None)
        command = (
            provider(self.project, routing)
            if callable(provider) else
            project_workbench_command(
                self.project, self.window.today_tasks, QDate.currentDate().toString(Qt.ISODate), primary
            )
        )
        self._primary_decision = primary
        self._primary_command = command
        self.command_card.setVisible(str(command.get("key") or "") in {
            "attention", "alignment", "lifecycle", "needs_next", "focus_commitment",
            "review", "ready", "idle",
        })
        palettes = {
            "danger": ("#b42318", "#fff7f5", "#efc9c2", "#fee9e5", "\uE7BA"),
            "warning": ("#a15c00", "#fffaf0", "#ead8ad", "#f8ebcf", "\uE7BA"),
            "primary": ("#1d4ed8", "#f6f9ff", "#cbdaf1", "#e5edfc", "\uE8A7"),
            "focus": ("#6d3fc0", "#faf7ff", "#ddcff3", "#eee7fb", "\uE945"),
            "success": ("#087443", "#f4fbf7", "#c5e3d1", "#e2f3ea", "\uE73E"),
            "neutral": ("#526071", "#f8fafc", "#d9e1eb", "#e9eef4", "\uE823"),
        }
        color, background, border, icon_background, glyph = palettes.get(command.get("tone"), palettes["neutral"])
        self.command_card.setStyleSheet(
            f"QFrame#projectCommandCard {{ background: {background}; border: 1px solid {border}; border-left: 4px solid {color}; border-radius: 12px; }}"
            "QFrame#projectCommandCard QLabel { background: transparent; border: none; }"
        )
        self.command_icon.setPixmap(fluent_icon(glyph, color=color, size=20).pixmap(QSize(20, 20)))
        self.command_icon.setStyleSheet(f"background: {icon_background}; border: none; border-radius: 11px;")
        self.command_kind.setText(str(command.get("kind") or "项目状态"))
        self.command_kind.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 720; letter-spacing: 0.4px;")
        self.command_title.setText(str(command.get("title") or "当前项目"))
        self.command_reason.setText(str(command.get("reason") or "")); self.command_reason.setToolTip(self.command_reason.text())
        evidence = str(command.get("evidenceText") or "")
        action = str(command.get("action") or "")
        action_icons = {
            "resolve_blocker": "\uE7BA", "edit_decision": "\uE70F", "calibrate_alignment": "\uE8A7",
            "calibrate_lifecycle": "\uE823", "define_next_step": "\uE72A", "schedule_next_step": "\uE787",
            "confirm_review": "\uE73E", "continue_codex": "\uE72A",
        }
        self.command_action.setVisible(bool(action))
        self.command_action.setText(str(command.get("actionLabel") or "处理"))
        self.command_action.setIcon(fluent_icon(action_icons.get(action, "\uE72A"), color=color, size=14)); self.command_action.setIconSize(QSize(14, 14))
        self.command_action.setStyleSheet(
            f"QPushButton {{ color: {color}; background: #ffffff; border: 1px solid {border}; border-radius: 9px; font-size: 12px; font-weight: 700; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: {icon_background}; border-color: {color}; }}"
        )
        accessible = f"{command.get('kind')}：{command.get('title')}。{command.get('reason')}。{evidence}"
        self.command_card.setAccessibleName(accessible)

    def refresh_after_primary_decision(self):
        self.apply_management_values(self.project)
        self.refresh_header_states()
        self.render_blocker_strip()
        self.render_project_outcome()
        self.render_decision_history()
        self.render_tasks()
        self.refresh_command_state()

    def run_primary_command(self):
        action = str((getattr(self, "_primary_command", None) or {}).get("action") or "")
        primary = getattr(self, "_primary_decision", None) or {}
        if action == "resolve_blocker":
            self.resolve_blocker()
        elif action == "edit_decision":
            self.set_management_expanded(True, self.blocker_field)
        elif action == "define_next_step":
            self.set_management_expanded(True, self.next_step_field)
        elif action == "schedule_next_step":
            self.schedule_next_step()
        elif action == "confirm_review":
            self.confirm_current_state()
        elif action == "calibrate_alignment":
            item = primary.get("item")
            if isinstance(item, dict):
                ExecutionAlignmentDialog(self.window, [item]).exec_()
                self.refresh_after_primary_decision()
        elif action == "calibrate_lifecycle":
            item = primary.get("item")
            if isinstance(item, dict):
                LifecycleCalibrationDialog(self.window, [item]).exec_()
                self.refresh_after_primary_decision()
        elif action == "continue_codex":
            self.continue_in_codex()

    def render_tasks(self):
        while self.project_tasks.count():
            item = self.project_tasks.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        today = QDate.currentDate().toString(Qt.ISODate)
        tasks = [
            task for task in self.window.today_tasks
            if task_matches_project(task, self.project)
            and not task_is_archived(task)
            and (task.get("date") or today) == today
        ]
        if not tasks:
            empty = QLabel("今天还没有关联任务")
            empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #748094; background: #f7f9fc; border: 1px dashed #cbd5e1; border-radius: 9px; padding: 28px 12px; font-size: 11px;")
            self.project_tasks.addWidget(empty); return
        for task in tasks:
            row = QFrame(); row.setObjectName("projectTaskRow"); row.setFixedHeight(48); row.setStyleSheet("QFrame#projectTaskRow { background: #f8fafc; border: 1px solid #e0e7ef; border-radius: 8px; }")
            row_layout = QHBoxLayout(row); row_layout.setContentsMargins(11, 0, 8, 0); row_layout.setSpacing(8)
            title = ElidedLabel(task.get("title") or "未命名任务"); title.setStyleSheet("color: #34445c; font-size: 12px; font-weight: 600;")
            completion_outcome = task_completion_outcome(task)
            if completion_outcome:
                title.setToolTip(f"完成成果：{completion_outcome}")
            row_layout.addWidget(title, 1)
            status = QLabel(TASK_STATUS.get(task.get("status", "planned"), "计划")); status.setStyleSheet(f"color: {TASK_COLORS.get(task.get('status'), '#64748b')}; font-size: 11px; font-weight: 650;"); row_layout.addWidget(status)
            edit = QToolButton(); edit.setFixedSize(30, 30); edit.setIcon(fluent_icon("\uE70F", size=13)); edit.setToolTip("编辑任务"); edit.clicked.connect(lambda _checked=False, value=task: self.edit_task(value)); row_layout.addWidget(edit)
            self.project_tasks.addWidget(row)

    def render_project_outcome(self):
        closeout = project_completion_outcome(self.project)
        recent_task = str(self.project.get("lastCompletedOutcome") or "").strip()
        if self.project.get("status", "active") == "completed":
            completed_at = format_project_decision_time(self.project.get("completedAt"), compact=True)
            acceptance_objective = str(self.project.get("completionObjectiveSnapshot") or "").strip()
            acceptance_criteria = str(self.project.get("completionCriteriaSnapshot") or "").strip()
            title_parts = ["项目完成成果"]
            if acceptance_criteria:
                title_parts.append("已按标准验收")
            elif acceptance_objective:
                title_parts.append("已按目标验收")
            if self.project.get("completedAt"):
                title_parts.append(completed_at)
            self.outcome_title.setText(" · ".join(title_parts))
            self.outcome_text.setText((closeout or "尚未记录最终交付成果").replace("\n", " "))
            tooltip = closeout or "这是旧版完成项目；补充成果后会形成可追溯收尾记录。"
            if acceptance_objective:
                tooltip = f"验收目标：{acceptance_objective}\n\n完成成果：{closeout}"
            if acceptance_criteria:
                tooltip = f"验收目标：{acceptance_objective}\n验收标准：{acceptance_criteria}\n\n完成成果：{closeout}"
            self.outcome_text.setToolTip(tooltip)
            self.outcome_icon.setPixmap(fluent_icon("\uE73E" if closeout else "\uE7BA", color="#16803c" if closeout else "#a15c00", size=14).pixmap(QSize(14, 14)))
            self.outcome_title.setStyleSheet(f"color: {'#17623b' if closeout else '#8a5800'}; font-size: 11px; font-weight: 700;")
            self.outcome_text.setStyleSheet(f"color: {'#456a55' if closeout else '#7d6537'}; font-size: 11px;")
            self.outcome_strip.setStyleSheet(
                "QFrame#projectOutcomeStrip { background: #eef8f2; border: 1px solid #c8e5d3; border-radius: 9px; } QFrame#projectOutcomeStrip QLabel { border: none; background: transparent; }"
                if closeout else
                "QFrame#projectOutcomeStrip { background: #fff8e8; border: 1px solid #ead7a4; border-radius: 9px; } QFrame#projectOutcomeStrip QLabel { border: none; background: transparent; }"
            )
            self.outcome_edit.setVisible(True); self.outcome_strip.setVisible(True); return
        if recent_task:
            self.outcome_title.setText("最近任务成果")
            self.outcome_text.setText(recent_task.replace("\n", " ")); self.outcome_text.setToolTip(recent_task)
            self.outcome_icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=14).pixmap(QSize(14, 14)))
            self.outcome_title.setStyleSheet("color: #17623b; font-size: 11px; font-weight: 700;")
            self.outcome_text.setStyleSheet("color: #456a55; font-size: 11px;")
            self.outcome_strip.setStyleSheet("QFrame#projectOutcomeStrip { background: #eef8f2; border: 1px solid #c8e5d3; border-radius: 9px; } QFrame#projectOutcomeStrip QLabel { border: none; background: transparent; }")
            self.outcome_edit.setVisible(False); self.outcome_strip.setVisible(True); return
        self.outcome_strip.setVisible(False)

    def render_blocker_strip(self):
        blocked = project_control_state(self.project)[0] == "blocked"
        if not blocked:
            self.blocker_strip.setVisible(False); return
        reason = project_control_state(self.project)[4]
        self.blocker_summary.setText(f"当前阻塞 · {reason}")
        details = [f"当前阻塞：{self.project.get('blocker') or '仅标记为阻塞'}"]
        if self.project.get("blockedAt"):
            timing = "（从最近确认起）" if self.project.get("blockedAtEstimated") else ""
            details.append(f"开始：{format_project_decision_time(self.project.get('blockedAt'))}{timing}")
        if self.project.get("blockerUpdatedAt") and self.project.get("blockerUpdatedAt") != self.project.get("blockedAt"):
            details.append(f"说明更新：{format_project_decision_time(self.project.get('blockerUpdatedAt'))}")
        self.blocker_summary.setToolTip("\n".join(details)); self.blocker_strip.setVisible(True)

    def resolve_blocker(self):
        if project_control_state(self.project)[0] != "blocked":
            self.render_blocker_strip(); return
        resolution = BlockerResolutionDialog(self, self.project)
        if resolution.exec_() != QDialog.Accepted:
            return
        self.blocker_field.clear()
        health_index = self.health_field.findData("on_track")
        if health_index >= 0:
            self.health_field.setCurrentIndex(health_index)
        if not self.save_changes(blocker_resolution=resolution.value()):
            self.blocker_field.setText(str(self.project.get("blocker") or ""))
            health_index = self.health_field.findData(project_health_key(self.project))
            if health_index >= 0:
                self.health_field.setCurrentIndex(health_index)

    def update_completion_controls(self):
        completed = self.status_field.currentData() == "completed"
        for control in (self.next_step_field, self.blocker_field, self.schedule_button, self.add_task_button):
            control.setEnabled(not completed)
        if completed:
            self.next_step_field.setToolTip("已完成项目没有待执行下一步；重新打开后可继续规划")
            self.blocker_field.setToolTip("已完成项目不保留当前阻塞；重新打开后可继续维护")
            self.schedule_button.setToolTip("重新打开项目后才能安排新的下一步")
            self.add_task_button.setToolTip("重新打开项目后才能新建关联任务")
        else:
            self.next_step_field.setToolTip(""); self.blocker_field.setToolTip("")
            self.schedule_button.setToolTip("把当前项目下一步直接加入今日任务，并保留项目关联")
            self.add_task_button.setToolTip("新建一项与当前项目稳定关联的今日任务")

    def edit_project_closeout(self):
        if self.project.get("status", "active") != "completed":
            QMessageBox.information(self, "项目尚未完成", "项目完成成果只记录整个项目的最终交付。请先将项目状态改为“已完成”。")
            return
        if not self.save_changes(notify=False):
            return
        pending = open_project_tasks(self.window.today_tasks, self.project)
        dialog = ProjectCloseoutDialog(self, self.project, len(pending), latest_project_completion_outcome(self.project))
        if dialog.exec_() != QDialog.Accepted:
            return
        if self.window.update_project_completion_summary(
            self.project, dialog.value(), dialog.acceptance_objective(), dialog.acceptance_criteria()
        ):
            self.render_project_outcome(); self.render_decision_history()

    def render_decision_history(self):
        entries = self.window.project_decisions_for(self.project)
        self.decision_history_frame.setVisible(bool(entries))
        if not entries:
            summary = "暂无记录；首次保存真实变更后会自动形成历史"
            count = "0 条"
        else:
            latest = entries[0]
            source = PROJECT_DECISION_SOURCES.get(latest.get("source"), "手动决策")
            summary = f"{format_project_decision_time(latest.get('at'), compact=True)} · {source} · {format_project_decision_summary(latest)}"
            count = f"{len(entries)} 条"
        self.decision_history_summary.setText(summary)
        self.decision_history_summary.setToolTip(summary)
        self.decision_history_count.setText(count)

    def show_decision_history(self):
        entries = self.window.project_decisions_for(self.project)
        dialog = ProjectDecisionHistoryDialog(self, self.project, entries)
        dialog.exec_()
        if dialog.rolled_back:
            self.apply_management_values(self.project)
            self.refresh_header_states()
            self.render_blocker_strip()
            self.render_project_outcome()
            self.render_decision_history()

    def apply_management_values(self, data):
        for control, key in (
            (self.priority_field, "priority"),
            (self.status_field, "status"),
            (self.category_field, "category"),
            (self.stage_field, "stage"),
            (self.health_field, "health"),
        ):
            index = control.findData(data.get(key))
            if index >= 0:
                control.setCurrentIndex(index)
        self.objective_field.setPlainText(str(data.get("objective") or ""))
        self.success_criteria_field.setPlainText(str(data.get("successCriteria") or ""))
        self.next_step_field.setText(str(data.get("nextStep") or ""))
        self.blocker_field.setText(str(data.get("blocker") or ""))
        self.next_step_field.setCursorPosition(0)
        self.blocker_field.setCursorPosition(0)

    def refresh_header_states(self):
        key, text, color, background, reason = project_control_state(self.project)
        self.control_badge.setText(text); self.control_badge.setToolTip(reason)
        self.control_badge.setStyleSheet(f"color: {color}; background: {background}; border-radius: 9px; font-size: 11px; font-weight: 650;")
        _state, state_text, state_color, state_background = project_display_state(self.project)
        running_count = sum(codex_state(conversation)[0] == "running" for conversation in (self.project.get("conversations") or []))
        self.project_state_badge.setText(f"● {running_count} 个对话运行中" if running_count else f"● {state_text}")
        self.project_state_badge.setFixedWidth(112 if running_count else 78)
        self.project_state_badge.setStyleSheet(f"color: {state_color}; background: {state_background}; border-radius: 9px; font-size: 11px; font-weight: 650;")
        self.control_badge.setVisible(key in {"blocked", "attention", "review"} and text != state_text)
        self.review_meta.setText(project_review_summary(self.project))
        drift = project_review_drift_presentation(self.project)
        self.review_meta.setToolTip(drift.get("tooltip") or drift["detail"])
        self.review_meta.setVisible(drift["state"] == "changed")
        next_step = str(self.project.get("nextStep") or "尚未设置下一步")
        self.project_context_summary.setText(f"下一步 · {next_step}")
        self.project_context_summary.setToolTip(f"目标：{self.project.get('objective') or '尚未明确'}\n下一步：{next_step}")
        if hasattr(self, "command_card"):
            self.refresh_command_state()

    def confirm_current_state(self):
        before = dict(self.project)
        if not self.save_changes(notify=False):
            return
        changed = bool(project_decision_changes(before, self.project))
        self.window.record_project_review(self.project, audit=not changed)
        self.refresh_header_states()
        self.render_decision_history()

    def save_changes(self, notify=True, blocker_resolution=""):
        criteria_field = getattr(self, "success_criteria_field", None)
        data = {
            "priority": self.priority_field.currentData(),
            "status": self.status_field.currentData(),
            "category": self.category_field.currentData(),
            "stage": self.stage_field.currentData(),
            "health": self.health_field.currentData(),
            "objective": self.objective_field.toPlainText().strip(),
            "successCriteria": (
                criteria_field.toPlainText().strip()
                if criteria_field is not None else
                str(self.project.get("successCriteria") or "").strip()
            ),
            "nextStep": self.next_step_field.text().strip(),
            "blocker": self.blocker_field.text().strip(),
        }
        if blocker_resolution:
            data["blockerResolution"] = blocker_resolution
        data, _notes = normalize_project_management_decision(self.project, data)
        validation_error = project_management_validation_error(data)
        if validation_error:
            self.blocker_field.setFocus(); QMessageBox.information(self, "项目决策不完整", validation_error)
            return False
        clears_blocker = bool(str(self.project.get("blocker") or "").strip()) and not bool(data.get("blocker"))
        if clears_blocker and not data.get("blockerResolution") and data.get("status") != "completed":
            resolution = BlockerResolutionDialog(self, self.project)
            if resolution.exec_() != QDialog.Accepted:
                return False
            data["blockerResolution"] = resolution.value()
        if self.project.get("status", "active") != "completed" and data.get("status") == "completed":
            pending = open_project_tasks(self.window.today_tasks, self.project)
            initial = str(self.project.get("lastCompletedOutcome") or "").strip() or latest_project_completion_outcome(self.project)
            closeout = ProjectCloseoutDialog(self, {**self.project, **data}, len(pending), initial)
            if closeout.exec_() != QDialog.Accepted:
                return False
            data["completionSummary"] = closeout.value()
            data["completionObjectiveSnapshot"] = closeout.acceptance_objective()
            if closeout.acceptance_criteria():
                data["completionCriteriaSnapshot"] = closeout.acceptance_criteria()
            if clears_blocker and not data.get("blockerResolution"):
                data["blockerResolution"] = f"项目完成验收：{closeout.value()}"
        saved = self.window.update_project_management(self.project, data, notify=notify)
        if saved is None:
            return False
        self.apply_management_values(saved or data)
        self.refresh_header_states()
        self.render_blocker_strip()
        self.render_project_outcome()
        self.render_decision_history()
        return True

    def new_task(self):
        if not self.save_changes(notify=False):
            return
        self.window.new_project_task(self.project)
        self.render_tasks()
        self.refresh_command_state()

    def schedule_next_step(self):
        if not self.save_changes(notify=False):
            return
        self.window.schedule_project_next_step(self.project)
        self.render_tasks()
        self.refresh_command_state()

    def edit_task(self, task):
        self.window.edit_today_task(task)
        self.render_tasks()
        self.refresh_command_state()

    def continue_in_codex(self):
        if not self.save_changes(notify=False):
            return
        self.window.continue_project(self.project)
        self.accept()

    def full_edit(self):
        self.accept()
        self.window.edit_project(self.project)


class RunningConversationsDialog(QDialog):
    def __init__(self, parent, conversations):
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("运行中的 Codex 对话")
        self.setObjectName("runningDialog")
        self.setMinimumSize(780, 430)
        self.resize(780, min(760, max(430, 220 + len(conversations) * 88)))
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self); layout.setContentsMargins(26, 24, 26, 22); layout.setSpacing(14)
        title_row = QHBoxLayout(); title_row.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(38, 38); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE768", color="#087443", size=20).pixmap(QSize(20, 20)))
        icon.setStyleSheet("background: #e7f7ef; border: 1px solid #c2e8d3; border-radius: 10px;"); title_row.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("运行中的 Codex 对话"); title.setStyleSheet("font-size: 22px; font-weight: 700; color: #172033;"); title_box.addWidget(title)
        subtitle = QLabel(f"{len(conversations)} 个对话正在处理；点击即可回到对应 Codex 任务")
        subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); title_row.addLayout(title_box); title_row.addStretch(); layout.addLayout(title_row)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: #f7f9fc; border: 1px solid #dbe3ee; border-radius: 11px; }")
        content = QWidget(); content.setObjectName("runningContent"); content.setStyleSheet("QWidget#runningContent { background: #f7f9fc; }")
        rows = QVBoxLayout(content); rows.setContentsMargins(10, 10, 10, 10); rows.setSpacing(8)
        if not conversations:
            empty = QLabel("当前没有正在运行的 Codex 对话")
            empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #748094; font-size: 13px; padding: 70px;")
            rows.addWidget(empty)
        for project, conversation in conversations:
            row = QFrame(); row.setObjectName("runningConversationRow")
            row.setStyleSheet("QFrame#runningConversationRow { background: #ffffff; border: 1px solid #d7e2eb; border-left: 3px solid #10a361; border-radius: 10px; }")
            row_layout = QHBoxLayout(row); row_layout.setContentsMargins(14, 12, 12, 12); row_layout.setSpacing(12)
            thread_icon = QLabel(); thread_icon.setFixedSize(34, 34); thread_icon.setAlignment(Qt.AlignCenter)
            thread_icon.setPixmap(fluent_icon("\uE8BD", color="#087443", size=17).pixmap(QSize(17, 17))); thread_icon.setStyleSheet("background: #e8f7ef; border-radius: 9px;"); row_layout.addWidget(thread_icon)
            text = QVBoxLayout(); text.setSpacing(3)
            name = ElidedLabel(conversation_name(conversation)); name.setToolTip(conversation_name(conversation)); name.setStyleSheet("color: #253247; font-size: 14px; font-weight: 680;"); text.addWidget(name)
            meta = QLabel(f"{project.get('name', '未命名项目')}  ·  {relative_time(conversation)}")
            meta.setStyleSheet("color: #66758a; font-size: 11px;"); text.addWidget(meta)
            summary = ElidedLabel(conversation.get("summary") or "Codex 正在处理此任务")
            summary.setToolTip(conversation.get("summary") or ""); summary.setStyleSheet("color: #526071; font-size: 11px;"); text.addWidget(summary)
            row_layout.addLayout(text, 1)
            state = QLabel("● 运行中"); state.setAlignment(Qt.AlignCenter); state.setFixedSize(72, 28)
            state.setStyleSheet("color: #087443; background: #e5f7ed; border: none; border-radius: 8px; font-size: 11px; font-weight: 650;"); row_layout.addWidget(state)
            open_button = QPushButton("打开 Codex"); open_button.setFixedSize(108, 34); open_button.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); open_button.setIconSize(QSize(14, 14))
            open_button.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c8d8f4; border-radius: 8px; font-size: 12px; font-weight: 650; } QPushButton:hover { background: #dfe9fb; border-color: #9eb8e4; }")
            open_button.clicked.connect(lambda _checked=False, value=conversation: self.open_conversation(value)); row_layout.addWidget(open_button)
            rows.addWidget(row)
        rows.addStretch(); scroll.setWidget(content); layout.addWidget(scroll, 1)
        actions = QHBoxLayout(); actions.addStretch()
        close = QPushButton("关闭"); close.setFixedHeight(36); close.clicked.connect(self.accept); actions.addWidget(close); layout.addLayout(actions)

    def open_conversation(self, conversation):
        self.window.open_codex_conversation(conversation)
        self.accept()


class CommandPaletteDialog(QDialog):
    """Compact keyboard-first navigation across the local Codex workspace."""

    TYPE_META = {
        "action": ("指令", "\uE945", "#526071", "#eef2f6"),
        "project": ("项目", "\uE8B7", "#1d4ed8", "#eaf1ff"),
        "task": ("任务", "\uE9D5", "#6d3fc0", "#f1ebff"),
        "conversation": ("对话", "\uE8BD", "#087443", "#e7f7ef"),
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.window = parent
        self.catalog = parent.command_catalog()
        self.results = []
        self.result_rows = []
        self.selected_index = 0
        self.setWindowTitle("快速打开")
        self.setObjectName("commandPalette")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.resize(760, 590)

        outer = QVBoxLayout(self); outer.setContentsMargins(18, 18, 18, 18)
        card = QFrame(); card.setObjectName("commandPaletteCard")
        card.setStyleSheet("""
            QFrame#commandPaletteCard { background: #ffffff; border: 1px solid #cbd7e6; border-radius: 17px; }
            QFrame#commandSearchFrame { background: #f7f9fc; border: 1px solid #b9c9dc; border-radius: 12px; }
            QFrame#commandResult { background: #ffffff; border: 1px solid transparent; border-radius: 10px; }
            QFrame#commandResult:hover { background: #f5f8fd; border-color: #d7e2ef; }
            QFrame#commandResult[selected='true'] { background: #edf4ff; border-color: #afc8ee; }
        """)
        outer.addWidget(card)
        layout = QVBoxLayout(card); layout.setContentsMargins(18, 17, 18, 14); layout.setSpacing(11)

        search_frame = QFrame(); search_frame.setObjectName("commandSearchFrame"); search_frame.setFixedHeight(58)
        search_layout = QHBoxLayout(search_frame); search_layout.setContentsMargins(15, 0, 13, 0); search_layout.setSpacing(10)
        search_icon = QLabel(); search_icon.setFixedSize(24, 24); search_icon.setAlignment(Qt.AlignCenter)
        search_icon.setPixmap(fluent_icon("\uE721", color="#2563eb", size=18).pixmap(QSize(18, 18))); search_layout.addWidget(search_icon)
        self.search = QLineEdit(); self.search.setFrame(False); self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("搜索项目、任务、Codex 对话或指令…")
        self.search.setAccessibleName("全局搜索")
        self.search.setStyleSheet("QLineEdit { background: transparent; border: none; padding: 0; color: #172033; font-size: 16px; font-weight: 520; }")
        self.search.textChanged.connect(self.refresh_results); self.search.returnPressed.connect(self.activate_selected); search_layout.addWidget(self.search, 1)
        shortcut_hint = QLabel("CTRL  K"); shortcut_hint.setAlignment(Qt.AlignCenter); shortcut_hint.setFixedSize(58, 28)
        shortcut_hint.setStyleSheet("color: #607087; background: #ffffff; border: 1px solid #d6e0eb; border-radius: 7px; font-size: 10px; font-weight: 700; letter-spacing: 0.6px;"); search_layout.addWidget(shortcut_hint)
        layout.addWidget(search_frame)

        result_header = QHBoxLayout(); result_header.setContentsMargins(3, 1, 3, 0)
        caption = QLabel("快速打开"); caption.setStyleSheet("color: #34445c; font-size: 12px; font-weight: 700; letter-spacing: 0.5px;"); result_header.addWidget(caption)
        result_header.addStretch(); self.result_meta = QLabel(); self.result_meta.setStyleSheet("color: #7a8798; font-size: 11px;"); result_header.addWidget(self.result_meta); layout.addLayout(result_header)

        self.results_widget = QWidget(); self.results_widget.setObjectName("commandResults"); self.results_widget.setStyleSheet("QWidget#commandResults { background: transparent; }")
        self.results_layout = QVBoxLayout(self.results_widget); self.results_layout.setContentsMargins(0, 0, 0, 0); self.results_layout.setSpacing(5); layout.addWidget(self.results_widget, 1)

        footer = QHBoxLayout(); footer.setContentsMargins(3, 2, 3, 0); footer.setSpacing(14)
        source = QLabel("项目、任务与对话均来自当前本地同步状态"); source.setStyleSheet("color: #7a8798; font-size: 10px;"); footer.addWidget(source); footer.addStretch()
        controls = QLabel("↑↓ 选择    ENTER 打开    ESC 关闭"); controls.setStyleSheet("color: #607087; font-size: 10px; font-weight: 600;"); footer.addWidget(controls); layout.addLayout(footer)

        self.down_shortcut = QShortcut(QKeySequence("Down"), self); self.down_shortcut.activated.connect(lambda: self.move_selection(1))
        self.up_shortcut = QShortcut(QKeySequence("Up"), self); self.up_shortcut.activated.connect(lambda: self.move_selection(-1))
        self.close_shortcut = QShortcut(QKeySequence("Escape"), self); self.close_shortcut.activated.connect(self.reject)
        self.refresh_results()
        QTimer.singleShot(0, self.search.setFocus)

    def showEvent(self, event):
        super().showEvent(event)
        if self.parentWidget():
            geometry = self.frameGeometry(); geometry.moveCenter(self.parentWidget().frameGeometry().center()); self.move(geometry.topLeft())

    def refresh_results(self):
        MainWindow._clear_layout(self.results_layout)
        matches = search_navigation_entries(self.catalog, self.search.text(), limit=1000)
        self.results = matches[:8]
        self.result_rows = []
        self.selected_index = 0
        if not self.results:
            empty = QFrame(); empty.setFixedHeight(290); empty_layout = QVBoxLayout(empty); empty_layout.setAlignment(Qt.AlignCenter)
            empty_icon = QLabel(); empty_icon.setAlignment(Qt.AlignCenter); empty_icon.setPixmap(fluent_icon("\uE721", color="#8a99ad", size=24).pixmap(QSize(24, 24))); empty_layout.addWidget(empty_icon)
            empty_text = QLabel("没有匹配的项目、任务、对话或指令"); empty_text.setAlignment(Qt.AlignCenter); empty_text.setStyleSheet("color: #66758a; font-size: 13px; margin-top: 8px;"); empty_layout.addWidget(empty_text); self.results_layout.addWidget(empty)
        else:
            for index, entry in enumerate(self.results):
                row = self.build_result_row(entry, index)
                self.result_rows.append(row); self.results_layout.addWidget(row)
            self.results_layout.addStretch()
        shown = len(self.results)
        self.result_meta.setText(f"{shown} / {len(matches)} 项" if len(matches) > shown else f"{shown} 项")
        self.update_selection()

    def build_result_row(self, entry, index):
        row = ClickableFrame(); row.setObjectName("commandResult"); row.setFixedHeight(56)
        row.setAccessibleName(f"{self.TYPE_META.get(entry.get('kind'), self.TYPE_META['action'])[0]}：{entry.get('title', '')}")
        layout = QHBoxLayout(row); layout.setContentsMargins(11, 7, 11, 7); layout.setSpacing(11)
        label, glyph, color, background = self.TYPE_META.get(entry.get("kind"), self.TYPE_META["action"])
        icon = QLabel(); icon.setAttribute(Qt.WA_TransparentForMouseEvents); icon.setFixedSize(34, 34); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon(glyph, color=color, size=17).pixmap(QSize(17, 17))); icon.setStyleSheet(f"background: {background}; border: none; border-radius: 9px;"); layout.addWidget(icon)
        text = QVBoxLayout(); text.setSpacing(1)
        title = ElidedLabel(str(entry.get("title") or "")); title.setAttribute(Qt.WA_TransparentForMouseEvents); title.setToolTip(str(entry.get("title") or "")); title.setStyleSheet("color: #253247; font-size: 13px; font-weight: 680; border: none;"); text.addWidget(title)
        subtitle = ElidedLabel(str(entry.get("subtitle") or "")); subtitle.setAttribute(Qt.WA_TransparentForMouseEvents); subtitle.setToolTip(str(entry.get("subtitle") or "")); subtitle.setStyleSheet("color: #6b788b; font-size: 10px; border: none;"); text.addWidget(subtitle); layout.addLayout(text, 1)
        kind = QLabel(label); kind.setAttribute(Qt.WA_TransparentForMouseEvents); kind.setAlignment(Qt.AlignCenter); kind.setFixedSize(52, 26)
        kind.setStyleSheet(f"color: {color}; background: {background}; border: none; border-radius: 7px; font-size: 10px; font-weight: 700;"); layout.addWidget(kind)
        arrow = QLabel(); arrow.setAttribute(Qt.WA_TransparentForMouseEvents); arrow.setFixedSize(18, 18); arrow.setAlignment(Qt.AlignCenter); arrow.setPixmap(fluent_icon("\uE76C", color="#718096", size=13).pixmap(QSize(13, 13))); layout.addWidget(arrow)
        row.clicked.connect(lambda value=entry: self.activate_entry(value))
        return row

    def move_selection(self, delta):
        if not self.results:
            return
        self.selected_index = (self.selected_index + delta) % len(self.results)
        self.update_selection()

    def update_selection(self):
        for index, row in enumerate(self.result_rows):
            row.setProperty("selected", index == self.selected_index)
            row.style().unpolish(row); row.style().polish(row)

    def activate_selected(self):
        if self.results:
            self.activate_entry(self.results[self.selected_index])

    def activate_entry(self, entry):
        self.accept()
        QTimer.singleShot(0, lambda value=entry: self.window.execute_command_entry(value))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.projects, self.saved_projects, self.category, self.running_count = [], [], "全部", 0
        self.categories = load_categories()
        self.project_layout = load_project_layout()
        self.today_tasks = load_json(TASKS_FILE, [])
        self.daily_summaries = load_json(DAILY_SUMMARIES_FILE, [])
        self.project_decisions = load_json(PROJECT_DECISIONS_FILE, [])
        if not isinstance(self.project_decisions, list):
            self.project_decisions = []
        self.daily_summary_worker = None
        self.daily_summary_error = ""
        self.summary_attempt_date = None
        self.usage_data, self.usage_scanner = {}, None
        self.section = "home"
        self.live_sessions, self.scan_ready, self.session_scanner = [], False, None
        self.expansion_preferences = {}
        self.view_signature = None
        self.last_scan_at = None
        self.home_scroll_reset_done = False
        self.pending_task_undo = None
        self.setWindowTitle("Codex 项目中心")
        self.resize(1360, 840); self.setMinimumSize(1120, 700); self.setStyleSheet(STYLE)
        self.build_ui(); self.refresh(); self.timer = QTimer(self); self.timer.timeout.connect(lambda: self.refresh(silent=True)); self.timer.start(15000)
        self.usage_timer = QTimer(self); self.usage_timer.timeout.connect(self.start_usage_scan); self.usage_timer.start(120000); self.start_usage_scan()

    def build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        top = QFrame(); top.setObjectName("systemSpine"); top.setFixedHeight(68)
        top.setStyleSheet("QFrame#systemSpine { background: #ffffff; border-bottom: 1px solid #dbe3ee; }")
        top_layout = QHBoxLayout(top); top_layout.setContentsMargins(18, 7, 20, 7); top_layout.setSpacing(12)

        brand_frame = QFrame(); brand_frame.setFixedWidth(218); brand_frame.setStyleSheet("background: transparent; border: none;")
        brand_layout = QHBoxLayout(brand_frame); brand_layout.setContentsMargins(0, 0, 0, 0); brand_layout.setSpacing(10)
        brand_icon = QLabel(); brand_icon.setFixedSize(36, 36); brand_icon.setAlignment(Qt.AlignCenter)
        brand_icon.setPixmap(fluent_icon("\uE950", color="#2563eb", size=23).pixmap(QSize(23, 23)))
        brand_icon.setStyleSheet("background: #edf3ff; border: 1px solid #c9daf7; border-radius: 10px;")
        brand_layout.addWidget(brand_icon)
        brand = QLabel("Codex 项目中心"); brand.setStyleSheet("font-size: 19px; font-weight: 680; color: #172033; letter-spacing: 0.1px;"); brand_layout.addWidget(brand); brand_layout.addStretch(); top_layout.addWidget(brand_frame)

        live_frame = ClickableFrame(); live_frame.setObjectName("liveSummary"); live_frame.setFixedHeight(54); live_frame.setMinimumWidth(250)
        live_frame.setAccessibleName("查看运行中的 Codex 对话"); live_frame.setToolTip("查看正在运行的 Codex 对话")
        live_frame.setStyleSheet("QFrame#liveSummary { background: #f8fafc; border: 1px solid #d9e2ec; border-radius: 12px; } QFrame#liveSummary:hover, QFrame#liveSummary:focus { background: #f1f6fd; border-color: #9eb8d8; }")
        live_layout = QHBoxLayout(live_frame); live_layout.setContentsMargins(13, 7, 14, 7); live_layout.setSpacing(10)
        live_icon = QLabel(); live_icon.setFixedSize(32, 32); live_icon.setAlignment(Qt.AlignCenter)
        live_icon.setPixmap(fluent_icon("\uE768", color="#2563eb", size=18).pixmap(QSize(18, 18)))
        live_icon.setAttribute(Qt.WA_TransparentForMouseEvents); live_icon.setStyleSheet("background: #e9f0ff; border: none; border-radius: 9px;"); live_layout.addWidget(live_icon)
        live_text = QVBoxLayout(); live_text.setSpacing(0)
        live_caption = QLabel("CODEX 工作区"); live_caption.setAttribute(Qt.WA_TransparentForMouseEvents); live_caption.setStyleSheet("color: #77869a; font-size: 10px; font-weight: 650; letter-spacing: 0.7px;"); live_text.addWidget(live_caption)
        self.pulse_state_label = QLabel("正在同步本地对话"); self.pulse_state_label.setAttribute(Qt.WA_TransparentForMouseEvents); self.pulse_state_label.setStyleSheet("color: #42526a; font-size: 13px; font-weight: 650;"); live_text.addWidget(self.pulse_state_label)
        live_layout.addLayout(live_text, 1)
        live_chevron = QLabel(); live_chevron.setFixedSize(18, 18); live_chevron.setPixmap(fluent_icon("\uE76C", color="#7a8798", size=13).pixmap(QSize(13, 13))); live_chevron.setAlignment(Qt.AlignCenter); live_chevron.setAttribute(Qt.WA_TransparentForMouseEvents); live_layout.addWidget(live_chevron)
        live_frame.clicked.connect(self.show_running_conversations); top_layout.addWidget(live_frame, 1)

        telemetry = QFrame(); telemetry.setObjectName("telemetry"); telemetry.setFixedHeight(54); telemetry.setMinimumWidth(390)
        telemetry.setStyleSheet("QFrame#telemetry { background: #f8fafc; border: 1px solid #d9e2ec; border-radius: 12px; }")
        telemetry_layout = QHBoxLayout(telemetry); telemetry_layout.setContentsMargins(14, 7, 14, 7); telemetry_layout.setSpacing(14)
        usage_title = QVBoxLayout(); usage_title.setSpacing(0)
        usage_caption = QLabel("CODEX 用量"); usage_caption.setStyleSheet("color: #526071; font-size: 11px; font-weight: 700; letter-spacing: 0.6px;"); usage_title.addWidget(usage_caption)
        self.usage_synced_label = ElidedLabel("正在读取额度…"); self.usage_synced_label.setMaximumWidth(150); self.usage_synced_label.setStyleSheet("color: #7a8798; font-size: 10px;"); usage_title.addWidget(self.usage_synced_label); telemetry_layout.addLayout(usage_title, 2)
        metrics = QHBoxLayout(); metrics.setSpacing(16)
        def telemetry_metric(caption):
            box = QVBoxLayout(); box.setSpacing(0); value = QLabel("—"); value.setStyleSheet("color: #172033; font-size: 15px; font-weight: 700;")
            label = QLabel(caption); label.setStyleSheet("color: #7a8798; font-size: 10px;"); box.addWidget(value); box.addWidget(label); metrics.addLayout(box, 1); return value
        self.usage_used_label = telemetry_metric("已使用")
        self.usage_remaining_label = telemetry_metric("剩余")
        self.usage_reset_label = telemetry_metric("刷新")
        today_box = QVBoxLayout(); today_box.setSpacing(0)
        self.usage_today_label = QLabel("—"); self.usage_today_label.setStyleSheet("color: #172033; font-size: 15px; font-weight: 700;")
        self.usage_today_caption = QLabel("今日 Tokens"); self.usage_today_caption.setStyleSheet("color: #7a8798; font-size: 10px;")
        today_box.addWidget(self.usage_today_label); today_box.addWidget(self.usage_today_caption); metrics.addLayout(today_box, 1)
        telemetry_layout.addLayout(metrics, 3)
        self.usage_progress = QProgressBar(); self.usage_progress.setRange(0, 100); self.usage_progress.setTextVisible(False); self.usage_progress.setFixedSize(4, 36)
        self.usage_progress.setOrientation(Qt.Vertical)
        self.usage_progress.setStyleSheet("QProgressBar { background: #e2e8f0; border: none; border-radius: 2px; } QProgressBar::chunk { background: #2563eb; border-radius: 2px; }")
        telemetry_layout.addWidget(self.usage_progress); top_layout.addWidget(telemetry, 2)

        self.sync = QLabel("●  自动同步"); self.sync.setAlignment(Qt.AlignRight | Qt.AlignVCenter); self.sync.setMinimumWidth(100); self.sync.setFixedHeight(34)
        self.sync.setStyleSheet("color: #087443; background: transparent; border: none; padding: 3px 2px; font-size: 11px; font-weight: 650;"); top_layout.addWidget(self.sync)
        root.addWidget(top)
        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0); root.addLayout(body)
        side = QFrame(); side.setObjectName("navigationRail"); side.setFixedWidth(248)
        side.setStyleSheet("QFrame#navigationRail { background: #f8fafc; border-right: 1px solid #dde5ee; }")
        side_layout = QVBoxLayout(side); side_layout.setContentsMargins(12, 18, 12, 14); side_layout.setSpacing(5)
        self.home_nav_button = QPushButton("主页"); self.home_nav_button.setObjectName("nav"); self.home_nav_button.setIcon(fluent_icon("\uE80F", color="#526071", size=16)); self.home_nav_button.setIconSize(QSize(16, 16)); self.home_nav_button.clicked.connect(lambda: self.select_section("home")); side_layout.addWidget(self.home_nav_button)
        self.project_nav_button = QPushButton("项目"); self.project_nav_button.setObjectName("nav"); self.project_nav_button.setIcon(fluent_icon("\uE8B7", color="#526071", size=16)); self.project_nav_button.setIconSize(QSize(16, 16)); self.project_nav_button.clicked.connect(lambda: self.select_section("projects")); side_layout.addWidget(self.project_nav_button)
        separator = QFrame(); separator.setFixedHeight(1); separator.setStyleSheet("background: #e1e7ef; margin: 11px 8px;"); side_layout.addWidget(separator)
        self.category_panel = QWidget(); category_panel_layout = QVBoxLayout(self.category_panel); category_panel_layout.setContentsMargins(0, 0, 0, 0); category_panel_layout.setSpacing(3)
        category_header_frame = QFrame(); category_header_frame.setObjectName("categoryHeader"); category_header_frame.setFixedHeight(40)
        category_header_frame.setStyleSheet("QFrame#categoryHeader { background: transparent; border: none; } QFrame#categoryHeader QLabel { color: #395679; background: transparent; }")
        category_header = QHBoxLayout(category_header_frame); category_header.setContentsMargins(10, 3, 4, 3); category_header.setSpacing(4)
        label = QLabel("项目分类"); label.setStyleSheet("color: #4b5c73; font-size: 12px; font-weight: 700; letter-spacing: 0.5px;"); category_header.addWidget(label); category_header.addStretch()
        manage_categories = QToolButton(); manage_categories.setText("管理"); manage_categories.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); manage_categories.setFixedSize(70, 30)
        manage_categories.setIcon(fluent_icon("\uE712", size=14)); manage_categories.setIconSize(QSize(14, 14)); manage_categories.setToolTip("管理项目分类")
        manage_categories.setStyleSheet("QToolButton { color: #53647a; border: 1px solid transparent; border-radius: 7px; background: transparent; padding: 4px 7px; font-size: 12px; } QToolButton:hover { background: #edf2f7; border-color: #d8e1eb; }")
        category_menu = QMenu(manage_categories)
        add_action = category_menu.addAction(fluent_icon("\uE710", size=14), "新建分类"); add_action.triggered.connect(self.add_category)
        reorder_action = category_menu.addAction(fluent_icon("\uE76F", size=14), "调整顺序"); reorder_action.triggered.connect(self.reorder_categories)
        rename_action = category_menu.addAction(fluent_icon("\uE70F", size=14), "修改名称"); rename_action.triggered.connect(self.rename_category)
        category_menu.addSeparator()
        delete_action = category_menu.addAction(fluent_icon("\uE74D", color="#b42318", size=14), "删除分类"); delete_action.triggered.connect(self.delete_category)
        manage_categories.setMenu(category_menu); manage_categories.setPopupMode(QToolButton.InstantPopup); category_header.addWidget(manage_categories)
        category_panel_layout.addWidget(category_header_frame)
        self.nav = QVBoxLayout(); self.nav.setSpacing(2); category_panel_layout.addLayout(self.nav); side_layout.addWidget(self.category_panel); side_layout.addStretch()
        body.addWidget(side)
        self.pages = QStackedWidget(); self.home_page = self.build_home_page(); self.projects_page = self.build_projects_page(); self.pages.addWidget(self.home_page); self.pages.addWidget(self.projects_page); body.addWidget(self.pages, 1)
        status_bar = QStatusBar(); self.setStatusBar(status_bar)
        self.undo_task_button = QPushButton("撤销操作"); self.undo_task_button.setFixedHeight(26); self.undo_task_button.setIcon(fluent_icon("\uE7A7", color="#1d4ed8", size=13)); self.undo_task_button.setIconSize(QSize(13, 13))
        self.undo_task_button.setToolTip("撤销最近一次可逆任务调整"); self.undo_task_button.setAccessibleName("撤销最近一次任务调整")
        self.undo_task_button.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #bfd1ef; border-radius: 7px; padding: 3px 9px; font-size: 11px; font-weight: 650; } QPushButton:hover, QPushButton:focus { background: #dfe9fb; border-color: #8eace0; }")
        self.undo_task_button.clicked.connect(self.undo_last_task_transition); self.undo_task_button.hide(); status_bar.addPermanentWidget(self.undo_task_button)
        self.undo_task_timer = QTimer(self); self.undo_task_timer.setSingleShot(True); self.undo_task_timer.timeout.connect(self.clear_task_undo)
        self.command_shortcut = QShortcut(QKeySequence("Ctrl+K"), self); self.command_shortcut.activated.connect(self.show_command_palette)
        self.select_section("home")

    def build_projects_page(self):
        main = QWidget(); main.setObjectName("projectsPage"); main.setStyleSheet("QWidget#projectsPage { background: #f5f7fb; } QWidget#projectsPage QLabel { background: transparent; }"); main_layout = QVBoxLayout(main); main_layout.setContentsMargins(32, 26, 28, 24); main_layout.setSpacing(16)
        heading = QHBoxLayout(); heading.setSpacing(24)
        heading_text = QVBoxLayout(); heading_text.setSpacing(4)
        title = QLabel("项目"); title.setStyleSheet("font-size: 29px; font-weight: 720; color: #172033;"); heading_text.addWidget(title)
        subtitle = QLabel("按分类查看项目，并展开每个项目关联的 Codex 对话")
        subtitle.setStyleSheet("color: #66758a; font-size: 13px;"); heading_text.addWidget(subtitle)
        heading.addLayout(heading_text); heading.addStretch()
        self.governance_button = QPushButton("Codex 补全"); self.governance_button.setFixedHeight(40)
        self.governance_button.setIcon(fluent_icon("\uE945", color="#1d4ed8", size=15)); self.governance_button.setIconSize(QSize(15, 15))
        self.governance_button.setToolTip("批量补齐缺失的项目目标和下一步，审核后再写入")
        self.governance_button.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c8d8f4; border-radius: 9px; padding: 7px 12px; font-size: 12px; font-weight: 650; } QPushButton:hover, QPushButton:focus { background: #dfe9fb; border-color: #9eb8e4; }")
        self.governance_button.clicked.connect(lambda: self.show_project_governance()); heading.addWidget(self.governance_button)
        self.archive_button = QPushButton("归档箱"); self.archive_button.setFixedHeight(40)
        self.archive_button.setIcon(fluent_icon("\uE7B8", color="#42526a", size=15)); self.archive_button.setIconSize(QSize(15, 15))
        self.archive_button.setToolTip("查看并恢复从项目中心归档的项目"); self.archive_button.clicked.connect(self.show_archived_projects); heading.addWidget(self.archive_button)
        new_project = QPushButton("新建项目"); new_project.setIcon(fluent_icon("\uE710", color="#ffffff", size=15)); new_project.setIconSize(QSize(15, 15)); new_project.setObjectName("primary"); new_project.setFixedHeight(40); new_project.clicked.connect(lambda: self.edit_project(None)); heading.addWidget(new_project); main_layout.addLayout(heading)
        tools = QHBoxLayout(); tools.setSpacing(8)
        self.search = QLineEdit(); self.search.setFixedHeight(42); self.search.setPlaceholderText("搜索项目、分类或 Codex 对话"); self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.render); tools.addWidget(self.search, 1)
        self.status_filter = QComboBox(); self.status_filter.setFixedSize(132, 42); self.status_filter.setAccessibleName("项目状态筛选")
        for label, value in (("全部状态", "all"), ("运行中", "running"), ("已完成", "completed"), ("已关联", "linked"), ("未关联", "unlinked")):
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self.render); tools.addWidget(self.status_filter)
        self.scope_filter = QComboBox(); self.scope_filter.setFixedSize(148, 42); self.scope_filter.setAccessibleName("项目管理筛选")
        self.scope_filter.setToolTip("战略重点是人工决策；实际推进来自进行中任务和运行中的 Codex 对话")
        for label, value in (("全部项目", "all"), ("战略重点", "strategic_focus"), ("实际推进", "executing"), ("项目变化", "review"), ("风险与阻塞", "attention"), ("阻塞项目", "blocked"), ("需要下一步", "needs_next"), ("暂缓与想法", "paused")):
            self.scope_filter.addItem(label, value)
        self.scope_filter.currentIndexChanged.connect(self.render); self.scope_filter.hide()
        self.project_result_count = QLabel("0 个项目"); self.project_result_count.setFixedWidth(76); self.project_result_count.setAlignment(Qt.AlignCenter)
        self.project_result_count.setStyleSheet("color: #66758a; background: #eef2f6; border: none; border-radius: 8px; padding: 7px 5px; font-size: 11px; font-weight: 650;"); tools.addWidget(self.project_result_count)
        refresh = QToolButton(); refresh.setFixedSize(42, 42); refresh.setIcon(fluent_icon("\uE72C", color="#42526a")); refresh.setIconSize(QSize(16, 16)); refresh.setToolTip("刷新项目与 Codex 状态")
        refresh.setStyleSheet("QToolButton { background: #ffffff; border: 1px solid #d5dee9; border-radius: 9px; } QToolButton:hover { background: #f1f5fa; border-color: #9fb6d0; }")
        refresh.clicked.connect(self.refresh); tools.addWidget(refresh); main_layout.addLayout(tools)
        self.project_content = QStackedWidget(); self.project_content.setStyleSheet("background: transparent;")
        self.mind_map = ProjectMindMap(self); self.project_content.addWidget(self.mind_map)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setStyleSheet("QScrollArea { background: transparent; }"); self.list_widget = QWidget(); self.list_widget.setStyleSheet("background: transparent;"); self.list = QVBoxLayout(self.list_widget); self.list.setContentsMargins(0, 8, 8, 0); self.list.setSpacing(6); self.scroll.setWidget(self.list_widget); self.project_content.addWidget(self.scroll)
        main_layout.addWidget(self.project_content, 1)
        return main

    def build_home_page(self):
        page = QWidget(); page.setObjectName("homePage"); page.setStyleSheet("QWidget#homePage { background: #f5f7fb; }"); outer = QVBoxLayout(page); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); self.home_scroll = scroll; scroll.setWidgetResizable(True); scroll.setStyleSheet("QScrollArea { background: #f5f7fb; }")
        content = QWidget(); content.setObjectName("homeContent")
        content.setStyleSheet("QWidget#homeContent { background: #f5f7fb; } QWidget#homeContent QLabel { background: transparent; }")
        layout = QVBoxLayout(content); layout.setContentsMargins(32, 26, 28, 26); layout.setSpacing(16); scroll.setWidget(content); outer.addWidget(scroll)

        heading = QHBoxLayout(); heading.setSpacing(14)
        heading_text = QVBoxLayout(); heading_text.setSpacing(2)
        title = QLabel("今日工作台"); title.setStyleSheet("font-size: 29px; font-weight: 720; color: #172033; letter-spacing: 0.1px;"); heading_text.addWidget(title)
        date_text = datetime.now().strftime("%Y年%m月%d日  %A").replace("Monday", "星期一").replace("Tuesday", "星期二").replace("Wednesday", "星期三").replace("Thursday", "星期四").replace("Friday", "星期五").replace("Saturday", "星期六").replace("Sunday", "星期日")
        date = QLabel(date_text); date.setStyleSheet("color: #66758a; font-size: 13px; font-weight: 500;"); heading_text.addWidget(date); heading.addLayout(heading_text); heading.addStretch()
        new_task = QPushButton("新建任务"); new_task.setIcon(fluent_icon("\uE710", color="#ffffff", size=16)); new_task.setIconSize(QSize(16, 16)); new_task.setObjectName("primary"); new_task.setFixedHeight(42); new_task.clicked.connect(self.new_today_task); heading.addWidget(new_task); layout.addLayout(heading)

        self.daily_summary_panel = ClickableFrame(); self.daily_summary_panel.setObjectName("dailySummaryPanel")
        self.daily_summary_panel.setAccessibleName("打开昨日工作总结")
        self.daily_summary_panel.setToolTip("点击查看昨日工作的完整总结")
        self.daily_summary_panel.setStyleSheet("QFrame#dailySummaryPanel { background: #ffffff; border: 1px solid #d8e1eb; border-left: 4px solid #2563eb; border-radius: 12px; } QFrame#dailySummaryPanel:hover, QFrame#dailySummaryPanel:focus { background: #fbfdff; border-color: #a9bfdf; border-left-color: #1d4ed8; }")
        self.daily_summary_panel.clicked.connect(self.show_daily_summary_dialog)
        summary_layout = QVBoxLayout(self.daily_summary_panel); summary_layout.setContentsMargins(16, 10, 14, 10); summary_layout.setSpacing(4)
        summary_head = QHBoxLayout(); summary_head.setSpacing(9)
        summary_icon = QLabel(); summary_icon.setAttribute(Qt.WA_TransparentForMouseEvents); summary_icon.setFixedSize(24, 24); summary_icon.setAlignment(Qt.AlignCenter); summary_icon.setPixmap(fluent_icon("\uE81C", color="#1d4ed8", size=15).pixmap(QSize(15, 15))); summary_icon.setStyleSheet("background: #eaf1ff; border-radius: 7px;"); summary_head.addWidget(summary_icon)
        summary_title = QLabel("昨日回顾"); summary_title.setAttribute(Qt.WA_TransparentForMouseEvents); summary_title.setStyleSheet("color: #253247; font-size: 14px; font-weight: 700;"); summary_head.addWidget(summary_title)
        self.daily_summary_date_label = QLabel(); self.daily_summary_date_label.setAttribute(Qt.WA_TransparentForMouseEvents); self.daily_summary_date_label.setStyleSheet("color: #748094; font-size: 10px;"); summary_head.addWidget(self.daily_summary_date_label)
        summary_head.addStretch()
        self.daily_summary_state = QLabel("等待总结"); self.daily_summary_state.setAlignment(Qt.AlignCenter); self.daily_summary_state.setFixedHeight(26)
        self.daily_summary_state.setStyleSheet("color: #526071; background: #eef2f6; border-radius: 8px; padding: 2px 9px; font-size: 10px; font-weight: 650;"); summary_head.addWidget(self.daily_summary_state)
        summary_chevron = QLabel(); summary_chevron.setAttribute(Qt.WA_TransparentForMouseEvents); summary_chevron.setFixedSize(18, 18); summary_chevron.setPixmap(fluent_icon("\uE76C", color="#64748b", size=13).pixmap(QSize(13, 13))); summary_chevron.setAlignment(Qt.AlignCenter); summary_head.addWidget(summary_chevron)
        summary_layout.addLayout(summary_head)
        self.daily_summary_overview = QLabel("软件将在每天首次打开时，用固定 Codex 任务总结前一天的工作记录。")
        self.daily_summary_overview.setAttribute(Qt.WA_TransparentForMouseEvents); self.daily_summary_overview.setWordWrap(False); self.daily_summary_overview.setMaximumHeight(22); self.daily_summary_overview.setStyleSheet("color: #42526a; font-size: 12px;"); summary_layout.addWidget(self.daily_summary_overview)
        self.daily_summary_meta = QLabel("点击查看完整回顾"); self.daily_summary_meta.hide()
        layout.addWidget(self.daily_summary_panel)

        board_head = QHBoxLayout(); board_head.setSpacing(9)
        board_icon = QLabel(); board_icon.setFixedSize(26, 26); board_icon.setPixmap(fluent_icon("\uE9D2", color="#176cff", size=19).pixmap(QSize(19, 19))); board_icon.setAlignment(Qt.AlignCenter); board_head.addWidget(board_icon)
        self.task_board_title = QLabel("今日任务规划"); self.task_board_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #172033;"); board_head.addWidget(self.task_board_title)
        self.task_summary = QLabel(); self.task_summary.setStyleSheet("color: #66758a; font-size: 12px;"); board_head.addWidget(self.task_summary)
        board_head.addStretch()
        self.task_tools_button = QToolButton(); self.task_tools_button.setFixedSize(36, 36)
        self.task_tools_button.setIcon(fluent_icon("\uE712", color="#526071", size=16)); self.task_tools_button.setIconSize(QSize(16, 16))
        self.task_tools_button.setToolTip("任务记录与回收站"); self.task_tools_button.setAccessibleName("更多任务工具")
        self.task_tools_button.setStyleSheet("QToolButton { background: #ffffff; border: 1px solid #d5dee9; border-radius: 9px; } QToolButton:hover, QToolButton:focus { background: #f1f5fa; border-color: #9fb6d0; }")
        task_tools_menu = QMenu(self.task_tools_button)
        history_action = task_tools_menu.addAction(fluent_icon("\uE81C", color="#24588f", size=14), "任务记录")
        history_action.triggered.connect(lambda: self.show_task_history(0))
        self.task_archive_action = task_tools_menu.addAction(fluent_icon("\uE74D", color="#526071", size=14), "任务回收站")
        self.task_archive_action.triggered.connect(self.show_task_archive)
        task_tools_menu.addSeparator()
        self.task_link_repair_action = task_tools_menu.addAction(fluent_icon("\uE71B", color="#315f9b", size=14), "修复任务关联")
        self.task_link_repair_action.triggered.connect(self.show_task_link_repair); self.task_link_repair_action.setVisible(False)
        self.task_tools_button.setMenu(task_tools_menu); self.task_tools_button.setPopupMode(QToolButton.InstantPopup); board_head.addWidget(self.task_tools_button)
        self.board_date_field = QDateEdit(QDate.currentDate()); self.board_date_field.setCalendarPopup(True); self.board_date_field.setDisplayFormat("yyyy年MM月dd日"); self.board_date_field.setFixedSize(150, 36); self.board_date_field.dateChanged.connect(lambda _date: self.render_today_tasks()); board_head.addWidget(self.board_date_field)
        today_button = QPushButton("今天"); today_button.setFixedHeight(36); today_button.clicked.connect(lambda: self.board_date_field.setDate(QDate.currentDate())); board_head.addWidget(today_button); layout.addLayout(board_head)

        self.task_board = QWidget(); self.task_board.setObjectName("taskBoard"); self.task_board.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.task_board_layout = QHBoxLayout(self.task_board); self.task_board_layout.setContentsMargins(0, 0, 0, 0); self.task_board_layout.setSpacing(11); layout.addWidget(self.task_board)
        layout.addStretch()
        self.render_daily_summary()
        self.render_today_tasks()
        return page

    def select_section(self, section):
        self.section = section
        self.pages.setCurrentWidget(self.home_page if section == "home" else self.projects_page)
        for button, active in ((self.home_nav_button, section == "home"), (self.project_nav_button, section == "projects")):
            button.setProperty("active", active); button.style().unpolish(button); button.style().polish(button)
        if hasattr(self, "nav"):
            self.render_nav()

    def open_project_scope(self, scope):
        if scope == "focus_capacity":
            self.show_focus_capacity()
            return
        if scope == "attention":
            self.show_risk_response_queue()
            return
        if scope == "review":
            self.show_portfolio_review_queue()
            return
        if scope == "needs_next":
            self.show_next_step_decision_queue()
            return
        if scope == "focus":
            scope = "strategic_focus"
        if scope not in {"strategic_focus", "executing", "attention", "review", "needs_next"}:
            return
        self.category = "全部"
        for control in (self.search, self.status_filter, self.scope_filter):
            control.blockSignals(True)
        self.search.clear()
        self.status_filter.setCurrentIndex(max(0, self.status_filter.findData("all")))
        self.scope_filter.setCurrentIndex(max(0, self.scope_filter.findData(scope)))
        for control in (self.search, self.status_filter, self.scope_filter):
            control.blockSignals(False)
        self.select_section("projects")
        self.render_nav(); self.render()

    def portfolio_review_queue(self):
        """Return only reviews not already owned by a more specific management decision."""
        projects = MainWindow.project_decision_routing(self)["queues"].get("review", [])
        return sorted(projects, key=project_confirmation_sort_key)

    def project_decision_routing(self):
        """Give every project one primary action owner while preserving raw portfolio facets."""
        groups = portfolio_decision_groups(self.projects)
        alignments = list(self.execution_alignment_queue() or [])
        lifecycle_items = list(self.lifecycle_calibration_queue() or [])
        focus_provider = getattr(self, "focus_commitment_queue", None)
        focus_commitments = list(focus_provider() or []) if callable(focus_provider) else []
        return route_project_decision_queues((
            ("attention", groups.get("attention", [])),
            ("alignment", alignments),
            ("lifecycle", lifecycle_items),
            ("needs_next", groups.get("needs_next", [])),
            ("focus_commitment", focus_commitments),
            ("review", groups.get("review", [])),
        ))

    def open_project_decision_queue(self, queue_name):
        """Open the exact workflow represented by a portfolio decision-distribution item."""
        actions = {
            "attention": self.show_risk_response_queue,
            "alignment": self.show_execution_alignment_queue,
            "lifecycle": self.show_lifecycle_calibration,
            "needs_next": self.show_next_step_decision_queue,
            "focus_commitment": self.show_focus_capacity,
            "review": self.show_portfolio_review_queue,
        }
        action = actions.get(str(queue_name or ""))
        if action is None:
            return False
        action()
        return True

    def project_command_for(self, project, routing=None):
        """Use the same primary decision in portfolio rows and the project workbench."""
        routing = routing or self.project_decision_routing()
        primary = primary_project_decision(project, routing)
        today = QDate.currentDate().toString(Qt.ISODate)
        return project_workbench_command(project, self.today_tasks, today, primary)

    def risk_response_queue(self):
        return sorted(
            portfolio_decision_groups(self.projects).get("attention", []),
            key=project_risk_priority_key,
        )

    def next_step_decision_queue(self):
        return MainWindow.project_decision_routing(self)["queues"].get("needs_next", [])

    def show_next_step_decision_queue(self):
        projects = self.next_step_decision_queue()
        if not projects:
            QMessageBox.information(self, "项目下一步已明确", "当前所有活跃项目都已有可执行下一步。")
            return
        PortfolioReviewDialog(
            self,
            projects[:PROJECT_REVIEW_BATCH_SIZE],
            total_count=len(projects),
            purpose="next_step",
        ).exec_()

    def show_risk_response_queue(self):
        projects = self.risk_response_queue()
        if not projects:
            QMessageBox.information(self, "当前没有风险项目", "当前没有已确认的阻塞或需关注项目。")
            return
        PortfolioRiskDialog(self, projects).exec_()

    def show_portfolio_review_queue(self):
        projects = self.portfolio_review_queue()
        if not projects:
            QMessageBox.information(self, "暂无项目变化", "当前没有缺少必要信息或关键决策发生变化的项目。")
            return
        PortfolioReviewDialog(
            self,
            projects[:PROJECT_REVIEW_BATCH_SIZE],
            total_count=len(projects),
        ).exec_()

    def show_focus_capacity(self):
        FocusCapacityDialog(self).exec_()

    def update_portfolio_focus_capacity(self, value):
        capacity = save_portfolio_focus_capacity(value)
        self.render_portfolio_decisions()
        self.statusBar().showMessage(f"战略重点容量已调整为 {capacity} 项", 3200)
        return capacity

    def set_project_focus_priority(self, project, enabled):
        data = {
            "priority": "focus" if enabled else "normal",
            "stage": project_stage_key(project),
            "health": project_health_key(project),
            "status": project.get("status", "active"),
            "category": project.get("category", "未分类"),
            "objective": project.get("objective", ""),
            "nextStep": project.get("nextStep", ""),
            "blocker": project.get("blocker", ""),
        }
        result = self.update_project_management(project, data, notify=False, source="focus")
        if result is None:
            self.statusBar().showMessage("没有成功调整项目重点，请确认项目仍然存在", 3600)
            return False
        action = "设为战略重点" if enabled else "移出战略重点"
        self.statusBar().showMessage(f"{project.get('name') or '项目'}已{action}，并写入决策记录", 3600)
        return True

    def lifecycle_calibration_queue(self):
        return portfolio_lifecycle_calibration_queue(
            self.projects, self.today_tasks, inactivity_days=portfolio_inactivity_days()
        )

    def show_lifecycle_calibration(self):
        queue_items = self.actionable_lifecycle_calibration_queue()
        if not queue_items:
            QMessageBox.information(self, "组合已校准", "当前没有达到静默阈值且仍需确认的活跃项目。")
            return
        LifecycleCalibrationDialog(self, queue_items).exec_()

    def update_portfolio_inactivity_days(self, value):
        days = save_portfolio_inactivity_days(value)
        self.render_portfolio_decisions()
        self.statusBar().showMessage(f"活跃组合静默阈值已调整为 {days} 天", 3200)
        return days

    def pause_project_from_calibration(self, project):
        if open_project_tasks(self.today_tasks, project):
            self.statusBar().showMessage("此项目仍有未完成任务，请先处理任务再暂缓", 3600)
            return False
        data = {
            "priority": "later",
            "stage": project_stage_key(project),
            "health": project_health_key(project),
            "status": "paused",
            "category": project.get("category", "未分类"),
            "objective": project.get("objective", ""),
            "nextStep": project.get("nextStep", ""),
            "blocker": project.get("blocker", ""),
        }
        result = self.update_project_management(project, data, notify=False, source="calibration")
        if result is None:
            return False
        self.statusBar().showMessage(f"{project.get('name') or '项目'}已暂缓；资料、文件和 Codex 对话均保留", 4000)
        return True

    def running_codex_session_ids(self):
        return {
            str(conversation.get("sessionId"))
            for project in self.projects
            for conversation in project.get("conversations", [])
            if conversation.get("sessionId") and codex_state(conversation)[0] == "running"
        }

    def task_wip_state(self, target_date=None):
        target_date = target_date or QDate.currentDate().toString(Qt.ISODate)
        return task_wip_capacity_state(
            self.today_tasks, target_date, task_wip_limit(), self.running_codex_session_ids()
        )

    def show_task_wip(self):
        target_date = QDate.currentDate().toString(Qt.ISODate)
        TaskWipDialog(self, target_date).exec_()

    def planning_backlog(self):
        today = QDate.currentDate().toString(Qt.ISODate)
        return overdue_planned_tasks(self.today_tasks, today)

    def show_planning_backlog(self):
        tasks = self.planning_backlog()
        if not tasks:
            QMessageBox.information(self, "计划已清晰", "当前没有遗留在过去日期的未启动计划。")
            return
        PlanningBacklogDialog(self).exec_()

    def reschedule_planned_task(self, task, target_date=None):
        current = next(
            (item for item in self.today_tasks if str(item.get("id") or "") == str((task or {}).get("id") or "")),
            None,
        )
        target = target_date or QDate.currentDate().toString(Qt.ISODate)
        occurred_at = datetime.now().isoformat(timespec="seconds")
        movement = reschedule_task_date(
            self.today_tasks, (current or {}).get("id"), target, occurred_at, "planning_review"
        )
        if not movement.get("changed"):
            self.statusBar().showMessage("任务已经发生变化，无法按原计划重新安排", 3400)
            return False
        save_json(TASKS_FILE, self.today_tasks)
        target_qdate = QDate.fromString(target, Qt.ISODate)
        if target_qdate.isValid() and hasattr(self, "board_date_field"):
            self.board_date_field.setDate(target_qdate)
        self.view_signature = None
        self.render_today_tasks(); self.render_portfolio_decisions()
        self.offer_task_schedule_undo(
            current, movement.get("previousDate"), movement.get("targetDate"), occurred_at
        )
        self.statusBar().showMessage(f"“{current.get('title') or '任务'}”已移到今天，并保留原计划日期", 3800)
        return True

    def update_task_wip_limit(self, value):
        limit = save_task_wip_limit(value)
        self.render_today_tasks()
        self.statusBar().showMessage(f"进行中任务容量已调整为 {limit} 项", 3200)
        return limit

    def task_link_project_catalog(self):
        active = list(self.projects)
        active_references = {reference for project in active for reference in project_reference_ids(project)}
        archived = [
            {**project, "_archived": True}
            for project in self.archived_projects()
            if not (project_reference_ids(project) & active_references)
        ]
        return active + archived

    def task_link_issues(self):
        return task_project_link_issues(self.today_tasks, self.task_link_project_catalog())

    def show_task_link_repair(self):
        issues = self.task_link_issues()
        if not issues:
            QMessageBox.information(self, "关联完整", "当前任务都已关联到可识别的项目。")
            return
        dialog = TaskLinkRepairDialog(self, issues, self.task_link_project_catalog())
        if dialog.exec_() == QDialog.Accepted:
            self.repair_task_project_links(dialog.value())

    def repair_task_project_links(self, selections, source="manual_repair", occurred_at=None):
        task_index = {str(task.get("id") or ""): task for task in self.today_tasks}
        project_index = {str(project.get("id") or ""): project for project in self.task_link_project_catalog()}
        repaired = []
        timestamp = occurred_at or datetime.now().isoformat(timespec="seconds")
        for task_id, project_id in selections or []:
            task = task_index.get(str(task_id or ""))
            project = project_index.get(str(project_id or ""))
            if assign_task_project(task, project, timestamp, source):
                repaired.append(task)
        if not repaired:
            self.statusBar().showMessage("没有产生关联变化，请重新确认所选项目", 3200)
            return 0
        save_json(TASKS_FILE, self.today_tasks)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage(f"已修复 {len(repaired)} 条任务项目关联，并保留关联历史", 4200)
        return len(repaired)

    def defer_task_from_wip(self, task):
        current = next((item for item in self.today_tasks if str(item.get("id") or "") == str((task or {}).get("id") or "")), None)
        if current is None or current.get("status", "planned") != "doing":
            return False
        if str(current.get("sessionId") or "") in self.running_codex_session_ids():
            self.statusBar().showMessage("Codex 正在执行此任务，暂不能移回计划", 3600)
            return False
        changed = self.move_task_on_board(current.get("id"), "planned", None, source="wip")
        if changed:
            state = self.task_wip_state(current.get("date"))
            message = "进行中容量已恢复" if not state["overBy"] else f"仍超出 WIP 容量 {state['overBy']} 项"
            self.statusBar().showMessage(f"任务已移回计划；{message}", 3600)
        return changed

    def execution_alignment_queue(self):
        today = QDate.currentDate().toString(Qt.ISODate)
        return portfolio_execution_alignment_queue(self.projects, self.today_tasks, today)

    def focus_commitment_queue(self):
        return portfolio_focus_commitment_queue(self.projects, self.today_tasks)

    def actionable_execution_alignment_queue(self):
        return self.project_decision_routing()["queues"].get("alignment", [])

    def actionable_lifecycle_calibration_queue(self):
        return self.project_decision_routing()["queues"].get("lifecycle", [])

    def actionable_focus_commitment_queue(self):
        return self.project_decision_routing()["queues"].get("focus_commitment", [])

    def open_portfolio_priority_decision(self):
        scope = str(getattr(self, "_portfolio_priority_scope", "") or "")
        if scope == "attention":
            self.show_risk_response_queue()
        elif scope == "task_wip":
            self.show_task_wip()
        elif scope == "completion_evidence":
            self.show_completion_evidence_queue()
        elif scope == "plan_backlog":
            self.show_planning_backlog()
        elif scope == "alignment":
            self.show_execution_alignment_queue()
        elif scope == "lifecycle":
            self.show_lifecycle_calibration()
        elif scope == "focus_commitment":
            self.show_focus_capacity()
        elif scope:
            self.open_project_scope(scope)

    def show_execution_alignment_queue(self):
        alignments = self.actionable_execution_alignment_queue()
        if not alignments:
            QMessageBox.information(self, "执行方向已对齐", "当前进行中的任务与项目下一步没有待确认差异。")
            return
        ExecutionAlignmentDialog(self, alignments).exec_()

    def render_portfolio_decisions(self):
        if not hasattr(self, "portfolio_decision_cards"):
            return
        groups = portfolio_decision_groups(self.projects)
        routing = self.project_decision_routing()
        groups["attention"] = routing["queues"].get("attention", [])
        groups["review"] = sorted(routing["queues"].get("review", []), key=project_confirmation_sort_key)
        groups["needs_next"] = routing["queues"].get("needs_next", [])
        prefixes = {"attention": "风险处置", "review": "项目变化", "needs_next": "等待决策"}
        capacity_state = portfolio_focus_capacity_state(self.projects, portfolio_focus_capacity())
        focus_commitments = routing["queues"].get("focus_commitment", [])
        for scope, controls in self.portfolio_decision_cards.items():
            if scope == "focus_capacity":
                strategic = capacity_state["strategic"]
                executing = capacity_state["executing"]
                controls["count"].setText(f"{len(strategic)}/{capacity_state['capacity']}")
                if capacity_state["overBy"]:
                    summary = f"超出 {capacity_state['overBy']} 项 · {len(executing)} 项实际推进"
                elif capacity_state["executionOutsideFocus"]:
                    summary = portfolio_focus_guidance(capacity_state)
                elif focus_commitments:
                    summary = f"{len(focus_commitments)} 项重点下一步待落地"
                elif strategic:
                    summary = "重点已落地" + (f" · 可增加 {capacity_state['remaining']} 项" if capacity_state["remaining"] else "")
                else:
                    summary = f"尚未选择重点 · {len(executing)} 项实际推进"
                strategic_names = [str(project.get("name") or "未命名项目") for project in strategic]
                executing_names = [str(project.get("name") or "未命名项目") for project in executing]
                tooltip_lines = [f"战略重点 {len(strategic)} / {capacity_state['capacity']}"]
                tooltip_lines.extend(f"• {name}" for name in strategic_names[:8])
                tooltip_lines.append(f"实际推进 {len(executing)} 项")
                tooltip_lines.extend(f"• {name}" for name in executing_names[:8])
                if focus_commitments:
                    tooltip_lines.append(f"下一步待落地 {len(focus_commitments)} 项")
                    tooltip_lines.extend(f"• {(item.get('project') or {}).get('name') or '未命名项目'}" for item in focus_commitments[:8])
                tooltip = "\n".join(tooltip_lines)
                controls["preview"].setText(summary); controls["preview"].setToolTip(tooltip); controls["frame"].setToolTip(tooltip)
                controls["frame"].setAccessibleName(f"重点容量，{len(strategic)} / {capacity_state['capacity']}；{len(executing)} 项实际推进。{summary}")
                continue
            projects = groups.get(scope, [])
            confirmation_workload = {
                "manual": [], "manualCount": 0, "batch": [], "batchCount": 0,
            }
            manual_projects = []
            batch_projects = []
            if scope == "review":
                confirmation_counts = project_confirmation_counts(projects)
                confirmation_workload = project_confirmation_workload(
                    projects,
                    self.today_tasks,
                    QDate.currentDate().toString(Qt.ISODate),
                )
                manual_projects = confirmation_workload["manual"]
                batch_projects = confirmation_workload["batch"]
                if manual_projects:
                    review_caption = "需你确认"
                elif batch_projects:
                    review_caption = "首次基线"
                else:
                    review_caption = project_confirmation_caption(confirmation_counts)
                controls["caption"] = review_caption
                controls["title"].setText(review_caption)
                prefixes["review"] = review_caption
            routed_to = routing.get("routedTo", {}).get(scope, {})
            route_labels = {
                "attention": "风险与阻塞", "alignment": "执行校准", "lifecycle": "生命周期",
                "needs_next": "待定下一步", "focus_commitment": "重点落地", "review": "项目变化",
            }
            routed_summary = "、".join(
                f"{route_labels.get(owner, owner)} {count}"
                for owner, count in routed_to.items()
            )
            visible_count = (
                confirmation_workload["manualCount"]
                if scope == "review" and confirmation_workload["manualCount"]
                else confirmation_workload["batchCount"]
                if scope == "review" and confirmation_workload["batchCount"]
                else len(projects)
            )
            controls["count"].setText(str(visible_count))
            if projects:
                preview_projects = (
                    manual_projects
                    if scope == "review" and manual_projects
                    else projects
                )
                names = [str(project.get("name") or "未命名项目") for project in preview_projects]
                preview = "、".join(names[:2])
                if len(names) > 2:
                    preview += f" 等 {len(names)} 项"
                if scope == "review":
                    parts = []
                    if manual_projects:
                        parts.append(f"逐项判断 {len(manual_projects)}")
                    if batch_projects:
                        parts.append(f"可一次建基线 {len(batch_projects)}")
                    urgency = project_review_urgency_summary(projects)
                    if urgency:
                        parts.append(urgency)
                    summary = f"{' · '.join(parts)}：{preview}"
                else:
                    summary = f"{prefixes[scope]}：{preview}"
                if scope == "attention":
                    details = [f"• {project.get('name') or '未命名项目'}：{project_control_state(project)[4]}" for project in projects]
                elif scope == "review":
                    details = [
                        f"• {project.get('name') or '未命名项目'}：{project_control_state(project)[4]}"
                        for project in manual_projects
                    ]
                    if batch_projects:
                        batch_names = "、".join(
                            str(project.get("name") or "未命名项目")
                            for project in batch_projects[:8]
                        )
                        details.append(
                            f"• 可一次建立首次基线 {len(batch_projects)} 项：{batch_names}"
                        )
                else:
                    details = [f"• {name}" for name in names]
                tooltip = f"{prefixes[scope]}\n" + "\n".join(details)
                if routed_summary:
                    summary += f" · 另 {sum(routed_to.values())} 项已路由"
                    tooltip += f"\n由更优先决策承接：{routed_summary}"
            elif routed_summary:
                summary = f"已由更优先队列承接 · {routed_summary}"
                tooltip = f"{controls['caption']}当前无需重复处理\n由更优先决策承接：{routed_summary}"
            else:
                summary = "当前无需处理"
                tooltip = f"{controls['caption']}：当前没有项目"
            controls["preview"].setText(summary)
            controls["preview"].setToolTip(tooltip)
            controls["frame"].setToolTip(tooltip)
            controls["frame"].setAccessibleName(f"{controls['caption']}，{visible_count} 个项目。{summary}")
        if hasattr(self, "portfolio_priority_panel"):
            alignments = routing["queues"].get("alignment", [])
            lifecycle_items = routing["queues"].get("lifecycle", [])
            wip_state = self.task_wip_state(QDate.currentDate().toString(Qt.ISODate))
            overdue_tasks = self.planning_backlog()
            completion_tasks = self.completion_evidence_queue()
            decision = portfolio_priority_decision(
                groups, capacity_state, alignments, lifecycle_items,
                wip_state=wip_state, focus_commitments=focus_commitments,
                overdue_tasks=overdue_tasks, completion_tasks=completion_tasks,
            )
            self.portfolio_priority_panel.setVisible(decision is not None)
            self._portfolio_priority_scope = (decision or {}).get("scope", "")
            if decision:
                scope = decision["scope"]
                palette = {
                    "attention": ("#b54708", "#fff8ed", "#efd7b4", "#f8e7cd", "\uE7BA"),
                    "task_wip": ("#b54708", "#fff8ed", "#efd7b4", "#f8e7cd", "\uE8EF"),
                    "completion_evidence": ("#176b4d", "#f3faf7", "#c9e3d6", "#e2f3ea", "\uE73E"),
                    "plan_backlog": ("#9a6700", "#fffaf0", "#ead7ad", "#f7ebcf", "\uE787"),
                    "alignment": ("#1d4ed8", "#f5f8ff", "#c9d8ee", "#e7effc", "\uE8A7"),
                    "needs_next": ("#6d3fc0", "#f8f5ff", "#ded2f4", "#eee7fb", "\uE72A"),
                    "focus_commitment": ("#6d3fc0", "#f8f5ff", "#ded2f4", "#eee7fb", "\uE9D2"),
                    "focus_capacity": ("#6d3fc0", "#f8f5ff", "#ded2f4", "#eee7fb", "\uE8D4"),
                    "review": ("#315f9b", "#f6f9fd", "#cfdae8", "#e7eef7", "\uE81C"),
                    "lifecycle": ("#315f9b", "#f7f9fc", "#d2dce8", "#e7eef7", "\uE823"),
                }
                color, background, border, icon_background, glyph = palette[scope]
                self.portfolio_priority_panel.setStyleSheet(
                    f"QFrame#portfolioPriorityPanel {{ background: {background}; border: 1px solid {border}; border-left: 4px solid {color}; border-radius: 11px; }}"
                    f"QFrame#portfolioPriorityPanel:hover, QFrame#portfolioPriorityPanel:focus {{ background: #ffffff; border-color: {color}; }}"
                )
                self.portfolio_priority_icon.setPixmap(fluent_icon(glyph, color=color, size=17).pixmap(QSize(17, 17)))
                self.portfolio_priority_icon.setStyleSheet(f"background: {icon_background}; border-radius: 9px;")
                self.portfolio_priority_title.setText(decision["title"])
                self.portfolio_priority_title.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: 720;")
                summary_text = decision["summary"]
                if decision.get("secondary"):
                    summary_text += f"  ·  后续：{decision['secondary']}"
                self.portfolio_priority_summary.setText(summary_text)
                outcome_text = f"完成标准：{decision['outcome']}"
                self.portfolio_priority_outcome.setText(outcome_text)
                self.portfolio_priority_outcome.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 650; border: none;")
                self.portfolio_priority_count.setText(str(decision["count"]))
                self.portfolio_priority_count.setStyleSheet(f"color: {color}; background: #ffffff; border: 1px solid {border}; border-radius: 8px; font-size: 12px; font-weight: 750;")
                self.portfolio_priority_action.setText(f"{decision['action']}  →")
                self.portfolio_priority_action.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700;")
                tooltip = decision["title"] + "\n" + "\n".join(f"• {name}" for name in decision["names"])
                tooltip += f"\n完成标准：{decision['outcome']}"
                if decision.get("secondaryFull"):
                    tooltip += f"\n后续队列：{decision['secondaryFull']}"
                self.portfolio_priority_summary.setToolTip(tooltip)
                self.portfolio_priority_outcome.setToolTip(tooltip)
                self.portfolio_priority_panel.setToolTip(tooltip)
                self.portfolio_priority_panel.setAccessibleName(
                    f"下一项管理决策：{decision['title']}，{decision['count']} 项。{summary_text}。{outcome_text}"
                )

    def refresh(self, silent=False, scan=True):
        task_board_dirty = False
        categories = load_categories()
        if categories != self.categories:
            self.categories = categories
            self.view_signature = None
            if self.category not in self.categories:
                self.category = "全部"
        project_layout = load_project_layout()
        if project_layout != self.project_layout:
            self.project_layout = project_layout
            self.view_signature = None
        stored_tasks = load_json(TASKS_FILE, [])
        tasks, rolled_over = rollover_in_progress_tasks(stored_tasks)
        rollover_count = max(0, len(tasks) - len(stored_tasks))
        if rolled_over:
            save_json(TASKS_FILE, tasks)
        if tasks != self.today_tasks:
            self.today_tasks = tasks
            task_board_dirty = True
        stored_summaries = load_json(DAILY_SUMMARIES_FILE, [])
        if isinstance(stored_summaries, list) and stored_summaries != self.daily_summaries:
            self.daily_summaries = stored_summaries
            self.render_daily_summary()
        stored_decisions = load_json(PROJECT_DECISIONS_FILE, [])
        if isinstance(stored_decisions, list) and stored_decisions != self.project_decisions:
            self.project_decisions = stored_decisions
        self.saved_projects = load_json(PROJECTS_FILE, [])
        self.projects = visible_project_catalog(self.saved_projects, self.project_layout)
        snapshot_updates = reconcile_task_project_snapshots(self.today_tasks, self.projects)
        category_updates = reconcile_task_project_categories(self.today_tasks, self.managed_project_catalog())
        if snapshot_updates or category_updates:
            save_json(TASKS_FILE, self.today_tasks)
            task_board_dirty = True
        events = self.live_sessions
        conversations = conversations_by_project(events)
        for project in self.projects:
            project["conversations"] = conversations.get(project["id"], [])
            project["lastActivity"] = project["conversations"][0] if project["conversations"] else None
        automatic_link_repairs = reconcile_task_project_links_from_conversations(
            self.today_tasks,
            self.projects,
            datetime.now().isoformat(timespec="seconds"),
            self.task_link_project_catalog(),
        )
        if automatic_link_repairs:
            save_json(TASKS_FILE, self.today_tasks)
            task_board_dirty = True
        self.running_count = sum(codex_state(session)[0] == "running" for project in self.projects for session in project["conversations"])
        if hasattr(self, "pulse_state_label"):
            if self.running_count:
                self.pulse_state_label.setText(f"● 活跃 · {self.running_count} 个对话运行中")
                self.pulse_state_label.setStyleSheet("color: #087443; font-size: 13px; font-weight: 700;")
            else:
                self.pulse_state_label.setText("待机 · 正在监听 Codex")
                self.pulse_state_label.setStyleSheet("color: #526071; font-size: 13px; font-weight: 650;")
        if self.auto_start_tasks_from_codex(render_board=False):
            task_board_dirty = True
        self.sync_project_workload(render_portfolio=False)
        self.start_daily_summary()
        signature = workspace_view_signature(self.projects, self.today_tasks)
        if signature != self.view_signature:
            self.view_signature = signature
            self.render_nav(); self.render()
            self.render_portfolio_decisions()
            task_board_dirty = True
        if task_board_dirty:
            self.render_today_tasks()
        if not self.scan_ready:
            self.sync.setText("●  正在同步")
        else:
            self.sync.setText(f"●  已同步 {datetime.now().strftime('%H:%M')}")
        if scan:
            self.start_session_scan()
        storage_notice = storage_recovery_notice(consume_json_recovery_events())
        if storage_notice:
            self.statusBar().showMessage(*storage_notice)
        elif automatic_link_repairs:
            self.statusBar().showMessage(f"已依据唯一 Codex 对话自动恢复 {len(automatic_link_repairs)} 条任务项目关联", 4500)
        elif rollover_count:
            self.statusBar().showMessage(f"已将 {rollover_count} 个进行中任务延续到下一天，并保留原日期记录", 4500)
        elif not silent:
            self.statusBar().showMessage("已从本地项目与 Codex 活动记录刷新", 2000)

    def start_session_scan(self):
        if self.session_scanner is not None:
            return
        now = datetime.now(timezone.utc)
        if self.last_scan_at and now - self.last_scan_at < timedelta(seconds=12):
            return
        self.last_scan_at = now
        scanner = SessionScanner(self.projects)
        scanner.scanned.connect(self.on_sessions_scanned)
        scanner.finished.connect(lambda: self.finish_session_scan(scanner))
        self.session_scanner = scanner
        scanner.start()

    def finish_session_scan(self, scanner):
        if self.session_scanner is scanner:
            self.session_scanner = None
        scanner.deleteLater()

    def on_sessions_scanned(self, sessions):
        first_sync = not self.scan_ready
        sessions = list(sessions or [])
        sessions_changed = sessions != self.live_sessions
        self.scan_ready = True
        if not first_sync and not sessions_changed:
            return
        self.live_sessions = sessions
        self.refresh(silent=True, scan=False)
        if first_sync and hasattr(self, "home_scroll") and not self.home_scroll_reset_done:
            self.home_scroll_reset_done = True
            QTimer.singleShot(80, lambda: self.home_scroll.verticalScrollBar().setValue(0))

    def running_conversations(self):
        return [
            (project, conversation)
            for project in self.projects
            for conversation in project.get("conversations", [])
            if codex_state(conversation)[0] == "running"
        ]

    def show_running_conversations(self):
        RunningConversationsDialog(self, self.running_conversations()).exec_()

    def completion_evidence_queue(self):
        return tasks_missing_completion_outcomes(self.today_tasks)

    def show_completion_evidence_queue(self):
        tasks = self.completion_evidence_queue()
        if not tasks:
            QMessageBox.information(self, "成果已完整", "当前已完成任务都有可引用的实际成果。")
            return
        TaskCompletionEvidenceDialog(self).exec_()

    @staticmethod
    def _command_action(action, title, subtitle, keywords, priority, order):
        return {
            "kind": "action",
            "key": f"action:{action}",
            "title": title,
            "subtitle": subtitle,
            "searchText": " ".join((title, subtitle, keywords)).casefold(),
            "payload": {"action": action},
            "priority": priority,
            "order": order,
        }

    def command_catalog(self):
        actions = [
            self._command_action("new_task", "新建今日任务", "建立计划并关联项目与 Codex 对话", "添加 计划", -30, 0),
            self._command_action("new_project", "新建项目", "建立项目目标、阶段和明确下一步", "添加 项目", -29, 1),
            self._command_action("task_history", "查看任务记录", "回顾每日计划、进行中和完成记录", "历史 每日", -28, 2),
            self._command_action("refresh", "刷新项目与 Codex 状态", "立即读取本地项目、任务和对话活动", "同步 更新", 90, 3),
            self._command_action("home", "切换到今日工作台", "查看昨日回顾与今日任务", "主页 首页", 91, 4),
            self._command_action("projects", "切换到项目中心", "查看分类、项目与 Codex 对话", "项目列表", 92, 5),
        ]
        if self.running_count:
            actions.append(self._command_action(
                "running", "查看运行中的 Codex 对话", f"当前有 {self.running_count} 个对话正在执行",
                "运行 工作区", 8, 6,
            ))
        completion_count = len(self.completion_evidence_queue())
        if completion_count:
            actions.append(self._command_action(
                "completion_evidence", "补齐任务完成成果", f"{completion_count} 项已完成任务尚无可验证结果",
                "成果 结果 交付 验证 补录", 6, 7,
            ))
        backlog_count = len(self.planning_backlog())
        if backlog_count:
            actions.append(self._command_action(
                "plan_backlog", "重新安排历史计划", f"{backlog_count} 项未启动计划需要确认日期",
                "改期 遗留 过期 计划债务", 7, 8,
            ))
        today = QDate.currentDate().toString(Qt.ISODate)
        return actions + build_navigation_entries(self.projects, active_task_records(self.today_tasks), today=today)

    def show_command_palette(self):
        CommandPaletteDialog(self).exec_()

    def execute_command_entry(self, entry):
        kind = str((entry or {}).get("kind") or "")
        payload = (entry or {}).get("payload") or {}
        if kind == "project":
            self.open_project_workspace(payload)
            return True
        if kind == "task":
            current = next((task for task in self.today_tasks if task.get("id") == payload.get("id")), payload)
            self.show_task_audit(current)
            return True
        if kind == "conversation":
            self.open_codex_conversation(payload)
            return True
        if kind != "action":
            return False
        action = payload.get("action")
        handlers = {
            "new_task": lambda: self.new_today_task(),
            "new_project": lambda: self.edit_project(None),
            "task_history": lambda: self.show_task_history(0),
            "refresh": lambda: self.refresh(),
            "home": lambda: self.select_section("home"),
            "projects": lambda: self.select_section("projects"),
            "running": self.show_running_conversations,
            "completion_evidence": self.show_completion_evidence_queue,
            "plan_backlog": self.show_planning_backlog,
        }
        handler = handlers.get(action)
        if handler is None:
            return False
        handler()
        return True

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
            elif child.layout(): MainWindow._clear_layout(child.layout())

    def render_nav(self):
        while self.nav.count():
            item = self.nav.takeAt(0)
            if item.widget(): item.widget().hide(); item.widget().deleteLater()
        for category in self.categories:
            count = len(self.projects) if category == "全部" else sum(item.get("category") == category for item in self.projects)
            button = SidebarCategoryButton(
                category,
                count,
                self.section == "projects" and category == self.category,
                lambda _checked=False, value=category: self.select_category(value),
            )
            self.nav.addWidget(button)

    def select_category(self, category):
        self.category = category; self.select_section("projects"); self.render_nav(); self.render()

    @staticmethod
    def format_tokens(value):
        value = int(value or 0)
        if value >= 1_000_000_000: return f"{value / 1_000_000_000:.1f}B"
        if value >= 1_000_000: return f"{value / 1_000_000:.1f}M"
        if value >= 1_000: return f"{value / 1_000:.1f}K"
        return str(value)

    def start_usage_scan(self):
        if self.usage_scanner is not None:
            return
        previous_sync = str((self.usage_data or {}).get("syncedAt") or "").strip()
        self.usage_synced_label.setText(f"正在刷新 · 上次 {previous_sync}" if previous_sync else "正在读取真实额度…")
        self.usage_synced_label.setToolTip("正在读取 Codex 官方额度并更新本地 Tokens 估算")
        scanner = UsageScanner(self); scanner.scanned.connect(self.on_usage_scanned); scanner.finished.connect(lambda: self.finish_usage_scan(scanner)); self.usage_scanner = scanner; scanner.start()

    def finish_usage_scan(self, scanner):
        if self.usage_scanner is scanner:
            self.usage_scanner = None
        scanner.deleteLater()

    def on_usage_scanned(self, data):
        data = dict(data or {})
        source = data.get("todayTokensSource")
        if "todayTokens" in data:
            self.usage_today_label.setText(self.format_tokens(data.get("todayTokens")))
            if hasattr(self, "usage_today_caption"):
                estimated = source == "local"
                self.usage_today_caption.setText("今日 Tokens*" if estimated else "今日 Tokens")
                self.usage_today_caption.setToolTip("由本地 Codex 对话日志实时估算" if estimated else "Codex 官方今日用量")
                self.usage_today_label.setToolTip(self.usage_today_caption.toolTip())
        if data.get("error"):
            previous_sync = str((self.usage_data or {}).get("syncedAt") or "").strip()
            attempted_at = str(data.get("syncedAt") or datetime.now().strftime("%H:%M"))
            if self.usage_data:
                self.usage_data = {
                    **self.usage_data,
                    "todayTokens": data.get("todayTokens", self.usage_data.get("todayTokens")),
                    "todayTokensSource": source or self.usage_data.get("todayTokensSource"),
                    "lastAttemptAt": attempted_at,
                    "lastError": str(data.get("error")),
                }
            else:
                self.usage_data = data
            status = f"额度暂不可用 · 保留 {previous_sync}" if previous_sync else f"额度暂不可用 · Tokens 已更新 {attempted_at}"
            self.usage_synced_label.setText(status)
            self.usage_synced_label.setToolTip(f"{data.get('error')}；将在 2 分钟后自动重试")
            return
        self.usage_data = data
        used = data.get("usedPercent", 0); remaining = data.get("remainingPercent", 100)
        self.usage_used_label.setText(f"{used}%"); self.usage_remaining_label.setText(f"{remaining}%")
        self.usage_reset_label.setText(data.get("resetText") or "—")
        self.usage_progress.setValue(used); plan = str(data.get("planType") or "").upper(); suffix = f" · {plan}" if plan else ""
        token_note = " · Tokens 本地估算" if source == "local" else ""
        sync_text = f"真实额度{suffix}{token_note} · {data.get('syncedAt', '')} 同步"
        self.usage_synced_label.setText(sync_text)
        self.usage_synced_label.setToolTip(sync_text)

    @staticmethod
    def daily_summary_target_date():
        return (datetime.now().date() - timedelta(days=1)).isoformat()

    def daily_summary_for_date(self, target_date=None):
        target_date = target_date or self.daily_summary_target_date()
        return next((item for item in self.daily_summaries if item.get("date") == target_date), None)

    def plan_daily_summary_suggestion(self, summary, suggestion):
        summary_date = str((summary or {}).get("date") or "").strip()
        existing = find_daily_summary_suggestion_task(self.today_tasks, summary_date, suggestion)
        if existing is not None:
            task_date = QDate.fromString(str(existing.get("date") or ""), Qt.ISODate)
            if task_date.isValid() and hasattr(self, "board_date_field"):
                self.board_date_field.setDate(task_date)
            self.render_today_tasks()
            self.statusBar().showMessage("这条总结建议已经进入任务记录，已为你定位", 3400)
            return existing
        draft, project = daily_summary_suggestion_draft(suggestion, self.projects, summary_date)
        if not draft.get("title"):
            self.statusBar().showMessage("总结建议内容为空，无法建立任务", 3000)
            return None
        draft["date"] = QDate.currentDate().toString(Qt.ISODate)
        project_id = project.get("id") if project is not None else None
        task = self.edit_today_task(None, "planned", project_id, draft=draft)
        if task is not None:
            linked_project = next(
                (candidate for candidate in self.projects if task_matches_project(task, candidate)),
                None,
            )
            link_text = f"并关联到“{linked_project.get('name')}”" if linked_project is not None else "；当前未关联项目"
            self.statusBar().showMessage(f"已从昨日总结建立今日计划{link_text}", 4000)
        return task

    def render_daily_summary(self):
        if not hasattr(self, "daily_summary_meta"):
            return
        target_date = self.daily_summary_target_date()
        thread_label = "固定 Codex 总结" if daily_summary_thread_id() else "尚未配置总结任务"
        self.daily_summary_date_label.setText(f"{target_date} · {thread_label}")
        summary = self.daily_summary_for_date(target_date)
        running = self.daily_summary_worker is not None
        if hasattr(self, "daily_summary_regenerate_button"):
            self.daily_summary_regenerate_button.setEnabled(not running)

        if running:
            self.daily_summary_state.setText("Codex 重新总结中" if summary else "Codex 总结中")
            self.daily_summary_state.setStyleSheet(
                "color: #1d4ed8; background: #eaf1ff; border-radius: 8px; padding: 2px 9px; font-size: 10px; font-weight: 650;"
            )
            self.daily_summary_overview.setText(
                compact_summary_text((summary or {}).get("overview"), 145)
                if summary else
                "正在整理昨天的任务和 Codex 活动，完成后会自动写回工作台。"
            )
            self.daily_summary_meta.setText("正在调用固定总结对话 · 完成后自动更新")
            return

        if self.daily_summary_error:
            self.daily_summary_state.setText("总结失败，可重试")
            self.daily_summary_state.setStyleSheet("color: #b42318; background: #fff0ee; border-radius: 8px; padding: 2px 9px; font-size: 10px; font-weight: 650;")
            self.daily_summary_overview.setText(
                compact_summary_text((summary or {}).get("overview"), 145)
                if summary else
                "固定 Codex 总结任务暂时没有返回结果。"
            )
            self.daily_summary_meta.setText("上次生成失败 · 点击“重新生成”重试")
            self.daily_summary_panel.setToolTip(self.daily_summary_error)
            return

        self.daily_summary_panel.setToolTip("点击查看昨日工作的完整总结")
        if not summary:
            self.daily_summary_state.setText("等待自动总结")
            self.daily_summary_state.setStyleSheet("color: #526071; background: #eef2f6; border-radius: 8px; padding: 2px 9px; font-size: 10px; font-weight: 650;")
            self.daily_summary_overview.setText("每天首次打开软件时，会自动调用固定 Codex 任务总结昨天做了什么。")
            self.daily_summary_meta.setText("尚无昨日总结 · 可点击“重新生成”")
            return

        self.daily_summary_state.setText("已生成")
        self.daily_summary_state.setStyleSheet("color: #087443; background: #e7f7ef; border-radius: 8px; padding: 2px 9px; font-size: 10px; font-weight: 650;")
        self.daily_summary_overview.setText(compact_summary_text(summary.get("overview") or "昨天没有足够的工作记录可总结。", 145))
        counts = (
            len(summary.get("completed") or []),
            len(summary.get("inProgress") or []),
            len(summary.get("nextFocus") or []),
        )
        source_counts = summary.get("sourceCounts") if isinstance(summary.get("sourceCounts"), dict) else {}
        task_count = int(source_counts.get("tasks") or 0)
        activity_count = int(source_counts.get("codexActivities") or 0)
        decision_count = int(source_counts.get("projectDecisions") or 0)
        turn_count = int(source_counts.get("codexTurns") or 0)
        work_item_count = task_count + activity_count + decision_count
        generated_at = str(summary.get("generatedAt") or "")
        updated_text = ""
        try:
            updated_text = f" · 更新于 {datetime.fromisoformat(generated_at).strftime('%H:%M')}"
        except ValueError:
            pass
        self.daily_summary_meta.setText(
            f"覆盖 {work_item_count} 个工作项：{task_count} 项计划任务、{activity_count} 个 Codex 对话、{decision_count} 项项目决策、{turn_count} 次提问 · 完成 {counts[0]} · 进行中 {counts[1]} · 建议 {counts[2]}{updated_text}"
        )

    def start_daily_summary(self, force=False):
        target_date = self.daily_summary_target_date()
        if self.daily_summary_worker is not None:
            self.statusBar().showMessage("Codex 正在生成昨日总结", 2500)
            return
        if not force and self.daily_summary_for_date(target_date):
            return
        if not force and self.summary_attempt_date == target_date:
            return
        self.summary_attempt_date = target_date
        self.daily_summary_error = ""
        payload = build_daily_summary_payload(self.today_tasks, self.projects, target_date, self.project_decisions)
        worker = DailySummaryWorker(payload, self.projects, self, visible=force)
        worker.generated.connect(self.on_daily_summary_generated)
        worker.finished.connect(lambda: self.finish_daily_summary(worker))
        self.daily_summary_worker = worker
        self.render_daily_summary()
        if force:
            self.statusBar().showMessage("正在切换到 Codex 的固定总结对话并发送请求……", 5000)
            self.showMinimized()
            QApplication.processEvents()
        else:
            self.statusBar().showMessage("正在后台生成昨日工作总结……", 5000)
        worker.start()

    def finish_daily_summary(self, worker):
        if self.daily_summary_worker is worker:
            self.daily_summary_worker = None
        self.render_daily_summary()
        worker.deleteLater()

    def on_daily_summary_generated(self, result):
        if result.get("error"):
            self.daily_summary_error = str(result.get("error") or "未知错误")
            self.statusBar().showMessage("昨日总结生成失败，可点击“重新总结”重试", 5000)
            return
        self.daily_summary_error = ""
        self.daily_summaries = [item for item in self.daily_summaries if item.get("date") != result.get("date")]
        self.daily_summaries.append(result)
        self.daily_summaries.sort(key=lambda item: item.get("date", ""), reverse=True)
        self.daily_summaries = self.daily_summaries[:120]
        save_json(DAILY_SUMMARIES_FILE, self.daily_summaries)
        self.statusBar().showMessage("Codex 已完成昨日总结并写回工作台", 4500)

    def show_daily_summary_dialog(self):
        summary = self.daily_summary_for_date()
        if summary:
            DailySummaryDialog(self, summary).exec_()
            return
        if self.daily_summary_worker is not None:
            self.statusBar().showMessage("Codex 正在生成昨日总结，完成后可点击查看", 3000)
            return
        self.start_daily_summary(force=True)

    def open_daily_summary_thread(self):
        thread_id = daily_summary_thread_id()
        if not thread_id:
            QMessageBox.information(self, "尚未配置", "请先在本地设置中配置 Codex 每日总结任务。")
            return
        metadata = codex_thread_index().get(thread_id) or {}
        thread_title = str(metadata.get("title") or "").strip()
        if not thread_title:
            QMessageBox.warning(self, "无法打开", "没有找到固定总结任务的本地标题。")
            return
        self.showMinimized()
        QApplication.processEvents()
        QTimer.singleShot(250, lambda: self.focus_daily_summary_thread(thread_title))

    def focus_daily_summary_thread(self, thread_title):
        try:
            from codex_hub.desktop_bridge import focus_codex_thread
            focus_codex_thread(thread_title)
        except (OSError, RuntimeError) as error:
            self.showNormal()
            self.raise_()
            QMessageBox.warning(self, "无法打开", f"没有成功切换到 Codex 总结任务：\n{error}")

    def project_by_id(self, project_id):
        reference = str(project_id or "")
        if not reference:
            return None
        return next((project for project in self.projects if reference in project_reference_ids(project)), None)

    def project_decisions_for(self, project):
        references = project_reference_ids(project)
        return sorted(
            [entry for entry in self.project_decisions if str(entry.get("projectId") or "") in references],
            key=lambda entry: str(entry.get("at") or ""),
            reverse=True,
        )

    def show_project_decision_history(self, project, read_only=False):
        dialog = ProjectDecisionHistoryDialog(
            self,
            project,
            self.project_decisions_for(project),
            allow_rollback=not read_only,
        )
        dialog.exec_()
        return dialog.rolled_back

    def record_project_decision(self, project, before, after, source="manual", occurred_at=None):
        entry = build_project_decision_entry(
            project,
            before,
            after,
            source,
            occurred_at or datetime.now().isoformat(timespec="seconds"),
        )
        if entry is None:
            return None
        self.project_decisions.append(entry)
        if len(self.project_decisions) > 2000:
            self.project_decisions = self.project_decisions[-2000:]
        save_json(PROJECT_DECISIONS_FILE, self.project_decisions)
        return entry

    def record_project_lifecycle(self, project, action, occurred_at=None):
        entry = build_project_lifecycle_entry(
            project,
            action,
            occurred_at or datetime.now().isoformat(timespec="seconds"),
        )
        if entry is None:
            return None
        self.project_decisions.append(entry)
        if len(self.project_decisions) > 2000:
            self.project_decisions = self.project_decisions[-2000:]
        save_json(PROJECT_DECISIONS_FILE, self.project_decisions)
        return entry

    def record_project_closeout(self, project, action, outcome, occurred_at=None):
        entry = build_project_closeout_entry(
            project,
            action,
            outcome,
            occurred_at or datetime.now().isoformat(timespec="seconds"),
        )
        if entry is None:
            return None
        self.project_decisions.append(entry)
        if len(self.project_decisions) > 2000:
            self.project_decisions = self.project_decisions[-2000:]
        save_json(PROJECT_DECISIONS_FILE, self.project_decisions)
        return entry

    def apply_project_completion_lifecycle(self, project, before, target, requested, occurred_at, source="manual"):
        """Keep current closeout truth and immutable closeout history in sync."""
        previous_status = (before or {}).get("status", "active")
        current_status = (target or {}).get("status", "active")
        identity = project or {**(target or {}), "savedId": (target or {}).get("id")}

        def audit_identity():
            return {
                **(target or {}),
                "savedId": (target or {}).get("id") or (project or {}).get("savedId"),
                "codexProjectId": (project or {}).get("codexProjectId"),
                "name": (target or {}).get("name") or (project or {}).get("name"),
            }

        if current_status == "completed":
            requested_outcome = str((requested or {}).get("completionSummary") or "").strip()
            acceptance_objective = str(
                (requested or {}).get("completionObjectiveSnapshot")
                or (target or {}).get("objective")
                or (before or {}).get("objective")
                or ""
            ).strip()
            acceptance_criteria = str(
                (requested or {}).get("completionCriteriaSnapshot")
                or (target or {}).get("completionCriteriaSnapshot")
                or (target or {}).get("successCriteria")
                or (before or {}).get("completionCriteriaSnapshot")
                or (before or {}).get("successCriteria")
                or ""
            ).strip()
            if previous_status != "completed" and not requested_outcome:
                requested_outcome = latest_project_completion_outcome(before) or latest_project_completion_outcome(target)
            if previous_status != "completed" and not acceptance_objective:
                return False
            if previous_status != "completed":
                target.pop("completionSummary", None)
                target.pop("completedAt", None)
            changed = bool(requested_outcome) and record_project_completion_outcome(
                target,
                requested_outcome,
                occurred_at,
                "closeout" if previous_status != "completed" else source,
                acceptance_objective,
                acceptance_criteria,
            )
            for key in ("completionSummary", "completedAt", "completionHistory", "completionObjectiveSnapshot", "completionCriteriaSnapshot", "completionAcceptedAt"):
                if key in target:
                    identity[key] = target.get(key)
            if changed:
                action = "complete" if previous_status != "completed" else "revise"
                self.record_project_closeout(audit_identity(), action, requested_outcome, occurred_at)
            return previous_status == "completed" or bool(project_completion_outcome(target))
        if previous_status == "completed":
            previous_outcome = str((before or {}).get("completionSummary") or "").strip() or latest_project_completion_outcome(before)
            changed = clear_project_completion_outcome(target, occurred_at, "reopen")
            for key in ("completionSummary", "completedAt", "completionObjectiveSnapshot", "completionCriteriaSnapshot", "completionAcceptedAt"):
                identity.pop(key, None)
            if "completionHistory" in target:
                identity["completionHistory"] = target.get("completionHistory")
            if changed:
                self.record_project_closeout(audit_identity(), "reopen", previous_outcome, occurred_at)
        return True

    def record_project_review(self, project, audit=True, occurred_at=None):
        """Confirm current project state without inventing a field change."""
        gap_text = project_governance_gap_text(project)
        if gap_text:
            self.statusBar().showMessage(f"项目资料尚未完整，请先补齐：{gap_text}", 4200)
            return False
        today = QDate.currentDate().toString(Qt.ISODate)
        alignment = project_execution_alignment(project, self.today_tasks, today)
        if alignment is not None and not alignment.get("acknowledged"):
            self.statusBar().showMessage("实际执行与已保存下一步不同，请先完成执行方向校准", 4200)
            return False
        reviewed_at = occurred_at or datetime.now().isoformat(timespec="seconds")
        target = self.saved_record_for_project(project)
        baseline = establish_project_review_baseline(project, reviewed_at)
        target["reviewedAt"] = reviewed_at
        target["reviewBaseline"] = dict(baseline or {})
        entry = build_project_review_entry(project, reviewed_at) if audit else None
        if entry is not None:
            self.project_decisions.append(entry)
            if len(self.project_decisions) > 2000:
                self.project_decisions = self.project_decisions[-2000:]
            save_json(PROJECT_DECISIONS_FILE, self.project_decisions)
        save_json(PROJECTS_FILE, self.saved_projects)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage("项目变化已确认；后续没有真实变化时不会重复提醒", 4200)
        return entry or True

    def record_project_review_batch(self, projects, occurred_at=None):
        """Atomically establish several safe first baselines after one explicit choice."""
        candidates = list(projects or [])
        if len(candidates) < 2:
            self.statusBar().showMessage("批量基线至少需要 2 个可合并项目", 3200)
            return None
        today = QDate.currentDate().toString(Qt.ISODate)
        for project in candidates:
            eligible, reason = project_baseline_batch_eligibility(project, self.today_tasks, today)
            if not eligible:
                self.statusBar().showMessage(f"“{project.get('name') or '未命名项目'}”需要逐项处理：{reason}", 4200)
                return None

        reviewed_at = occurred_at or datetime.now().isoformat(timespec="seconds")
        batch_id = str(uuid.uuid4())
        prepared = []
        seen = set()
        for project in candidates:
            target = self.saved_record_for_project(project)
            stable_id = str(target.get("id") or "")
            if not stable_id or stable_id in seen:
                continue
            seen.add(stable_id)
            previous_baseline = target.get("reviewBaseline")
            prepared.append((
                project,
                target,
                stable_id,
                {
                    "reviewedAt": str(target.get("reviewedAt") or ""),
                    "reviewBaseline": dict(previous_baseline) if isinstance(previous_baseline, dict) else None,
                },
            ))
        if len(prepared) < 2:
            self.statusBar().showMessage("没有形成有效的批量基线，未保存本次操作", 3600)
            return None

        entries = []
        project_ids = []
        for project, target, stable_id, previous_review in prepared:
            baseline = establish_project_review_baseline(target, reviewed_at)
            project["reviewedAt"] = reviewed_at
            project["reviewBaseline"] = dict(baseline or {})
            audit_project = {**project, "savedId": stable_id}
            entry = build_project_review_entry(
                audit_project,
                reviewed_at,
                batch_id=batch_id,
                previous_review=previous_review,
            )
            if entry is None:
                continue
            entry["establishedReview"] = dict(baseline or {})
            entries.append(entry)
            project_ids.append(stable_id)
        self.project_decisions.extend(entries)
        if len(self.project_decisions) > 2000:
            self.project_decisions = self.project_decisions[-2000:]
        save_json(PROJECTS_FILE, self.saved_projects)
        save_json(PROJECT_DECISIONS_FILE, self.project_decisions)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage(f"已为 {len(entries)} 个项目建立首次管理基线", 4200)
        return {
            "batchId": batch_id,
            "reviewedAt": reviewed_at,
            "projectIds": project_ids,
            "count": len(entries),
        }

    def undo_project_review_batch(self, result, occurred_at=None):
        """Undo the latest untouched batch baseline while preserving an audit trail."""
        batch_id = str((result or {}).get("batchId") or "")
        if not batch_id:
            return []
        entries = [
            entry for entry in self.project_decisions
            if entry.get("kind") == "review"
            and entry.get("source") == "review"
            and str(entry.get("batchId") or "") == batch_id
        ]
        if not entries:
            return []

        prepared = []
        for entry in entries:
            project = self.project_by_id(entry.get("projectId"))
            if project is None:
                self.statusBar().showMessage("批量基线中的项目已不可用，未执行撤销", 4200)
                return []
            target = self.saved_record_for_project(project)
            expected_at = str(entry.get("at") or "")
            expected_baseline = entry.get("establishedReview") or {}
            if (
                str(target.get("reviewedAt") or "") != expected_at
                or target.get("reviewBaseline") != expected_baseline
            ):
                self.statusBar().showMessage(f"“{project.get('name') or '未命名项目'}”的基线已经更新，未执行撤销", 4200)
                return []
            prepared.append((project, target, entry))

        undone_at = occurred_at or datetime.now().isoformat(timespec="seconds")
        undo_batch_id = str(uuid.uuid4())
        restored_ids = []
        undo_entries = []
        for project, target, entry in prepared:
            previous = entry.get("previousReview") or {}
            previous_at = str(previous.get("reviewedAt") or "")
            previous_baseline = previous.get("reviewBaseline")
            if previous_at:
                target["reviewedAt"] = previous_at
                project["reviewedAt"] = previous_at
            else:
                target.pop("reviewedAt", None)
                project.pop("reviewedAt", None)
            if isinstance(previous_baseline, dict):
                target["reviewBaseline"] = dict(previous_baseline)
                project["reviewBaseline"] = dict(previous_baseline)
            else:
                target.pop("reviewBaseline", None)
                project.pop("reviewBaseline", None)
            stable_id = str(target.get("id") or entry.get("projectId") or "")
            audit_project = {**project, "savedId": stable_id}
            undo_entry = build_project_review_entry(
                audit_project,
                undone_at,
                batch_id=undo_batch_id,
                previous_review={
                    "reviewedAt": str(entry.get("at") or ""),
                    "reviewBaseline": dict(entry.get("establishedReview") or {}),
                },
                action="undo",
            )
            if undo_entry is not None:
                undo_entry["source"] = "review_undo"
                undo_entry["revertsEntryId"] = entry.get("id")
                undo_entry["revertsBatchId"] = batch_id
                undo_entries.append(undo_entry)
            restored_ids.append(stable_id)

        self.project_decisions.extend(undo_entries)
        if len(self.project_decisions) > 2000:
            self.project_decisions = self.project_decisions[-2000:]
        save_json(PROJECTS_FILE, self.saved_projects)
        save_json(PROJECT_DECISIONS_FILE, self.project_decisions)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        restored = [self.project_by_id(project_id) for project_id in restored_ids]
        restored = [project for project in restored if project is not None]
        self.statusBar().showMessage(f"已撤销 {len(restored)} 个项目的本次批量基线", 4200)
        return restored

    def acknowledge_execution_alignment(self, alignment):
        """Keep the declared next step and audit that the live divergence was reviewed."""
        project = (alignment or {}).get("project") or {}
        today = QDate.currentDate().toString(Qt.ISODate)
        current = project_execution_alignment(project, self.today_tasks, today)
        if current is None or current.get("signature") != (alignment or {}).get("signature"):
            return False
        occurred_at = datetime.now().isoformat(timespec="seconds")
        target = self.saved_record_for_project(project)
        target["executionAlignmentSignature"] = current["signature"]
        target["executionAlignmentReviewedAt"] = occurred_at
        project["executionAlignmentSignature"] = current["signature"]
        project["executionAlignmentReviewedAt"] = occurred_at
        entry = build_project_alignment_entry(project, current.get("tasks"), occurred_at)
        if entry is not None:
            self.project_decisions.append(entry)
            if len(self.project_decisions) > 2000:
                self.project_decisions = self.project_decisions[-2000:]
            save_json(PROJECT_DECISIONS_FILE, self.project_decisions)
        save_json(PROJECTS_FILE, self.saved_projects)
        self.view_signature = None; self.refresh(silent=True, scan=False)
        self.statusBar().showMessage("已保留项目原下一步，并记录本次执行方向确认", 3600)
        return True

    def adopt_execution_alignment(self, alignment, task):
        """Promote selected live work to the project's declared next step."""
        project = (alignment or {}).get("project") or {}
        today = QDate.currentDate().toString(Qt.ISODate)
        current = project_execution_alignment(project, self.today_tasks, today)
        if current is None or current.get("signature") != (alignment or {}).get("signature"):
            return False
        task_id = str((task or {}).get("id") or "")
        selected = next((item for item in current.get("tasks") or [] if str(item.get("id") or "") == task_id), None)
        if selected is None or not str(selected.get("title") or "").strip():
            return False
        data = {
            "priority": project_priority_key(project),
            "stage": project_stage_key(project),
            "health": project_health_key(project),
            "status": project.get("status", "active"),
            "category": project.get("category", "未分类"),
            "objective": project.get("objective", ""),
            "nextStep": str(selected.get("title") or "").strip(),
            "blocker": project.get("blocker", ""),
        }
        if self.update_project_management(project, data, notify=False, source="alignment") is None:
            return False
        linked_task = next((item for item in self.today_tasks if str(item.get("id") or "") == task_id), None)
        if linked_task is not None:
            linked_task["origin"] = "project_next_step"
            linked_task["projectNextStep"] = data["nextStep"]
            linked_task["updatedAt"] = datetime.now().isoformat(timespec="seconds")
            save_json(TASKS_FILE, self.today_tasks)
            self.view_signature = None; self.refresh(silent=True, scan=False)
        self.statusBar().showMessage("已将正在执行的任务设为项目下一步，并写入决策记录", 3800)
        return True

    def sync_project_workload(self, render_portfolio=True):
        """Attach today's task counts so portfolio focus reflects work that is actually moving."""
        today = QDate.currentDate().toString(Qt.ISODate)
        for project in self.projects:
            project["plannedTaskCount"] = 0
            project["activeTaskCount"] = 0
            project["completedTaskCount"] = 0
        field_by_status = {
            "planned": "plannedTaskCount",
            "doing": "activeTaskCount",
            "done": "completedTaskCount",
        }
        for task in self.today_tasks:
            if task_is_archived(task):
                continue
            if (task.get("date") or today) != today:
                continue
            project = self.project_by_id(task.get("projectId"))
            field = field_by_status.get(task.get("status", "planned"))
            if project is not None and field:
                project[field] = int(project.get(field) or 0) + 1
        if render_portfolio:
            self.render_portfolio_decisions()

    def conversation_by_id(self, session_id):
        if not session_id:
            return None
        for project in self.projects:
            for conversation in project.get("conversations", []):
                if conversation.get("sessionId") == session_id:
                    return conversation
        return None

    def auto_start_tasks_from_codex(self, render_board=True):
        today = QDate.currentDate().toString(Qt.ISODate)
        running_sessions = {
            str(conversation.get("sessionId"))
            for project in self.projects
            for conversation in project.get("conversations", [])
            if conversation.get("sessionId") and codex_state(conversation)[0] == "running"
        }
        if not running_sessions:
            return 0
        changed = []
        now = datetime.now().isoformat(timespec="seconds")
        for task in self.today_tasks:
            if task_is_archived(task):
                continue
            if task.get("status", "planned") != "planned":
                continue
            if (task.get("date") or today) != today:
                continue
            if str(task.get("sessionId") or "") not in running_sessions:
                continue
            reorder_task_board(self.today_tasks, task.get("id"), "doing", None)
            record_task_status_event(task, "planned", "doing", now, "codex")
            task["autoStartedAt"] = now
            task["updatedAt"] = now
            changed.append(task)
        if not changed:
            return 0
        save_json(TASKS_FILE, self.today_tasks)
        if render_board:
            self.render_today_tasks()
        self.statusBar().showMessage(f"检测到 Codex 已开始处理，{len(changed)} 个任务已自动移至“进行中”", 4500)
        return len(changed)

    def render_today_tasks(self):
        if not hasattr(self, "task_board_layout"):
            return
        while self.task_board_layout.count():
            item = self.task_board_layout.takeAt(0)
            if item.widget(): item.widget().hide(); item.widget().deleteLater()
        selected_date = self.board_date_field.date() if hasattr(self, "board_date_field") else QDate.currentDate()
        date_key = selected_date.toString(Qt.ISODate)
        tasks = [
            task for task in self.today_tasks
            if not task_is_archived(task)
            and (task.get("date") or QDate.currentDate().toString(Qt.ISODate)) == date_key
        ]
        title = "今日任务规划" if selected_date == QDate.currentDate() else selected_date.toString("MM月dd日任务规划")
        self.task_board_title.setText(title)
        counts = {status: sum(task.get("status") == status for task in tasks) for status in TASK_STATUS}
        self.task_summary.setText(f"{len(tasks)} 项 · {counts['doing']} 项进行中 · {counts['done']} 项完成")
        if hasattr(self, "task_link_repair_action"):
            link_issues = self.task_link_issues()
            self.task_link_repair_action.setVisible(bool(link_issues))
            self.task_link_repair_action.setText(f"修复任务关联（{len(link_issues)}）")
        if hasattr(self, "task_archive_action"):
            archived_count = len(archived_task_records(self.today_tasks))
            self.task_archive_action.setText(f"任务回收站（{archived_count}）" if archived_count else "任务回收站")
        for status, label in TASK_STATUS.items():
            accent = TASK_COLORS[status]
            surface = {"planned": "#faf8ff", "doing": "#f7faff", "done": "#f7fcf9"}.get(status, "#f8fafc")
            column = TaskDropColumn(self, status); column.setMinimumSize(250, 236); column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            column.setStyleSheet(
                f"QFrame#taskColumn {{ background: {surface}; border: 1px solid #d8e1eb; border-top: 3px solid {accent}; border-radius: 12px; }}"
                f"QFrame#taskColumn[dropActive='true'] {{ background: #eef5ff; border: 2px dashed {accent}; border-top: 3px solid {accent}; }}"
                "QFrame#taskColumn QLabel { background: transparent; }"
            )
            column_layout = QVBoxLayout(column); column_layout.setContentsMargins(12, 10, 12, 12); column_layout.setSpacing(8)
            header = QHBoxLayout(); header.setSpacing(7)
            state_icon = QLabel(); state_icon.setFixedSize(18, 18); state_icon.setPixmap(fluent_icon("\uE768", color=accent, size=14).pixmap(QSize(14, 14))); state_icon.setAlignment(Qt.AlignCenter); header.addWidget(state_icon)
            name = QLabel(label); name.setStyleSheet("font-size: 14px; font-weight: 700; color: #253247; border: none;"); header.addWidget(name); header.addStretch()
            count_text = str(counts[status])
            count_width = 24
            count_bg = accent if counts[status] else "#e1eaf6"
            count_color = "#ffffff" if counts[status] else "#637994"
            count = QLabel(count_text); count.setAlignment(Qt.AlignCenter); count.setFixedSize(count_width, 20); count.setStyleSheet(f"color: {count_color}; background: {count_bg}; font-size: 10px; font-weight: 700; border: none; border-radius: 9px;"); header.addWidget(count); column_layout.addLayout(header)
            status_tasks = ordered_board_tasks(tasks, date_key, status)
            if not status_tasks:
                empty = QLabel("暂无任务"); empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #7a8798; background: #ffffff; font-size: 11px; border: 1px dashed #cbd5e1; border-radius: 9px; padding: 20px 12px;"); column_layout.addWidget(empty)
            for task in status_tasks:
                column_layout.addWidget(TodayTaskCard(task, self))
            column_layout.addStretch(); self.task_board_layout.addWidget(column, 1, Qt.AlignTop)
        self.render_today_activity(tasks)

    def render_today_activity(self, tasks):
        if not hasattr(self, "activity_rows_layout"):
            return
        self._clear_layout(self.activity_rows_layout)
        recent = task_status_events(tasks)[:6]
        if not recent:
            empty = QLabel("当天还没有任务记录"); empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #6b809e; padding: 24px; font-size: 12px;")
            self.activity_rows_layout.addWidget(empty)
            return
        action_names = {"planned": "加入计划", "doing": "开始推进", "done": "完成任务"}
        for index, event in enumerate(recent):
            task = event.get("task") or {}
            status = event.get("to", "planned"); accent = TASK_COLORS.get(status, "#64748b")
            row = QFrame(); row.setObjectName("activityRow"); row.setFixedHeight(46)
            previous_label = TASK_STATUS.get(event.get("from"), "新建")
            row.setToolTip(f"{previous_label} → {TASK_STATUS.get(status, '更新')} · {TASK_EVENT_SOURCES.get(event.get('source'), '手动')} · {event.get('at') or '时间未知'}")
            border = "border-bottom: 1px solid #e5eaf0;" if index < len(recent) - 1 else "border: none;"
            row.setStyleSheet(f"QFrame#activityRow {{ background: transparent; {border} }} QFrame#activityRow:hover {{ background: #f5f8fc; }}")
            row_layout = QHBoxLayout(row); row_layout.setContentsMargins(8, 4, 8, 4); row_layout.setSpacing(11)
            icon = QLabel(); icon.setFixedSize(24, 24); icon.setPixmap(fluent_icon("\uE8A7", color=accent, size=15).pixmap(QSize(15, 15))); icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet(f"background: { {'planned':'#f1eaff','doing':'#e6f1ff','done':'#e4f7ed'}.get(status, '#eef4fb') }; border: 1px solid {accent}; border-radius: 6px;"); row_layout.addWidget(icon)
            kind = QLabel(action_names.get(status, "任务更新")); kind.setFixedWidth(76); kind.setStyleSheet(f"color: {accent}; font-size: 11px; font-weight: 650;"); row_layout.addWidget(kind)
            project = self.project_by_id(task.get("projectId")); project_name = task_project_identity(task, project)["name"]
            description = ElidedLabel(f"{task.get('title') or '未命名任务'}  ·  {project_name}"); description.setStyleSheet("color: #34445c; font-size: 12px;"); row_layout.addWidget(description, 1)
            source_text = TASK_EVENT_SOURCES.get(event.get("source"), "手动")
            source = QLabel(source_text); source.setStyleSheet("color: #748094; font-size: 11px;"); row_layout.addWidget(source)
            try:
                updated = datetime.fromisoformat(str(event.get("at") or "")).strftime("%H:%M")
            except ValueError:
                updated = "—"
            time_label = QLabel(updated); time_label.setFixedWidth(44); time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter); time_label.setStyleSheet("color: #53647a; font-size: 11px; font-weight: 600;"); row_layout.addWidget(time_label)
            self.activity_rows_layout.addWidget(row)

    def show_task_history(self, initial_tab=0):
        selected = self.board_date_field.date().toString(Qt.ISODate) if hasattr(self, "board_date_field") else None
        dialog = TaskHistoryDialog(self, active_task_records(self.today_tasks), selected)
        if hasattr(dialog, "tabs"):
            dialog.tabs.setCurrentIndex(max(0, min(initial_tab, dialog.tabs.count() - 1)))
        dialog.exec_()

    def show_task_audit(self, task):
        TaskAuditDialog(self, task).exec_()

    def show_task_archive(self):
        TaskArchiveDialog(self, self.today_tasks).exec_()

    def restore_archived_task(self, task):
        stored = next((item for item in self.today_tasks if item.get("id") == (task or {}).get("id")), None)
        if (stored or {}).get("origin") == "project_next_step" and not task_is_superseded_daily_record(stored):
            project = self.project_by_id(stored.get("projectId"))
            title = str(stored.get("projectNextStep") or stored.get("title") or "").strip()
            existing = find_open_project_next_step_task(self.today_tasks, project, title) if project else None
            if existing is not None and existing.get("id") != stored.get("id"):
                QMessageBox.information(
                    self,
                    "已有相同项目下一步",
                    "这个项目在原日期已经存在同名的开放任务。为避免项目行动重复，旧任务将继续保留在回收站。",
                )
                return False
        now = datetime.now().isoformat(timespec="seconds")
        if not restore_task_record(stored, now):
            return False
        reorder_task_board(self.today_tasks, stored.get("id"), stored.get("status", "planned"), None)
        save_json(TASKS_FILE, self.today_tasks)
        task_date = QDate.fromString(str(stored.get("date") or ""), Qt.ISODate)
        if task_date.isValid() and hasattr(self, "board_date_field"):
            self.board_date_field.setDate(task_date)
        self.sync_project_workload(); self.view_signature = None
        self.render_today_tasks(); self.render()
        self.statusBar().showMessage(f"“{stored.get('title', '任务')}”已恢复到原日期和状态", 3200)
        return True

    def new_today_task(self, status=None):
        self.edit_today_task(None, status if status in TASK_STATUS else "planned")

    def edit_task_outcome(self, task):
        if (task or {}).get("status") != "done":
            QMessageBox.information(self, "任务尚未完成", "完成成果只记录实际结束后的结果。请先将任务移到“已完成”。")
            return False
        dialog = TaskOutcomeDialog(self, task)
        if dialog.exec_() != QDialog.Accepted:
            return False
        now = datetime.now().isoformat(timespec="seconds")
        if not record_task_completion_outcome(task, dialog.value(), now, "outcome_editor"):
            self.statusBar().showMessage("完成成果没有变化", 2200)
            return False
        save_json(TASKS_FILE, self.today_tasks)
        self.sync_project_completion_outcome(task, now)
        self.view_signature = None
        self.render_today_tasks(); self.render()
        self.statusBar().showMessage("完成成果已记录，并纳入项目交接与每日总结", 3800)
        return True

    def edit_today_task(self, task=None, default_status=None, default_project_id=None, draft=None):
        if task_is_superseded_daily_record(task):
            self.open_current_task_record(task)
            return
        default_date = self.board_date_field.date().toString(Qt.ISODate) if hasattr(self, "board_date_field") else QDate.currentDate().toString(Qt.ISODate)
        draft = dict(draft or {})
        dialog = TaskEditor(self, self.projects, task, default_date, default_status, default_project_id, draft=draft)
        if dialog.exec_() != QDialog.Accepted:
            return
        data = dialog.value()
        if not data.get("title"):
            QMessageBox.information(self, "任务名称为空", "请输入一个清晰的任务名称。")
            return
        requested_outcome = data.pop("completionNote", "")
        now = datetime.now().isoformat(timespec="seconds")
        previous_status = task.get("status", "planned") if task is not None else None
        previous_date = task.get("date") if task is not None else None
        created = task is None
        if created:
            task = {"id": str(uuid.uuid4()), "createdAt": now}
            for key in ("origin", "sourceSummaryDate", "sourceSuggestion"):
                if draft.get(key):
                    task[key] = draft[key]
            self.today_tasks.append(task)
        task.update(data); task["updatedAt"] = now
        if not created and previous_date != task.get("date"):
            record_task_schedule_event(task, previous_date, task.get("date"), now, "editor")
        current_status = task.get("status", "planned")
        if not created and (previous_status != current_status or previous_date != task.get("date")):
            task["status"] = previous_status
            task.pop("boardOrder", None)
            reorder_task_board(self.today_tasks, task.get("id"), current_status, None)
        if created:
            source = "summary" if task.get("origin") == "daily_summary" else "manual"
            record_task_status_event(task, None, task.get("status", "planned"), now, source)
        else:
            record_task_status_event(task, previous_status, task.get("status", "planned"), now, "editor")
        current_status = task.get("status", "planned")
        outcome_changed = False
        if current_status == "done":
            outcome_changed = record_task_completion_outcome(task, requested_outcome, now, "task_editor")
        else:
            outcome_changed = clear_task_completion_outcome(task, now, "reopen")
        completed_handoff = previous_status != "done" and current_status == "done" and self.complete_project_next_step(task, now)
        reopened_handoff = previous_status == "done" and current_status != "done" and self.reopen_project_next_step(task, now, "task_reopen")
        if current_status == "done" and outcome_changed:
            self.sync_project_completion_outcome(task, now)
        save_json(TASKS_FILE, self.today_tasks)
        task_date = QDate.fromString(task.get("date", ""), Qt.ISODate)
        if task_date.isValid(): self.board_date_field.setDate(task_date)
        if completed_handoff or reopened_handoff:
            self.view_signature = None
            self.refresh(silent=True, scan=False)
            if completed_handoff:
                message = "任务已完成，成果待补录；项目已回到“需要下一步”" if not task_completion_outcome(task) else "任务已完成；项目已回到“需要下一步”，请明确后续动作"
            else:
                message = "任务已重新打开；项目下一步已同步恢复"
            self.statusBar().showMessage(message, 4500)
        else:
            self.sync_project_workload(); self.view_signature = None
            self.render_today_tasks(); self.render()
        if not created and previous_status != current_status:
            self.offer_task_undo(task, previous_status, current_status, now)
        if dialog.codex_requested and not completed_handoff and not reopened_handoff:
            self.plan_task_in_codex(task)
        elif not completed_handoff and not reopened_handoff:
            if current_status == "done" and not task_completion_outcome(task):
                message = "任务已保存；完成成果待补录"
            else:
                message = "任务与完成成果已保存" if outcome_changed and current_status == "done" else "今日任务已保存"
            self.statusBar().showMessage(message, 3000)
        return task

    def set_task_status(self, task_id, status, source="manual", allow_undo=True):
        task = next((item for item in self.today_tasks if item.get("id") == task_id), None)
        if not task_status_transition_allowed(task, status):
            return False
        return MainWindow.move_task_on_board(self, task_id, status, None, source, allow_undo)

    def open_current_task_record(self, task):
        current = current_task_record(self.today_tasks, task)
        if current is None or current is task:
            self.statusBar().showMessage("这已经是任务的最新记录", 2500)
            return False
        task_date = QDate.fromString(str(current.get("date") or ""), Qt.ISODate)
        if task_date.isValid() and hasattr(self, "board_date_field"):
            self.board_date_field.setDate(task_date)
        self.render_today_tasks()
        self.statusBar().showMessage(f"已跳转到“{current.get('title', '任务')}”的最新记录", 3200)
        return True

    def move_task_on_board(self, task_id, status, target_index=None, source="drag", allow_undo=True):
        task = next((item for item in self.today_tasks if item.get("id") == task_id), None)
        movement = reorder_task_board(self.today_tasks, task_id, status, target_index)
        if task is None or not movement.get("changed"):
            return False
        previous_status = movement.get("previousStatus", "planned")
        status_changed = previous_status != status
        now = datetime.now().isoformat(timespec="seconds")
        if status_changed:
            record_task_status_event(task, previous_status, status, now, source)
            if status != "done":
                clear_task_completion_outcome(task, now, "reopen")
        task["updatedAt"] = now
        completed_handoff = status_changed and previous_status != "done" and status == "done" and self.complete_project_next_step(task, now)
        reopened_handoff = status_changed and previous_status == "done" and status != "done" and self.reopen_project_next_step(task, now, "undo" if source == "undo" else "task_reopen")
        missing_outcome = status_changed and status == "done" and not task_completion_outcome(task)
        save_json(TASKS_FILE, self.today_tasks)
        if completed_handoff or reopened_handoff:
            self.view_signature = None
            self.refresh(silent=True, scan=False)
            if completed_handoff:
                message = "任务已完成，成果待补录；项目已回到“需要下一步”" if missing_outcome else "任务已完成；项目已回到“需要下一步”，请明确后续动作"
            else:
                message = "任务已重新打开；项目下一步已同步恢复"
            self.statusBar().showMessage(message, 4500)
        elif status_changed:
            self.sync_project_workload(); self.view_signature = None
            self.render_today_tasks(); self.render()
            if missing_outcome:
                self.statusBar().showMessage("任务已完成；请记录实际成果，供日报与项目交接引用", 4200)
            else:
                self.statusBar().showMessage(f"任务已移至“{TASK_STATUS[status]}”", 2200)
        else:
            self.render_today_tasks()
            self.statusBar().showMessage(f"“{task.get('title', '任务')}”已调整为第 {movement.get('targetIndex', 0) + 1} 项", 2200)
        if status_changed and allow_undo and source in {"manual", "selector", "drag", "wip"}:
            self.offer_task_undo(task, previous_status, status, now)
        return True

    def offer_task_undo(self, task, previous_status, status, occurred_at):
        if previous_status not in TASK_STATUS or status not in TASK_STATUS or previous_status == status:
            return
        self.pending_task_undo = {
            "kind": "status",
            "taskId": task.get("id"),
            "from": previous_status,
            "to": status,
            "at": occurred_at,
        }
        self.undo_task_button.setText(f"撤销到{TASK_STATUS[previous_status]}")
        self.undo_task_button.setToolTip("撤销最近一次手动任务状态切换")
        self.undo_task_button.show()
        self.undo_task_timer.start(8000)

    def offer_task_schedule_undo(self, task, previous_date, target_date, occurred_at):
        if not task or not previous_date or not target_date or previous_date == target_date:
            return
        self.pending_task_undo = {
            "kind": "schedule",
            "taskId": task.get("id"),
            "from": previous_date,
            "to": target_date,
            "at": occurred_at,
        }
        self.undo_task_button.setText("撤销改期")
        self.undo_task_button.setToolTip(f"恢复到原计划日期 {previous_date}")
        self.undo_task_button.show()
        self.undo_task_timer.start(8000)

    def clear_task_undo(self):
        self.pending_task_undo = None
        if hasattr(self, "undo_task_timer"):
            self.undo_task_timer.stop()
        if hasattr(self, "undo_task_button"):
            self.undo_task_button.hide()

    def undo_last_task_transition(self):
        transition = dict(self.pending_task_undo or {})
        task = next((item for item in self.today_tasks if item.get("id") == transition.get("taskId")), None)
        if transition.get("kind") == "schedule":
            history = task.get("scheduleHistory") if isinstance((task or {}).get("scheduleHistory"), list) else []
            latest = history[-1] if history else {}
            still_current = (
                task is not None
                and task.get("status", "planned") == "planned"
                and str(task.get("date") or "") == str(transition.get("to") or "")
                and str(latest.get("at") or "") == str(transition.get("at") or "")
                and str(latest.get("from") or "") == str(transition.get("from") or "")
                and str(latest.get("to") or "") == str(transition.get("to") or "")
            )
            self.clear_task_undo()
            if not still_current:
                self.statusBar().showMessage("任务已经发生新的变化，无法撤销之前的改期", 3500)
                return
            now = datetime.now().isoformat(timespec="seconds")
            movement = reschedule_task_date(
                self.today_tasks, task.get("id"), transition.get("from"), now, "undo"
            )
            if not movement.get("changed"):
                self.statusBar().showMessage("任务已经发生新的变化，无法恢复原计划日期", 3500)
                return
            save_json(TASKS_FILE, self.today_tasks)
            previous_qdate = QDate.fromString(str(transition.get("from") or ""), Qt.ISODate)
            if previous_qdate.isValid() and hasattr(self, "board_date_field"):
                self.board_date_field.setDate(previous_qdate)
            self.view_signature = None
            self.render_today_tasks(); self.render_portfolio_decisions()
            self.statusBar().showMessage(f"已撤销改期，任务恢复到 {transition.get('from')}", 3400)
            return
        history = task.get("statusHistory") if isinstance((task or {}).get("statusHistory"), list) else []
        latest = history[-1] if history else {}
        still_current = (
            task is not None
            and task.get("status", "planned") == transition.get("to")
            and str(latest.get("at") or "") == str(transition.get("at") or "")
            and latest.get("to") == transition.get("to")
        )
        self.clear_task_undo()
        if not still_current:
            self.statusBar().showMessage("任务已经发生新的变化，无法撤销之前的状态", 3500)
            return
        if self.set_task_status(task.get("id"), transition.get("from"), source="undo", allow_undo=False):
            self.statusBar().showMessage(f"已撤销，任务恢复为“{TASK_STATUS[transition['from']]}”", 3200)

    def delete_today_task(self, task):
        message = (
            f"确定将“{task.get('title', '未命名任务')}”移到任务回收站吗？\n\n"
            "任务会离开看板、项目负载和每日总结，但原日期、状态和变更历史都会保留，可随时恢复。"
        )
        if QMessageBox.question(self, "移到任务回收站", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        now = datetime.now().isoformat(timespec="seconds")
        if not archive_task_record(task, now):
            return
        if (self.pending_task_undo or {}).get("taskId") == task.get("id"):
            self.clear_task_undo()
        save_json(TASKS_FILE, self.today_tasks)
        self.sync_project_workload(); self.view_signature = None
        self.render_today_tasks(); self.render()
        self.statusBar().showMessage("任务已移到回收站，原状态历史仍保留", 3000)

    def open_task_conversation(self, task):
        self.open_codex_conversation({"sessionId": task.get("sessionId"), "conversationLabel": task.get("conversationTitle") or task.get("title")})

    def plan_task_in_codex(self, task):
        project = self.project_by_id(task.get("projectId")); project_name = (project or {}).get("name") or "当前项目"
        schedule = task.get('date', '')
        prompt = f"请帮我规划并推进这项每日任务：{task.get('title')}\n日期：{schedule}\n项目：{project_name}\n补充说明：{task.get('notes') or '无'}\n\n请拆分清晰的执行步骤，说明可完成的交付结果，然后从第一步开始。"
        QApplication.clipboard().setText(prompt); self.open_task_conversation(task); self.statusBar().showMessage("已复制任务规划提示并打开 Codex；粘贴即可继续", 4500)

    def add_category(self):
        name, accepted = QInputDialog.getText(self, "新建分类", "分类名称：")
        name = name.strip()
        if not accepted or not name:
            return
        if name == "全部" or name in self.categories:
            QMessageBox.information(self, "分类已存在", "请使用一个新的分类名称。")
            return
        self.categories.insert(-1, name)
        save_json(CATEGORIES_FILE, self.categories[1:])
        self.view_signature = None
        self.render_nav(); self.render()
        self.statusBar().showMessage(f"已新建分类：{name}", 2500)

    def reorder_categories(self):
        editable = [category for category in self.categories[1:] if category != "未分类"]
        if len(editable) < 2:
            QMessageBox.information(self, "无需调整", "至少需要两个自定义分类才能调整顺序。")
            return
        dialog = CategoryOrderDialog(self, editable)
        if dialog.exec_() != QDialog.Accepted:
            return
        ordered = dialog.value()
        if ordered == editable:
            return
        self.categories = ["全部", *ordered, "未分类"]
        save_json(CATEGORIES_FILE, self.categories[1:])
        self.view_signature = None
        self.render_nav(); self.render()
        self.statusBar().showMessage("项目分类顺序已保存", 2500)

    def managed_project_catalog(self):
        """Return active, archived, and detached saved records for taxonomy migrations."""
        catalog = visible_project_catalog(self.saved_projects, {**self.project_layout, "hiddenProjectIds": []})
        represented = {str(project.get("savedId") or "") for project in catalog if project.get("savedId")}
        for saved in self.saved_projects:
            saved_id = str(saved.get("id") or "")
            if not saved_id or saved_id in represented:
                continue
            catalog.append({
                **saved,
                "id": f"saved:{saved_id}",
                "savedId": saved_id,
                "codexProjectId": None,
                "_detached": True,
            })
        return catalog

    def apply_category_migration(self, previous_category, next_category, occurred_at=None):
        """Migrate one taxonomy label across projects, tasks, layout, and audit history."""
        previous = str(previous_category or "").strip()
        replacement = str(next_category or "").strip()
        if not previous or not replacement or previous == replacement:
            return {"projects": 0, "tasks": 0, "decisions": 0}
        timestamp = occurred_at or datetime.now().isoformat(timespec="seconds")
        projects = [project for project in self.managed_project_catalog() if project.get("category") == previous]
        task_categories_before = [
            (str(task.get("category") or ""), str(task.get("projectCategorySnapshot") or ""))
            for task in self.today_tasks
        ]
        migrate_task_category_references(self.today_tasks, previous, replacement)
        entries = []
        for project in projects:
            before = dict(project)
            target = self.saved_record_for_project(project)
            target["category"] = replacement
            project["category"] = replacement
            migrate_project_task_category_references(self.today_tasks, project, replacement)
            after = {**target, "name": project.get("name") or target.get("name")}
            entry = build_project_decision_entry(project, before, after, "category", timestamp)
            if entry is not None:
                entries.append(entry)
        reconcile_task_project_categories(self.today_tasks, self.managed_project_catalog())
        task_count = sum(
            before != (str(task.get("category") or ""), str(task.get("projectCategorySnapshot") or ""))
            for before, task in zip(task_categories_before, self.today_tasks)
        )
        orders = self.project_layout.setdefault("categoryOrders", {})
        moved_ids = list(orders.pop(previous, []))
        moved_ids.extend(
            project.get("id") for project in projects
            if project.get("id") and not project.get("_detached")
        )
        destination = orders.setdefault(replacement, [])
        for project_id in moved_ids:
            if project_id and project_id not in destination:
                destination.append(project_id)
        self.project_decisions.extend(entries)
        if len(self.project_decisions) > 2000:
            self.project_decisions = self.project_decisions[-2000:]
        save_json(CATEGORIES_FILE, self.categories[1:])
        save_json(PROJECTS_FILE, self.saved_projects)
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        if task_count:
            save_json(TASKS_FILE, self.today_tasks)
        if entries:
            save_json(PROJECT_DECISIONS_FILE, self.project_decisions)
        return {"projects": len(projects), "tasks": task_count, "decisions": len(entries)}

    def rename_category(self):
        editable = [category for category in self.categories[1:] if category != "未分类"]
        if not editable:
            QMessageBox.information(self, "没有可修改的分类", "请先新建一个分类。")
            return
        old_name, accepted = QInputDialog.getItem(self, "修改分类名", "选择分类：", editable, 0, False)
        if not accepted:
            return
        new_name, accepted = QInputDialog.getText(self, "修改分类名", "新的分类名称：", text=old_name)
        new_name = new_name.strip()
        if not accepted or not new_name or new_name == old_name:
            return
        if new_name == "全部" or new_name in self.categories:
            QMessageBox.information(self, "名称不可用", "该分类名称已经存在。")
            return
        self.categories[self.categories.index(old_name)] = new_name
        if self.category == old_name:
            self.category = new_name
        result = self.apply_category_migration(old_name, new_name)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage(
            f"分类已重命名：{old_name} → {new_name} · {result['projects']} 个项目 · {result['tasks']} 条任务记录已同步",
            4200,
        )

    def delete_category(self):
        editable = [category for category in self.categories[1:] if category != "未分类"]
        if not editable:
            QMessageBox.information(self, "没有可删除的分类", "“全部”和“未分类”是系统分类，不能删除。")
            return
        category, accepted = QInputDialog.getItem(self, "删除分类", "选择要删除的分类：", editable, 0, False)
        if not accepted or not category:
            return
        affected = [project for project in self.managed_project_catalog() if project.get("category") == category]
        task_count = sum(
            str(task.get("category") or "").strip() == category
            or str(task.get("projectCategorySnapshot") or "").strip() == category
            or any(task_matches_project(task, project) for project in affected)
            for task in self.today_tasks
        )
        message = f"确定删除分类“{category}”吗？"
        if affected or task_count:
            message += f"\n\n{len(affected)} 个项目和 {task_count} 条任务记录会迁移到“未分类”。项目文件、Codex 对话和历史记录不会被删除。"
        else:
            message += "\n\n该操作不会删除任何项目文件或 Codex 对话。"
        if QMessageBox.question(self, "确认删除分类", message) != QMessageBox.Yes:
            return

        self.categories = [value for value in self.categories if value != category]
        if self.category == category:
            self.category = "未分类"
        result = self.apply_category_migration(category, "未分类")
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage(
            f"分类“{category}”已删除 · {result['projects']} 个项目 · {result['tasks']} 条任务记录已移到“未分类”",
            4200,
        )

    def saved_record_for_project(self, project):
        saved_id = project.get("savedId")
        target = next((item for item in self.saved_projects if item.get("id") == saved_id), None)
        if target is None:
            roots = project.get("rootPaths") or [project.get("path", "")]
            normalized_roots = {normalized_path(path) for path in roots if path}
            target = next(
                (
                    item for item in self.saved_projects
                    if normalized_path(item.get("path")) in normalized_roots
                ),
                None,
            )
        if target is None:
            target = {
                "id": str(uuid.uuid4()),
                "name": project.get("name", ""),
                "path": project.get("path", ""),
                "status": project.get("status", "active"),
                "category": project.get("category", "未分类"),
                "icon": project.get("icon", ""),
                "color": project.get("color", "#58d7f6"),
                "priority": project_priority_key(project),
                "stage": project_stage_key(project),
                "health": project_health_key(project),
                "objective": project.get("objective", ""),
                "successCriteria": project.get("successCriteria", ""),
                "nextStep": project.get("nextStep", ""),
                "blocker": project.get("blocker", ""),
                "reviewedAt": project.get("reviewedAt", ""),
                "reviewBaseline": project.get("reviewBaseline"),
            }
            for field in PROJECT_BLOCKER_LIFECYCLE_FIELDS:
                if field in project:
                    target[field] = project.get(field)
            self.saved_projects.append(target)
        project["savedId"] = target["id"]
        return target

    def update_project_management(self, project, data, notify=True, source="manual"):
        previous_category = project.get("category", "未分类")
        before = dict(project)
        occurred_at = datetime.now().isoformat(timespec="seconds")
        data, normalization_notes = normalize_project_management_decision(project, data)
        name_requested = "name" in data
        restored_category = ""
        requested_category = str(data.get("category") or "").strip()
        validation_error = project_management_validation_error(data)
        if validation_error:
            if notify:
                self.statusBar().showMessage(validation_error, 4000)
            return None
        if before.get("status", "active") != "completed" and data.get("status") == "completed":
            closeout = str(data.get("completionSummary") or "").strip() or latest_project_completion_outcome(before)
            if not closeout:
                if notify:
                    self.statusBar().showMessage("完成项目需要先记录最终交付成果", 4000)
                return None
            data["completionSummary"] = closeout
            if not str(data.get("objective") or "").strip():
                if notify:
                    self.statusBar().showMessage("完成项目前需要先明确项目目标", 4000)
                return None
            data["completionObjectiveSnapshot"] = str(
                data.get("completionObjectiveSnapshot") or data.get("objective") or ""
            ).strip()
            criteria_snapshot = str(
                data.get("completionCriteriaSnapshot") or data.get("successCriteria") or ""
            ).strip()
            if criteria_snapshot:
                data["completionCriteriaSnapshot"] = criteria_snapshot
        if (
            source == "undo"
            and requested_category
            and requested_category != "全部"
            and requested_category not in self.categories[1:]
        ):
            insert_at = max(1, len(self.categories) - 1)
            self.categories.insert(insert_at, requested_category)
            restored_category = requested_category
        target = self.saved_record_for_project(project)
        target.update({
            "priority": data.get("priority") if data.get("priority") in PROJECT_PRIORITY else "normal",
            "stage": data.get("stage") if data.get("stage") in PROJECT_STAGE else "execution",
            "health": data.get("health") if data.get("health") in PROJECT_HEALTH else "on_track",
            "status": data.get("status") if data.get("status") in STATUS_TEXT else "active",
            "category": data.get("category") if data.get("category") in self.categories[1:] else previous_category,
            "objective": str(data.get("objective") or "").strip(),
            "successCriteria": str(data.get("successCriteria", before.get("successCriteria")) or "").strip(),
            "nextStep": str(data.get("nextStep") or "").strip(),
            "blocker": str(data.get("blocker") or "").strip(),
        })
        if name_requested:
            apply_project_display_name(target, project, data.get("name"))
        blocker_event = reconcile_project_blocker_lifecycle(
            before, target, occurred_at, data.get("blockerResolution")
        )
        if not self.apply_project_completion_lifecycle(project, before, target, data, occurred_at, source):
            if notify:
                self.statusBar().showMessage("完成项目需要先记录最终交付成果", 4000)
            return None
        if target.get("nextStep"):
            target["nextStepReviewNeeded"] = False
        new_category = target.get("category", previous_category)
        task_category_updates = 0
        if new_category != previous_category:
            orders = self.project_layout.setdefault("categoryOrders", {})
            orders[previous_category] = [value for value in orders.get(previous_category, []) if value != project.get("id")]
            if project.get("id") not in orders.setdefault(new_category, []):
                orders[new_category].append(project.get("id"))
            task_category_updates = migrate_project_task_category_references(self.today_tasks, project, new_category)
        for key in ("priority", "stage", "health", "status", "category", "objective", "successCriteria", "nextStep", "blocker", "nextStepReviewNeeded", "completionSummary", "completedAt", "completionHistory", "completionObjectiveSnapshot", "completionCriteriaSnapshot", "completionAcceptedAt", *PROJECT_BLOCKER_LIFECYCLE_FIELDS):
            project[key] = target.get(key)
        for key in ("reviewedAt", "reviewBaseline"):
            if key in target:
                project[key] = target.get(key)
        if name_requested:
            project["name"] = target.get("name")
            if target.get("nameOverride"):
                project["nameOverride"] = target.get("nameOverride")
            else:
                project.pop("nameOverride", None)
        for key in ("completionSummary", "completedAt", "completionObjectiveSnapshot", "completionCriteriaSnapshot", "completionAcceptedAt", "blockedAt", "blockerUpdatedAt", "blockedAtEstimated", "lastBlockerResolution"):
            if key not in target:
                project.pop(key, None)
        decision_source = source if source in PROJECT_DECISION_SOURCES else "manual"
        decision_after = dict(target)
        if not name_requested:
            decision_after["name"] = project.get("name") or target.get("name")
        entry = self.record_project_decision(project, before, decision_after, decision_source, occurred_at)
        if project_change_establishes_review(target, decision_source, entry is not None):
            baseline = establish_project_review_baseline(target, occurred_at)
            project["reviewedAt"] = occurred_at
            project["reviewBaseline"] = dict(baseline or {})
        save_json(PROJECTS_FILE, self.saved_projects)
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        if task_category_updates:
            save_json(TASKS_FILE, self.today_tasks)
        if restored_category:
            save_json(CATEGORIES_FILE, self.categories[1:])
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        if notify:
            blocker_messages = {
                "started": "已开始记录项目阻塞时长",
                "updated": "阻塞说明已更新，持续时间保持不变",
                "confirmed": "已从本次确认开始记录阻塞时长",
                "resolved": "阻塞已解除，解决说明和时间已写入项目记录",
            }
            message = blocker_messages.get((blocker_event or {}).get("action")) or (normalization_notes[0] if normalization_notes else "项目目标与下一步已保存")
            self.statusBar().showMessage(message, 3500 if blocker_event or normalization_notes else 2500)
        return dict(target)

    def update_project_completion_summary(self, project, outcome, objective_snapshot="", criteria_snapshot=""):
        if (project or {}).get("status", "active") != "completed":
            self.statusBar().showMessage("项目尚未完成，不能记录项目级完成成果", 3500)
            return False
        text = str(outcome or "").strip()
        if not text:
            self.statusBar().showMessage("项目完成成果不能为空", 3000)
            return False
        acceptance_objective = str(objective_snapshot or project.get("objective") or "").strip()
        if not acceptance_objective:
            self.statusBar().showMessage("项目目标缺失，无法确认完成验收", 3500)
            return False
        target = self.saved_record_for_project(project)
        previous = project_completion_outcome(target)
        occurred_at = datetime.now().isoformat(timespec="seconds")
        acceptance_criteria = str(
            criteria_snapshot
            or project.get("completionCriteriaSnapshot")
            or project.get("successCriteria")
            or ""
        ).strip()
        if not record_project_completion_outcome(
            target, text, occurred_at, "closeout_editor", acceptance_objective, acceptance_criteria
        ):
            self.statusBar().showMessage("项目完成成果没有变化", 2300)
            return False
        for key in ("completionSummary", "completedAt", "completionHistory", "completionObjectiveSnapshot", "completionCriteriaSnapshot", "completionAcceptedAt"):
            project[key] = target.get(key)
        self.record_project_closeout(project, "revise" if previous else "complete", text, occurred_at)
        save_json(PROJECTS_FILE, self.saved_projects)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage("项目完成成果已保存，并纳入项目档案与每日总结", 3800)
        return True

    def rollback_project_decision(self, project, entry):
        if str((entry or {}).get("projectId") or "") not in project_reference_ids(project):
            self.statusBar().showMessage("这条决策记录不属于当前项目，无法恢复", 3500)
            return False
        requested, affected, _conflicts = build_project_decision_rollback(project, entry)
        if not affected:
            self.statusBar().showMessage("当前项目已经是目标状态，无需恢复", 3000)
            return False
        previous_count = len(self.project_decisions)
        saved = self.update_project_management(project, requested, notify=False, source="undo")
        if saved is None or len(self.project_decisions) == previous_count:
            self.statusBar().showMessage("项目规则未允许产生有效回滚，请检查当前状态", 4000)
            return False
        self.statusBar().showMessage(f"已恢复 {len(affected)} 项项目决策，并保留回滚记录", 4000)
        return True

    def open_project_workspace(self, project):
        ProjectWorkbenchDialog(self, project).exec_()

    def new_project_task(self, project):
        self.edit_today_task(None, "planned", project.get("id"))

    def schedule_project_next_step(self, project):
        title = str(project.get("nextStep") or "").strip()
        if not title:
            QMessageBox.information(self, "尚未明确下一步", "请先在项目面板中填写一个可以直接执行的下一步。")
            return None
        today = QDate.currentDate().toString(Qt.ISODate)
        existing = find_open_project_next_step_task(self.today_tasks, project, title)
        if existing:
            existing_date = QDate.fromString(str(existing.get("date") or ""), Qt.ISODate)
            if existing_date.isValid() and hasattr(self, "board_date_field"):
                self.board_date_field.setDate(existing_date)
            self.render_today_tasks()
            date_text = existing_date.toString("yyyy年MM月dd日") if existing_date.isValid() else "任务记录"
            self.statusBar().showMessage(f"这个项目下一步已存在于 {date_text}，已为你定位", 3800)
            return existing
        conversations = project.get("conversations") or []
        conversation = next((item for item in conversations if codex_state(item)[0] == "running"), None)
        conversation = conversation or (conversations[0] if conversations else None)
        now = datetime.now().isoformat(timespec="seconds")
        task = build_project_next_step_task(project, today, now, conversation)
        self.today_tasks.append(task)
        save_json(TASKS_FILE, self.today_tasks)
        self.sync_project_workload()
        self.view_signature = None
        self.render_today_tasks(); self.render()
        self.statusBar().showMessage("项目下一步已加入今日任务；完成后会提示明确后续动作", 4000)
        return task

    def complete_project_next_step(self, task, now=None):
        project = self.project_by_id(task.get("projectId"))
        if project is None:
            return False
        before = dict(project)
        completed_at = now or datetime.now().isoformat(timespec="seconds")
        update = project_next_step_completion_update(project, task, completed_at)
        if update is None:
            return False
        target = self.saved_record_for_project(project)
        target.update(update)
        project.update(update)
        self.record_project_decision(project, before, target, "task_completion", completed_at)
        save_json(PROJECTS_FILE, self.saved_projects)
        return True

    def sync_project_completion_outcome(self, task, now=None):
        """Keep a project handoff's completion evidence aligned with its completed task."""
        if (task or {}).get("origin") != "project_next_step" or task.get("status") != "done":
            return False
        project = self.project_by_id(task.get("projectId"))
        if project is None:
            return False
        completed_step = str(task.get("projectNextStep") or task.get("title") or "").strip()
        if normalized_action_text(project.get("lastCompletedNextStep")) != normalized_action_text(completed_step):
            return False
        outcome = task_completion_outcome(task)
        if normalized_decision_value(project.get("lastCompletedOutcome")) == normalized_decision_value(outcome):
            return False
        recorded_at = str(task.get("completionRecordedAt") or now or datetime.now().isoformat(timespec="seconds"))
        target = self.saved_record_for_project(project)
        for record in (target, project):
            record["lastCompletedOutcome"] = outcome
            record["lastCompletedOutcomeAt"] = recorded_at if outcome else ""
        save_json(PROJECTS_FILE, self.saved_projects)
        return True

    def reopen_project_next_step(self, task, now=None, source="task_reopen"):
        project = self.project_by_id(task.get("projectId"))
        if project is None:
            return False
        before = dict(project)
        reopened_at = now or datetime.now().isoformat(timespec="seconds")
        update = project_next_step_reopen_update(project, task)
        if update is None:
            return False
        target = self.saved_record_for_project(project)
        target.update(update)
        project.update(update)
        self.record_project_decision(project, before, target, source if source in PROJECT_DECISION_SOURCES else "task_reopen", reopened_at)
        save_json(PROJECTS_FILE, self.saved_projects)
        return True

    def change_project_category(self, project, category):
        if category not in self.categories[1:] or category == project.get("category"):
            return
        before = dict(project)
        previous_category = project.get("category", "未分类")
        target = self.saved_record_for_project(project)
        target["category"] = category
        project["category"] = category
        self.record_project_decision(project, before, target, "category")
        task_category_updates = migrate_project_task_category_references(self.today_tasks, project, category)
        orders = self.project_layout.setdefault("categoryOrders", {})
        orders[previous_category] = [value for value in orders.get(previous_category, []) if value != project.get("id")]
        if project.get("id") not in orders.setdefault(category, []):
            orders[category].append(project.get("id"))
        save_json(PROJECTS_FILE, self.saved_projects)
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        if task_category_updates:
            save_json(TASKS_FILE, self.today_tasks)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage(f"{project.get('name', '项目')} 已移至“{category}”", 2500)

    def reorder_projects(self, category, ordered_ids):
        self.project_layout.setdefault("categoryOrders", {})[category] = list(ordered_ids)
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage("项目顺序已保存", 1800)

    def move_project(self, project, offset):
        category = project.get("category", "未分类")
        category_projects = [item for item in self.projects if item.get("category", "未分类") == category]
        ids = [item.get("id") for item in category_projects if item.get("id")]
        project_id = project.get("id")
        if project_id not in ids:
            return
        index = ids.index(project_id); target = index + offset
        if target < 0 or target >= len(ids):
            self.statusBar().showMessage("项目已经位于当前方向的末端", 1800)
            return
        ids[index], ids[target] = ids[target], ids[index]
        self.reorder_projects(category, ids)

    def archived_projects(self):
        return archived_project_catalog(self.saved_projects, self.project_layout)

    def project_governance_candidates(self, projects=None):
        source = list(self.projects if projects is None else projects)
        candidates = [
            project for project in source
            if project.get("status", "active") != "completed"
            and project_governance_gaps(project)
            and project_has_local_folder(project)
        ]
        return sorted(candidates, key=project_management_sort_key)

    def show_project_governance(self, projects=None):
        candidates = self.project_governance_candidates(projects)
        if not candidates:
            source = list(self.projects if projects is None else projects)
            missing_without_folder = [
                project for project in source
                if project.get("status", "active") != "completed"
                and project_governance_gaps(project)
                and not project_has_local_folder(project)
            ]
            if missing_without_folder:
                QMessageBox.information(self, "需要有效项目目录", "这些项目仍有管理缺项，但本地目录不可用。请先编辑项目并选择有效文件夹。")
            else:
                QMessageBox.information(self, "项目治理已完整", "当前项目都已经具备目标、必要的下一步和一致的健康状态。")
            return
        PortfolioGovernanceDialog(self, candidates).exec_()
        self.render()

    def show_archived_projects(self):
        ArchivedProjectsDialog(self, self.archived_projects()).exec_()

    def restore_project(self, project):
        project_id = str((project or {}).get("id") or "")
        updated_layout, changed = restore_project_layout(self.project_layout, project_id)
        if not changed:
            return False
        self.project_layout = updated_layout
        self.record_project_lifecycle(project, "restore")
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage(f"{project.get('name', '项目')} 已恢复到项目中心", 2500)
        return True

    def delete_project(self, project):
        pending_tasks = open_project_tasks(self.today_tasks, project)
        running_conversations = [
            conversation for conversation in (project.get("conversations") or [])
            if codex_state(conversation)[0] == "running"
        ]
        if pending_tasks or running_conversations:
            details = []
            if pending_tasks:
                details.append(f"{len(pending_tasks)} 项未完成任务")
            if running_conversations:
                details.append(f"{len(running_conversations)} 个运行中的 Codex 对话")
            QMessageBox.information(
                self,
                "项目仍在执行",
                f"暂不能归档“{project.get('name', '未命名项目')}”，因为仍有{'、'.join(details)}。\n\n"
                "请先完成或移除关联任务，并等待 Codex 对话结束；这样归档后不会产生失去项目归属的活动记录。",
            )
            return False
        message = (
            f"确定归档“{project.get('name', '未命名项目')}”吗？\n\n"
            "项目会离开当前项目列表，但保留全部本地管理信息；之后可从“归档箱”恢复。\n"
            "不会删除磁盘文件，也不会删除 Codex 对话。"
        )
        if QMessageBox.question(self, "归档项目", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return False
        project_id = project.get("id")
        self.project_layout, changed = archive_project_layout(self.project_layout, project_id)
        if not changed:
            self.statusBar().showMessage("项目已经在归档箱中", 2000)
            return False
        self.record_project_lifecycle(project, "archive")
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage("项目已归档，可随时从归档箱恢复", 2800)
        return True

    def shown(self):
        query = self.search.text().strip().lower()
        state_filter = self.status_filter.currentData() if hasattr(self, "status_filter") else "all"
        management_scope = self.scope_filter.currentData() if hasattr(self, "scope_filter") else "all"
        result = []
        for item in self.projects:
            if self.category != "全部" and item.get("category") != self.category:
                continue
            if state_filter != "all" and project_display_state(item)[0] != state_filter:
                continue
            if not project_management_scope_matches(item, management_scope):
                continue
            conversations = " ".join(
                f"{conversation_name(conversation)} {conversation.get('summary', '')}"
                for conversation in item.get("conversations", [])
            )
            searchable = (
                f"{item.get('name', '')} {item.get('category', '')} {item.get('path', '')} "
                f"{item.get('objective', '')} {item.get('successCriteria', '')} {item.get('nextStep', '')} {item.get('blocker', '')} "
                f"{PROJECT_PRIORITY.get(project_priority_key(item), '')} {PROJECT_STAGE.get(project_stage_key(item), '')} "
                f"{PROJECT_HEALTH.get(project_health_key(item), '')} {project_control_state(item)[1]} {conversations}"
            ).lower()
            if query and query not in searchable:
                continue
            result.append(item)
        return result

    def clear_project_filters(self):
        self.category = "全部"
        self.search.clear()
        self.status_filter.setCurrentIndex(max(0, self.status_filter.findData("all")))
        if hasattr(self, "scope_filter"):
            self.scope_filter.setCurrentIndex(max(0, self.scope_filter.findData("all")))
        self.render_nav(); self.render()

    def clear_project_list(self):
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget(): item.widget().hide(); item.widget().deleteLater()

    def render(self):
        projects = self.shown()
        if hasattr(self, "governance_button"):
            governance_count = len(self.project_governance_candidates())
            self.governance_button.setVisible(bool(governance_count))
            if governance_count:
                self.governance_button.setText(f"Codex 补全  {governance_count}")
                self.governance_button.setIcon(fluent_icon("\uE945", color="#1d4ed8", size=15))
                self.governance_button.setEnabled(True)
                self.governance_button.setToolTip(f"{governance_count} 个项目存在可由 Codex 补齐的管理缺项")
                self.governance_button.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c8d8f4; border-radius: 9px; padding: 7px 12px; font-size: 12px; font-weight: 650; } QPushButton:hover, QPushButton:focus { background: #dfe9fb; border-color: #9eb8e4; }")
        if hasattr(self, "archive_button"):
            archived_count = len(self.archived_projects())
            self.archive_button.setText(f"归档箱  {archived_count}" if archived_count else "归档箱")
        if hasattr(self, "project_result_count"):
            self.project_result_count.setText(f"{len(projects)} 个项目")
        if not projects:
            self.project_content.setCurrentWidget(self.scroll)
            self.clear_project_list()
            filtered = bool(self.search.text().strip()) or self.status_filter.currentData() != "all" or self.scope_filter.currentData() != "all" or self.category != "全部"
            empty = QFrame(); empty.setObjectName("projectEmptyState"); empty.setMinimumHeight(260)
            empty.setStyleSheet("QFrame#projectEmptyState { background: #ffffff; border: 1px solid #dbe3ee; border-radius: 12px; }")
            empty_layout = QVBoxLayout(empty); empty_layout.setContentsMargins(24, 44, 24, 44); empty_layout.setSpacing(10); empty_layout.setAlignment(Qt.AlignCenter)
            icon = QLabel(); icon.setFixedSize(42, 42); icon.setAlignment(Qt.AlignCenter); icon.setPixmap(fluent_icon("\uE721", color="#64748b", size=21).pixmap(QSize(21, 21))); icon.setStyleSheet("background: #eef2f6; border-radius: 11px;"); empty_layout.addWidget(icon, 0, Qt.AlignCenter)
            title = QLabel("没有符合当前条件的项目" if filtered else "还没有项目"); title.setStyleSheet("color: #253247; font-size: 16px; font-weight: 700;"); empty_layout.addWidget(title, 0, Qt.AlignCenter)
            hint = QLabel("清除搜索或状态筛选后再试一次" if filtered else "新建一个项目开始整理 Codex 工作")
            hint.setStyleSheet("color: #748094; font-size: 12px;"); empty_layout.addWidget(hint, 0, Qt.AlignCenter)
            action = QPushButton("清除筛选" if filtered else "新建项目"); action.setFixedHeight(36)
            if not filtered: action.setObjectName("primary")
            action.clicked.connect(self.clear_project_filters if filtered else lambda: self.edit_project(None)); empty_layout.addWidget(action, 0, Qt.AlignCenter)
            self.list.addWidget(empty); self.list.addStretch(); return
        if self.category == "全部":
            self.project_content.setCurrentWidget(self.mind_map)
            self.mind_map.update_map(projects, self.categories)
            return
        self.project_content.setCurrentWidget(self.scroll)
        self.clear_project_list()
        groups = {}
        for project in projects: groups.setdefault(project.get("category", "未分类"), []).append(project)
        order = [item for item in self.categories[1:] if item in groups] + sorted(set(groups) - set(self.categories))
        for category in order:
            header = QLabel(f"{category}    {len(groups[category])} 个项目"); header.setStyleSheet("color: #34445c; font-size: 15px; font-weight: 700; padding: 12px 2px 4px;"); self.list.addWidget(header)
            rows_holder = ProjectReorderContainer(self, category); rows = QVBoxLayout(rows_holder); rows.setContentsMargins(0, 0, 0, 10); rows.setSpacing(8)
            for project in groups[category]: rows.addWidget(ProjectGroup(project, self))
            self.list.addWidget(rows_holder)
        self.list.addStretch()

    def copy_context(self, project):
        recent = (project.get("lastActivity") or {}).get("summary") or "暂无自动同步的进度记录。"
        completed_outcome = str(project.get("lastCompletedOutcome") or "").strip()
        completed_outcome_line = f"最近完成成果：{completed_outcome}\n" if completed_outcome else ""
        project_outcome = project_completion_outcome(project)
        project_outcome_line = f"项目最终成果：{project_outcome}\n" if project_outcome else ""
        blocker_context = project_control_state(project)[4] if project_control_state(project)[0] == "blocked" else "无"
        text = (
            f"继续项目：{project['name']}\n"
            f"项目目标：{project.get('objective') or '尚未明确'}\n"
            f"管理优先级：{PROJECT_PRIORITY.get(project_priority_key(project), '常规推进')}\n"
            f"当前阶段：{PROJECT_STAGE.get(project_stage_key(project), '执行')}\n"
            f"项目健康度：{project_control_state(project)[1]}\n"
            f"当前阻塞：{blocker_context}\n"
            f"工作目录：{project['path']}\n"
            f"当前下一步：{project.get('nextStep') or '请先判断下一步'}\n"
            f"{project_outcome_line}"
            f"{completed_outcome_line}"
            f"最近动态：{recent}\n\n"
            "请先读取项目现状，围绕项目目标说明当前进度、风险和建议的下一步，再等待我的具体指令。"
        )
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("已复制项目上下文，回到 Codex 粘贴即可继续", 3500)

    def continue_project(self, project):
        """Copy the project handoff and return to its most relevant Codex conversation."""
        self.copy_context(project)
        conversations = project.get("conversations") or []
        target = next((item for item in conversations if codex_state(item)[0] == "running"), None)
        target = target or (conversations[0] if conversations else None)
        if target:
            self.open_codex_conversation(target)
        else:
            self.statusBar().showMessage("已复制项目上下文；此项目尚未关联 Codex 对话", 4000)

    def open_folder(self, project):
        path = Path(project["path"])
        if not path.exists():
            QMessageBox.warning(self, "路径不存在", f"未找到：\n{path}"); return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_codex_conversation(self, conversation):
        session_id = str(conversation.get("sessionId") or "").strip()
        if not session_id:
            QMessageBox.information(self, "无法打开", "这个对话缺少 Codex 任务 ID。")
            return
        opened = QDesktopServices.openUrl(QUrl(f"codex://threads/{session_id}"))
        if opened:
            self.statusBar().showMessage(f"正在 Codex 中打开：{conversation_name(conversation)}", 3000)
        else:
            QMessageBox.warning(self, "无法打开", "Codex 没有响应任务跳转，请确认 Codex 桌面应用已安装。")

    def edit_project(self, project=None):
        dialog = ProjectEditor(self, project, self.categories)
        if dialog.exec_() != QDialog.Accepted: return
        data = dialog.value()
        if not data["name"] or not data["path"]:
            QMessageBox.warning(self, "信息不完整", "项目名称和本地路径不能为空。", parent=self); return
        if not data["color"].startswith("#") or len(data["color"]) != 7: data["color"] = "#58d7f6"
        before = dict(project or {})
        if before.get("status", "active") != "completed" and data.get("status") == "completed":
            closeout = str(data.get("completionSummary") or "").strip() or latest_project_completion_outcome(before)
            if not closeout:
                QMessageBox.information(self, "还没有项目成果", "完成项目需要先记录最终交付或验证结果。")
                return
            data["completionSummary"] = closeout
        clears_blocker = bool(str(before.get("blocker") or "").strip()) and not bool(str(data.get("blocker") or "").strip())
        if clears_blocker and data.get("status") == "completed":
            data["blockerResolution"] = f"项目完成验收：{data.get('completionSummary') or latest_project_completion_outcome(before)}"
        elif clears_blocker:
            resolution = BlockerResolutionDialog(self, before)
            if resolution.exec_() != QDialog.Accepted:
                return
            data["blockerResolution"] = resolution.value()
        task_category_updates = 0
        if project:
            previous_category = project.get("category", "未分类")
            target = self.saved_record_for_project(project)
            target.update({key: value for key, value in data.items() if key not in {"name", "completionSummary", "completedAt", "completionHistory", "blockerResolution"}})
            apply_project_display_name(target, project, data.get("name"))
            if target.get("nextStep"):
                target["nextStepReviewNeeded"] = False
            if data.get("category") != previous_category:
                orders = self.project_layout.setdefault("categoryOrders", {})
                orders[previous_category] = [value for value in orders.get(previous_category, []) if value != project.get("id")]
                destination = orders.setdefault(data["category"], [])
                if project.get("id") not in destination:
                    destination.append(project.get("id"))
                task_category_updates = migrate_project_task_category_references(self.today_tasks, project, data["category"])
        else:
            target = next((item for item in self.saved_projects if normalized_path(item.get("path")) == normalized_path(data.get("path"))), None)
            if target is None:
                target = {"id": str(uuid.uuid4())}; self.saved_projects.append(target)
            target.update({key: value for key, value in data.items() if key not in {"completionSummary", "completedAt", "completionHistory", "blockerResolution"}})
            if target.get("nextStep"):
                target["nextStepReviewNeeded"] = False
            codex_projects = codex_sidebar_projects(self.saved_projects)
            codex_match = next((item for item in codex_projects if normalized_path(item.get("path")) == normalized_path(data.get("path"))), None)
            target["manualProject"] = codex_match is None
            if codex_match:
                apply_project_display_name(target, codex_match, data.get("name"))
                hidden = self.project_layout.setdefault("hiddenProjectIds", [])
                self.project_layout["hiddenProjectIds"] = [value for value in hidden if value != codex_match.get("id")]
        decision_project = project or {**target, "savedId": target.get("id")}
        source = ("codex" if dialog.insight_applied else "editor") if project else "created"
        occurred_at = datetime.now().isoformat(timespec="seconds")
        blocker_event = reconcile_project_blocker_lifecycle(
            before, target, occurred_at, data.get("blockerResolution")
        )
        if not self.apply_project_completion_lifecycle(decision_project, before, target, data, occurred_at, source):
            QMessageBox.information(self, "还没有项目成果", "完成项目需要先记录最终交付或验证结果。")
            return
        entry = self.record_project_decision(decision_project, before, target, source, occurred_at)
        if project_change_establishes_review(target, source, entry is not None):
            baseline = establish_project_review_baseline(target, occurred_at)
            decision_project["reviewedAt"] = occurred_at
            decision_project["reviewBaseline"] = dict(baseline or {})
        save_json(PROJECTS_FILE, self.saved_projects)
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        if task_category_updates:
            save_json(TASKS_FILE, self.today_tasks)
        self.view_signature = None
        self.refresh()
        blocker_messages = {
            "started": "项目已保存，并开始记录阻塞时长",
            "updated": "项目已保存；阻塞说明已更新，持续时间保持不变",
            "confirmed": "项目已保存；从本次确认开始记录阻塞时长",
            "resolved": "项目已保存；阻塞已解除并保留解决说明",
        }
        self.statusBar().showMessage(blocker_messages.get((blocker_event or {}).get("action"), "项目已保存"), 3200 if blocker_event else 2000)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    for font_file in ("segoeui.ttf", "segoeuib.ttf", "msyh.ttc", "segmdl2.ttf"):
        font_path = Path("C:/Windows/Fonts") / font_file
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))
    families = set(QFontDatabase().families())
    family = "Noto Sans SC" if "Noto Sans SC" in families else "Microsoft YaHei UI"
    application_font = QFont(family, 10)
    application_font.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
    app.setFont(application_font)
    window = MainWindow(); window.show()
    sys.exit(app.exec_())
