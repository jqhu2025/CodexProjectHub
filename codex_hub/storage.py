"""Reliable JSON persistence for local Codex Project Hub data.

Writes are atomic and keep the previous valid document as a local safety copy.
Reads can fall back to that copy without making the UI depend on storage details.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any


@dataclass(frozen=True)
class JsonRecoveryEvent:
    """One primary-file read failure observed by the storage layer."""

    path: Path
    backup_path: Path
    reason: str
    recovered: bool

    @property
    def filename(self) -> str:
        return self.path.name


_EVENT_LOCK = threading.Lock()
_PENDING_EVENTS: list[JsonRecoveryEvent] = []
_FAILURE_SIGNATURES: dict[str, tuple[Any, ...]] = {}


def json_backup_path(path: str | os.PathLike[str]) -> Path:
    """Return the private rolling-backup location for a JSON document."""

    source = Path(path)
    return source.parent / ".backups" / f"{source.name}.bak"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _failure_reason(error: BaseException) -> str:
    if isinstance(error, FileNotFoundError):
        return "missing"
    if isinstance(error, (json.JSONDecodeError, UnicodeError)):
        return "invalid"
    return "unreadable"


def _file_signature(path: Path) -> tuple[Any, ...]:
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError as error:
        return (type(error).__name__, getattr(error, "errno", None))


def _event_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _record_failure(path: Path, backup: Path, reason: str, recovered: bool) -> None:
    key = _event_key(path)
    signature = (reason, recovered, *_file_signature(path), *_file_signature(backup))
    with _EVENT_LOCK:
        if _FAILURE_SIGNATURES.get(key) == signature:
            return
        _FAILURE_SIGNATURES[key] = signature
        _PENDING_EVENTS.append(JsonRecoveryEvent(path, backup, reason, recovered))


def _clear_failure(path: Path) -> None:
    with _EVENT_LOCK:
        _FAILURE_SIGNATURES.pop(_event_key(path), None)


def consume_json_recovery_events() -> list[JsonRecoveryEvent]:
    """Return newly observed recovery events once for the current process."""

    with _EVENT_LOCK:
        events = list(_PENDING_EVENTS)
        _PENDING_EVENTS.clear()
    return events


def load_json(
    path: str | os.PathLike[str],
    default: Any,
    *,
    use_backup: bool = True,
    report_failure: bool = True,
) -> Any:
    """Load JSON, falling back to the last known-good local copy when possible."""

    source = Path(path)
    backup = json_backup_path(source)
    try:
        value = _read_json(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as primary_error:
        reason = _failure_reason(primary_error)
        if use_backup:
            try:
                value = _read_json(backup)
            except (OSError, UnicodeError, json.JSONDecodeError):
                if report_failure and not (
                    isinstance(primary_error, FileNotFoundError) and not backup.exists()
                ):
                    _record_failure(source, backup, reason, recovered=False)
                return default
            if report_failure:
                _record_failure(source, backup, reason, recovered=True)
            return value
        return default
    _clear_failure(source)
    return value


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def save_json(path: str | os.PathLike[str], data: Any) -> None:
    """Atomically save JSON after preserving the previous valid document."""

    destination = Path(path)
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    try:
        previous_payload = destination.read_bytes()
        json.loads(previous_payload.decode("utf-8-sig"))
    except FileNotFoundError:
        previous_payload = None
    except (OSError, UnicodeError, json.JSONDecodeError):
        # Never replace a known-good safety copy with an unreadable primary.
        previous_payload = None

    if previous_payload is not None:
        _atomic_write(json_backup_path(destination), previous_payload)
    _atomic_write(destination, payload)
