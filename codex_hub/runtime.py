import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


TERMINAL_EVENTS = {"task_complete", "task_aborted", "task_interrupted", "turn_aborted"}
START_EVENTS = {"task_started"}
ACTIVE_LOG_WINDOW_SECONDS = 150


def read_user_thread_rows(database_path):
    """Read non-archived, user-owned Codex threads from a database in read-only mode."""
    database = Path(database_path).as_posix()
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=0.2)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
        if "thread_source" in columns and "source" in columns:
            source_filter = """
              AND (
                    thread_source = 'user'
                    OR (
                        thread_source IS NULL
                        AND COALESCE(source, '') NOT LIKE '%subagent%'
                    )
                  )
            """
        elif "thread_source" in columns:
            source_filter = "AND COALESCE(thread_source, 'user') = 'user'"
        else:
            source_filter = ""
        return connection.execute(
            f"""
            SELECT id, cwd,
                   COALESCE(NULLIF(name, ''), NULLIF(title, ''), ''),
                   COALESCE(recency_at_ms, updated_at_ms, updated_at * 1000, created_at_ms, created_at * 1000, 0),
                   COALESCE(NULLIF(preview, ''), NULLIF(first_user_message, ''), ''),
                   COALESCE(rollout_path, '')
            FROM threads
            WHERE COALESCE(archived, 0) = 0
              {source_filter}
            """
        ).fetchall()
    finally:
        connection.close()


def analyze_session_records(records, modified_at, now=None, active_window_seconds=ACTIVE_LOG_WINDOW_SECONDS):
    """Classify a local Codex turn from explicit start/terminal events and log freshness."""
    now = now or datetime.now(timezone.utc)
    terminal_at = -1
    started_at = -1
    user_at = -1
    has_activity = False
    last_prompt = ""

    for position, record in enumerate(records):
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        event_type = payload.get("type") if record.get("type") == "event_msg" else ""
        if event_type in TERMINAL_EVENTS:
            terminal_at = position
        if event_type in START_EVENTS:
            started_at = position
        if event_type == "user_message":
            user_at = position
            if isinstance(payload.get("message"), str):
                last_prompt = payload["message"].replace("\n", " ").strip()
        if record.get("type") in {"event_msg", "response_item", "turn_context"}:
            has_activity = True

    latest_open_event = max(started_at, user_at)
    if not has_activity:
        state = "linked"
    elif terminal_at >= latest_open_event and terminal_at >= 0:
        state = "completed"
    elif latest_open_event >= 0 or terminal_at < 0:
        age = max(0.0, (now - modified_at).total_seconds())
        state = "working" if age <= active_window_seconds else "linked"
    else:
        state = "linked"

    return {"state": state, "lastPrompt": last_prompt, "hasActivity": has_activity}


def activity_state(activity):
    """Normalize persisted session states to the three states shown by the UI."""
    if not activity:
        return "linked"
    state = str(activity.get("state") or "linked")
    if state == "working":
        return "running"
    if state == "completed":
        return "completed"
    return "linked"


def find_codex_binary(local_app_data=None, path_env=None, override=None):
    """Locate Codex without depending on one desktop installation layout."""
    configured = override or os.environ.get("CODEX_EXECUTABLE")
    if configured and Path(configured).is_file():
        return str(Path(configured))

    local_root = Path(local_app_data or os.environ.get("LOCALAPPDATA", ""))
    bin_root = local_root / "OpenAI" / "Codex" / "bin"
    candidates = []
    direct = bin_root / "codex.exe"
    if direct.is_file():
        candidates.append(direct)
    try:
        candidates.extend(
            sorted(
                bin_root.glob("*/codex.exe"),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
        )
    except OSError:
        pass
    if candidates:
        return str(candidates[0])

    search_path = path_env if path_env is not None else os.environ.get("PATH")
    for command in ("codex.exe", "codex"):
        located = shutil.which(command, path=search_path)
        if located:
            return located
    return ""
