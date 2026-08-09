"""Small Windows UI bridge for user-visible Codex desktop actions.

The bridge is intentionally narrow: it selects one existing task by its exact
title, fills Codex's composer, and submits the prompt.  It never edits Codex's
databases or session files.
"""

from __future__ import annotations

import time


class CodexDesktopBridgeError(RuntimeError):
    """Raised when the Codex desktop window cannot be controlled safely."""


def _control_text(control) -> str:
    try:
        return str(control.window_text() or "").strip()
    except Exception:
        return ""


def _find_codex_window(timeout: float = 12.0):
    from pywinauto import Desktop

    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        candidates = []
        try:
            windows = Desktop(backend="uia").windows()
        except Exception as error:
            last_error = str(error)
            time.sleep(0.35)
            continue

        for window in windows:
            try:
                rectangle = window.rectangle()
                if not window.is_visible() or rectangle.width() < 700 or rectangle.height() < 480:
                    continue
                editors = window.descendants(control_type="Edit")
                if not any("随心输入" in _control_text(editor) for editor in editors):
                    continue
                candidates.append((rectangle.width() * rectangle.height(), window))
            except Exception as error:
                last_error = str(error)

        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
        time.sleep(0.35)

    detail = f"：{last_error}" if last_error else ""
    raise CodexDesktopBridgeError(f"未找到可操作的 Codex 桌面窗口{detail}")


def _select_thread(window, thread_title: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            window.set_focus()
            bounds = window.rectangle()
            matches = []
            for button in window.descendants(control_type="Button"):
                if _control_text(button) != thread_title:
                    continue
                rectangle = button.rectangle()
                # Task entries live in Codex's left navigation.  This prevents
                # an identically named control in the content area being used.
                if rectangle.left > bounds.left + max(430, int(bounds.width() * 0.42)):
                    continue
                matches.append(button)
            if matches:
                target = min(matches, key=lambda item: (item.rectangle().left, item.rectangle().top))
                try:
                    target.scroll_into_view()
                except Exception:
                    pass
                target.click_input()
                time.sleep(0.7)
                return
        except Exception:
            pass
        time.sleep(0.35)
    raise CodexDesktopBridgeError(f"Codex 侧边栏中未找到任务“{thread_title}”")


def _composer(window, timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            editors = [
                editor for editor in window.descendants(control_type="Edit")
                if "随心输入" in _control_text(editor) and editor.is_visible() and editor.is_enabled()
            ]
            if editors:
                return max(editors, key=lambda item: item.rectangle().width())
        except Exception:
            pass
        time.sleep(0.25)
    raise CodexDesktopBridgeError("未找到 Codex 消息输入框")


def _paste_unicode(prompt: str):
    import win32clipboard
    from pywinauto import keyboard

    previous = None
    for _ in range(20):
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                previous = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, prompt)
            win32clipboard.CloseClipboard()
            break
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            time.sleep(0.05)
    else:
        raise CodexDesktopBridgeError("无法写入剪贴板以发送中文总结请求")

    keyboard.send_keys("^v", pause=0.02)
    time.sleep(0.15)
    keyboard.send_keys("{ENTER}", pause=0.02)

    # Restore the user's text clipboard after Codex has consumed the paste.
    if previous is not None:
        time.sleep(0.15)
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, previous)
            win32clipboard.CloseClipboard()
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass


def focus_codex_thread(thread_title: str) -> None:
    """Bring Codex forward and select an existing task by its exact title."""
    if not thread_title.strip():
        raise CodexDesktopBridgeError("固定总结任务没有可用标题")

    import pythoncom

    pythoncom.CoInitialize()
    try:
        window = _find_codex_window()
        _select_thread(window, thread_title.strip())
    finally:
        pythoncom.CoUninitialize()


def send_prompt_to_codex_thread(thread_title: str, prompt: str) -> None:
    """Select an existing Codex task and submit a Unicode prompt visibly."""
    if not thread_title.strip():
        raise CodexDesktopBridgeError("固定总结任务没有可用标题")
    if not prompt.strip():
        raise CodexDesktopBridgeError("总结请求为空")

    import pythoncom
    from pywinauto import keyboard

    pythoncom.CoInitialize()
    try:
        window = _find_codex_window()
        _select_thread(window, thread_title.strip())
        editor = _composer(window)
        editor.click_input()
        editor.set_focus()
        try:
            editor.set_edit_text(prompt)
            time.sleep(0.15)
            keyboard.send_keys("{ENTER}", pause=0.02)
        except Exception:
            editor.click_input()
            keyboard.send_keys("^a{BACKSPACE}", pause=0.02)
            _paste_unicode(prompt)
    finally:
        pythoncom.CoUninitialize()
