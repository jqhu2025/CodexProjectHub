"""Codex quota and local token telemetry without Qt dependencies."""

import json
import mmap
import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


_LOCAL_TOKEN_CACHE = {"root": None, "date": None, "files": {}}


def reset_local_token_cache():
    """Clear incremental token offsets; primarily useful after a day or root change."""
    _LOCAL_TOKEN_CACHE.update({"root": None, "date": None, "files": {}})


def _initial_file_state(path, target_start):
    """Walk token events backward only as far as the requested local day."""
    try:
        size = path.stat().st_size
        if size <= 0:
            return {"offset": 0, "previousTotal": None, "tokens": 0}
        with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapping:
            target = target_start.date().isoformat()
            local_tz = target_start.tzinfo
            target_totals = []
            baseline_total = None
            marker = b'"payload":{"type":"token_count"'
            cursor = size
            while cursor > 0:
                marker_at = mapping.rfind(marker, 0, cursor)
                if marker_at < 0:
                    break
                line_start = mapping.rfind(b"\n", 0, marker_at) + 1
                line_end = mapping.find(b"\n", marker_at)
                if line_end < 0:
                    line_end = size
                try:
                    record = json.loads(mapping[line_start:line_end])
                    payload = record.get("payload") or {}
                    if payload.get("type") != "token_count":
                        cursor = marker_at
                        continue
                    token_usage = ((payload.get("info") or {}).get("total_token_usage") or {})
                    current_total = int(token_usage.get("total_tokens") or 0)
                    point = datetime.fromisoformat(str(record.get("timestamp") or record.get("at") or "").replace("Z", "+00:00"))
                    if point.tzinfo is None:
                        point = point.replace(tzinfo=timezone.utc)
                    event_date = point.astimezone(local_tz).date().isoformat()
                except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
                    cursor = marker_at
                    continue
                if current_total <= 0:
                    cursor = marker_at
                    continue
                if event_date < target:
                    baseline_total = current_total
                    break
                if event_date == target:
                    target_totals.append(current_total)
                cursor = marker_at

            previous_total = baseline_total
            tokens = 0
            for current_total in reversed(target_totals):
                delta = current_total if previous_total is None or current_total < previous_total else current_total - previous_total
                tokens += max(0, delta)
                previous_total = current_total
            return {"offset": size, "previousTotal": previous_total, "tokens": tokens}
    except (OSError, OverflowError, ValueError):
        return {"offset": 0, "previousTotal": None, "tokens": 0}


def local_codex_tokens_for_date(sessions_root, date_value=None, now=None):
    """Estimate one day's usage from cumulative token events in local Codex logs."""
    now = now or datetime.now().astimezone()
    target = str(date_value or now.date().isoformat())
    local_tz = now.astimezone().tzinfo
    try:
        target_start = datetime.strptime(target, "%Y-%m-%d").replace(tzinfo=local_tz)
    except ValueError:
        return 0

    root = Path(sessions_root)
    root_key = str(root.resolve()) if root.exists() else str(root)
    if _LOCAL_TOKEN_CACHE.get("root") != root_key or _LOCAL_TOKEN_CACHE.get("date") != target:
        _LOCAL_TOKEN_CACHE.update({"root": root_key, "date": target, "files": {}})
    cache_files = _LOCAL_TOKEN_CACHE["files"]
    try:
        files = root.rglob("*.jsonl")
    except OSError:
        return 0

    cutoff_mtime = target_start.timestamp()
    for path in files:
        try:
            stat = path.stat()
            if stat.st_mtime < cutoff_mtime:
                continue
            cache_key = str(path)
            state = cache_files.get(cache_key)
            if state is None:
                state = _initial_file_state(path, target_start)
            if stat.st_size < state["offset"]:
                state = _initial_file_state(path, target_start)
            previous_total = state["previousTotal"]
            with path.open("rb") as stream:
                stream.seek(state["offset"])
                while True:
                    line_start = stream.tell()
                    line = stream.readline()
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        stream.seek(line_start)
                        break
                    if b'"payload":{"type":"token_count"' not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    payload = record.get("payload") or {}
                    if payload.get("type") != "token_count":
                        continue
                    token_usage = ((payload.get("info") or {}).get("total_token_usage") or {})
                    current_total = int(token_usage.get("total_tokens") or 0)
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
        except (OSError, TypeError, ValueError):
            continue
    return sum(int(state.get("tokens") or 0) for state in cache_files.values())


def read_codex_rate_limits(binary, timeout=5):
    """Read the one telemetry endpoint currently supported by Codex App Server."""
    process = None
    try:
        process = subprocess.Popen(
            [str(binary), "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        messages = queue.Queue()
        pending = {}

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

        def response(request_id):
            if request_id in pending:
                return pending.pop(request_id)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    message = messages.get(timeout=max(0.05, deadline - time.monotonic()))
                except queue.Empty:
                    break
                message_id = message.get("id")
                if message_id == request_id:
                    return message
                if message_id is not None:
                    pending[message_id] = message
            return None

        send({"method": "initialize", "id": 0, "params": {"clientInfo": {"name": "codex_project_hub", "title": "Codex Project Hub", "version": "0.4.0"}}})
        initialized = response(0)
        if not initialized:
            return {"error": "Codex App Server 初始化超时"}
        if initialized.get("error"):
            return initialized
        send({"method": "initialized", "params": {}})
        send({"method": "account/rateLimits/read", "id": 1, "params": {}})
        result = response(1)
        return result or {"error": "Codex 额度接口响应超时"}
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return {"error": str(error)}
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


def _response_error_text(response):
    error = (response or {}).get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "Codex 额度接口返回错误")
    return str(error or "")


def build_codex_usage_snapshot(response, today_tokens=0, now=None):
    """Normalize App Server quota data into the small UI telemetry contract."""
    now = now or datetime.now().astimezone()
    error_text = _response_error_text(response)
    base = {
        "todayTokens": max(0, int(today_tokens or 0)),
        "todayTokensSource": "local",
        "localTodayTokens": max(0, int(today_tokens or 0)),
        "syncedAt": now.strftime("%H:%M"),
    }
    if error_text:
        return {**base, "error": error_text}
    limits = ((response or {}).get("result") or {}).get("rateLimits") or {}
    primary = limits.get("primary") or {}
    if primary.get("usedPercent") is None:
        return {**base, "error": "Codex 未返回主额度窗口"}
    try:
        used = max(0, min(100, int(round(float(primary.get("usedPercent"))))))
    except (TypeError, ValueError):
        return {**base, "error": "Codex 返回了无法识别的额度值"}
    reset_at = primary.get("resetsAt")
    reset_text = "暂无刷新时间"
    if reset_at:
        try:
            timestamp = float(reset_at)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            reset_text = datetime.fromtimestamp(timestamp).strftime("%m月%d日 %H:%M")
        except (OSError, OverflowError, TypeError, ValueError):
            reset_text = "刷新时间未知"
    return {
        **base,
        "usedPercent": used,
        "remainingPercent": 100 - used,
        "resetText": reset_text,
        "windowMinutes": primary.get("windowDurationMins"),
        "planType": limits.get("planType") or "",
    }


def read_codex_usage(binary, sessions_root, timeout=5, now=None, rate_limit_reader=None):
    """Return real quota plus local tokens, retaining tokens even when quota fails."""
    now = now or datetime.now().astimezone()
    today = now.date().isoformat()
    today_tokens = local_codex_tokens_for_date(sessions_root, today, now)
    if not binary:
        return build_codex_usage_snapshot({"error": "未找到 Codex App Server"}, today_tokens, now)
    reader = rate_limit_reader or read_codex_rate_limits
    try:
        response = reader(binary, timeout=timeout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        response = {"error": str(error)}
    return build_codex_usage_snapshot(response, today_tokens, now)
