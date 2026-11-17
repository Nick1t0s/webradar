"""Общая подписка оверлеев и opt-in проверка настоящего окна Windows."""
from __future__ import annotations

from collections.abc import Callable
import ctypes
from ctypes import wintypes
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve

from perspective.config import SettingsError
from perspective.geometry import Rect
from perspective.overlay_state import OverlayState
from tests.test_perspective import player_data, settings


def wait_until(predicate: Callable[[], bool], pump: Callable[[], None] | None = None) -> None:
    """Ждёт проверяемое состояние, при необходимости обрабатывая события GUI."""
    deadline = time.monotonic() + 5
    while not predicate():
        if pump is not None:
            pump()
        if time.monotonic() >= deadline:
            raise AssertionError("Ожидаемое состояние не наступило")
        time.sleep(0.01)


class OverlayStateTests(unittest.TestCase):
    """Проверяет реальные кадры, потерю связи и смену источника."""

    def test_real_stream_and_source_change_clear_previous_frame(self) -> None:
        """Старые игроки исчезают при переподключении, новые настройки применяются."""
        stop = Event()
        players = [player_data(), dict(player_data(2, False), m_position={"x": 200, "y": -70, "z": 0})]
        def send(connection: ServerConnection) -> None:
            """Отправляет реальные тестовые кадры по WebSocket."""
            try:
                while not stop.wait(0.02):
                    connection.send(json.dumps({"m_players": players}))
            except ConnectionClosed:
                pass
        with tempfile.TemporaryDirectory() as directory, serve(send, "127.0.0.1", 0) as server:
            path = Path(directory) / "settings.json"
            replace(settings(), width=1280, height=960,
                    ws_url=f"ws://127.0.0.1:{server.socket.getsockname()[1]}/cs2_webradar").save(path)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            state = OverlayState(path)
            state.start()
            try:
                wait_until(lambda: state.poll() and state.fresh)
                self.assertTrue(state.boxes(Rect(0, 0, 800, 600)))
                state.received_at -= 3
                self.assertFalse(state.fresh)
                self.assertEqual(state.boxes(Rect(0, 0, 800, 600)), ())
                replace(state.settings, ws_url="ws://127.0.0.1:1/cs2_webradar").save(path)
                self.assertTrue(state.reload())
                self.assertFalse(state.fresh)
                self.assertEqual(state.frame.players, ())
                self.assertEqual(state.boxes(Rect(0, 0, 800, 600)), ())
                self.assertFalse(state.reload())
                self.assertEqual(state.settings.ws_url, "ws://127.0.0.1:1/cs2_webradar")
            finally:
                state.close()
                stop.set()
                server.shutdown()
                thread.join(timeout=2)

    @unittest.skipIf(sys.platform == "win32", "Проверка ошибки неподдерживаемой платформы")
    def test_windows_backend_import_is_safe_on_linux(self) -> None:
        """Импорт Windows-модуля не загружает WinAPI на других платформах."""
        from perspective.overlay_windows import WindowsDesktop
        with self.assertRaises(SettingsError):
            WindowsDesktop()


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("WEBRADAR_WINDOWS_TEST") == "1",
                     "Set WEBRADAR_WINDOWS_TEST=1 on Windows for native GUI integration")
class WindowsNativeOverlayTests(unittest.TestCase):
    """Проверяет прозрачность и ввод настоящего слоя поверх своего тестового окна."""

    def test_real_window_transparency_clickthrough_focus_geometry_and_stale(self) -> None:
        """Проверяет настоящие WinAPI/Tk, подменяя лишь имя своего процесса."""
        import tkinter as tk
        from perspective.overlay_windows import WindowsDesktop, WindowsOverlay
        desktop = WindowsDesktop()  # DPI устанавливается до первого окна Tk.
        stop = Event()
        players = [player_data(), dict(player_data(2, False), m_health=25,
                                      m_position={"x": 200, "y": -70, "z": 0})]
        def send(connection: ServerConnection) -> None:
            """Отправляет кадры до проверки устаревания данных."""
            try:
                while not stop.wait(0.02):
                    connection.send(json.dumps({"m_players": players}))
            except ConnectionClosed:
                pass
        user32 = desktop.user32
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.SetCursorPos.restype = wintypes.BOOL
        user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, ctypes.c_size_t]
        user32.mouse_event.restype = None
        user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
        user32.keybd_event.restype = None
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.ReleaseDC.restype = ctypes.c_int
        loader = getattr(ctypes, "WinDLL")
        gdi32 = loader("gdi32", use_last_error=True)
        gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi32.GetPixel.restype = wintypes.DWORD
        previous = user32.GetForegroundWindow()
        cursor = wintypes.POINT()
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.GetCursorPos(ctypes.byref(cursor))
        game = tk.Tk()
        game.title("WebRadar own Windows integration fixture")
        game.geometry("800x600+50+50")
        game.configure(background="#183858")
        clicked, keyed = Event(), Event()
        game.bind("<Button-1>", lambda event: clicked.set())
        game.bind("<KeyPress-x>", lambda event: keyed.set())
        game.update()
        game_window = int(user32.GetAncestor(game.winfo_id(), 2))
        self.assertNotEqual(desktop.process_name(game_window), "cs2.exe")
        original_process_name = WindowsDesktop.process_name
        def fixture_process(instance: WindowsDesktop, window: int) -> str:
            """Разрешает только собственное тестовое окно вместо CS2."""
            return "cs2.exe" if window == game_window else original_process_name(instance, window)
        overlay: WindowsOverlay | None = None
        try:
            with tempfile.TemporaryDirectory() as directory, serve(send, "127.0.0.1", 0) as server:
                path = Path(directory) / "settings.json"
                replace(settings(), width=800, height=600, fov=90,
                        ws_url=f"ws://127.0.0.1:{server.socket.getsockname()[1]}/cs2_webradar",
                        enemy_color="#ff0000").save(path)
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                with patch.object(WindowsDesktop, "process_name", fixture_process):
                    user32.SetForegroundWindow(game_window)
                    overlay = WindowsOverlay(path)
                    def pump() -> None:
                        """Обрабатывает настоящие очереди событий обоих окон."""
                        game.update()
                        if overlay is not None and not overlay.closed:
                            overlay.root.update()
                    wait_until(lambda: overlay is not None and overlay.visible, pump)
                    self.assertEqual(int(user32.GetForegroundWindow()), game_window, "Оверлей украл фокус")
                    native = overlay.native
                    styles = int(user32.GetWindowLongW(native, -20))
                    self.assertEqual(styles & 0x08080020, 0x08080020)
                    target = desktop.active_game()
                    assert target is not None
                    self.assertEqual(overlay.game, target)
                    dc = user32.GetDC(None)
                    try:
                        background = int(gdi32.GetPixel(dc, round(target.x + 20), round(target.y + 20)))
                        self.assertEqual(background, 0x583818, "Фон оверлея непрозрачный")
                        outlines = overlay.state.boxes(Rect(0, 0, target.width, target.height))
                        colors: set[int] = set()
                        for box in outlines:
                            for a, b in box.segments:
                                for factor in (0.1, 0.25, 0.5, 0.75, 0.9):
                                    x = round(target.x + a[0] + (b[0] - a[0]) * factor)
                                    y = round(target.y + a[1] + (b[1] - a[1]) * factor)
                                    colors.add(int(gdi32.GetPixel(dc, x, y)))
                        self.assertIn(0x0000ff, colors, "Не видны цветные каркасы")
                        self.assertIn(0xffffff, colors, "Не видна белая часть отсутствующего HP")
                    finally:
                        user32.ReleaseDC(None, dc)
                    point = outlines[0].segments[0][0]
                    user32.SetCursorPos(round(target.x + point[0]), round(target.y + point[1]))
                    user32.mouse_event(0x0002, 0, 0, 0, 0)
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                    wait_until(clicked.is_set, pump)
                    user32.keybd_event(0x58, 0, 0, 0)
                    user32.keybd_event(0x58, 0, 0x0002, 0)
                    wait_until(keyed.is_set, pump)
                    other = tk.Toplevel(game)
                    other.title("WebRadar own focus fixture")
                    other.update()
                    other_window = int(user32.GetAncestor(other.winfo_id(), 2))
                    try:
                        user32.SetForegroundWindow(other_window)
                        wait_until(lambda: overlay is not None and not overlay.visible, pump)
                    finally:
                        other.destroy()
                    user32.SetForegroundWindow(game_window)
                    wait_until(lambda: overlay is not None and overlay.visible, pump)
                    game.geometry("640x480+100+100")
                    wait_until(lambda: overlay is not None and overlay.game is not None and overlay.game.width == 640, pump)
                    user32.ShowWindow(game_window, 6)
                    wait_until(lambda: overlay is not None and not overlay.visible, pump)
                    user32.ShowWindow(game_window, 9)
                    user32.SetForegroundWindow(game_window)
                    wait_until(lambda: overlay is not None and overlay.visible, pump)
                    stop.set()
                    wait_until(lambda: overlay is not None and not overlay.visible, pump)
                    self.assertFalse(user32.IsWindowVisible(native))
                overlay.close()
                server.shutdown()
                thread.join(timeout=2)
        finally:
            stop.set()
            if overlay is not None:
                overlay.close()
            game.destroy()
            user32.SetCursorPos(cursor.x, cursor.y)
            if previous:
                user32.SetForegroundWindow(previous)


if __name__ == "__main__":
    unittest.main()
