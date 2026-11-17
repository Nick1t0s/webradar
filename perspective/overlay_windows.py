"""Прозрачное окно Windows, пропускающее ввод к активной CS2."""
from __future__ import annotations

from collections.abc import Callable
import ctypes
from ctypes import wintypes
from pathlib import Path
import signal
import sys
import time
import tkinter as tk
from typing import cast

from .config import SettingsError
from .geometry import Rect
from .overlay_state import OverlayState
from .scene import player_health_strokes


# Цвет фона не совпадает ни с чёрной обводкой, ни с белым отсутствующим HP.
TRANSPARENT_COLOR = "#010203"
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GA_ROOT = 2


class WindowsDesktop:
    """Находит клиентскую область активного процесса CS2 и управляет слоем."""

    def __init__(self) -> None:
        """Объявляет WinAPI с корректными типами указателей для Windows x64."""
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            raise SettingsError("Этот оверлей требует Windows 10/11")
        # WinDLL наследует CDLL; getattr сохраняет импортируемость модуля на Linux.
        load = cast(type[ctypes.CDLL], loader)
        self.user32 = load("user32", use_last_error=True)
        self.kernel32 = load("kernel32", use_last_error=True)
        self.last_error = cast(Callable[[], int], getattr(ctypes, "get_last_error"))
        self.set_error = cast(Callable[[int], int], getattr(ctypes, "set_last_error"))
        self.win_error = cast(Callable[[int], OSError], getattr(ctypes, "WinError"))
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user32.GetAncestor.restype = wintypes.HWND
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.user32.IsIconic.restype = wintypes.BOOL
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetClientRect.restype = wintypes.BOOL
        self.user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.user32.ClientToScreen.restype = wintypes.BOOL
        self.user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.GetWindowLongW.restype = wintypes.LONG
        self.user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        self.user32.SetWindowLongW.restype = wintypes.LONG
        self.user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.user32.SetWindowPos.restype = wintypes.BOOL
        self.user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.ShowWindow.restype = wintypes.BOOL
        self.user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        self.user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        self.user32.SetThreadDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        self.user32.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                           wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        # Запускается до создания Tk: координаты всех мониторов — физические пиксели.
        if not self.user32.SetProcessDpiAwarenessContext(wintypes.HANDLE(-4)):
            error = self.last_error()
            if error != 5:  # ERROR_ACCESS_DENIED: manifest/host уже установил режим DPI.
                raise self.win_error(error)
        if not self.user32.SetThreadDpiAwarenessContext(wintypes.HANDLE(-4)):
            raise self.win_error(self.last_error())

    def process_name(self, window: int) -> str:
        """Читает имя исполняемого файла владельца окна без доступа к его памяти."""
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        process = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not process:
            return ""
        try:
            length = wintypes.DWORD(32768)
            name = ctypes.create_unicode_buffer(length.value)
            if not self.kernel32.QueryFullProcessImageNameW(process, 0, name, ctypes.byref(length)):
                return ""
            return name.value.rsplit("\\", 1)[-1].casefold()
        finally:
            self.kernel32.CloseHandle(process)

    def active_game(self) -> Rect | None:
        """Возвращает физическую клиентскую область только активной CS2."""
        window = self.user32.GetForegroundWindow()
        if not window or not self.user32.IsWindowVisible(window) or self.user32.IsIconic(window):
            return None
        if self.process_name(int(window)) != "cs2.exe":
            return None
        area = wintypes.RECT()
        origin = wintypes.POINT(0, 0)
        if not self.user32.GetClientRect(window, ctypes.byref(area)):
            return None
        if not self.user32.ClientToScreen(window, ctypes.byref(origin)):
            return None
        width, height = area.right - area.left, area.bottom - area.top
        if width <= 0 or height <= 0:
            return None
        return Rect(origin.x, origin.y, width, height)

    def prepare_overlay(self, window: int) -> int:
        """Настраивает внешнее Tk-окно как слой без фокуса и обработки ввода."""
        native = int(self.user32.GetAncestor(window, GA_ROOT))
        styles = int(self.user32.GetWindowLongW(native, GWL_EXSTYLE))
        styles = (styles & ~WS_EX_APPWINDOW) | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self.set_error(0)
        previous = self.user32.SetWindowLongW(native, GWL_EXSTYLE, styles)
        if previous == 0 and self.last_error() != 0:
            raise self.win_error(self.last_error())
        return native

    def show(self, window: int, game: Rect) -> None:
        """Совмещает слой с клиентской областью без активации окна."""
        if not self.user32.SetWindowPos(window, wintypes.HWND(-1), round(game.x), round(game.y),
                                        round(game.width), round(game.height), SWP_NOACTIVATE | SWP_SHOWWINDOW):
            raise self.win_error(self.last_error())
        self.user32.ShowWindow(window, SW_SHOWNOACTIVATE)

    def hide(self, window: int) -> None:
        """Скрывает слой, не меняя активное приложение."""
        self.user32.ShowWindow(window, SW_HIDE)


class WindowsOverlay:
    """Рисует общую сцену перспективы поверх клиентской области игры."""

    def __init__(self, settings_path: Path) -> None:
        """Создаёт прозрачное окно и подключение к явно заданному helper."""
        self.desktop = WindowsDesktop()
        self.state = OverlayState(settings_path)
        self.closed = False
        self.visible = False
        self.last_message = ""
        self.game: Rect | None = None
        self.last_reload = 0.0
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("CS2 Perspective Overlay")
        self.root.overrideredirect(True)
        self.root.configure(background=TRANSPARENT_COLOR)
        self.root.attributes("-transparentcolor", TRANSPARENT_COLOR)
        self.root.attributes("-disabled", True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.canvas = tk.Canvas(self.root, background=TRANSPARENT_COLOR, highlightthickness=0,
                                borderwidth=0, takefocus=False)
        self.canvas.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.native = self.desktop.prepare_overlay(self.root.winfo_id())
        # Отключённое окно не может активироваться даже при первом отображении Tk.
        self.root.deiconify()
        self.root.update_idletasks()
        self.native = self.desktop.prepare_overlay(self.root.winfo_id())
        self.desktop.hide(self.native)
        self.state.start()
        self.timer = self.root.after(8, self._tick)

    def _message(self, text: str) -> None:
        """Пишет изменившуюся диагностику в журнал оверлея."""
        if text != self.last_message:
            print(f"Overlay: {text}", file=sys.stderr, flush=True)
            self.last_message = text

    def _tick(self) -> None:
        """Обновляет кадр, положение окна и состояние подключения."""
        if self.closed:
            return
        changed = self.state.poll()
        now = time.monotonic()
        if now - self.last_reload >= 0.5:
            self.last_reload = now
            try:
                changed = self.state.reload() or changed
            except (OSError, SettingsError) as exc:
                self._message(str(exc))
        game = self.desktop.active_game()
        if game is None or not self.state.fresh:
            if self.visible:
                self.desktop.hide(self.native)
                self.visible = False
            self.canvas.delete("scene")
        else:
            moved = game != self.game
            showing = not self.visible
            if moved or showing:
                # Tk обрабатывает размеры холста, WinAPI задаёт физическое положение.
                self.root.geometry(f"{round(game.width)}x{round(game.height)}")
                self.root.update_idletasks()
                self.desktop.show(self.native, game)
                self.visible = True
            if changed or moved or showing:
                self._draw(game)
        self.game = game
        self.timer = self.root.after(8, self._tick)

    def _draw(self, game: Rect) -> None:
        """Рисует каркасы с чёрной обводкой и горизонтальным уровнем здоровья."""
        self.canvas.delete("scene")
        try:
            boxes = self.state.boxes(Rect(0, 0, game.width, game.height))
        except SettingsError as exc:
            self._message(str(exc))
            return
        for box in boxes:
            for a, b in box.segments:
                self.canvas.create_line(*a, *b, fill="black", width=4, tags="scene")
            for stroke in player_health_strokes(box.segments, box.health, box.color):
                a, b = stroke.segment
                self.canvas.create_line(*a, *b, fill=stroke.color, width=2, tags="scene")

    def close(self) -> None:
        """Останавливает подписчика и освобождает окно."""
        if self.closed:
            return
        self.closed = True
        self.root.after_cancel(self.timer)
        self.desktop.hide(self.native)
        self.state.close()
        self.root.destroy()


def run(settings_path: Path) -> None:
    """Запускает оверлей Windows и освобождает ресурсы при завершении."""
    try:
        overlay = WindowsOverlay(settings_path)
    except tk.TclError as exc:
        raise SettingsError(f"Не удалось создать прозрачное окно Windows: {exc}") from exc
    def stop(signum: int, frame: object) -> None:
        """Завершает цикл окна по сигналу терминала."""
        overlay.close()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        overlay.root.mainloop()
    finally:
        overlay.close()
