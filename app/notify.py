"""Windows notifications ("Box farm finished") without extra packages.

A tray icon is added just long enough to show a balloon; on Windows 10 and 11 that appears as a
normal notification (and respects Focus Assist / Do not disturb). It runs on its own thread, so
the window never waits for it.
"""
import ctypes
import sys
import threading
import time
from ctypes import wintypes

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO, NIIF_USER, NIIF_LARGE_ICON = 0x1, 0x4, 0x20
HWND_MESSAGE = wintypes.HWND(-3)
IDI_APPLICATION = 32512
SHOW_FOR = 12   # s the tray icon stays (removing it early can cancel the notification)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


_lock = threading.Lock()
_next_id = [1]


def _icon():
    """TACMonkey's own icon (the installed exe's), else the plain application icon."""
    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    shell32.ExtractIconW.restype = wintypes.HICON
    user32.LoadIconW.restype = wintypes.HICON
    if getattr(sys, "frozen", False):
        h = shell32.ExtractIconW(None, sys.executable, 0)
        if h and h != 1:
            return h, True
    return user32.LoadIconW(None, wintypes.LPCWSTR(IDI_APPLICATION)), False


def _show(title, text):
    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                       wintypes.HINSTANCE, wintypes.LPVOID]
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    hwnd = user32.CreateWindowExW(0, "STATIC", "TACMonkey notify", 0, 0, 0, 0, 0,
                                  HWND_MESSAGE, None, None, None)
    if not hwnd:
        return False
    with _lock:
        uid = _next_id[0]
        _next_id[0] += 1
    icon, own = _icon()
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd, nid.uID = hwnd, uid
    nid.uFlags = NIF_ICON | NIF_TIP | NIF_INFO
    nid.hIcon = icon
    nid.szTip = "TACMonkey"
    nid.szInfoTitle = title[:63]
    nid.szInfo = text[:255] or " "
    nid.dwInfoFlags = (NIIF_USER | NIIF_LARGE_ICON) if own else NIIF_INFO
    ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
    if ok:
        time.sleep(SHOW_FOR)
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
    user32.DestroyWindow(hwnd)
    return ok


def notify(title, text=""):
    """Show a Windows notification (on its own thread). Never raises."""
    if sys.platform != "win32":
        return

    def run():
        try:
            _show(title, text)
        except Exception:
            pass   # a notification is a nicety: never break a farm over it
    threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":
    notify("TACMonkey", "Test notification")
    time.sleep(SHOW_FOR + 1)
