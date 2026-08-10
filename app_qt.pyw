import json
import mmap
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PyQt5.QtCore import QDate, QMimeData, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QDrag, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFrame, QGridLayout,
    QFileDialog, QGraphicsScene, QGraphicsView, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QStatusBar, QStyle, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from codex_hub.management import (
    PROJECT_DECISION_FIELDS,
    PROJECT_DECISION_SOURCES,
    PROJECT_HEALTH,
    PROJECT_PRIORITY,
    PROJECT_STAGE,
    STATUS_COLOR,
    STATUS_TEXT,
    TASK_COLORS,
    TASK_EVENT_SOURCES,
    TASK_STATUS,
    active_task_records,
    archive_task_record,
    archive_project_layout,
    archived_task_records,
    build_project_decision_entry,
    build_project_alignment_entry,
    build_project_decision_rollback,
    build_project_lifecycle_entry,
    build_project_review_entry,
    clear_task_completion_outcome,
    compact_project_decision_value,
    display_project_decision_value,
    format_project_decision_summary,
    format_project_decision_time,
    merge_missing_project_insight,
    normalize_project_management_decision,
    normalized_action_text,
    normalized_decision_value,
    ordered_board_tasks,
    project_decision_changes,
    project_execution_alignment,
    project_governance_gaps,
    portfolio_execution_alignment_queue,
    project_review_status,
    project_management_validation_error,
    project_next_step_completion_update,
    project_next_step_reopen_update,
    record_task_completion_outcome,
    record_task_status_event,
    reorder_task_board,
    rollover_in_progress_tasks,
    restore_project_layout,
    restore_task_record,
    task_status_events,
    task_status_transition_allowed,
    task_is_archived,
    task_completion_outcome,
    task_completion_revisions,
)
from codex_hub.runtime import activity_state, analyze_session_records, find_codex_binary as locate_codex_binary, read_user_thread_rows

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


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def daily_summary_thread_id():
    configured = str(os.environ.get("CODEX_HUB_SUMMARY_THREAD_ID") or "").strip()
    if configured:
        return configured
    settings = load_json(SETTINGS_FILE, {})
    return str(settings.get("dailySummaryThreadId") or "").strip() if isinstance(settings, dict) else ""


def save_json(path, data):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
        temp = file.name
    os.replace(temp, path)


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


def normalized_path(value):
    path = str(value or "").replace("/", "\\")
    if path.startswith("\\\\?\\"):
        path = path[4:]
    return path.rstrip("\\").lower()


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
    return load_json(CODEX_GLOBAL_STATE, {})


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
        projects.append({
            **saved,
            "id": project_id,
            "savedId": saved.get("id"),
            "codexProjectId": project_id,
            "name": source.get("name") or saved.get("name") or Path(roots[0]).name,
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


_LOCAL_TOKEN_CACHE = {"date": None, "files": {}}


def local_codex_tokens_for_date(date_value=None):
    """Estimate daily usage from cumulative token_count events in local Codex logs."""
    target = date_value or datetime.now().date().isoformat()
    local_tz = datetime.now().astimezone().tzinfo
    try:
        target_start = datetime.strptime(target, "%Y-%m-%d").replace(tzinfo=local_tz)
    except ValueError:
        return 0
    cutoff_mtime = target_start.timestamp()
    if _LOCAL_TOKEN_CACHE.get("date") != target:
        _LOCAL_TOKEN_CACHE["date"] = target
        _LOCAL_TOKEN_CACHE["files"] = {}
    cache_files = _LOCAL_TOKEN_CACHE["files"]
    try:
        files = CODEX_SESSIONS.rglob("*.jsonl")
    except OSError:
        return 0
    for path in files:
        try:
            stat = path.stat()
            if stat.st_mtime < cutoff_mtime:
                continue
            cache_key = str(path)
            state = cache_files.get(cache_key, {"offset": 0, "previousTotal": None, "tokens": 0})
            if stat.st_size < state["offset"]:
                state = {"offset": 0, "previousTotal": None, "tokens": 0}
            previous_total = state["previousTotal"]
            with path.open("r", encoding="utf-8", errors="ignore") as stream:
                stream.seek(state["offset"])
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    if "token_count" not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = record.get("payload") or {}
                    if payload.get("type") != "token_count":
                        continue
                    usage = ((payload.get("info") or {}).get("total_token_usage") or {})
                    current_total = int(usage.get("total_tokens") or 0)
                    if current_total <= 0:
                        continue
                    delta = current_total if previous_total is None or current_total < previous_total else current_total - previous_total
                    previous_total = current_total
                    timestamp = record.get("timestamp") or record.get("at")
                    if not timestamp:
                        continue
                    try:
                        point = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                        if point.tzinfo is None:
                            point = point.replace(tzinfo=timezone.utc)
                        event_date = point.astimezone(local_tz).date().isoformat()
                    except ValueError:
                        continue
                    if event_date == target:
                        state["tokens"] += max(0, delta)
                state["offset"] = stream.tell()
            state["previousTotal"] = previous_total
            cache_files[cache_key] = state
        except OSError:
            continue
    return sum(int(state.get("tokens") or 0) for state in cache_files.values())


def read_codex_usage():
    binary = find_codex_binary()
    if not binary:
        return {"error": "未找到 Codex App Server"}
    process = None
    try:
        process = subprocess.Popen(
            [binary, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        messages = queue.Queue()

        def read_stdout():
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue

        threading.Thread(target=read_stdout, daemon=True).start()

        def send(message):
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()

        def response(request_id, timeout=12):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    message = messages.get(timeout=max(0.1, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if message.get("id") == request_id:
                    return message
            return None

        send({"method": "initialize", "id": 0, "params": {"clientInfo": {"name": "codex_project_hub", "title": "Codex Project Hub", "version": "0.3.0"}}})
        initialized = response(0)
        if not initialized or initialized.get("error"):
            return {"error": "Codex 用量连接初始化失败"}
        send({"method": "initialized", "params": {}})
        send({"method": "account/rateLimits/read", "id": 6, "params": {}})
        limits_response = response(6)
        send({"method": "account/usage/read", "id": 7, "params": {}})
        usage_response = response(7)
        limits = ((limits_response or {}).get("result") or {}).get("rateLimits") or {}
        usage = (usage_response or {}).get("result") or {}
        primary = limits.get("primary") or {}
        used = max(0, min(100, int(round(float(primary.get("usedPercent") or 0)))))
        reset_at = primary.get("resetsAt")
        reset_text = "暂无刷新时间"
        if reset_at:
            reset_text = datetime.fromtimestamp(float(reset_at)).strftime("%m月%d日 %H:%M")
        today = datetime.now().date().isoformat()
        buckets = usage.get("dailyUsageBuckets") or []
        official_today_tokens = next((int(item.get("tokens") or 0) for item in buckets if item.get("startDate") == today), None)
        local_today_tokens = local_codex_tokens_for_date(today)
        today_tokens = official_today_tokens if official_today_tokens is not None else local_today_tokens
        return {
            "usedPercent": used,
            "remainingPercent": 100 - used,
            "resetText": reset_text,
            "windowMinutes": primary.get("windowDurationMins"),
            "planType": limits.get("planType") or "",
            "todayTokens": today_tokens,
            "todayTokensSource": "official" if official_today_tokens is not None else "local",
            "localTodayTokens": local_today_tokens,
            "lifetimeTokens": int((usage.get("summary") or {}).get("lifetimeTokens") or 0),
            "syncedAt": datetime.now().strftime("%H:%M"),
        }
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return {"error": str(error)}
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


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
            "objective 用一句话说明最终交付或解决的问题；nextStep 必须是一个可以立刻执行的具体动作；"
            "blocker 没有明确证据时返回空字符串；summary 用 1-2 句话说明判断依据。\n"
            f"stage 只能是 {list(PROJECT_STAGE)} 之一；health 只能是 {list(PROJECT_HEALTH)} 之一。\n\n"
            "已有项目信息：\n" + json.dumps(context, ensure_ascii=False, indent=2)
        )
        schema = {
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "stage": {"type": "string", "enum": list(PROJECT_STAGE)},
                "health": {"type": "string", "enum": list(PROJECT_HEALTH)},
                "blocker": {"type": "string"},
                "nextStep": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["objective", "stage", "health", "blocker", "nextStep", "summary"],
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
                for key in ("objective", "blocker", "nextStep", "summary"):
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


def find_open_project_next_step_task(tasks, project, title, target_date):
    expected = normalized_action_text(title)
    return next(
        (
            task for task in tasks
            if task_matches_project(task, project)
            and not task_is_archived(task)
            and str(task.get("date") or "") == str(target_date or "")
            and task.get("status", "planned") != "done"
            and normalized_action_text(task.get("title")) == expected
        ),
        None,
    )


def build_project_next_step_task(project, target_date, now, conversation=None, task_id=None):
    title = str((project or {}).get("nextStep") or "").strip()
    stable_project_id = (project or {}).get("savedId") or (project or {}).get("codexProjectId") or (project or {}).get("id")
    conversation = conversation or {}
    task = {
        "id": task_id or str(uuid.uuid4()),
        "title": title,
        "category": (project or {}).get("category") or "未分类",
        "projectId": stable_project_id,
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
        and task.get("status", "planned") != "done"
    ]


def project_focus_state(project):
    """Resolve the live portfolio focus from deliberate priority and actual work."""
    if (project or {}).get("status", "active") != "active":
        status_text = STATUS_TEXT.get((project or {}).get("status"), "非活动")
        return False, "", f"项目状态为{status_text}，不计入当前重点", "#66758a", "#eef2f6"
    if project_priority_key(project) == "focus":
        return True, "重点", "已手动设为当前重点", "#7c3aed", "#f1eaff"
    active_tasks = int((project or {}).get("activeTaskCount") or 0)
    running_conversations = sum(
        codex_state(conversation)[0] == "running"
        for conversation in (project or {}).get("conversations") or []
    )
    if active_tasks:
        reason = f"今日 {active_tasks} 项任务进行中"
        if running_conversations:
            reason += f"，{running_conversations} 个 Codex 对话运行中"
        return True, "推进中", reason, "#1d4ed8", "#e8f0ff"
    if running_conversations:
        return True, "推进中", f"{running_conversations} 个 Codex 对话运行中", "#087443", "#e7f7ef"
    return False, "", "当前没有进行中的任务或 Codex 对话", "#66758a", "#eef2f6"


def project_stage_key(project):
    value = str((project or {}).get("stage") or "execution")
    return value if value in PROJECT_STAGE else "execution"


def project_health_key(project):
    value = str((project or {}).get("health") or "on_track")
    return value if value in PROJECT_HEALTH else "on_track"


def project_control_state(project):
    """Return the decision-facing project state and its most useful explanation."""
    if project.get("status") == "completed":
        return "completed", "已完成", "#2563eb", "#edf3ff", "项目已完成"
    if project.get("status") in {"paused", "idea"}:
        return "paused", STATUS_TEXT.get(project.get("status"), "暂缓"), "#7c3aed", "#f3edff", "当前不在主动推进"
    blocker = str(project.get("blocker") or "").strip()
    health = project_health_key(project)
    if health == "blocked" or blocker:
        return "blocked", "阻塞", "#b42318", "#fff0ee", blocker or "项目已标记阻塞"
    review_due, review_age, review_cadence = project_review_status(project)
    if health == "attention" and (not review_due or review_age is not None):
        return "attention", "需关注", "#b54708", "#fff4e5", "已确认关注；请处理风险并按复核节奏更新"
    if review_due:
        reason = (
            f"距离上次复核已 {review_age} 天，超过 {review_cadence} 天周期"
            if review_age is not None else
            "历史关注状态尚未经过当前复核"
        )
        return "review", "待复核", "#315f9b", "#edf4ff", reason
    if not str(project.get("nextStep") or "").strip():
        reason = "上一项下一步已完成，请明确后续动作" if project.get("nextStepReviewNeeded") else "尚未设置下一步"
        return "on_track", "正常", "#087443", "#e7f7ef", reason
    return "on_track", "正常", "#087443", "#e7f7ef", "按当前下一步推进"


def project_review_summary(project):
    due, age_days, cadence = project_review_status(project)
    reviewed_at = str((project or {}).get("reviewedAt") or "").strip()
    if reviewed_at:
        state = "已到复核周期" if due else f"{max(0, cadence - (age_days or 0))} 天后复核"
        return f"上次复核 {format_project_decision_time(reviewed_at, compact=True)} · {cadence} 天周期 · {state}"
    if due:
        return f"历史状态尚未确认 · 建议现在复核 · 后续每 {cadence} 天"
    return f"尚未建立复核节奏 · 确认后每 {cadence} 天自动提醒"


def project_management_scope_matches(project, scope):
    """Filter projects by decisions the user can act on, not by decorative metrics."""
    if scope == "focus":
        return project_focus_state(project)[0]
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
        return project_review_status(project)[0] and project_control_state(project)[0] != "blocked"
    if scope == "blocked":
        return project_control_state(project)[0] == "blocked"
    if scope == "paused":
        return project.get("status") in {"paused", "idea"}
    return True


def project_management_sort_key(project):
    priority_order = {"focus": 0, "normal": 1, "later": 2}
    control_order = {"blocked": 0, "attention": 1, "review": 2, "on_track": 3, "paused": 4, "completed": 5}
    return (
        control_order.get(project_control_state(project)[0], 2),
        0 if project_focus_state(project)[0] else priority_order.get(project_priority_key(project), 1) + 1,
        0 if project.get("nextStep") else 1,
        str(project.get("name") or "").casefold(),
    )


def portfolio_decision_groups(projects):
    ordered = sorted(projects or [], key=project_management_sort_key)
    return {
        "focus": [project for project in ordered if project_focus_state(project)[0]],
        "attention": [
            project for project in ordered
            if project_management_scope_matches(project, "attention")
        ],
        "review": [project for project in ordered if project_management_scope_matches(project, "review")],
        "needs_next": [
            project for project in ordered
            if project_management_scope_matches(project, "needs_next")
        ],
    }


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
        transitions = [
            {
                "at": str(event.get("at") or ""),
                "from": TASK_STATUS.get(event.get("from"), "新建"),
                "to": TASK_STATUS.get(event.get("to"), "更新"),
                "source": TASK_EVENT_SOURCES.get(event.get("source"), "手动"),
            }
            for event in reversed(task_status_events([task])[:8])
        ]
        selected_tasks.append({
            "title": str(task.get("title") or "未命名任务"),
            "status": TASK_STATUS.get(task.get("status", "planned"), "计划"),
            "project": str(project.get("name") or "未关联项目"),
            "notes": str(task.get("notes") or "").strip(),
            "completionOutcome": task_completion_outcome(task),
            "conversation": str(task.get("conversationTitle") or "").strip(),
            "statusTransitions": transitions,
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
            "kind": {"review": "项目复核", "alignment": "执行方向确认", "lifecycle": "项目生命周期"}.get(kind, "项目决策"),
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
        "projectDecisions 是人工确认的项目管理活动，可用于说明方向、阶段、风险和下一步发生了什么变化；它本身不等于交付成果，不能仅凭复核或字段变更写入 completed。\n"
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
        self.setWindowTitle("编辑项目" if project else "新建项目")
        self.setObjectName("projectEditor")
        self.setMinimumSize(720, 650)
        self.resize(760, 720)
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
        subtitle = QLabel("定义项目目标和下一步；项目中心不会修改或移动磁盘文件")
        subtitle.setStyleSheet("color: #718096; font-size: 12px;"); layout.addWidget(subtitle)
        self.fields = {}
        name = QLineEdit(item.get("name", "")); name.setFixedHeight(40); name.setPlaceholderText("例如：Desktop Analytics App"); name.setAccessibleName("项目名称"); self.fields["name"] = name
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
        form.addWidget(field_label("项目名称"), 0, 0, 1, 6); form.addWidget(name, 1, 0, 1, 6)
        form.addWidget(field_label("类别"), 2, 0, 1, 3); form.addWidget(field_label("项目状态"), 2, 3, 1, 3)
        form.addWidget(category, 3, 0, 1, 3); form.addWidget(status, 3, 3, 1, 3)
        form.addWidget(field_label("本地路径"), 4, 0, 1, 6)
        path_holder = QWidget(); path_layout = QHBoxLayout(path_holder); path_layout.setContentsMargins(0, 0, 0, 0); path_layout.setSpacing(7); path_layout.addWidget(path, 1)
        browse = QPushButton("选择文件夹"); browse.setFixedHeight(40); browse.setIcon(fluent_icon("\uE838", size=15)); browse.setIconSize(QSize(15, 15)); browse.clicked.connect(self.choose_folder); path_layout.addWidget(browse)
        form.addWidget(path_holder, 5, 0, 1, 6)
        form.addWidget(field_label("管理优先级"), 6, 0, 1, 2); form.addWidget(field_label("当前阶段"), 6, 2, 1, 2); form.addWidget(field_label("项目健康度"), 6, 4, 1, 2)
        form.addWidget(priority, 7, 0, 1, 2); form.addWidget(stage, 7, 2, 1, 2); form.addWidget(health, 7, 4, 1, 2)
        layout.addLayout(form)

        objective_label = field_label("项目目标"); layout.addWidget(objective_label)
        self.objective = QTextEdit(); self.objective.setFixedHeight(76); self.objective.setPlainText(str(item.get("objective") or ""))
        self.objective.setPlaceholderText("这个项目最终要交付或解决什么？")
        self.objective.setAccessibleName("项目目标"); layout.addWidget(self.objective)
        decision = QGridLayout(); decision.setHorizontalSpacing(10); decision.setVerticalSpacing(6)
        next_step_label = field_label("明确下一步"); decision.addWidget(next_step_label, 0, 0)
        blocker_label = field_label("当前阻塞"); decision.addWidget(blocker_label, 0, 1)
        self.next_step = QLineEdit(str(item.get("nextStep") or "")); self.next_step.setFixedHeight(40)
        self.next_step.setPlaceholderText("一个可以直接开始的具体动作")
        self.next_step.setAccessibleName("项目下一步"); decision.addWidget(self.next_step, 1, 0)
        self.blocker = QLineEdit(str(item.get("blocker") or "")); self.blocker.setFixedHeight(40)
        self.blocker.setPlaceholderText("没有阻塞可留空；有阻塞时写清具体原因")
        self.blocker.setAccessibleName("项目阻塞项"); decision.addWidget(self.blocker, 1, 1); layout.addLayout(decision)
        actions = QHBoxLayout(); actions.setContentsMargins(0, 10, 0, 0); actions.setSpacing(8)
        self.insight_button = QPushButton("Codex 自动整理"); self.insight_button.setFixedHeight(38); self.insight_button.setIcon(fluent_icon("\uE945", color="#1d4ed8", size=14)); self.insight_button.setIconSize(QSize(14, 14)); self.insight_button.clicked.connect(self.start_codex_insight); actions.addWidget(self.insight_button)
        self.insight_status = QLabel("选择文件夹后可让 Codex 填写项目态势"); self.insight_status.setMaximumWidth(280); self.insight_status.setStyleSheet("color: #748094; font-size: 11px;"); actions.addWidget(self.insight_status)
        actions.addStretch()
        cancel = QPushButton("取消"); cancel.setFixedHeight(38); cancel.clicked.connect(self.reject); actions.addWidget(cancel)
        save = QPushButton("保存项目"); save.setFixedHeight(38); save.setObjectName("primary"); save.clicked.connect(self.accept_project); actions.addWidget(save); layout.addLayout(actions)
        self.fields["name"].setFocus()

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
        if self.project and self.project.get("status", "active") != "completed" and data.get("status") == "completed":
            pending = open_project_tasks(getattr(self.parent(), "today_tasks", []), self.project)
            if pending:
                answer = QMessageBox.question(
                    self,
                    "项目仍有未完成任务",
                    f"这个项目仍关联 {len(pending)} 项未完成任务。\n\n继续会完成项目本身，但不会改写这些任务，便于你逐项确认。是否继续？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return
        self.accept()

    def value(self):
        data = {
            key: (control.currentData() if isinstance(control, QComboBox) else control.text().strip())
            for key, control in self.fields.items()
        }
        data["icon"] = (self.project or {}).get("icon", "")
        data["color"] = (self.project or {}).get("color", "#58d7f6")
        data["objective"] = self.objective.toPlainText().strip()
        data["nextStep"] = self.next_step.text().strip()
        data["blocker"] = self.blocker.text().strip()
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
    def __init__(self, project, state_text, state_color, state_background, handler):
        super().__init__()
        self.handler = handler
        self.setObjectName("projectMapRow")
        self.setFixedHeight(56)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("打开项目管理面板；总览不展开具体对话")
        control_key, control_label, control_color, _control_background, control_reason = project_control_state(project)
        stage_label = PROJECT_STAGE.get(project_stage_key(project), "执行")
        is_focus, focus_label, focus_reason, focus_color, focus_background = project_focus_state(project)
        focus_description = f"，{focus_label}：{focus_reason}" if is_focus else ""
        self.setAccessibleName(f"项目：{project.get('name') or '未命名项目'}，{stage_label}阶段，{control_label}{focus_description}，Codex {state_text}")
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
        dot.setToolTip(f"项目健康度：{control_label} · {control_reason}")
        dot.setStyleSheet(f"background: {control_color}; border: none; border-radius: 3px;")
        layout.addWidget(dot)
        text_box = QVBoxLayout(); text_box.setSpacing(1)
        title_row = QHBoxLayout(); title_row.setSpacing(6)
        name = ElidedLabel(project.get("name") or "未命名项目")
        name.setToolTip(project.get("name") or "未命名项目")
        name.setStyleSheet("color: #26364c; border: none; font-size: 13px; font-weight: 650;")
        title_row.addWidget(name, 1)
        if is_focus:
            focus = QLabel(focus_label); focus.setAlignment(Qt.AlignCenter); focus.setFixedSize(44, 20); focus.setToolTip(focus_reason)
            focus.setStyleSheet(f"color: {focus_color}; background: {focus_background}; border: none; border-radius: 7px; font-size: 10px; font-weight: 650;")
            title_row.addWidget(focus)
        text_box.addLayout(title_row)
        next_step = str(project.get("nextStep") or "").strip()
        if control_key in {"blocked", "review", "attention"}:
            control_text = f"{stage_label} · {control_label}：{control_reason}"
        else:
            control_text = f"{stage_label} · {next_step or control_reason}"
        next_label = ElidedLabel(control_text)
        next_label.setToolTip(f"阶段：{stage_label}\n健康度：{control_label}\n{control_reason}\n下一步：{next_step or '尚未设置'}")
        next_label.setStyleSheet(f"color: {control_color if control_key in {'blocked', 'review', 'attention'} else '#66758a'}; border: none; font-size: 10px;")
        text_box.addWidget(next_label)
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

        overview = QFrame()
        overview.setFixedSize(canvas_width - side_margin * 2, 58)
        overview.setObjectName("mapOverview")
        overview.setStyleSheet(
            "QFrame#mapOverview { background: transparent; border: none; }"
            "QLabel { border: none; background: transparent; }"
        )
        overview_layout = QHBoxLayout(overview)
        overview_layout.setContentsMargins(4, 0, 4, 0)
        overview_layout.setSpacing(10)
        accent = QLabel(); accent.setFixedSize(4, 30); accent.setStyleSheet("background: #2563eb; border-radius: 2px;")
        overview_layout.addWidget(accent)
        title_box = QVBoxLayout(); title_box.setSpacing(1)
        title = QLabel("项目驾驶舱"); title.setStyleSheet("color: #172033; font-size: 19px; font-weight: 700;")
        subtitle = QLabel("重点由今日任务、Codex 活动和人工优先级实时汇总")
        subtitle.setStyleSheet("color: #748094; font-size: 12px;")
        title_box.addWidget(title); title_box.addWidget(subtitle)
        overview_layout.addLayout(title_box)
        overview_layout.addStretch(1)
        focus_count = sum(project_focus_state(project)[0] for project in projects)
        blocked_count = sum(project_control_state(project)[0] == "blocked" for project in projects)
        attention_count = sum(project_control_state(project)[0] == "attention" for project in projects)
        review_count = sum(project_management_scope_matches(project, "review") for project in projects)
        summary = QLabel(f"{len(projects)} 个项目  ·  {focus_count} 个重点  ·  {blocked_count} 个阻塞  ·  {attention_count} 个风险  ·  {review_count} 个待复核")
        summary.setStyleSheet("color: #65758b; background: transparent; border: none; padding: 4px 2px; font-size: 12px; font-weight: 500;")
        overview_layout.addWidget(summary)
        overview_proxy = self.map_scene.addWidget(overview)
        overview_proxy.setPos(side_margin, 8)

        column_heights = [82] * columns
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
    def __init__(self, project, window):
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
        is_focus, focus_label, focus_reason, focus_color, focus_background = project_focus_state(project)
        if is_focus:
            focus = QLabel("当前重点" if focus_label == "重点" else "今日推进"); focus.setFixedSize(58, 20); focus.setAlignment(Qt.AlignCenter); focus.setToolTip(focus_reason)
            focus.setStyleSheet(f"color: {focus_color}; background: {focus_background}; border: none; border-radius: 7px; font-size: 10px; font-weight: 650;"); name_row.addWidget(focus)
        control_key, control_label, control_color, control_background, control_reason = project_control_state(project)
        health = QLabel(control_label); health.setFixedSize(48, 20); health.setAlignment(Qt.AlignCenter); health.setToolTip(control_reason)
        health.setStyleSheet(f"color: {control_color}; background: {control_background}; border: none; border-radius: 7px; font-size: 10px; font-weight: 650;"); name_row.addWidget(health)
        name_box.addLayout(name_row)
        next_step = str(project.get("nextStep") or "").strip()
        stage_label = PROJECT_STAGE.get(project_stage_key(project), "执行")
        detail_text = control_reason if control_key in {"blocked", "review", "attention"} else (next_step or control_reason)
        next_label = ElidedLabel(f"{stage_label} · {detail_text}"); next_label.setToolTip(f"阶段：{stage_label}\n健康度：{control_label}\n下一步：{next_step or '尚未设置'}")
        next_label.setStyleSheet(f"color: {control_color if control_key in {'blocked', 'review', 'attention'} else '#66758a'}; font-size: 10px; border: none;"); name_box.addWidget(next_label)
        layout.addLayout(name_box, 1)
        category_select = QComboBox(); category_select.setFixedSize(138, 34); category_select.addItems(window.categories[1:]); category_select.setCurrentText(project.get("category", "未分类")); category_select.setToolTip("调整项目分类"); category_select.setAccessibleName(f"{project['name']} 的项目分类")
        category_select.setStyleSheet("QComboBox { background: #f3f6fa; border: 1px solid transparent; border-radius: 8px; padding: 4px 10px; color: #526071; font-size: 12px; } QComboBox:hover, QComboBox:focus { background: #eef3f8; border-color: #cbd7e5; } QComboBox::drop-down { border: none; width: 22px; }")
        category_select.activated[str].connect(lambda category: window.change_project_category(project, category)); layout.addWidget(category_select)
        state_key, state_label, status_color, status_background = project_display_state(project)
        status_text = f"● {state_label}"
        count = QLabel(f"{len(self.conversations)} 个对话"); count.setFixedWidth(72); count.setAlignment(Qt.AlignRight | Qt.AlignVCenter); count.setStyleSheet("color: #748094; font-size: 11px; border: none;"); layout.addWidget(count)
        status = QLabel(status_text); status.setFixedWidth(78); status.setAlignment(Qt.AlignCenter); status.setStyleSheet(f"color: {status_color}; background: {status_background}; border-radius: 9px; padding: 4px 7px; font-size: 11px; font-weight: 650;"); layout.addWidget(status)
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
        governance_action.setEnabled(bool(project_governance_gaps(project)) and Path(str(project.get("path") or "")).is_dir() and project.get("status", "active") != "completed")
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


class TaskEditor(QDialog):
    def __init__(self, parent, projects, task=None, default_date=None, default_status=None, default_project_id=None):
        super().__init__(parent)
        self.projects = projects
        self.task = task or {}
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
        for project in projects:
            category = project.get("category") or "未分类"
            if category not in categories: categories.append(category)
        current_project_id = self.task.get("projectId") or default_project_id
        current_project = next(
            (item for item in projects if str(current_project_id or "") in project_reference_ids(item)),
            None,
        )
        if current_project:
            current_project_id = current_project.get("id")
        current_category = (current_project or {}).get("category") or self.task.get("category")
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
        layout.addWidget(QLabel("当前阶段")); self.status_field = QComboBox(); self.status_field.setFixedHeight(38); self.status_field.setAccessibleName("当前阶段")
        for status, label in TASK_STATUS.items(): self.status_field.addItem(label, status)
        status_index = self.status_field.findData(self.task.get("status") or default_status or "planned"); self.status_field.setCurrentIndex(max(0, status_index)); layout.addWidget(self.status_field)
        layout.addWidget(QLabel("备注")); self.notes_field = QTextEdit(self.task.get("notes", "")); self.notes_field.setFixedHeight(88); self.notes_field.setAccessibleName("任务备注"); self.notes_field.setPlaceholderText("补充交付标准、重点或下一步…"); layout.addWidget(self.notes_field)
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
        return {
            "title": self.title_field.text().strip(),
            "category": self.category_field.currentData(),
            "projectId": self.project_field.currentData(),
            "sessionId": self.conversation_field.currentData(),
            "conversationTitle": self.conversation_field.currentText() if self.conversation_field.currentData() else "",
            "status": self.status_field.currentData(),
            "date": self.date_field.date().toString(Qt.ISODate),
            "notes": self.notes_field.toPlainText().strip(),
            "completionNote": self.outcome_field.toPlainText().strip(),
        }


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


class TodayTaskCard(QFrame):
    def __init__(self, task, window):
        super().__init__()
        self.task_id = str((task or {}).get("id") or "")
        self.setObjectName("todayTaskCard")
        project = window.project_by_id(task.get("projectId")); project_name = (project or {}).get("name") or "未关联项目"
        conversation = window.conversation_by_id(task.get("sessionId")); conversation_title = conversation_name(conversation) if conversation else task.get("conversationTitle") or "未关联 Codex"
        conversation_state = codex_state(conversation)[0] if conversation else None
        accent = TASK_COLORS.get(task.get("status"), "#64748b")
        tint = {"planned": "#f4efff", "doing": "#eaf2ff", "done": "#e8f7ef"}.get(task.get("status"), "#eef4fb")
        self.setStyleSheet(f"QFrame#todayTaskCard {{ background: #ffffff; border: 1px solid #d9e2ec; border-left: 3px solid {accent}; border-radius: 10px; }} QFrame#todayTaskCard:hover {{ background: #fbfdff; border-color: #9eb4ce; border-left-color: {accent}; }}")
        root = QVBoxLayout(self); root.setContentsMargins(12, 10, 10, 9); root.setSpacing(7)
        headline = QHBoxLayout(); headline.setSpacing(8)
        title = QLabel(task.get("title") or "未命名任务"); title.setWordWrap(True); title.setStyleSheet("font-size: 14px; font-weight: 680; color: #253247; border: none;"); headline.addWidget(title, 1)
        headline.addWidget(TaskDragHandle(task), 0, Qt.AlignTop)
        root.addLayout(headline)
        meta_row = QHBoxLayout(); meta_row.setSpacing(7)
        meta = ElidedLabel(f"{project_name}  ·  {conversation_title}"); meta.setStyleSheet("color: #66758a; font-size: 11px; border: none;"); meta_row.addWidget(meta, 1)
        if conversation_state == "running":
            live = QLabel("● Codex 运行中"); live.setStyleSheet("color: #087443; background: #e3f6ec; border: 1px solid #b6e1c9; border-radius: 8px; padding: 3px 7px; font-size: 10px; font-weight: 700;"); meta_row.addWidget(live)
        elif not task.get("sessionId") and task.get("origin") != "project_next_step":
            manual = QLabel("手动状态"); manual.setToolTip("未关联具体 Codex 对话，因此不会自动切换任务状态")
            manual.setStyleSheet("color: #8a5a00; background: #fff4d8; border: none; border-radius: 7px; padding: 3px 7px; font-size: 11px; font-weight: 600;")
            meta_row.addWidget(manual)
        if task.get("origin") == "project_next_step":
            source_step = QLabel("项目下一步"); source_step.setToolTip("从项目面板的一项明确下一步加入；完成后项目会等待新的下一步")
            source_step.setStyleSheet("color: #315f9b; background: #eaf2ff; border: none; border-radius: 7px; padding: 3px 7px; font-size: 11px; font-weight: 600;")
            meta_row.addWidget(source_step)
        if task.get("carriedFromTaskId"):
            carried = QLabel("延续任务"); carried.setToolTip(f"由 {task.get('carriedFromDate', '前一天')} 的进行中任务自动延续")
            carried.setStyleSheet("color: #315f9b; background: #eaf2ff; border: none; border-radius: 7px; padding: 3px 7px; font-size: 11px; font-weight: 500;")
            meta_row.addWidget(carried)
        root.addLayout(meta_row)
        if task.get("notes"):
            notes = ElidedLabel(task["notes"].replace("\n", " ")); notes.setStyleSheet("color: #526071; font-size: 11px; border: none;"); root.addWidget(notes)
        completion_outcome = task_completion_outcome(task)
        if completion_outcome:
            outcome_row = QFrame(); outcome_row.setObjectName("completionOutcome")
            outcome_row.setStyleSheet("QFrame#completionOutcome { background: #eef8f2; border: 1px solid #c8e5d3; border-radius: 8px; } QFrame#completionOutcome QLabel { border: none; background: transparent; }")
            outcome_layout = QHBoxLayout(outcome_row); outcome_layout.setContentsMargins(9, 6, 9, 6); outcome_layout.setSpacing(7)
            outcome_icon = QLabel(); outcome_icon.setFixedSize(16, 16); outcome_icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=13).pixmap(QSize(13, 13))); outcome_layout.addWidget(outcome_icon)
            outcome_text = ElidedLabel(f"成果 · {completion_outcome.replace(chr(10), ' ')}"); outcome_text.setToolTip(completion_outcome); outcome_text.setStyleSheet("color: #17623b; font-size: 11px; font-weight: 600;"); outcome_layout.addWidget(outcome_text, 1)
            root.addWidget(outcome_row)
        actions = QHBoxLayout(); actions.setSpacing(6)
        status = QComboBox(); status.setFixedSize(86, 30); status.setToolTip("调整任务状态")
        for value, label in TASK_STATUS.items(): status.addItem(label, value)
        status.setCurrentIndex(max(0, status.findData(task.get("status", "planned"))))
        status.setStyleSheet(f"QComboBox {{ background: {tint}; color: {accent}; border: 1px solid {accent}; border-radius: 8px; padding: 2px 8px; font-size: 11px; font-weight: 650; }} QComboBox::drop-down {{ border: none; width: 18px; }}")
        status.activated.connect(lambda _index: window.set_task_status(task["id"], status.currentData(), source="selector")); actions.addWidget(status); actions.addStretch()
        if task.get("status") == "done" and not completion_outcome:
            record_outcome = QPushButton("记录成果"); record_outcome.setFixedSize(88, 30)
            record_outcome.setIcon(fluent_icon("\uE73E", color="#16803c", size=13)); record_outcome.setIconSize(QSize(13, 13)); record_outcome.setToolTip("补充实际完成结果，供项目交接与每日总结使用")
            record_outcome.setStyleSheet("QPushButton { color: #126b3b; background: #eaf7ef; border: 1px solid #b9dfc8; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 650; } QPushButton:hover { background: #dff2e7; border-color: #88cda4; }")
            record_outcome.clicked.connect(lambda: window.edit_task_outcome(task)); actions.addWidget(record_outcome)
        if task.get("sessionId"):
            open_codex = QPushButton("打开 Codex")
            open_codex.setFixedSize(96, 30)
            open_codex.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14))
            open_codex.setIconSize(QSize(14, 14))
            open_codex.setToolTip("打开关联的 Codex 对话")
            open_codex.setAccessibleName(f"打开任务 {task.get('title', '')} 的 Codex 对话")
            open_codex.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c7d7f2; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 650; } QPushButton:hover { background: #dfe9fb; border-color: #9db7e4; }")
            open_codex.clicked.connect(lambda: window.open_task_conversation(task))
            actions.addWidget(open_codex)
        more = QToolButton(); more.setFixedSize(32, 30); more.setIcon(fluent_icon("\uE712", size=14)); more.setIconSize(QSize(14, 14)); more.setToolTip("更多操作")
        more.setAccessibleName(f"任务 {task.get('title', '')} 的更多操作")
        more.setStyleSheet("QToolButton { border: none; border-radius: 7px; background: transparent; } QToolButton:hover { background: #eaf1fa; } QToolButton::menu-indicator { image: none; }")
        menu = QMenu(more)
        audit_action = menu.addAction(fluent_icon("\uE81C", color="#315f9b", size=14), "查看任务记录")
        audit_action.triggered.connect(lambda: window.show_task_audit(task))
        menu.addSeparator()
        edit_action = menu.addAction(fluent_icon("\uE70F", size=14), "编辑任务")
        edit_action.triggered.connect(lambda: window.edit_today_task(task))
        if task.get("status") == "done":
            outcome_action = menu.addAction(fluent_icon("\uE73E", color="#16803c", size=14), "编辑完成成果" if completion_outcome else "记录完成成果")
            outcome_action.triggered.connect(lambda: window.edit_task_outcome(task))
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
        project = self.window.project_by_id(self.task.get("projectId")); project_name = (project or {}).get("name") or "未关联项目"
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
        project = window.project_by_id(task.get("projectId")); project_name = (project or {}).get("name") or "未关联项目"
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
        subtitle = QLabel("保留每天的计划、进行中和已完成状态；进行中任务会延续到下一天")
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
            project = self.window.project_by_id(task.get("projectId")); project_name = (project or {}).get("name") or "未关联项目"
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
                    text = QLabel(item); text.setWordWrap(True); text.setStyleSheet("color: #42526a; font-size: 12px;"); row.addWidget(text, 1); card_layout.addLayout(row)
            content_layout.addWidget(card)
        content_layout.addStretch(); scroll.setWidget(content); root.addWidget(scroll, 1)

        actions = QHBoxLayout(); actions.setSpacing(8)
        open_thread = QPushButton("打开总结对话"); open_thread.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); open_thread.setIconSize(QSize(14, 14)); open_thread.clicked.connect(parent.open_daily_summary_thread); actions.addWidget(open_thread)
        regenerate = QPushButton("重新生成"); regenerate.setIcon(fluent_icon("\uE72C", color="#1d4ed8", size=13)); regenerate.setIconSize(QSize(13, 13)); regenerate.clicked.connect(self.regenerate); actions.addWidget(regenerate)
        actions.addStretch(); close = QPushButton("关闭"); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)

    def regenerate(self):
        self.accept()
        self.window.start_daily_summary(force=True)


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
            source = QLabel(source_text); source.setAlignment(Qt.AlignCenter); source.setStyleSheet("color: #315f9b; background: #eaf2ff; border: none; border-radius: 7px; padding: 4px 8px; font-size: 10px; font-weight: 650;"); header.addWidget(source)
            if entry.get("changes") and self.allow_rollback:
                rollback = QPushButton("恢复到变更前"); rollback.setFixedHeight(30); rollback.setIcon(fluent_icon("\uE7A7", color="#526071", size=12)); rollback.setIconSize(QSize(12, 12))
                rollback.setToolTip("仅恢复这条记录中发生变化的字段，并保留一条新的回滚记录")
                rollback.clicked.connect(lambda _checked=False, value=entry: self.rollback_entry(value)); header.addWidget(rollback)
            card_layout.addLayout(header)
            if entry.get("kind") in {"review", "alignment", "lifecycle"}:
                review_line = QLabel(format_project_decision_summary(entry)); review_line.setWordWrap(True)
                review_line.setStyleSheet("color: #526071; background: #f7f9fc; border: none; border-radius: 7px; padding: 7px 9px; font-size: 12px;"); card_layout.addWidget(review_line)
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


class PortfolioReviewDialog(QDialog):
    """A deliberate one-project-at-a-time review flow; never bulk-confirms state."""
    def __init__(self, parent, projects):
        super().__init__(parent)
        self.window = parent
        self.pending = list(projects or [])
        self.reviewed_count = 0
        self.setWindowTitle("项目复核")
        self.setObjectName("portfolioReviewDialog")
        self.setMinimumSize(720, 520)
        self.resize(780, 570)
        self.setStyleSheet(STYLE + """
            QDialog#portfolioReviewDialog QLabel[sectionLabel='true'] { color: #66758a; font-size: 11px; font-weight: 650; }
        """)
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 22); root.setSpacing(14)

        heading = QHBoxLayout(); heading.setSpacing(11)
        icon = QLabel(); icon.setFixedSize(40, 40); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(fluent_icon("\uE73E", color="#1d4ed8", size=20).pixmap(QSize(20, 20)))
        icon.setStyleSheet("background: #eaf1ff; border: 1px solid #c9d9f6; border-radius: 11px;"); heading.addWidget(icon)
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("逐项确认项目现状"); title.setStyleSheet("color: #172033; font-size: 23px; font-weight: 720;"); title_box.addWidget(title)
        subtitle = QLabel("核对目标、健康度和下一步；只有点击“确认现状”才会写入审计记录")
        subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box, 1)
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
        self.open_button = QPushButton("打开项目面板"); self.open_button.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); self.open_button.setIconSize(QSize(14, 14)); self.open_button.clicked.connect(self.open_current); actions.addWidget(self.open_button)
        self.skip_button = QPushButton("稍后处理"); self.skip_button.clicked.connect(self.skip_current); actions.addWidget(self.skip_button)
        self.confirm_button = QPushButton("确认现状"); self.confirm_button.setObjectName("primary"); self.confirm_button.setIcon(fluent_icon("\uE73E", color="#ffffff", size=14)); self.confirm_button.setIconSize(QSize(14, 14)); self.confirm_button.clicked.connect(self.confirm_current); actions.addWidget(self.confirm_button)
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
        remaining = len(self.pending)
        total = self.reviewed_count + remaining
        self.counter.setText(f"{self.reviewed_count + 1} / {total}" if remaining else f"已完成 {self.reviewed_count}")
        self.open_button.setVisible(bool(remaining)); self.skip_button.setVisible(bool(remaining)); self.skip_button.setEnabled(remaining > 1)
        self.confirm_button.setText("确认现状" if remaining else "关闭")
        if not remaining:
            done_icon = QLabel(); done_icon.setFixedSize(54, 54); done_icon.setAlignment(Qt.AlignCenter)
            done_icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=28).pixmap(QSize(28, 28))); done_icon.setStyleSheet("background: #e8f7ef; border-radius: 15px;")
            self.card_layout.addStretch(); self.card_layout.addWidget(done_icon, 0, Qt.AlignCenter)
            done = QLabel("本轮项目复核已完成"); done.setAlignment(Qt.AlignCenter); done.setStyleSheet("color: #172033; font-size: 20px; font-weight: 720;"); self.card_layout.addWidget(done)
            detail = QLabel(f"已确认 {self.reviewed_count} 个项目；新的复核日期和周期已经写入决策记录")
            detail.setAlignment(Qt.AlignCenter); detail.setWordWrap(True); detail.setStyleSheet("color: #66758a; font-size: 12px;"); self.card_layout.addWidget(detail)
            self.card_layout.addStretch(); self.feedback.setText("主页和项目页的待复核数量已同步更新。")
            self.feedback.setStyleSheet("color: #087443; background: #e8f7ef; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
            return

        project = self.current_project()
        _review_due, review_age, review_cadence = project_review_status(project)
        review_reason = (
            f"距离上次复核已 {review_age} 天，已到 {review_cadence} 天复核周期"
            if review_age is not None else
            "历史关注状态尚未经过当前复核"
        )
        name_row = QHBoxLayout(); name_row.setSpacing(9)
        name = QLabel(project.get("name") or "未命名项目"); name.setWordWrap(True); name.setStyleSheet("color: #172033; font-size: 20px; font-weight: 720;"); name_row.addWidget(name, 1)
        priority = QLabel(PROJECT_PRIORITY.get(project_priority_key(project), "常规推进")); priority.setAlignment(Qt.AlignCenter)
        priority.setStyleSheet("color: #1d4ed8; background: #edf3ff; border-radius: 8px; padding: 5px 9px; font-size: 10px; font-weight: 650;"); name_row.addWidget(priority)
        self.card_layout.addLayout(name_row)
        reason = QLabel(f"待复核原因 · {review_reason}"); reason.setWordWrap(True)
        reason.setStyleSheet("color: #315f9b; background: #edf4ff; border-radius: 8px; padding: 8px 10px; font-size: 11px; font-weight: 600;"); self.card_layout.addWidget(reason)

        metrics = QHBoxLayout(); metrics.setSpacing(9)
        metric_values = (
            ("当前阶段", PROJECT_STAGE.get(project_stage_key(project), "执行")),
            ("健康度", PROJECT_HEALTH.get(project_health_key(project), "正常")),
            ("复核节奏", project_review_summary(project)),
        )
        for caption, value in metric_values:
            metric = QFrame(); metric.setObjectName("reviewMetric"); metric.setStyleSheet("QFrame#reviewMetric { background: #f7f9fc; border: 1px solid #e0e7ef; border-radius: 9px; }")
            metric_layout = QVBoxLayout(metric); metric_layout.setContentsMargins(11, 8, 11, 9); metric_layout.setSpacing(2)
            label = QLabel(caption); label.setProperty("sectionLabel", True); metric_layout.addWidget(label)
            text = ElidedLabel(value); text.setToolTip(value); text.setStyleSheet("color: #34445c; font-size: 12px; font-weight: 650;"); metric_layout.addWidget(text); metrics.addWidget(metric, 1)
        self.card_layout.addLayout(metrics)

        for caption, value, fallback in (
            ("项目目标", project.get("objective"), "尚未明确项目目标"),
            ("当前下一步", project.get("nextStep"), "尚未设置下一步"),
        ):
            label = QLabel(caption); label.setProperty("sectionLabel", True); self.card_layout.addWidget(label)
            text = QLabel(str(value or fallback)); text.setWordWrap(True)
            text.setStyleSheet("color: #34445c; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 9px; padding: 9px 11px; font-size: 12px;"); self.card_layout.addWidget(text)

        legacy_attention = project_health_key(project) == "attention" and not str(project.get("reviewedAt") or "").strip()
        if legacy_attention:
            self.feedback.setText("当前保存的是历史“需关注”状态：若风险仍存在，可确认现状；若已恢复正常，请先打开项目面板修改健康度。")
            self.feedback.setStyleSheet("color: #8a5a00; background: #fff7e6; border-radius: 8px; padding: 7px 9px; font-size: 11px;")
        else:
            self.feedback.setText("确认后将按项目优先级重新计算下一次复核日期，不会修改目标、健康度或下一步。")
            self.feedback.setStyleSheet("color: #66758a; font-size: 11px;")

    def skip_current(self):
        if len(self.pending) <= 1:
            return
        self.pending.append(self.pending.pop(0))
        self.render_current()

    def open_current(self):
        project = self.current_project()
        if project is None:
            return
        self.accept()
        self.window.open_project_workspace(project)

    def confirm_current(self):
        project = self.current_project()
        if project is None:
            self.accept(); return
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
        subtitle = QLabel("逐项确认正在做的工作是否应成为项目下一步；系统不会自动覆盖你的决策")
        subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box, 1)
        self.counter = QLabel(); self.counter.setAlignment(Qt.AlignCenter); self.counter.setFixedHeight(28)
        self.counter.setStyleSheet("color: #315f9b; background: #eaf2ff; border-radius: 8px; padding: 2px 10px; font-size: 11px; font-weight: 650;"); heading.addWidget(self.counter)
        root.addLayout(heading)

        self.card = QFrame(); self.card.setObjectName("alignmentCard")
        self.card.setStyleSheet("QFrame#alignmentCard { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 13px; } QFrame#alignmentCard QLabel { background: transparent; border: none; }")
        self.card_layout = QVBoxLayout(self.card); self.card_layout.setContentsMargins(20, 18, 20, 20); self.card_layout.setSpacing(12); root.addWidget(self.card, 1)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); self.feedback.setStyleSheet("color: #66758a; font-size: 11px;"); root.addWidget(self.feedback)

        actions = QHBoxLayout(); actions.setSpacing(8)
        close = QPushButton("关闭"); close.clicked.connect(self.reject); actions.addWidget(close); actions.addStretch()
        self.open_button = QPushButton("打开项目面板"); self.open_button.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); self.open_button.setIconSize(QSize(14, 14)); self.open_button.clicked.connect(self.open_current); actions.addWidget(self.open_button)
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
        self.accept(); self.window.open_project_workspace(alignment.get("project") or {})

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
        subtitle = QLabel(f"{project.get('category', '未分类')}  ·  在一个地方维护目标、下一步、任务和 Codex 对话")
        subtitle.setStyleSheet("color: #66758a; font-size: 12px;"); title_box.addWidget(subtitle); heading.addLayout(title_box, 1)
        is_focus, focus_text, focus_reason, focus_color, focus_background = project_focus_state(project)
        if is_focus:
            focus = QLabel(focus_text); focus.setAlignment(Qt.AlignCenter); focus.setFixedSize(64, 30); focus.setToolTip(focus_reason)
            focus.setStyleSheet(f"color: {focus_color}; background: {focus_background}; border-radius: 9px; font-size: 11px; font-weight: 650;"); heading.addWidget(focus)
        _control_key, control_text, control_color, control_background, control_reason = project_control_state(project)
        self.control_badge = QLabel(control_text); self.control_badge.setAlignment(Qt.AlignCenter); self.control_badge.setFixedSize(64, 30); self.control_badge.setToolTip(control_reason)
        self.control_badge.setStyleSheet(f"color: {control_color}; background: {control_background}; border-radius: 9px; font-size: 11px; font-weight: 650;"); heading.addWidget(self.control_badge)
        _state, state_text, state_color, state_background = project_display_state(project)
        self.project_state_badge = QLabel(f"● {state_text}"); self.project_state_badge.setAlignment(Qt.AlignCenter); self.project_state_badge.setFixedSize(78, 30)
        self.project_state_badge.setStyleSheet(f"color: {state_color}; background: {state_background}; border-radius: 9px; font-size: 11px; font-weight: 650;"); heading.addWidget(self.project_state_badge)
        continue_button = QPushButton("在 Codex 中继续"); continue_button.setObjectName("primary"); continue_button.setFixedHeight(38)
        continue_button.setIcon(fluent_icon("\uE72A", color="#ffffff", size=15)); continue_button.setIconSize(QSize(15, 15)); continue_button.clicked.connect(self.continue_in_codex); heading.addWidget(continue_button)
        root.addLayout(heading)

        management = QFrame(); management.setObjectName("managementCard")
        management.setStyleSheet("QFrame#managementCard { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 12px; }")
        management_layout = QVBoxLayout(management); management_layout.setContentsMargins(18, 15, 18, 17); management_layout.setSpacing(10)
        management_head = QHBoxLayout(); management_head.setSpacing(9)
        management_title = QLabel("项目决策"); management_title.setProperty("sectionTitle", True); management_head.addWidget(management_title)
        management_head.addStretch()
        self.review_meta = QLabel(project_review_summary(project)); self.review_meta.setStyleSheet("color: #66758a; font-size: 10px;"); management_head.addWidget(self.review_meta)
        review_button = QPushButton("确认现状"); review_button.setFixedHeight(32); review_button.setIcon(fluent_icon("\uE73E", color="#1d4ed8", size=13)); review_button.setIconSize(QSize(13, 13))
        review_button.setToolTip("确认当前目标、阶段、健康度和下一步仍然有效，并建立自动复核周期")
        review_button.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c8d8f4; border-radius: 8px; padding: 4px 9px; font-size: 11px; font-weight: 650; } QPushButton:hover, QPushButton:focus { background: #dfe9fb; border-color: #9eb8e4; }")
        review_button.clicked.connect(self.confirm_current_state); management_head.addWidget(review_button); management_layout.addLayout(management_head)
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
        management_layout.addLayout(meta)
        objective_label = QLabel("项目目标"); objective_label.setProperty("fieldLabel", True); management_layout.addWidget(objective_label)
        self.objective_field = QTextEdit(); self.objective_field.setFixedHeight(66); self.objective_field.setPlainText(str(project.get("objective") or ""))
        self.objective_field.setPlaceholderText("这个项目最终要交付或解决什么？"); management_layout.addWidget(self.objective_field)
        next_row = QHBoxLayout(); next_row.setSpacing(9)
        next_box = QVBoxLayout(); next_box.setSpacing(5); next_label = QLabel("明确下一步"); next_label.setProperty("fieldLabel", True); next_box.addWidget(next_label)
        self.next_step_field = QLineEdit(str(project.get("nextStep") or "")); self.next_step_field.setFixedHeight(40); self.next_step_field.setPlaceholderText("一个可以直接开始的具体动作"); next_box.addWidget(self.next_step_field); next_row.addLayout(next_box, 1)
        blocker_box = QVBoxLayout(); blocker_box.setSpacing(5); blocker_label = QLabel("当前阻塞"); blocker_label.setProperty("fieldLabel", True); blocker_box.addWidget(blocker_label)
        self.blocker_field = QLineEdit(str(project.get("blocker") or "")); self.blocker_field.setFixedHeight(40); self.blocker_field.setPlaceholderText("没有阻塞可留空"); blocker_box.addWidget(self.blocker_field); next_row.addLayout(blocker_box, 1)
        schedule = QPushButton("加入今日"); schedule.setFixedHeight(40); schedule.setIcon(fluent_icon("\uE787", color="#1d4ed8", size=14)); schedule.setIconSize(QSize(14, 14)); schedule.setToolTip("把当前项目下一步直接加入今日任务，并保留项目关联"); schedule.clicked.connect(self.schedule_next_step); next_row.addWidget(schedule, 0, Qt.AlignBottom)
        save = QPushButton("保存项目决策"); save.setFixedHeight(40); save.setIcon(fluent_icon("\uE74E", color="#1d4ed8", size=14)); save.setIconSize(QSize(14, 14)); save.clicked.connect(lambda: self.save_changes()); next_row.addWidget(save, 0, Qt.AlignBottom)
        management_layout.addLayout(next_row)
        last_outcome = str(project.get("lastCompletedOutcome") or "").strip()
        if last_outcome:
            outcome_strip = QFrame(); outcome_strip.setObjectName("projectOutcomeStrip")
            outcome_strip.setStyleSheet("QFrame#projectOutcomeStrip { background: #eef8f2; border: 1px solid #c8e5d3; border-radius: 9px; } QFrame#projectOutcomeStrip QLabel { border: none; background: transparent; }")
            outcome_layout = QHBoxLayout(outcome_strip); outcome_layout.setContentsMargins(11, 7, 11, 7); outcome_layout.setSpacing(8)
            outcome_icon = QLabel(); outcome_icon.setFixedSize(18, 18); outcome_icon.setPixmap(fluent_icon("\uE73E", color="#16803c", size=14).pixmap(QSize(14, 14))); outcome_layout.addWidget(outcome_icon)
            outcome_title = QLabel("最近完成成果"); outcome_title.setStyleSheet("color: #17623b; font-size: 11px; font-weight: 700;"); outcome_layout.addWidget(outcome_title)
            outcome_text = ElidedLabel(last_outcome.replace("\n", " ")); outcome_text.setToolTip(last_outcome); outcome_text.setStyleSheet("color: #456a55; font-size: 11px;"); outcome_layout.addWidget(outcome_text, 1)
            management_layout.addWidget(outcome_strip)
        root.addWidget(management)

        self.decision_history_frame = ClickableFrame(); self.decision_history_frame.setObjectName("decisionHistoryStrip"); self.decision_history_frame.setFixedHeight(52)
        self.decision_history_frame.setAccessibleName("查看项目决策记录"); self.decision_history_frame.setToolTip("查看这个项目的目标、阶段、健康度和下一步等真实变更")
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

        lower = QHBoxLayout(); lower.setSpacing(12)
        tasks_card = QFrame(); tasks_card.setObjectName("projectTasksCard"); tasks_card.setStyleSheet("QFrame#projectTasksCard { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 12px; }")
        tasks_layout = QVBoxLayout(tasks_card); tasks_layout.setContentsMargins(16, 14, 16, 14); tasks_layout.setSpacing(8)
        task_head = QHBoxLayout(); task_title = QLabel("今日任务"); task_title.setProperty("sectionTitle", True); task_head.addWidget(task_title); task_head.addStretch()
        add_task = QPushButton("新建关联任务"); add_task.setFixedHeight(32); add_task.setIcon(fluent_icon("\uE710", color="#1d4ed8", size=13)); add_task.setIconSize(QSize(13, 13)); add_task.clicked.connect(self.new_task); task_head.addWidget(add_task); tasks_layout.addLayout(task_head)
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
        root.addLayout(lower, 1)

        actions = QHBoxLayout(); actions.setSpacing(8)
        folder = QPushButton("打开项目文件夹"); folder.setIcon(fluent_icon("\uE838", size=14)); folder.setIconSize(QSize(14, 14)); folder.clicked.connect(lambda: parent.open_folder(project)); actions.addWidget(folder)
        edit = QPushButton("完整编辑"); edit.setIcon(fluent_icon("\uE70F", size=14)); edit.setIconSize(QSize(14, 14)); edit.clicked.connect(self.full_edit); actions.addWidget(edit)
        actions.addStretch(); close = QPushButton("关闭"); close.clicked.connect(self.accept); actions.addWidget(close); root.addLayout(actions)
        self.render_tasks()
        self.render_decision_history()

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

    def render_decision_history(self):
        entries = self.window.project_decisions_for(self.project)
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
        self.next_step_field.setText(str(data.get("nextStep") or ""))
        self.blocker_field.setText(str(data.get("blocker") or ""))

    def refresh_header_states(self):
        _key, text, color, background, reason = project_control_state(self.project)
        self.control_badge.setText(text); self.control_badge.setToolTip(reason)
        self.control_badge.setStyleSheet(f"color: {color}; background: {background}; border-radius: 9px; font-size: 11px; font-weight: 650;")
        _state, state_text, state_color, state_background = project_display_state(self.project)
        self.project_state_badge.setText(f"● {state_text}")
        self.project_state_badge.setStyleSheet(f"color: {state_color}; background: {state_background}; border-radius: 9px; font-size: 11px; font-weight: 650;")
        self.review_meta.setText(project_review_summary(self.project))

    def confirm_current_state(self):
        before = dict(self.project)
        if not self.save_changes(notify=False):
            return
        changed = bool(project_decision_changes(before, self.project))
        self.window.record_project_review(self.project, audit=not changed)
        self.refresh_header_states()
        self.render_decision_history()

    def save_changes(self, notify=True):
        data = {
            "priority": self.priority_field.currentData(),
            "status": self.status_field.currentData(),
            "category": self.category_field.currentData(),
            "stage": self.stage_field.currentData(),
            "health": self.health_field.currentData(),
            "objective": self.objective_field.toPlainText().strip(),
            "nextStep": self.next_step_field.text().strip(),
            "blocker": self.blocker_field.text().strip(),
        }
        data, _notes = normalize_project_management_decision(self.project, data)
        validation_error = project_management_validation_error(data)
        if validation_error:
            self.blocker_field.setFocus(); QMessageBox.information(self, "项目决策不完整", validation_error)
            return False
        if self.project.get("status", "active") != "completed" and data.get("status") == "completed":
            pending = open_project_tasks(self.window.today_tasks, self.project)
            if pending:
                answer = QMessageBox.question(
                    self,
                    "项目仍有未完成任务",
                    f"这个项目仍关联 {len(pending)} 项未完成任务。\n\n继续会完成项目本身，但不会改写这些任务，便于你逐项确认。是否继续？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return False
        saved = self.window.update_project_management(self.project, data, notify=notify)
        self.apply_management_values(saved or data)
        self.refresh_header_states()
        self.render_decision_history()
        return True

    def new_task(self):
        if not self.save_changes(notify=False):
            return
        self.window.new_project_task(self.project)

    def schedule_next_step(self):
        if not self.save_changes(notify=False):
            return
        if self.window.schedule_project_next_step(self.project):
            self.render_tasks()
        self.render_tasks()

    def edit_task(self, task):
        self.window.edit_today_task(task)
        self.render_tasks()

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
        top = QFrame(); top.setObjectName("systemSpine"); top.setFixedHeight(76)
        top.setStyleSheet("QFrame#systemSpine { background: #ffffff; border-bottom: 1px solid #dbe3ee; }")
        top_layout = QHBoxLayout(top); top_layout.setContentsMargins(18, 10, 20, 10); top_layout.setSpacing(12)

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

        self.sync = QLabel("●  自动同步"); self.sync.setAlignment(Qt.AlignCenter); self.sync.setMinimumWidth(112); self.sync.setFixedHeight(34)
        self.sync.setStyleSheet("color: #087443; background: #e9f8f0; border: 1px solid #b9e5cd; border-radius: 9px; padding: 3px 9px; font-size: 11px; font-weight: 650;"); top_layout.addWidget(self.sync)
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

        history_nav = QPushButton("今日任务记录"); history_nav.setObjectName("nav"); history_nav.setIcon(fluent_icon("\uE81C", color="#315b94", size=16)); history_nav.setIconSize(QSize(16, 16)); history_nav.clicked.connect(lambda: self.show_task_history(0)); side_layout.addWidget(history_nav)
        body.addWidget(side)
        self.pages = QStackedWidget(); self.home_page = self.build_home_page(); self.projects_page = self.build_projects_page(); self.pages.addWidget(self.home_page); self.pages.addWidget(self.projects_page); body.addWidget(self.pages, 1)
        status_bar = QStatusBar(); self.setStatusBar(status_bar)
        self.undo_task_button = QPushButton("撤销状态"); self.undo_task_button.setFixedHeight(26); self.undo_task_button.setIcon(fluent_icon("\uE7A7", color="#1d4ed8", size=13)); self.undo_task_button.setIconSize(QSize(13, 13))
        self.undo_task_button.setToolTip("撤销最近一次手动任务状态切换"); self.undo_task_button.setAccessibleName("撤销最近一次任务状态切换")
        self.undo_task_button.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #bfd1ef; border-radius: 7px; padding: 3px 9px; font-size: 11px; font-weight: 650; } QPushButton:hover, QPushButton:focus { background: #dfe9fb; border-color: #8eace0; }")
        self.undo_task_button.clicked.connect(self.undo_last_task_transition); self.undo_task_button.hide(); status_bar.addPermanentWidget(self.undo_task_button)
        self.undo_task_timer = QTimer(self); self.undo_task_timer.setSingleShot(True); self.undo_task_timer.timeout.connect(self.clear_task_undo)
        self.select_section("home")

    def build_projects_page(self):
        main = QWidget(); main.setObjectName("projectsPage"); main.setStyleSheet("QWidget#projectsPage { background: #f5f7fb; } QWidget#projectsPage QLabel { background: transparent; }"); main_layout = QVBoxLayout(main); main_layout.setContentsMargins(32, 26, 28, 24); main_layout.setSpacing(16)
        heading = QHBoxLayout(); heading.setSpacing(24)
        heading_text = QVBoxLayout(); heading_text.setSpacing(4)
        title = QLabel("项目"); title.setStyleSheet("font-size: 29px; font-weight: 720; color: #172033;"); heading_text.addWidget(title)
        subtitle = QLabel("集中管理项目阶段、健康度、阻塞项、下一步与 Codex 工作上下文")
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
        self.scope_filter.setToolTip("“当前重点”包含人工重点、今日进行中任务和运行中的 Codex 对话")
        for label, value in (("全部项目", "all"), ("当前重点", "focus"), ("待复核", "review"), ("风险与阻塞", "attention"), ("阻塞项目", "blocked"), ("需要下一步", "needs_next"), ("暂缓与想法", "paused")):
            self.scope_filter.addItem(label, value)
        self.scope_filter.currentIndexChanged.connect(self.render); tools.addWidget(self.scope_filter)
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
        summary_layout = QVBoxLayout(self.daily_summary_panel); summary_layout.setContentsMargins(16, 12, 16, 12); summary_layout.setSpacing(6)
        summary_head = QHBoxLayout(); summary_head.setSpacing(9)
        summary_icon = QLabel(); summary_icon.setAttribute(Qt.WA_TransparentForMouseEvents); summary_icon.setFixedSize(28, 28); summary_icon.setAlignment(Qt.AlignCenter); summary_icon.setPixmap(fluent_icon("\uE81C", color="#1d4ed8", size=16).pixmap(QSize(16, 16))); summary_icon.setStyleSheet("background: #eaf1ff; border-radius: 8px;"); summary_head.addWidget(summary_icon)
        summary_title_box = QVBoxLayout(); summary_title_box.setSpacing(0)
        summary_title = QLabel("昨日回顾"); summary_title.setAttribute(Qt.WA_TransparentForMouseEvents); summary_title.setStyleSheet("color: #253247; font-size: 15px; font-weight: 700;"); summary_title_box.addWidget(summary_title)
        self.daily_summary_date_label = QLabel(); self.daily_summary_date_label.setAttribute(Qt.WA_TransparentForMouseEvents); self.daily_summary_date_label.setStyleSheet("color: #748094; font-size: 10px;"); summary_title_box.addWidget(self.daily_summary_date_label); summary_head.addLayout(summary_title_box)
        summary_head.addStretch()
        self.daily_summary_state = QLabel("等待总结"); self.daily_summary_state.setAlignment(Qt.AlignCenter); self.daily_summary_state.setFixedHeight(26)
        self.daily_summary_state.setStyleSheet("color: #526071; background: #eef2f6; border-radius: 8px; padding: 2px 9px; font-size: 10px; font-weight: 650;"); summary_head.addWidget(self.daily_summary_state)
        open_summary_thread = QPushButton("总结对话"); open_summary_thread.setFixedHeight(32); open_summary_thread.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); open_summary_thread.setIconSize(QSize(14, 14)); open_summary_thread.setToolTip("打开固定的 Codex 总结任务"); open_summary_thread.setAccessibleName("打开 Codex 每日总结任务"); open_summary_thread.clicked.connect(self.open_daily_summary_thread); summary_head.addWidget(open_summary_thread)
        self.daily_summary_regenerate_button = QPushButton("重新生成"); self.daily_summary_regenerate_button.setFixedHeight(32); self.daily_summary_regenerate_button.setIcon(fluent_icon("\uE72C", color="#1d4ed8", size=13)); self.daily_summary_regenerate_button.setIconSize(QSize(13, 13)); self.daily_summary_regenerate_button.clicked.connect(lambda: self.start_daily_summary(force=True)); summary_head.addWidget(self.daily_summary_regenerate_button)
        summary_layout.addLayout(summary_head)
        self.daily_summary_overview = QLabel("软件将在每天首次打开时，用固定 Codex 任务总结前一天的工作记录。")
        self.daily_summary_overview.setAttribute(Qt.WA_TransparentForMouseEvents); self.daily_summary_overview.setWordWrap(True); self.daily_summary_overview.setMaximumHeight(42); self.daily_summary_overview.setStyleSheet("color: #42526a; font-size: 13px; line-height: 1.35;"); summary_layout.addWidget(self.daily_summary_overview)
        self.daily_summary_meta = QLabel("点击查看完整回顾")
        self.daily_summary_meta.setAttribute(Qt.WA_TransparentForMouseEvents); self.daily_summary_meta.setStyleSheet("color: #718096; font-size: 11px;"); summary_layout.addWidget(self.daily_summary_meta)
        layout.addWidget(self.daily_summary_panel)

        decision_panel = QFrame(); decision_panel.setObjectName("portfolioDecisionQueue")
        decision_panel.setStyleSheet("QFrame#portfolioDecisionQueue { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 12px; }")
        decision_layout = QHBoxLayout(decision_panel); decision_layout.setContentsMargins(14, 12, 14, 12); decision_layout.setSpacing(10)
        decision_intro = QWidget(); decision_intro.setFixedWidth(178); intro_layout = QHBoxLayout(decision_intro); intro_layout.setContentsMargins(0, 0, 8, 0); intro_layout.setSpacing(10)
        decision_icon = QLabel(); decision_icon.setAttribute(Qt.WA_TransparentForMouseEvents); decision_icon.setFixedSize(34, 34); decision_icon.setAlignment(Qt.AlignCenter)
        decision_icon.setPixmap(fluent_icon("\uE9D9", color="#1d4ed8", size=18).pixmap(QSize(18, 18))); decision_icon.setStyleSheet("background: #eaf1ff; border: none; border-radius: 9px;"); intro_layout.addWidget(decision_icon)
        intro_text = QVBoxLayout(); intro_text.setSpacing(1)
        decision_title = QLabel("项目决策"); decision_title.setAttribute(Qt.WA_TransparentForMouseEvents); decision_title.setStyleSheet("color: #253247; font-size: 15px; font-weight: 700;"); intro_text.addWidget(decision_title)
        decision_hint = QLabel("点击直达处理队列"); decision_hint.setAttribute(Qt.WA_TransparentForMouseEvents); decision_hint.setStyleSheet("color: #748094; font-size: 10px;"); intro_text.addWidget(decision_hint); intro_layout.addLayout(intro_text); decision_layout.addWidget(decision_intro)
        self.portfolio_decision_cards = {}
        decision_specs = (
            ("focus", "正在推进", "#1d4ed8", "#f2f6ff", "#cfdbf1"),
            ("attention", "风险与阻塞", "#b54708", "#fff8ed", "#efd7b4"),
            ("review", "待复核", "#315f9b", "#f4f7fb", "#d5e0ec"),
            ("needs_next", "待定下一步", "#6d3fc0", "#f6f3fb", "#dfd5f1"),
        )
        for scope, caption, color, background, border in decision_specs:
            card = ClickableFrame(); card.setObjectName(f"decisionCard_{scope}"); card.setMinimumHeight(64)
            card.setStyleSheet(
                f"QFrame#decisionCard_{scope} {{ background: {background}; border: 1px solid {border}; border-radius: 10px; }}"
                f"QFrame#decisionCard_{scope}:hover, QFrame#decisionCard_{scope}:focus {{ background: #ffffff; border-color: {color}; }}"
            )
            card.clicked.connect(lambda value=scope: self.open_project_scope(value))
            card_layout = QHBoxLayout(card); card_layout.setContentsMargins(12, 8, 10, 8); card_layout.setSpacing(9)
            count = QLabel("0"); count.setAttribute(Qt.WA_TransparentForMouseEvents); count.setFixedSize(34, 34); count.setAlignment(Qt.AlignCenter)
            count.setStyleSheet(f"color: {color}; background: #ffffff; border: 1px solid {border}; border-radius: 9px; font-size: 16px; font-weight: 750;"); card_layout.addWidget(count)
            card_text = QVBoxLayout(); card_text.setSpacing(1)
            card_title = QLabel(caption); card_title.setAttribute(Qt.WA_TransparentForMouseEvents); card_title.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 700;"); card_text.addWidget(card_title)
            preview = ElidedLabel("当前无需处理"); preview.setAttribute(Qt.WA_TransparentForMouseEvents); preview.setStyleSheet("color: #66758a; font-size: 10px; border: none;"); card_text.addWidget(preview); card_layout.addLayout(card_text, 1)
            arrow = QLabel(); arrow.setAttribute(Qt.WA_TransparentForMouseEvents); arrow.setFixedSize(18, 18); arrow.setPixmap(fluent_icon("\uE72A", color=color, size=12).pixmap(QSize(12, 12))); arrow.setAlignment(Qt.AlignCenter); card_layout.addWidget(arrow)
            self.portfolio_decision_cards[scope] = {"frame": card, "count": count, "preview": preview, "caption": caption}
            decision_layout.addWidget(card, 1)
        layout.addWidget(decision_panel)

        self.execution_alignment_panel = ClickableFrame(); self.execution_alignment_panel.setObjectName("executionAlignmentPanel"); self.execution_alignment_panel.setMinimumHeight(54)
        self.execution_alignment_panel.setToolTip("逐项确认项目保存的下一步与今日实际执行是否一致")
        self.execution_alignment_panel.setStyleSheet(
            "QFrame#executionAlignmentPanel { background: #f7faff; border: 1px solid #c9d8ee; border-left: 4px solid #2563eb; border-radius: 10px; }"
            "QFrame#executionAlignmentPanel:hover, QFrame#executionAlignmentPanel:focus { background: #ffffff; border-color: #7ea4db; border-left-color: #1d4ed8; }"
        )
        self.execution_alignment_panel.clicked.connect(self.show_execution_alignment_queue)
        alignment_layout = QHBoxLayout(self.execution_alignment_panel); alignment_layout.setContentsMargins(13, 8, 12, 8); alignment_layout.setSpacing(10)
        alignment_icon = QLabel(); alignment_icon.setAttribute(Qt.WA_TransparentForMouseEvents); alignment_icon.setFixedSize(30, 30); alignment_icon.setAlignment(Qt.AlignCenter)
        alignment_icon.setPixmap(fluent_icon("\uE8A7", color="#1d4ed8", size=16).pixmap(QSize(16, 16))); alignment_icon.setStyleSheet("background: #e7effc; border-radius: 8px;"); alignment_layout.addWidget(alignment_icon)
        alignment_text_box = QVBoxLayout(); alignment_text_box.setSpacing(1)
        alignment_title = QLabel("执行方向待确认"); alignment_title.setAttribute(Qt.WA_TransparentForMouseEvents); alignment_title.setStyleSheet("color: #253247; font-size: 13px; font-weight: 700;"); alignment_text_box.addWidget(alignment_title)
        self.execution_alignment_summary = ElidedLabel(); self.execution_alignment_summary.setAttribute(Qt.WA_TransparentForMouseEvents); self.execution_alignment_summary.setStyleSheet("color: #66758a; font-size: 10px; border: none;"); alignment_text_box.addWidget(self.execution_alignment_summary); alignment_layout.addLayout(alignment_text_box, 1)
        self.execution_alignment_count = QLabel("0"); self.execution_alignment_count.setAttribute(Qt.WA_TransparentForMouseEvents); self.execution_alignment_count.setAlignment(Qt.AlignCenter); self.execution_alignment_count.setFixedSize(30, 26)
        self.execution_alignment_count.setStyleSheet("color: #1d4ed8; background: #e8f0ff; border-radius: 8px; font-size: 12px; font-weight: 750;"); alignment_layout.addWidget(self.execution_alignment_count)
        alignment_action = QLabel("逐项校准  →"); alignment_action.setAttribute(Qt.WA_TransparentForMouseEvents); alignment_action.setStyleSheet("color: #1d4ed8; font-size: 11px; font-weight: 700;"); alignment_layout.addWidget(alignment_action)
        self.execution_alignment_panel.hide(); layout.addWidget(self.execution_alignment_panel)

        board_head = QHBoxLayout(); board_head.setSpacing(9)
        board_icon = QLabel(); board_icon.setFixedSize(26, 26); board_icon.setPixmap(fluent_icon("\uE9D2", color="#176cff", size=19).pixmap(QSize(19, 19))); board_icon.setAlignment(Qt.AlignCenter); board_head.addWidget(board_icon)
        self.task_board_title = QLabel("今日任务规划"); self.task_board_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #172033;"); board_head.addWidget(self.task_board_title)
        self.task_summary = QLabel(); self.task_summary.setStyleSheet("color: #66758a; font-size: 12px;"); board_head.addWidget(self.task_summary); board_head.addStretch()
        self.task_archive_button = QToolButton(); self.task_archive_button.setFixedSize(36, 36); self.task_archive_button.setIcon(fluent_icon("\uE74D", color="#526071", size=16)); self.task_archive_button.setIconSize(QSize(16, 16)); self.task_archive_button.setToolTip("任务回收站"); self.task_archive_button.setAccessibleName("任务回收站")
        self.task_archive_button.setStyleSheet("QToolButton { background: #ffffff; border: 1px solid #d5dee9; border-radius: 9px; } QToolButton:hover, QToolButton:focus { background: #f1f5fa; border-color: #9fb6d0; }"); self.task_archive_button.clicked.connect(self.show_task_archive); board_head.addWidget(self.task_archive_button)
        history = QToolButton(); history.setFixedSize(36, 36); history.setIcon(fluent_icon("\uE81C", color="#24588f", size=17)); history.setIconSize(QSize(17, 17)); history.setToolTip("查看每日任务记录"); history.setAccessibleName("每日任务记录")
        history.setStyleSheet("QToolButton { background: #ffffff; border: 1px solid #d5dee9; border-radius: 9px; } QToolButton:hover, QToolButton:focus { background: #f1f5fa; border-color: #9fb6d0; }"); history.clicked.connect(lambda: self.show_task_history(0)); board_head.addWidget(history)
        self.board_date_field = QDateEdit(QDate.currentDate()); self.board_date_field.setCalendarPopup(True); self.board_date_field.setDisplayFormat("yyyy年MM月dd日"); self.board_date_field.setFixedSize(150, 36); self.board_date_field.dateChanged.connect(lambda _date: self.render_today_tasks()); board_head.addWidget(self.board_date_field)
        today_button = QPushButton("今天"); today_button.setFixedHeight(36); today_button.clicked.connect(lambda: self.board_date_field.setDate(QDate.currentDate())); board_head.addWidget(today_button); layout.addLayout(board_head)

        self.task_board = QWidget(); self.task_board.setObjectName("taskBoard"); self.task_board.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.task_board_layout = QHBoxLayout(self.task_board); self.task_board_layout.setContentsMargins(0, 0, 0, 0); self.task_board_layout.setSpacing(11); layout.addWidget(self.task_board)

        self.activity_panel = QFrame(); self.activity_panel.setObjectName("activityPanel")
        self.activity_panel.setStyleSheet("QFrame#activityPanel { background: #ffffff; border: 1px solid #d8e1eb; border-radius: 12px; }")
        activity_layout = QVBoxLayout(self.activity_panel); activity_layout.setContentsMargins(0, 0, 0, 0); activity_layout.setSpacing(0)
        activity_header = QFrame(); activity_header.setObjectName("activityHeader"); activity_header.setFixedHeight(54)
        activity_header.setStyleSheet("QFrame#activityHeader { background: #fbfcfe; border: none; border-bottom: 1px solid #e2e8f0; border-radius: 12px 12px 0 0; }")
        activity_head = QHBoxLayout(activity_header); activity_head.setContentsMargins(16, 8, 12, 8); activity_head.setSpacing(9)
        activity_icon = QLabel(); activity_icon.setFixedSize(28, 28); activity_icon.setAlignment(Qt.AlignCenter); activity_icon.setPixmap(fluent_icon("\uE81C", color="#2563eb", size=17).pixmap(QSize(17, 17))); activity_icon.setStyleSheet("background: #eaf1ff; border-radius: 8px;"); activity_head.addWidget(activity_icon)
        activity_title = QLabel("今日任务记录"); activity_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #253247;"); activity_head.addWidget(activity_title)
        activity_hint = QLabel("状态变化与 Codex 活动"); activity_hint.setStyleSheet("color: #748094; font-size: 11px;"); activity_head.addWidget(activity_hint); activity_head.addStretch()
        show_all = QPushButton("查看全部"); show_all.setFixedHeight(32); show_all.clicked.connect(lambda: self.show_task_history(0)); activity_head.addWidget(show_all); activity_layout.addWidget(activity_header)
        activity_rows = QWidget(); activity_rows.setObjectName("activityRows"); activity_rows.setStyleSheet("QWidget#activityRows { background: #ffffff; border: none; }")
        self.activity_rows_layout = QVBoxLayout(activity_rows); self.activity_rows_layout.setContentsMargins(10, 4, 10, 6); self.activity_rows_layout.setSpacing(0); activity_layout.addWidget(activity_rows); layout.addWidget(self.activity_panel)
        layout.addStretch()
        self.render_daily_summary()
        self.render_portfolio_decisions()
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
        if scope == "review":
            self.show_portfolio_review_queue()
            return
        if scope not in {"focus", "attention", "review", "needs_next"}:
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

    def show_portfolio_review_queue(self):
        projects = portfolio_decision_groups(self.projects).get("review", [])
        if not projects:
            QMessageBox.information(self, "无需复核", "当前没有到期或尚未确认的项目。")
            return
        PortfolioReviewDialog(self, projects).exec_()

    def execution_alignment_queue(self):
        today = QDate.currentDate().toString(Qt.ISODate)
        return portfolio_execution_alignment_queue(self.projects, self.today_tasks, today)

    def show_execution_alignment_queue(self):
        alignments = self.execution_alignment_queue()
        if not alignments:
            QMessageBox.information(self, "执行方向已对齐", "当前进行中的任务与项目下一步没有待确认差异。")
            return
        ExecutionAlignmentDialog(self, alignments).exec_()

    def render_portfolio_decisions(self):
        if not hasattr(self, "portfolio_decision_cards"):
            return
        groups = portfolio_decision_groups(self.projects)
        prefixes = {"focus": "今日推进", "attention": "风险处置", "review": "等待确认", "needs_next": "等待决策"}
        for scope, controls in self.portfolio_decision_cards.items():
            projects = groups.get(scope, [])
            controls["count"].setText(str(len(projects)))
            if projects:
                names = [str(project.get("name") or "未命名项目") for project in projects]
                preview = "、".join(names[:2])
                if len(names) > 2:
                    preview += f" 等 {len(names)} 项"
                summary = f"{prefixes[scope]}：{preview}"
                tooltip = f"{prefixes[scope]}\n" + "\n".join(f"• {name}" for name in names)
            else:
                summary = "当前无需处理"
                tooltip = f"{controls['caption']}：当前没有项目"
            controls["preview"].setText(summary)
            controls["preview"].setToolTip(tooltip)
            controls["frame"].setToolTip(tooltip)
            controls["frame"].setAccessibleName(f"{controls['caption']}，{len(projects)} 个项目。{summary}")
        if hasattr(self, "execution_alignment_panel"):
            alignments = self.execution_alignment_queue()
            self.execution_alignment_panel.setVisible(bool(alignments))
            if alignments:
                names = [str((item.get("project") or {}).get("name") or "未命名项目") for item in alignments]
                preview = "、".join(names[:3])
                if len(names) > 3:
                    preview += f" 等 {len(names)} 项"
                summary = f"{len(names)} 个项目的今日执行与已保存下一步不同：{preview}"
                tooltip = "执行方向待确认\n" + "\n".join(f"• {name}" for name in names)
                self.execution_alignment_count.setText(str(len(names)))
                self.execution_alignment_summary.setText(summary); self.execution_alignment_summary.setToolTip(tooltip)
                self.execution_alignment_panel.setToolTip(tooltip)
                self.execution_alignment_panel.setAccessibleName(f"执行方向待确认，{len(names)} 个项目。{summary}")

    def refresh(self, silent=False, scan=True):
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
            self.render_today_tasks()
        stored_summaries = load_json(DAILY_SUMMARIES_FILE, [])
        if isinstance(stored_summaries, list) and stored_summaries != self.daily_summaries:
            self.daily_summaries = stored_summaries
            self.render_daily_summary()
        stored_decisions = load_json(PROJECT_DECISIONS_FILE, [])
        if isinstance(stored_decisions, list) and stored_decisions != self.project_decisions:
            self.project_decisions = stored_decisions
        self.saved_projects = load_json(PROJECTS_FILE, [])
        self.projects = visible_project_catalog(self.saved_projects, self.project_layout)
        events = self.live_sessions
        conversations = conversations_by_project(events)
        for project in self.projects:
            project["conversations"] = conversations.get(project["id"], [])
            project["lastActivity"] = project["conversations"][0] if project["conversations"] else None
        self.running_count = sum(codex_state(session)[0] == "running" for project in self.projects for session in project["conversations"])
        if hasattr(self, "pulse_state_label"):
            if self.running_count:
                self.pulse_state_label.setText(f"● 活跃 · {self.running_count} 个对话运行中")
                self.pulse_state_label.setStyleSheet("color: #087443; font-size: 13px; font-weight: 700;")
            else:
                self.pulse_state_label.setText("待机 · 正在监听 Codex")
                self.pulse_state_label.setStyleSheet("color: #526071; font-size: 13px; font-weight: 650;")
        self.auto_start_tasks_from_codex()
        self.sync_project_workload()
        self.start_daily_summary()
        signature = tuple(
            (
                project.get("id"), project.get("name"), project.get("path"), project.get("category"),
                project.get("status"), project_priority_key(project), project_stage_key(project), project_health_key(project),
                project.get("objective"), project.get("nextStep"), project.get("blocker"), project.get("nextStepReviewNeeded"), project.get("reviewedAt"),
                project.get("executionAlignmentSignature"), project.get("executionAlignmentReviewedAt"),
                project.get("plannedTaskCount"), project.get("activeTaskCount"), project.get("completedTaskCount"),
                tuple(
                    (session.get("sessionId"), session.get("conversationLabel"), session.get("state"), session.get("at"), session.get("summary"))
                    for session in project.get("conversations", [])
                ),
            )
            for project in self.projects
        )
        if signature != self.view_signature:
            self.view_signature = signature
            self.render_nav(); self.render()
            self.render_today_tasks()
        if not self.scan_ready:
            self.sync.setText("●  正在同步")
        else:
            self.sync.setText(f"●  已同步 {datetime.now().strftime('%H:%M')}")
        if scan:
            self.start_session_scan()
        if rollover_count:
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
        self.live_sessions = sessions
        self.scan_ready = True
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
        self.usage_synced_label.setText("正在同步真实额度…")
        scanner = UsageScanner(self); scanner.scanned.connect(self.on_usage_scanned); scanner.finished.connect(lambda: self.finish_usage_scan(scanner)); self.usage_scanner = scanner; scanner.start()

    def finish_usage_scan(self, scanner):
        if self.usage_scanner is scanner:
            self.usage_scanner = None
        scanner.deleteLater()

    def on_usage_scanned(self, data):
        if data.get("error"):
            self.usage_synced_label.setText("额度读取失败，稍后自动重试")
            return
        self.usage_data = data
        used = data.get("usedPercent", 0); remaining = data.get("remainingPercent", 100)
        self.usage_used_label.setText(f"{used}%"); self.usage_remaining_label.setText(f"{remaining}%")
        self.usage_reset_label.setText(data.get("resetText") or "—"); self.usage_today_label.setText(self.format_tokens(data.get("todayTokens")))
        source = data.get("todayTokensSource")
        if hasattr(self, "usage_today_caption"):
            estimated = source == "local"
            self.usage_today_caption.setText("今日 Tokens*" if estimated else "今日 Tokens")
            self.usage_today_caption.setToolTip("由本地 Codex 对话日志实时估算；官方日用量通常延迟一天" if estimated else "Codex 官方今日用量")
            self.usage_today_label.setToolTip(self.usage_today_caption.toolTip())
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

    def record_project_review(self, project, audit=True, occurred_at=None):
        """Confirm current project state without inventing a field change."""
        reviewed_at = occurred_at or datetime.now().isoformat(timespec="seconds")
        target = self.saved_record_for_project(project)
        target["reviewedAt"] = reviewed_at
        project["reviewedAt"] = reviewed_at
        entry = build_project_review_entry(project, reviewed_at) if audit else None
        if entry is not None:
            self.project_decisions.append(entry)
            if len(self.project_decisions) > 2000:
                self.project_decisions = self.project_decisions[-2000:]
            save_json(PROJECT_DECISIONS_FILE, self.project_decisions)
        save_json(PROJECTS_FILE, self.saved_projects)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        cadence = project_review_status(project)[2]
        self.statusBar().showMessage(f"已确认当前项目状态；{cadence} 天后自动进入待复核", 4200)
        return entry or True

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

    def sync_project_workload(self):
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
        self.render_portfolio_decisions()

    def conversation_by_id(self, session_id):
        if not session_id:
            return None
        for project in self.projects:
            for conversation in project.get("conversations", []):
                if conversation.get("sessionId") == session_id:
                    return conversation
        return None

    def auto_start_tasks_from_codex(self):
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
        if hasattr(self, "task_archive_button"):
            archived_count = len(archived_task_records(self.today_tasks))
            self.task_archive_button.setToolTip(f"任务回收站（{archived_count} 项）" if archived_count else "任务回收站为空")
            self.task_archive_button.setAccessibleName(f"任务回收站，{archived_count} 项任务")
            archive_color = "#9a5b12" if archived_count else "#526071"
            self.task_archive_button.setIcon(fluent_icon("\uE74D", color=archive_color, size=16))
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
            quick_add = QToolButton(); quick_add.setFixedSize(24, 22); quick_add.setIcon(fluent_icon("\uE710", color=accent, size=12)); quick_add.setIconSize(QSize(12, 12)); quick_add.setToolTip(f"直接新建“{label}”任务"); quick_add.setAccessibleName(f"新建{label}任务")
            quick_add.setStyleSheet(f"QToolButton {{ color: {accent}; background: #ffffff; border: 1px solid #d8e1eb; border-radius: 7px; }} QToolButton:hover, QToolButton:focus {{ background: {surface}; border-color: {accent}; }}")
            quick_add.clicked.connect(lambda _checked=False, value=status: self.new_today_task(value)); header.addWidget(quick_add)
            count = QLabel(str(counts[status])); count_bg = accent if counts[status] else "#e1eaf6"; count_color = "#ffffff" if counts[status] else "#637994"; count.setAlignment(Qt.AlignCenter); count.setFixedSize(24, 20); count.setStyleSheet(f"color: {count_color}; background: {count_bg}; font-size: 10px; font-weight: 700; border: none; border-radius: 9px;"); header.addWidget(count); column_layout.addLayout(header)
            status_tasks = ordered_board_tasks(tasks, date_key, status)
            if not status_tasks:
                empty = QLabel("暂无任务\n新建任务或从其他状态移入"); empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #7a8798; background: #ffffff; font-size: 11px; border: 1px dashed #cbd5e1; border-radius: 9px; padding: 20px 12px;"); column_layout.addWidget(empty)
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
            project = self.project_by_id(task.get("projectId")); project_name = (project or {}).get("name") or "未关联项目"
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
        if (stored or {}).get("origin") == "project_next_step":
            project = self.project_by_id(stored.get("projectId"))
            title = str(stored.get("projectNextStep") or stored.get("title") or "").strip()
            existing = find_open_project_next_step_task(self.today_tasks, project, title, stored.get("date")) if project else None
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

    def edit_today_task(self, task=None, default_status=None, default_project_id=None):
        default_date = self.board_date_field.date().toString(Qt.ISODate) if hasattr(self, "board_date_field") else QDate.currentDate().toString(Qt.ISODate)
        dialog = TaskEditor(self, self.projects, task, default_date, default_status, default_project_id)
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
            self.today_tasks.append(task)
        task.update(data); task["updatedAt"] = now
        current_status = task.get("status", "planned")
        if not created and (previous_status != current_status or previous_date != task.get("date")):
            task["status"] = previous_status
            task.pop("boardOrder", None)
            reorder_task_board(self.today_tasks, task.get("id"), current_status, None)
        if created:
            record_task_status_event(task, None, task.get("status", "planned"), now, "manual")
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
            message = "任务已完成；项目已回到“需要下一步”，请明确后续动作" if completed_handoff else "任务已重新打开；项目下一步已同步恢复"
            self.statusBar().showMessage(message, 4500)
        else:
            self.sync_project_workload(); self.view_signature = None
            self.render_today_tasks(); self.render()
        if not created and previous_status != current_status:
            self.offer_task_undo(task, previous_status, current_status, now)
        if dialog.codex_requested and not completed_handoff and not reopened_handoff:
            self.plan_task_in_codex(task)
        elif not completed_handoff and not reopened_handoff:
            message = "任务与完成成果已保存" if outcome_changed and current_status == "done" else "今日任务已保存"
            self.statusBar().showMessage(message, 3000)

    def set_task_status(self, task_id, status, source="manual", allow_undo=True):
        task = next((item for item in self.today_tasks if item.get("id") == task_id), None)
        if not task_status_transition_allowed(task, status):
            return False
        return MainWindow.move_task_on_board(self, task_id, status, None, source, allow_undo)

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
        save_json(TASKS_FILE, self.today_tasks)
        if completed_handoff or reopened_handoff:
            self.view_signature = None
            self.refresh(silent=True, scan=False)
            message = "任务已完成；项目已回到“需要下一步”，请明确后续动作" if completed_handoff else "任务已重新打开；项目下一步已同步恢复"
            self.statusBar().showMessage(message, 4500)
        elif status_changed:
            self.sync_project_workload(); self.view_signature = None
            self.render_today_tasks(); self.render()
            self.statusBar().showMessage(f"任务已移至“{TASK_STATUS[status]}”", 2200)
        else:
            self.render_today_tasks()
            self.statusBar().showMessage(f"“{task.get('title', '任务')}”已调整为第 {movement.get('targetIndex', 0) + 1} 项", 2200)
        if status_changed and allow_undo and source in {"manual", "selector", "drag"}:
            self.offer_task_undo(task, previous_status, status, now)
        return True

    def offer_task_undo(self, task, previous_status, status, occurred_at):
        if previous_status not in TASK_STATUS or status not in TASK_STATUS or previous_status == status:
            return
        self.pending_task_undo = {
            "taskId": task.get("id"),
            "from": previous_status,
            "to": status,
            "at": occurred_at,
        }
        self.undo_task_button.setText(f"撤销到{TASK_STATUS[previous_status]}")
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
        for item in self.saved_projects:
            if item.get("category") == old_name:
                item["category"] = new_name
        orders = self.project_layout.setdefault("categoryOrders", {})
        if old_name in orders:
            orders[new_name] = orders.pop(old_name)
        if self.category == old_name:
            self.category = new_name
        save_json(CATEGORIES_FILE, self.categories[1:])
        save_json(PROJECTS_FILE, self.saved_projects)
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage(f"分类已重命名：{old_name} → {new_name}", 3000)

    def delete_category(self):
        editable = [category for category in self.categories[1:] if category != "未分类"]
        if not editable:
            QMessageBox.information(self, "没有可删除的分类", "“全部”和“未分类”是系统分类，不能删除。")
            return
        category, accepted = QInputDialog.getItem(self, "删除分类", "选择要删除的分类：", editable, 0, False)
        if not accepted or not category:
            return
        affected = [project for project in self.projects if project.get("category") == category]
        message = f"确定删除分类“{category}”吗？"
        if affected:
            message += f"\n\n其中 {len(affected)} 个项目会移到“未分类”，项目文件和 Codex 对话不会被删除。"
        else:
            message += "\n\n该操作不会删除任何项目文件或 Codex 对话。"
        if QMessageBox.question(self, "确认删除分类", message) != QMessageBox.Yes:
            return

        for project in affected:
            target = self.saved_record_for_project(project)
            target["category"] = "未分类"
            project["category"] = "未分类"
        for project in self.saved_projects:
            if project.get("category") == category:
                project["category"] = "未分类"

        orders = self.project_layout.setdefault("categoryOrders", {})
        moved_ids = orders.pop(category, [])
        moved_ids.extend(project.get("id") for project in affected if project.get("id"))
        unclassified_order = orders.setdefault("未分类", [])
        for project_id in moved_ids:
            if project_id and project_id not in unclassified_order:
                unclassified_order.append(project_id)

        self.categories = [value for value in self.categories if value != category]
        if self.category == category:
            self.category = "未分类"
        save_json(CATEGORIES_FILE, self.categories[1:])
        save_json(PROJECTS_FILE, self.saved_projects)
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage(f"分类“{category}”已删除，项目已移到“未分类”", 3500)

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
                "nextStep": project.get("nextStep", ""),
                "blocker": project.get("blocker", ""),
                "reviewedAt": project.get("reviewedAt", ""),
            }
            self.saved_projects.append(target)
        project["savedId"] = target["id"]
        return target

    def update_project_management(self, project, data, notify=True, source="manual"):
        previous_category = project.get("category", "未分类")
        before = dict(project)
        occurred_at = datetime.now().isoformat(timespec="seconds")
        data, normalization_notes = normalize_project_management_decision(project, data)
        validation_error = project_management_validation_error(data)
        if validation_error:
            if notify:
                self.statusBar().showMessage(validation_error, 4000)
            return None
        target = self.saved_record_for_project(project)
        target.update({
            "priority": data.get("priority") if data.get("priority") in PROJECT_PRIORITY else "normal",
            "stage": data.get("stage") if data.get("stage") in PROJECT_STAGE else "execution",
            "health": data.get("health") if data.get("health") in PROJECT_HEALTH else "on_track",
            "status": data.get("status") if data.get("status") in STATUS_TEXT else "active",
            "category": data.get("category") if data.get("category") in self.categories[1:] else previous_category,
            "objective": str(data.get("objective") or "").strip(),
            "nextStep": str(data.get("nextStep") or "").strip(),
            "blocker": str(data.get("blocker") or "").strip(),
        })
        if target.get("nextStep"):
            target["nextStepReviewNeeded"] = False
        new_category = target.get("category", previous_category)
        if new_category != previous_category:
            orders = self.project_layout.setdefault("categoryOrders", {})
            orders[previous_category] = [value for value in orders.get(previous_category, []) if value != project.get("id")]
            if project.get("id") not in orders.setdefault(new_category, []):
                orders[new_category].append(project.get("id"))
        for key in ("priority", "stage", "health", "status", "category", "objective", "nextStep", "blocker", "nextStepReviewNeeded"):
            project[key] = target.get(key)
        decision_source = source if source in PROJECT_DECISION_SOURCES else "manual"
        entry = self.record_project_decision(project, before, target, decision_source, occurred_at)
        if entry is not None and decision_source in {"manual", "editor", "codex", "created"}:
            target["reviewedAt"] = occurred_at
            project["reviewedAt"] = occurred_at
        save_json(PROJECTS_FILE, self.saved_projects)
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        if notify:
            message = normalization_notes[0] if normalization_notes else "项目目标与下一步已保存"
            self.statusBar().showMessage(message, 3500 if normalization_notes else 2500)
        return dict(target)

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
        existing = find_open_project_next_step_task(self.today_tasks, project, title, today)
        if existing:
            self.statusBar().showMessage("这个项目下一步已经在今日任务中，无需重复添加", 3500)
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
        orders = self.project_layout.setdefault("categoryOrders", {})
        orders[previous_category] = [value for value in orders.get(previous_category, []) if value != project.get("id")]
        if project.get("id") not in orders.setdefault(category, []):
            orders[category].append(project.get("id"))
        save_json(PROJECTS_FILE, self.saved_projects)
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
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
            and Path(str(project.get("path") or "")).is_dir()
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
                and not Path(str(project.get("path") or "")).is_dir()
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
                f"{item.get('objective', '')} {item.get('nextStep', '')} {item.get('blocker', '')} "
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
            if governance_count:
                self.governance_button.setText(f"Codex 补全  {governance_count}")
                self.governance_button.setIcon(fluent_icon("\uE945", color="#1d4ed8", size=15))
                self.governance_button.setEnabled(True)
                self.governance_button.setToolTip(f"{governance_count} 个项目存在可由 Codex 补齐的管理缺项")
                self.governance_button.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c8d8f4; border-radius: 9px; padding: 7px 12px; font-size: 12px; font-weight: 650; } QPushButton:hover, QPushButton:focus { background: #dfe9fb; border-color: #9eb8e4; }")
            else:
                self.governance_button.setText("信息完整")
                self.governance_button.setIcon(fluent_icon("\uE73E", color="#087443", size=15))
                self.governance_button.setEnabled(False)
                self.governance_button.setToolTip("当前项目都具备目标、必要的下一步和一致的健康状态")
                self.governance_button.setStyleSheet("QPushButton:disabled { color: #087443; background: #e9f8f0; border: 1px solid #b9e5cd; border-radius: 9px; padding: 7px 12px; font-size: 12px; font-weight: 650; }")
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
        text = (
            f"继续项目：{project['name']}\n"
            f"项目目标：{project.get('objective') or '尚未明确'}\n"
            f"管理优先级：{PROJECT_PRIORITY.get(project_priority_key(project), '常规推进')}\n"
            f"当前阶段：{PROJECT_STAGE.get(project_stage_key(project), '执行')}\n"
            f"项目健康度：{project_control_state(project)[1]}\n"
            f"当前阻塞：{project.get('blocker') or '无'}\n"
            f"工作目录：{project['path']}\n"
            f"当前下一步：{project.get('nextStep') or '请先判断下一步'}\n"
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
        if project:
            previous_category = project.get("category", "未分类")
            target = self.saved_record_for_project(project)
            target.update(data)
            if target.get("nextStep"):
                target["nextStepReviewNeeded"] = False
            if data.get("category") != previous_category:
                orders = self.project_layout.setdefault("categoryOrders", {})
                orders[previous_category] = [value for value in orders.get(previous_category, []) if value != project.get("id")]
                orders.setdefault(data["category"], []).append(project.get("id"))
        else:
            target = next((item for item in self.saved_projects if normalized_path(item.get("path")) == normalized_path(data.get("path"))), None)
            if target is None:
                target = {"id": str(uuid.uuid4())}; self.saved_projects.append(target)
            target.update(data)
            if target.get("nextStep"):
                target["nextStepReviewNeeded"] = False
            codex_projects = codex_sidebar_projects(self.saved_projects)
            codex_match = next((item for item in codex_projects if normalized_path(item.get("path")) == normalized_path(data.get("path"))), None)
            target["manualProject"] = codex_match is None
            if codex_match:
                hidden = self.project_layout.setdefault("hiddenProjectIds", [])
                self.project_layout["hiddenProjectIds"] = [value for value in hidden if value != codex_match.get("id")]
        decision_project = project or {**target, "savedId": target.get("id")}
        source = ("codex" if dialog.insight_applied else "editor") if project else "created"
        occurred_at = datetime.now().isoformat(timespec="seconds")
        entry = self.record_project_decision(decision_project, before, target, source, occurred_at)
        if entry is not None:
            target["reviewedAt"] = occurred_at
            decision_project["reviewedAt"] = occurred_at
        save_json(PROJECTS_FILE, self.saved_projects)
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        self.view_signature = None
        self.refresh(); self.statusBar().showMessage("项目已保存", 2000)


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
