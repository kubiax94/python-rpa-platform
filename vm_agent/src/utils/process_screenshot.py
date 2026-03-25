import base64
import ctypes
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from io import BytesIO

from PIL import Image


user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except OSError:
    dwmapi = None


SRCCOPY = 0x00CC0020
PW_RENDERFULLCONTENT = 0x00000002
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DIB_RGB_COLORS = 0
BI_RGB = 0
GW_OWNER = 4
GW_CHILD = 5
GW_HWNDNEXT = 2
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", ctypes.c_ubyte),
        ("rgbGreen", ctypes.c_ubyte),
        ("rgbRed", ctypes.c_ubyte),
        ("rgbReserved", ctypes.c_ubyte),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", RGBQUAD * 1),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


@dataclass(slots=True)
class ProcessWindowCapture:
    image_base64: str
    image_format: str
    window_title: str | None


@dataclass(slots=True)
class WindowSnapshotEntry:
    pid: int
    hwnd: int
    title: str | None
    class_name: str | None
    window_kind: str
    width: int
    height: int


def _serialize_window_entry(entry: WindowSnapshotEntry, *, is_primary: bool) -> dict[str, int | str | bool | None]:
    return {
        "hwnd": entry.hwnd,
        "window_title": entry.title,
        "window_class": entry.class_name,
        "window_kind": entry.window_kind,
        "width": entry.width,
        "height": entry.height,
        "is_primary": is_primary,
    }


def _raise_last_win_error(message: str):
    raise ctypes.WinError(ctypes.get_last_error(), message)


def _get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value.strip()


def _get_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    length = user32.GetClassNameW(hwnd, buffer, len(buffer))
    if length <= 0:
        return ""
    return buffer.value.strip()


def _build_window_entry(hwnd: int, pid: int, window_kind: str) -> WindowSnapshotEntry | None:
    try:
        rect = _get_window_rect(hwnd)
    except OSError:
        return None

    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 1 or height <= 1:
        return None

    return WindowSnapshotEntry(
        pid=pid,
        hwnd=int(hwnd),
        title=_get_window_text(hwnd) or None,
        class_name=_get_class_name(hwnd) or None,
        window_kind=window_kind,
        width=width,
        height=height,
    )


def _window_priority(window_kind: str) -> int:
    if window_kind == "top-level":
        return 2
    if window_kind == "child-window":
        return 1
    return 0


def _should_replace_window(current: WindowSnapshotEntry | None, candidate: WindowSnapshotEntry) -> bool:
    if current is None:
        return True

    current_priority = _window_priority(current.window_kind)
    candidate_priority = _window_priority(candidate.window_kind)
    if candidate_priority != current_priority:
        return candidate_priority > current_priority

    return (candidate.width * candidate.height) > (current.width * current.height)


def _enumerate_candidate_windows(
    callback: Callable[[WindowSnapshotEntry], bool],
    *,
    include_child_windows: bool,
    pid_filter: int | None = None,
) -> None:
    aborted = False

    def _visit(hwnd: int, window_kind: str) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if window_kind == "top-level" and user32.GetWindow(hwnd, GW_OWNER):
            return True

        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value <= 0:
            return True
        if pid_filter is not None and process_id.value != pid_filter:
            return True

        entry = _build_window_entry(hwnd, process_id.value, window_kind)
        if entry is None:
            return True

        return callback(entry)

    def _walk_child_windows(parent_hwnd: int) -> bool:
        child_hwnd = int(user32.GetWindow(parent_hwnd, GW_CHILD))
        visited: set[int] = set()

        while child_hwnd and child_hwnd not in visited:
            visited.add(child_hwnd)

            if not _visit(child_hwnd, "child-window"):
                return False
            if not _walk_child_windows(child_hwnd):
                return False

            child_hwnd = int(user32.GetWindow(child_hwnd, GW_HWNDNEXT))

        return True

    @EnumWindowsProc
    def _enum_window(hwnd, _lparam):
        nonlocal aborted

        keep_going = _visit(int(hwnd), "top-level")
        if not keep_going:
            aborted = True
            return False

        if not include_child_windows:
            return True

        if not _walk_child_windows(int(hwnd)):
            aborted = True
            return False

        return True

    ctypes.set_last_error(0)
    if not user32.EnumWindows(_enum_window, 0):
        if aborted:
            return
        _raise_last_win_error("EnumWindows failed")


def _describe_pid_windows(pid: int) -> str:
    descriptions: list[str] = []

    try:
        def _collect(entry: WindowSnapshotEntry) -> bool:
            owner = user32.GetWindow(entry.hwnd, GW_OWNER)
            rect = _get_window_rect(entry.hwnd)
            rect_text = f"{rect.left},{rect.top},{rect.right},{rect.bottom}"
            title = entry.title or "<no-title>"
            descriptions.append(
                f"kind={entry.window_kind} hwnd=0x{entry.hwnd:X} visible=True owner=0x{int(owner):X} "
                f"size={entry.width}x{entry.height} rect={rect_text} title={title!r}"
            )
            return True

        _enumerate_candidate_windows(_collect, include_child_windows=True, pid_filter=pid)
    except Exception:
        return "EnumWindows failed while collecting diagnostics"

    if not descriptions:
        return "no windows for pid"

    return "; ".join(descriptions)


def enumerate_top_level_windows() -> list[WindowSnapshotEntry]:
    windows: list[WindowSnapshotEntry] = []

    def _collect(entry: WindowSnapshotEntry) -> bool:
        if entry.window_kind == "top-level":
            windows.append(entry)
        return True

    _enumerate_candidate_windows(_collect, include_child_windows=False)

    return windows


def build_window_snapshot() -> dict[str, dict]:
    windows_by_pid: dict[int, list[WindowSnapshotEntry]] = {}
    best_by_pid: dict[int, WindowSnapshotEntry] = {}

    def _collect(entry: WindowSnapshotEntry) -> bool:
        windows_by_pid.setdefault(entry.pid, []).append(entry)
        current = best_by_pid.get(entry.pid)
        if _should_replace_window(current, entry):
            best_by_pid[entry.pid] = entry
        return True

    _enumerate_candidate_windows(_collect, include_child_windows=True)

    snapshot: dict[str, dict] = {}
    for pid, entry in best_by_pid.items():
        windows = windows_by_pid.get(pid, [])
        windows.sort(
            key=lambda item: (
                0 if item.hwnd == entry.hwnd else 1,
                -_window_priority(item.window_kind),
                -(item.width * item.height),
                item.hwnd,
            )
        )
        snapshot[str(pid)] = {
            "pid": entry.pid,
            "hwnd": entry.hwnd,
            "window_title": entry.title,
            "window_class": entry.class_name,
            "window_kind": entry.window_kind,
            "width": entry.width,
            "height": entry.height,
            "windows": [_serialize_window_entry(window, is_primary=window.hwnd == entry.hwnd) for window in windows],
        }

    return snapshot


def _get_window_rect(hwnd: int) -> RECT:
    rect = RECT()
    if dwmapi is not None:
        result = dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if result == 0:
            return rect

    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        _raise_last_win_error("GetWindowRect failed")
    return rect


def _find_best_window_for_pid(pid: int) -> WindowSnapshotEntry | None:
    best_entry: WindowSnapshotEntry | None = None

    def _collect(entry: WindowSnapshotEntry) -> bool:
        nonlocal best_entry
        if _should_replace_window(best_entry, entry):
            best_entry = entry
        return True

    _enumerate_candidate_windows(_collect, include_child_windows=True, pid_filter=pid)

    return best_entry


def capture_window_handle(hwnd: int) -> ProcessWindowCapture:
    if hwnd <= 0:
        raise ValueError("HWND must be a positive integer")

    png_bytes = _render_window_to_png(hwnd)
    return ProcessWindowCapture(
        image_base64=base64.b64encode(png_bytes).decode("ascii"),
        image_format="png",
        window_title=_get_window_text(hwnd) or None,
    )

def _bitmap_to_png(memory_dc: int, bitmap: int, width: int, height: int) -> bytes:
    bitmap_info = BITMAPINFO()
    bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bitmap_info.bmiHeader.biWidth = width
    bitmap_info.bmiHeader.biHeight = -height
    bitmap_info.bmiHeader.biPlanes = 1
    bitmap_info.bmiHeader.biBitCount = 32
    bitmap_info.bmiHeader.biCompression = BI_RGB

    buffer_size = width * height * 4
    pixel_buffer = (ctypes.c_ubyte * buffer_size)()

    scanlines = gdi32.GetDIBits(
        memory_dc,
        bitmap,
        0,
        height,
        ctypes.byref(pixel_buffer),
        ctypes.byref(bitmap_info),
        DIB_RGB_COLORS,
    )
    if scanlines != height:
        _raise_last_win_error("GetDIBits failed")

    image = Image.frombuffer("RGBA", (width, height), bytes(pixel_buffer), "raw", "BGRA", 0, 1)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _render_window_to_png(hwnd: int) -> bytes:
    rect = _get_window_rect(hwnd)
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError("Window has invalid bounds")

    window_dc = user32.GetWindowDC(hwnd)
    if not window_dc:
        _raise_last_win_error("GetWindowDC failed")

    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    if not memory_dc:
        user32.ReleaseDC(hwnd, window_dc)
        _raise_last_win_error("CreateCompatibleDC failed")

    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    if not bitmap:
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)
        _raise_last_win_error("CreateCompatibleBitmap failed")

    old_bitmap = gdi32.SelectObject(memory_dc, bitmap)
    if not old_bitmap:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)
        _raise_last_win_error("SelectObject failed")

    try:
        rendered = bool(user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT))
        if not rendered:
            copied = bool(gdi32.BitBlt(memory_dc, 0, 0, width, height, window_dc, 0, 0, SRCCOPY))
            if not copied:
                _raise_last_win_error("PrintWindow and BitBlt failed")

        return _bitmap_to_png(memory_dc, bitmap, width, height)
    finally:
        gdi32.SelectObject(memory_dc, old_bitmap)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def capture_desktop() -> ProcessWindowCapture:
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    if width <= 0 or height <= 0:
        raise RuntimeError("Desktop has invalid bounds")

    screen_dc = user32.GetDC(0)
    if not screen_dc:
        _raise_last_win_error("GetDC failed")

    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    if not memory_dc:
        user32.ReleaseDC(0, screen_dc)
        _raise_last_win_error("CreateCompatibleDC failed")

    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    if not bitmap:
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)
        _raise_last_win_error("CreateCompatibleBitmap failed")

    old_bitmap = gdi32.SelectObject(memory_dc, bitmap)
    if not old_bitmap:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)
        _raise_last_win_error("SelectObject failed")

    try:
        copied = bool(gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc, left, top, SRCCOPY))
        if not copied:
            _raise_last_win_error("BitBlt desktop capture failed")

        return ProcessWindowCapture(
            image_base64=base64.b64encode(_bitmap_to_png(memory_dc, bitmap, width, height)).decode("ascii"),
            image_format="png",
            window_title="Desktop",
        )
    finally:
        gdi32.SelectObject(memory_dc, old_bitmap)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)


def capture_process_window(pid: int) -> ProcessWindowCapture:
    if pid <= 0:
        raise ValueError("PID must be a positive integer")

    best_entry = _find_best_window_for_pid(pid)
    if best_entry is None:
        raise RuntimeError(
            f"No visible window found for this process. Window diagnostics: {_describe_pid_windows(pid)}"
        )

    return capture_window_handle(best_entry.hwnd)