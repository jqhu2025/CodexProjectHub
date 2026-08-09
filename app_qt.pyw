import json
import os
import queue
import re
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
    QAbstractItemView, QApplication, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFrame, QGridLayout,
    QFileDialog, QGraphicsScene, QGraphicsView, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QStatusBar, QStyle, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from codex_hub.runtime import activity_state, analyze_session_records, find_codex_binary as locate_codex_binary, read_user_thread_rows

ROOT = Path(__file__).resolve().parent
PROJECTS_FILE = ROOT / "data" / "projects.json"
CATEGORIES_FILE = ROOT / "data" / "categories.json"
TASKS_FILE = ROOT / "data" / "today_tasks.json"
PROJECT_LAYOUT_FILE = ROOT / "data" / "project_layout.json"
CODEX_HOME = Path(os.environ.get("USERPROFILE", "")) / ".codex"
CODEX_SESSIONS = CODEX_HOME / "sessions"
CODEX_GLOBAL_STATE = CODEX_HOME / ".codex-global-state.json"
CODEX_SESSION_INDEX = CODEX_HOME / "session_index.jsonl"
DEFAULT_CATEGORIES = ["Product Development", "Research Lab", "Operations", "External Projects", "未分类"]
STATUS_TEXT = {"active": "进行中", "paused": "暂停", "idea": "想法库", "completed": "已完成"}
STATUS_COLOR = {"active": "#16803c", "paused": "#a15c00", "idea": "#7c3aed", "completed": "#2563eb"}
TASK_STATUS = {"planned": "计划", "doing": "进行中", "done": "已完成"}
TASK_COLORS = {"planned": "#7c3aed", "doing": "#2563eb", "done": "#16803c"}

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
QPushButton#categoryNav { text-align: left; background: transparent; border: 1px solid transparent; border-radius: 8px; color: #53647a; padding: 8px 10px 8px 15px; font-size: 13px; }
QPushButton#categoryNav:hover { background: #f0f4f9; color: #1d4ed8; }
QPushButton#categoryNav[active='true'] { background: #e9f0ff; border-color: #cbdaf1; color: #1d4ed8; font-weight: 650; }
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


def save_json(path, data):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
        temp = file.name
    os.replace(temp, path)


def rollover_in_progress_tasks(tasks, today=None):
    """Preserve each day's record and carry unfinished active work forward one day at a time."""
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
        carried["carriedFromTaskId"] = source.get("id")
        carried["carriedFromDate"] = source.get("date")
        carried.pop("carriedToTaskId", None)
        carried.pop("carriedToDate", None)
        carried.pop("autoStartedAt", None)
        source["carriedToTaskId"] = carried["id"]
        source["carriedToDate"] = next_date
        source["carriedAt"] = now
        source["updatedAt"] = now
        result.append(carried)
        changed = True
    return result, changed


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
        self.setWindowTitle("编辑项目" if project else "新建项目")
        self.setObjectName("projectEditor")
        self.setMinimumWidth(640)
        self.setStyleSheet(STYLE + """
            QDialog#projectEditor QLabel[fieldLabel='true'] { color: #4a586b; font-size: 12px; font-weight: 500; }
            QDialog#projectEditor QLineEdit, QDialog#projectEditor QComboBox { min-height: 24px; font-size: 13px; }
        """)
        item = project or {"name": "", "category": "未分类", "path": "", "status": "active"}
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 24, 28, 24); layout.setSpacing(10)
        title = QLabel("编辑项目" if project else "新建项目")
        title.setStyleSheet("font-size: 24px; font-weight: 600; color: #172033;")
        layout.addWidget(title)
        subtitle = QLabel("项目中心只保存管理信息，不会修改或移动磁盘中的项目文件")
        subtitle.setStyleSheet("color: #718096; font-size: 12px; margin-bottom: 8px;"); layout.addWidget(subtitle)
        self.fields = {}
        for label, key in [("项目名称", "name"), ("类别", "category"), ("本地路径", "path"), ("项目状态", "status")]:
            field_label = QLabel(label); field_label.setProperty("fieldLabel", True); layout.addWidget(field_label)
            if key == "category":
                control = QComboBox(); control.setEditable(False)
                for category in (categories or load_categories())[1:]: control.addItem(category, category)
                control.setCurrentIndex(max(0, control.findData(item[key])))
            elif key == "status":
                control = QComboBox()
                for status, status_label in STATUS_TEXT.items(): control.addItem(status_label, status)
                control.setCurrentIndex(max(0, control.findData(item[key])))
            else:
                control = QLineEdit(item.get(key, ""))
            control.setFixedHeight(40); control.setAccessibleName(label)
            if key == "name": control.setPlaceholderText("例如：Desktop Analytics App")
            if key == "path":
                control.setPlaceholderText("选择项目所在文件夹")
                path_row = QHBoxLayout(); path_row.setSpacing(8); path_row.addWidget(control, 1)
                browse = QPushButton("选择文件夹"); browse.setFixedHeight(40); browse.setIcon(fluent_icon("\uE838", size=15)); browse.setIconSize(QSize(15, 15))
                browse.clicked.connect(self.choose_folder); path_row.addWidget(browse); layout.addLayout(path_row)
            else:
                layout.addWidget(control)
            self.fields[key] = control
        actions = QHBoxLayout(); actions.setContentsMargins(0, 10, 0, 0); actions.addStretch()
        cancel = QPushButton("取消"); cancel.setFixedHeight(38); cancel.clicked.connect(self.reject); actions.addWidget(cancel)
        save = QPushButton("保存项目"); save.setFixedHeight(38); save.setObjectName("primary"); save.clicked.connect(self.accept_project); actions.addWidget(save); layout.addLayout(actions)
        self.fields["name"].setFocus()

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
        self.accept()

    def value(self):
        data = {
            key: (control.currentData() if isinstance(control, QComboBox) else control.text().strip())
            for key, control in self.fields.items()
        }
        data["icon"] = (self.project or {}).get("icon", "")
        data["color"] = (self.project or {}).get("color", "#58d7f6")
        data["nextStep"] = (self.project or {}).get("nextStep", "")
        return data


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
        self.setFixedHeight(44)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("复制项目上下文，回到 Codex 继续；不显示具体对话")
        self.setAccessibleName(f"项目：{project.get('name') or '未命名项目'}，{state_text}")
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
        dot.setStyleSheet(f"background: {state_color}; border: none; border-radius: 3px;")
        layout.addWidget(dot)
        name = ElidedLabel(project.get("name") or "未命名项目")
        name.setToolTip(project.get("name") or "未命名项目")
        name.setStyleSheet("color: #26364c; border: none; font-size: 13px; font-weight: 600;")
        layout.addWidget(name, 1)
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
            QTimer.singleShot(0, lambda: self.update_map(self.window.projects, self.window.categories))

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
        title = QLabel("项目总览"); title.setStyleSheet("color: #172033; font-size: 19px; font-weight: 700;")
        subtitle = QLabel("按分类查看全部项目")
        subtitle.setStyleSheet("color: #748094; font-size: 12px;")
        title_box.addWidget(title); title_box.addWidget(subtitle)
        overview_layout.addLayout(title_box)
        overview_layout.addStretch(1)
        summary = QLabel(f"{len(order)} 个分类    {len(projects)} 个项目")
        summary.setStyleSheet("color: #65758b; background: transparent; border: none; padding: 4px 2px; font-size: 12px; font-weight: 500;")
        overview_layout.addWidget(summary)
        overview_proxy = self.map_scene.addWidget(overview)
        overview_proxy.setPos(side_margin, 8)

        column_heights = [82] * columns
        for category_index, category in enumerate(order):
            items = groups[category]
            color = self.CATEGORY_COLORS[category_index % len(self.CATEGORY_COLORS)]
            tint = self.CATEGORY_BACKGROUNDS[category_index % len(self.CATEGORY_BACKGROUNDS)]
            card_height = 66 + len(items) * 50
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
                conversations = project.get("conversations") or []
                running = any(codex_state(conversation)[0] == "running" for conversation in conversations)
                project_status = project.get("status", "active")
                if running:
                    state_text, state_color, background = "运行中", "#087443", "#eaf8f0"
                elif project_status == "completed":
                    state_text, state_color, background = "已完成", "#2563eb", "#edf4ff"
                elif conversations:
                    state_text, state_color, background = "已关联", "#52657d", "#eef2f6"
                else:
                    state_text, state_color, background = "未关联", "#7a8798", "#f2f4f7"
                row = ProjectMapRow(
                    project, state_text, state_color, background,
                    lambda value=project: self.window.copy_context(value),
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
        header = QFrame(); header.setObjectName("projectHeader"); header.setFixedHeight(64); header.setStyleSheet("QFrame#projectHeader { background: #ffffff; border: none; border-radius: 10px; }")
        layout = QHBoxLayout(header); layout.setContentsMargins(12, 0, 12, 0); layout.setSpacing(10)
        layout.addWidget(ProjectDragHandle(project["id"]))
        self.toggle_button = QToolButton(); self.toggle_button.setFixedSize(32, 32); self.toggle_button.setAutoRaise(True); self.toggle_button.setToolTip("展开或收起 Codex 对话")
        self.toggle_button.setAccessibleName(f"展开或收起 {project['name']} 的 Codex 对话")
        self.toggle_button.setStyleSheet("QToolButton { border: none; border-radius: 7px; } QToolButton:hover, QToolButton:focus { background: #edf3fb; }")
        self.toggle_button.setEnabled(bool(self.conversations)); self.toggle_button.clicked.connect(self.toggle_details); layout.addWidget(self.toggle_button)
        name = ElidedLabel(project["name"]); name.setToolTip(project["name"]); name.setStyleSheet("font-size: 14px; font-weight: 680; color: #253247; border: none;"); layout.addWidget(name, 1)
        category_select = QComboBox(); category_select.setFixedSize(138, 34); category_select.addItems(window.categories[1:]); category_select.setCurrentText(project.get("category", "未分类")); category_select.setToolTip("调整项目分类"); category_select.setAccessibleName(f"{project['name']} 的项目分类")
        category_select.setStyleSheet("QComboBox { background: #f3f6fa; border: 1px solid transparent; border-radius: 8px; padding: 4px 10px; color: #526071; font-size: 12px; } QComboBox:hover, QComboBox:focus { background: #eef3f8; border-color: #cbd7e5; } QComboBox::drop-down { border: none; width: 22px; }")
        category_select.activated[str].connect(lambda category: window.change_project_category(project, category)); layout.addWidget(category_select)
        running = [item for item in self.conversations if codex_state(item)[0] == "running"]
        completed = [item for item in self.conversations if codex_state(item)[0] == "completed"]
        if running:
            status_text, status_color = "● 运行中", "#16803c"
        elif completed:
            status_text, status_color = "● 已完成", "#2563eb"
        else:
            status_text, status_color = "● 已关联", "#5f6368"
        count = QLabel(f"{len(self.conversations)} 个对话"); count.setFixedWidth(72); count.setAlignment(Qt.AlignRight | Qt.AlignVCenter); count.setStyleSheet("color: #748094; font-size: 11px; border: none;"); layout.addWidget(count)
        status = QLabel(status_text); status.setFixedWidth(78); status.setAlignment(Qt.AlignCenter); status.setStyleSheet(f"color: {status_color}; background: {'#e8f7ef' if running else '#eef2f6'}; border-radius: 9px; padding: 4px 7px; font-size: 11px; font-weight: 650;"); layout.addWidget(status)
        continue_button = QPushButton("继续项目"); continue_button.setFixedSize(94, 34); continue_button.setIcon(fluent_icon("\uE72A", color="#1d4ed8", size=14)); continue_button.setIconSize(QSize(14, 14)); continue_button.setToolTip("复制项目上下文，回到 Codex 继续")
        continue_button.setAccessibleName(f"继续项目 {project['name']}")
        continue_button.setStyleSheet("QPushButton { color: #1d4ed8; background: #edf3ff; border: 1px solid #c8d8f4; border-radius: 8px; padding: 4px 9px; font-size: 12px; font-weight: 650; } QPushButton:hover, QPushButton:focus { background: #dfe9fb; border-color: #9eb8e4; }")
        continue_button.clicked.connect(lambda: window.copy_context(project)); layout.addWidget(continue_button)
        more = QToolButton(); more.setFixedSize(32, 32); more.setIcon(fluent_icon("\uE712", size=15)); more.setIconSize(QSize(15, 15)); more.setToolTip("更多项目操作")
        more.setAccessibleName(f"{project['name']} 的更多操作")
        more.setStyleSheet("QToolButton { border: none; border-radius: 7px; background: transparent; } QToolButton:hover, QToolButton:focus { background: #edf3fb; } QToolButton::menu-indicator { image: none; }")
        project_menu = QMenu(more)
        folder_action = project_menu.addAction(fluent_icon("\uE838", size=14), "打开文件夹"); folder_action.triggered.connect(lambda: window.open_folder(project))
        up_action = project_menu.addAction(fluent_icon("\uE74A", size=14), "向上移动"); up_action.triggered.connect(lambda: window.move_project(project, -1))
        down_action = project_menu.addAction(fluent_icon("\uE74B", size=14), "向下移动"); down_action.triggered.connect(lambda: window.move_project(project, 1))
        project_menu.addSeparator()
        edit_action = project_menu.addAction(fluent_icon("\uE70F", size=14), "编辑项目"); edit_action.triggered.connect(lambda: window.edit_project(project))
        delete_action = project_menu.addAction(fluent_icon("\uE74D", color="#b42318", size=14), "从项目中心移除"); delete_action.triggered.connect(lambda: window.delete_project(project))
        more.setMenu(project_menu); more.setPopupMode(QToolButton.InstantPopup); layout.addWidget(more); root.addWidget(header)
        self.details = QFrame(); self.details.setObjectName("conversationDetails"); self.details.setStyleSheet("QFrame#conversationDetails { background: #f7f9fc; border: none; border-top: 1px solid #e3e9f0; border-radius: 0 0 10px 10px; }")
        detail_layout = QVBoxLayout(self.details); detail_layout.setContentsMargins(54, 8, 12, 10); detail_layout.setSpacing(6)
        for conversation in self.conversations:
            detail_layout.addWidget(ConversationRow(conversation, window))
        root.addWidget(self.details)
        default_open = bool(running)
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


class TaskEditor(QDialog):
    def __init__(self, parent, projects, task=None, default_date=None):
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
        current_project_id = self.task.get("projectId")
        current_project = next((item for item in projects if item.get("id") == current_project_id), None)
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
        status_index = self.status_field.findData(self.task.get("status", "planned")); self.status_field.setCurrentIndex(max(0, status_index)); layout.addWidget(self.status_field)
        layout.addWidget(QLabel("备注")); self.notes_field = QTextEdit(self.task.get("notes", "")); self.notes_field.setFixedHeight(88); self.notes_field.setAccessibleName("任务备注"); self.notes_field.setPlaceholderText("补充交付标准、重点或下一步…"); layout.addWidget(self.notes_field)
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
        }


class TodayTaskCard(QFrame):
    def __init__(self, task, window):
        super().__init__()
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
        root.addLayout(headline)
        meta_row = QHBoxLayout(); meta_row.setSpacing(7)
        meta = ElidedLabel(f"{project_name}  ·  {conversation_title}"); meta.setStyleSheet("color: #66758a; font-size: 11px; border: none;"); meta_row.addWidget(meta, 1)
        if conversation_state == "running":
            live = QLabel("● Codex 运行中"); live.setStyleSheet("color: #087443; background: #e3f6ec; border: 1px solid #b6e1c9; border-radius: 8px; padding: 3px 7px; font-size: 10px; font-weight: 700;"); meta_row.addWidget(live)
        elif not task.get("sessionId"):
            manual = QLabel("手动状态"); manual.setToolTip("未关联具体 Codex 对话，因此不会自动切换任务状态")
            manual.setStyleSheet("color: #8a5a00; background: #fff4d8; border: none; border-radius: 7px; padding: 3px 7px; font-size: 11px; font-weight: 600;")
            meta_row.addWidget(manual)
        if task.get("carriedFromTaskId"):
            carried = QLabel("延续任务"); carried.setToolTip(f"由 {task.get('carriedFromDate', '前一天')} 的进行中任务自动延续")
            carried.setStyleSheet("color: #315f9b; background: #eaf2ff; border: none; border-radius: 7px; padding: 3px 7px; font-size: 11px; font-weight: 500;")
            meta_row.addWidget(carried)
        root.addLayout(meta_row)
        if task.get("notes"):
            notes = ElidedLabel(task["notes"].replace("\n", " ")); notes.setStyleSheet("color: #526071; font-size: 11px; border: none;"); root.addWidget(notes)
        actions = QHBoxLayout(); actions.setSpacing(6)
        status = QComboBox(); status.setFixedSize(86, 30); status.setToolTip("调整任务状态")
        for value, label in TASK_STATUS.items(): status.addItem(label, value)
        status.setCurrentIndex(max(0, status.findData(task.get("status", "planned"))))
        status.setStyleSheet(f"QComboBox {{ background: {tint}; color: {accent}; border: 1px solid {accent}; border-radius: 8px; padding: 2px 8px; font-size: 11px; font-weight: 650; }} QComboBox::drop-down {{ border: none; width: 18px; }}")
        status.activated.connect(lambda _index: window.set_task_status(task["id"], status.currentData())); actions.addWidget(status); actions.addStretch()
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
        edit_action = menu.addAction(fluent_icon("\uE70F", size=14), "编辑任务")
        edit_action.triggered.connect(lambda: window.edit_today_task(task))
        delete_action = menu.addAction(fluent_icon("\uE74D", color="#b42318", size=14), "删除任务")
        delete_action.triggered.connect(lambda: window.delete_today_task(task))
        more.setMenu(menu); more.setPopupMode(QToolButton.InstantPopup); actions.addWidget(more)
        root.addLayout(actions)


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
        meta = QLabel(f"{project_name}{carry_text}"); meta.setStyleSheet("color: #718096; font-size: 11px; border: none;"); content.addWidget(meta)
        layout.addLayout(content, 1)
        state = QLabel(TASK_STATUS.get(status, status)); state.setAlignment(Qt.AlignCenter); state.setFixedSize(62, 26)
        state.setStyleSheet(f"color: {color}; background: {tint}; border: none; border-radius: 8px; font-size: 11px; font-weight: 600;"); layout.addWidget(state)


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
        self.summary.setText(f"{len(records)} 项 · {counts['planned']} 计划 · {counts['doing']} 进行中 · {counts['done']} 已完成")
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.projects, self.saved_projects, self.category, self.running_count = [], [], "全部", 0
        self.categories = load_categories()
        self.project_layout = load_project_layout()
        self.today_tasks = load_json(TASKS_FILE, [])
        self.usage_data, self.usage_scanner = {}, None
        self.section = "home"
        self.live_sessions, self.scan_ready, self.session_scanner = [], False, None
        self.expansion_preferences = {}
        self.view_signature = None
        self.last_scan_at = None
        self.home_scroll_reset_done = False
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

        live_frame = QFrame(); live_frame.setObjectName("liveSummary"); live_frame.setFixedHeight(54); live_frame.setMinimumWidth(250)
        live_frame.setStyleSheet("QFrame#liveSummary { background: #f8fafc; border: 1px solid #d9e2ec; border-radius: 12px; }")
        live_layout = QHBoxLayout(live_frame); live_layout.setContentsMargins(13, 7, 14, 7); live_layout.setSpacing(10)
        live_icon = QLabel(); live_icon.setFixedSize(32, 32); live_icon.setAlignment(Qt.AlignCenter)
        live_icon.setPixmap(fluent_icon("\uE768", color="#2563eb", size=18).pixmap(QSize(18, 18)))
        live_icon.setStyleSheet("background: #e9f0ff; border: none; border-radius: 9px;"); live_layout.addWidget(live_icon)
        live_text = QVBoxLayout(); live_text.setSpacing(0)
        live_caption = QLabel("CODEX 工作区"); live_caption.setStyleSheet("color: #77869a; font-size: 10px; font-weight: 650; letter-spacing: 0.7px;"); live_text.addWidget(live_caption)
        self.pulse_state_label = QLabel("正在同步本地对话"); self.pulse_state_label.setStyleSheet("color: #42526a; font-size: 13px; font-weight: 650;"); live_text.addWidget(self.pulse_state_label)
        live_layout.addLayout(live_text, 1); top_layout.addWidget(live_frame, 1)

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
        self.setStatusBar(QStatusBar()); self.select_section("home")

    def build_projects_page(self):
        main = QWidget(); main.setObjectName("projectsPage"); main.setStyleSheet("QWidget#projectsPage { background: #f5f7fb; } QWidget#projectsPage QLabel { background: transparent; }"); main_layout = QVBoxLayout(main); main_layout.setContentsMargins(32, 26, 28, 24); main_layout.setSpacing(16)
        heading = QHBoxLayout(); heading.setSpacing(24)
        heading_text = QVBoxLayout(); heading_text.setSpacing(4)
        title = QLabel("项目"); title.setStyleSheet("font-size: 29px; font-weight: 720; color: #172033;"); heading_text.addWidget(title)
        subtitle = QLabel("管理项目分类，并查看与 Codex 对话的关联状态")
        subtitle.setStyleSheet("color: #66758a; font-size: 13px;"); heading_text.addWidget(subtitle)
        heading.addLayout(heading_text); heading.addStretch()
        new_project = QPushButton("新建项目"); new_project.setIcon(fluent_icon("\uE710", color="#ffffff", size=15)); new_project.setIconSize(QSize(15, 15)); new_project.setObjectName("primary"); new_project.setFixedHeight(40); new_project.clicked.connect(lambda: self.edit_project(None)); heading.addWidget(new_project); main_layout.addLayout(heading)
        tools = QHBoxLayout(); tools.setSpacing(8)
        self.search = QLineEdit(); self.search.setFixedHeight(42); self.search.setPlaceholderText("搜索项目、分类或 Codex 对话"); self.search.textChanged.connect(self.render); tools.addWidget(self.search)
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

        board_head = QHBoxLayout(); board_head.setSpacing(9)
        board_icon = QLabel(); board_icon.setFixedSize(26, 26); board_icon.setPixmap(fluent_icon("\uE9D2", color="#176cff", size=19).pixmap(QSize(19, 19))); board_icon.setAlignment(Qt.AlignCenter); board_head.addWidget(board_icon)
        self.task_board_title = QLabel("今日任务规划"); self.task_board_title.setStyleSheet("font-size: 20px; font-weight: 700; color: #172033;"); board_head.addWidget(self.task_board_title)
        self.task_summary = QLabel(); self.task_summary.setStyleSheet("color: #66758a; font-size: 12px;"); board_head.addWidget(self.task_summary); board_head.addStretch()
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
        self.render_today_tasks()
        return page

    def select_section(self, section):
        self.section = section
        self.pages.setCurrentWidget(self.home_page if section == "home" else self.projects_page)
        for button, active in ((self.home_nav_button, section == "home"), (self.project_nav_button, section == "projects")):
            button.setProperty("active", active); button.style().unpolish(button); button.style().polish(button)
        if hasattr(self, "nav"):
            self.render_nav()

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
        signature = tuple(
            (
                project.get("id"), project.get("name"), project.get("path"), project.get("category"),
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

    def render_live_conversations(self):
        if not hasattr(self, "live_layout"):
            return
        while self.live_layout.count():
            item = self.live_layout.takeAt(0)
            if item.widget():
                item.widget().hide(); item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        running = []
        for project in self.projects:
            for session in project.get("conversations", []):
                state = codex_state(session)[0]
                if state == "running":
                    running.append((project, session))
        active = bool(running)
        panel_border = "#9fdabc" if active else "#d8e3f0"
        panel_bg = "#f1fbf6" if active else "#f8fbff"
        self.live_panel.setStyleSheet(f"QFrame#livePanel {{ background: {panel_bg}; border: 1px solid {panel_border}; border-radius: 13px; }} QFrame#livePanel QLabel {{ background: transparent; }}")
        header = QHBoxLayout(); header.setSpacing(8)
        live_icon = QLabel(); live_icon.setFixedSize(20, 20); live_icon.setPixmap(fluent_icon("\uE768", color="#0f9f64" if active else "#64748b", size=16).pixmap(QSize(16, 16))); live_icon.setAlignment(Qt.AlignCenter); header.addWidget(live_icon)
        title = QLabel("Codex 实时对话")
        title.setStyleSheet("font-size: 14px; font-weight: 600; color: #243247; border: none;")
        header.addWidget(title)
        header.addStretch()
        badge = QLabel(f"{len(running)} 运行中")
        badge_color = "#087443" if active else "#64748b"
        badge_bg = "#dff7e9" if active else "#edf2f7"
        badge.setStyleSheet(f"color: {badge_color}; background: {badge_bg}; border: none; border-radius: 9px; padding: 4px 9px; font-size: 11px; font-weight: 600;")
        header.addWidget(badge)
        header_widget = QWidget(); header_widget.setLayout(header); header_widget.setStyleSheet("background: transparent;")
        self.live_layout.addWidget(header_widget)
        visible_sessions = running
        if not visible_sessions:
            message = "正在读取本机 Codex 对话状态…" if not self.scan_ready else "当前没有正在执行的 Codex 对话；项目仍可继续保持“项目进行中”状态。"
            empty = QLabel(message)
            empty.setStyleSheet("color: #68758a; font-size: 12px; border: none; padding: 3px 28px 4px;")
            self.live_layout.addWidget(empty)
            return
        rows = QHBoxLayout(); rows.setSpacing(8)
        for project, session in visible_sessions[:3]:
            state, state_label, state_color = codex_state(session)
            border = "#94d4b3" if state == "running" else "#e3c786"
            background = "#ffffff" if state == "running" else "#fffaf0"
            card = QFrame(); card.setStyleSheet(f"background: {background}; border: 1px solid {border}; border-radius: 9px;")
            card_layout = QVBoxLayout(card); card_layout.setContentsMargins(11, 8, 11, 8); card_layout.setSpacing(3)
            name = QLabel(f"● {project['name']}  ·  {state_label}")
            name.setStyleSheet(f"color: {state_color}; font-size: 12px; font-weight: 700; border: none;")
            card_layout.addWidget(name)
            summary = QLabel((session.get("summary") or "Codex 正在处理本项目")[:62])
            summary.setWordWrap(True); summary.setStyleSheet("color: #344054; font-size: 11px; border: none;")
            card_layout.addWidget(summary)
            meta = QLabel(f"{conversation_name(session)} · {relative_time(session)}")
            meta.setStyleSheet("color: #748094; font-size: 11px; border: none;")
            card_layout.addWidget(meta)
            rows.addWidget(card, 1)
        row_widget = QWidget(); row_widget.setLayout(rows); row_widget.setStyleSheet("background: transparent;")
        self.live_layout.addWidget(row_widget)

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
            button = QPushButton(f"{category}    {count}"); button.setObjectName("categoryNav"); button.setProperty("active", self.section == "projects" and category == self.category)
            button.setIcon(fluent_icon("\uECCA", color="#94a3b8", size=8)); button.setIconSize(QSize(8, 8))
            button.clicked.connect(lambda _checked=False, value=category: self.select_category(value)); self.nav.addWidget(button)

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

    def project_by_id(self, project_id):
        return next((project for project in self.projects if project.get("id") == project_id), None)

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
            if task.get("status", "planned") != "planned":
                continue
            if (task.get("date") or today) != today:
                continue
            if str(task.get("sessionId") or "") not in running_sessions:
                continue
            task["status"] = "doing"
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
        tasks = [task for task in self.today_tasks if (task.get("date") or QDate.currentDate().toString(Qt.ISODate)) == date_key]
        title = "今日任务规划" if selected_date == QDate.currentDate() else selected_date.toString("MM月dd日任务规划")
        self.task_board_title.setText(title)
        counts = {status: sum(task.get("status") == status for task in tasks) for status in TASK_STATUS}
        self.task_summary.setText(f"{len(tasks)} 项 · {counts['doing']} 项进行中 · {counts['done']} 项完成")
        for status, label in TASK_STATUS.items():
            accent = TASK_COLORS[status]
            surface = {"planned": "#faf8ff", "doing": "#f7faff", "done": "#f7fcf9"}.get(status, "#f8fafc")
            column = QFrame(); column.setObjectName("taskColumn"); column.setMinimumSize(250, 236); column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            column.setStyleSheet(f"QFrame#taskColumn {{ background: {surface}; border: 1px solid #d8e1eb; border-top: 3px solid {accent}; border-radius: 12px; }} QFrame#taskColumn QLabel {{ background: transparent; }}")
            column_layout = QVBoxLayout(column); column_layout.setContentsMargins(12, 10, 12, 12); column_layout.setSpacing(8)
            header = QHBoxLayout(); header.setSpacing(7)
            state_icon = QLabel(); state_icon.setFixedSize(18, 18); state_icon.setPixmap(fluent_icon("\uE768", color=accent, size=14).pixmap(QSize(14, 14))); state_icon.setAlignment(Qt.AlignCenter); header.addWidget(state_icon)
            name = QLabel(label); name.setStyleSheet("font-size: 14px; font-weight: 700; color: #253247; border: none;"); header.addWidget(name); header.addStretch()
            count = QLabel(str(counts[status])); count_bg = accent if counts[status] else "#e1eaf6"; count_color = "#ffffff" if counts[status] else "#637994"; count.setAlignment(Qt.AlignCenter); count.setFixedSize(24, 20); count.setStyleSheet(f"color: {count_color}; background: {count_bg}; font-size: 10px; font-weight: 700; border: none; border-radius: 9px;"); header.addWidget(count); column_layout.addLayout(header)
            status_tasks = sorted([task for task in tasks if task.get("status", "planned") == status], key=lambda task: task.get("createdAt", ""))
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
        recent = sorted(tasks, key=lambda task: task.get("updatedAt") or task.get("createdAt") or "", reverse=True)[:6]
        if not recent:
            empty = QLabel("当天还没有任务记录"); empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #6b809e; padding: 24px; font-size: 12px;")
            self.activity_rows_layout.addWidget(empty)
            return
        action_names = {"planned": "任务计划", "doing": "任务推进", "done": "任务完成"}
        for index, task in enumerate(recent):
            status = task.get("status", "planned"); accent = TASK_COLORS.get(status, "#64748b")
            row = QFrame(); row.setObjectName("activityRow"); row.setFixedHeight(46)
            border = "border-bottom: 1px solid #e5eaf0;" if index < len(recent) - 1 else "border: none;"
            row.setStyleSheet(f"QFrame#activityRow {{ background: transparent; {border} }} QFrame#activityRow:hover {{ background: #f5f8fc; }}")
            row_layout = QHBoxLayout(row); row_layout.setContentsMargins(8, 4, 8, 4); row_layout.setSpacing(11)
            icon = QLabel(); icon.setFixedSize(24, 24); icon.setPixmap(fluent_icon("\uE8A7", color=accent, size=15).pixmap(QSize(15, 15))); icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet(f"background: { {'planned':'#f1eaff','doing':'#e6f1ff','done':'#e4f7ed'}.get(status, '#eef4fb') }; border: 1px solid {accent}; border-radius: 6px;"); row_layout.addWidget(icon)
            kind = QLabel(action_names.get(status, "任务更新")); kind.setFixedWidth(76); kind.setStyleSheet(f"color: {accent}; font-size: 11px; font-weight: 650;"); row_layout.addWidget(kind)
            project = self.project_by_id(task.get("projectId")); project_name = (project or {}).get("name") or "未关联项目"
            description = ElidedLabel(f"{task.get('title') or '未命名任务'}  ·  {project_name}"); description.setStyleSheet("color: #34445c; font-size: 12px;"); row_layout.addWidget(description, 1)
            source = QLabel("Codex" if task.get("sessionId") else "手动"); source.setStyleSheet("color: #748094; font-size: 11px;"); row_layout.addWidget(source)
            try:
                updated = datetime.fromisoformat(task.get("updatedAt") or task.get("createdAt") or "").strftime("%H:%M")
            except ValueError:
                updated = "—"
            time_label = QLabel(updated); time_label.setFixedWidth(44); time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter); time_label.setStyleSheet("color: #53647a; font-size: 11px; font-weight: 600;"); row_layout.addWidget(time_label)
            self.activity_rows_layout.addWidget(row)

    def show_task_history(self, initial_tab=0):
        selected = self.board_date_field.date().toString(Qt.ISODate) if hasattr(self, "board_date_field") else None
        dialog = TaskHistoryDialog(self, self.today_tasks, selected)
        if hasattr(dialog, "tabs"):
            dialog.tabs.setCurrentIndex(max(0, min(initial_tab, dialog.tabs.count() - 1)))
        dialog.exec_()

    def new_today_task(self):
        self.edit_today_task(None)

    def edit_today_task(self, task=None):
        default_date = self.board_date_field.date().toString(Qt.ISODate) if hasattr(self, "board_date_field") else QDate.currentDate().toString(Qt.ISODate)
        dialog = TaskEditor(self, self.projects, task, default_date)
        if dialog.exec_() != QDialog.Accepted:
            return
        data = dialog.value()
        if not data.get("title"):
            QMessageBox.information(self, "任务名称为空", "请输入一个清晰的任务名称。")
            return
        now = datetime.now().isoformat(timespec="seconds")
        if task is None:
            task = {"id": str(uuid.uuid4()), "createdAt": now}
            self.today_tasks.append(task)
        task.update(data); task["updatedAt"] = now
        save_json(TASKS_FILE, self.today_tasks)
        task_date = QDate.fromString(task.get("date", ""), Qt.ISODate)
        if task_date.isValid(): self.board_date_field.setDate(task_date)
        self.render_today_tasks()
        if dialog.codex_requested:
            self.plan_task_in_codex(task)
        else:
            self.statusBar().showMessage("今日任务已保存", 2500)

    def set_task_status(self, task_id, status):
        task = next((item for item in self.today_tasks if item.get("id") == task_id), None)
        if not task or status not in TASK_STATUS:
            return
        task["status"] = status; task["updatedAt"] = datetime.now().isoformat(timespec="seconds"); save_json(TASKS_FILE, self.today_tasks); self.render_today_tasks()

    def delete_today_task(self, task):
        if QMessageBox.question(self, "删除任务", f"确定删除“{task.get('title', '未命名任务')}”吗？") != QMessageBox.Yes:
            return
        self.today_tasks = [item for item in self.today_tasks if item.get("id") != task.get("id")]; save_json(TASKS_FILE, self.today_tasks); self.render_today_tasks()

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
                "nextStep": project.get("nextStep", ""),
            }
            self.saved_projects.append(target)
        project["savedId"] = target["id"]
        return target

    def change_project_category(self, project, category):
        if category not in self.categories[1:] or category == project.get("category"):
            return
        previous_category = project.get("category", "未分类")
        target = self.saved_record_for_project(project)
        target["category"] = category
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

    def delete_project(self, project):
        message = f"确定从项目中心移除“{project.get('name', '未命名项目')}”吗？\n\n不会删除磁盘文件，也不会删除 Codex 对话。"
        if QMessageBox.question(self, "移除项目", message) != QMessageBox.Yes:
            return
        project_id = project.get("id")
        if project.get("codexProjectId"):
            hidden = self.project_layout.setdefault("hiddenProjectIds", [])
            if project_id not in hidden:
                hidden.append(project_id)
        else:
            saved_id = project.get("savedId")
            self.saved_projects = [item for item in self.saved_projects if item.get("id") != saved_id]
            save_json(PROJECTS_FILE, self.saved_projects)
        for values in self.project_layout.setdefault("categoryOrders", {}).values():
            while project_id in values:
                values.remove(project_id)
        save_json(PROJECT_LAYOUT_FILE, self.project_layout)
        self.view_signature = None
        self.refresh(silent=True, scan=False)
        self.statusBar().showMessage("项目已从项目中心移除", 2500)

    def shown(self):
        query = self.search.text().strip().lower()
        return [item for item in self.projects if (self.category == "全部" or item.get("category") == self.category) and (not query or query in f"{item.get('name','')} {item.get('path','')} {item.get('nextStep','')}".lower())]

    def render(self):
        projects = self.shown()
        if self.category == "全部":
            self.project_content.setCurrentWidget(self.mind_map)
            self.mind_map.update_map(projects, self.categories)
            return
        self.project_content.setCurrentWidget(self.scroll)
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget(): item.widget().hide(); item.widget().deleteLater()
        groups = {}
        for project in projects: groups.setdefault(project.get("category", "未分类"), []).append(project)
        order = [item for item in self.categories[1:] if item in groups] + sorted(set(groups) - set(self.categories))
        if not order:
            empty = QLabel("没有找到匹配的项目"); empty.setAlignment(Qt.AlignCenter); empty.setStyleSheet("color: #737373; font-size: 13px; padding: 90px;"); self.list.addWidget(empty); return
        for category in order:
            header = QLabel(f"{category}    {len(groups[category])} 个项目"); header.setStyleSheet("color: #34445c; font-size: 15px; font-weight: 700; padding: 12px 2px 4px;"); self.list.addWidget(header)
            rows_holder = ProjectReorderContainer(self, category); rows = QVBoxLayout(rows_holder); rows.setContentsMargins(0, 0, 0, 10); rows.setSpacing(8)
            for project in groups[category]: rows.addWidget(ProjectGroup(project, self))
            self.list.addWidget(rows_holder)
        self.list.addStretch()

    def copy_context(self, project):
        recent = (project.get("lastActivity") or {}).get("summary") or "暂无自动同步的进度记录。"
        text = f"继续项目：{project['name']}\n工作目录：{project['path']}\n当前下一步：{project.get('nextStep') or '请先判断下一步'}\n最近动态：{recent}\n\n请先读取项目现状，简要汇报当前进度和建议的下一步，再等待我的具体指令。"
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("已复制项目上下文，回到 Codex 粘贴即可继续", 3500)

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
        if project:
            previous_category = project.get("category", "未分类")
            target = self.saved_record_for_project(project)
            target.update(data)
            if data.get("category") != previous_category:
                orders = self.project_layout.setdefault("categoryOrders", {})
                orders[previous_category] = [value for value in orders.get(previous_category, []) if value != project.get("id")]
                orders.setdefault(data["category"], []).append(project.get("id"))
        else:
            target = next((item for item in self.saved_projects if normalized_path(item.get("path")) == normalized_path(data.get("path"))), None)
            if target is None:
                target = {"id": str(uuid.uuid4())}; self.saved_projects.append(target)
            target.update(data)
            codex_projects = codex_sidebar_projects(self.saved_projects)
            codex_match = next((item for item in codex_projects if normalized_path(item.get("path")) == normalized_path(data.get("path"))), None)
            target["manualProject"] = codex_match is None
            if codex_match:
                hidden = self.project_layout.setdefault("hiddenProjectIds", [])
                self.project_layout["hiddenProjectIds"] = [value for value in hidden if value != codex_match.get("id")]
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
