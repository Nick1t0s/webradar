"""Интеграция службы с настоящим WebSocket и искусственной физической мышью."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
import json
import os
import sys
from pathlib import Path
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve

from perspective.config import Settings
from perspective.recoil import RecoilSettings, RecoilStep
from tests.test_perspective import player_data, settings

if sys.platform.startswith("linux"):
    import fcntl
    from perspective.recoil_linux import RecoilService
    from perspective.mouse_linux import BTN_LEFT, LinuxMouse, MouseDevice, VIRTUAL_NAME


@dataclass
class TestMouse:
    """Хранит кнопки и записывает движения без изменения настоящего указателя."""

    pressed: bool = False
    toggle: bool = False
    closed: bool = False
    moves: list[tuple[int, int]] = field(default_factory=list)

    def buttons(self) -> tuple[bool, bool]:
        """Возвращает заданное тестом состояние кнопок."""
        return self.pressed, self.toggle

    def move(self, x: int, y: int) -> None:
        """Запоминает только ненулевые перемещения."""
        if x or y:
            self.moves.append((x, y))

    def close(self) -> None:
        """Отмечает завершение сессии ввода."""
        self.closed = True


@unittest.skipUnless(sys.platform.startswith("linux"), "Управление мышью поддерживает Linux / Hyprland")
class ServiceTests(unittest.TestCase):
    """Проверяет остановки на реальном потоке кадров и одиночный исполнитель."""

    def wait_for(self, predicate: Callable[[], bool]) -> None:
        """Дожидается наблюдаемого состояния службы с ограничением времени."""
        deadline = time.monotonic() + 3
        while not predicate():
            if time.monotonic() > deadline:
                self.fail("Служба не достигла ожидаемого состояния")
            time.sleep(0.005)

    def test_real_frames_toggle_focus_stale_data_singleton_and_shutdown(self) -> None:
        """Не двигает мышь после потери условий и не создаёт второго исполнителя."""
        stopped, silent = Event(), Event()
        focused = Event()
        focused.set()
        source = TestMouse()
        message = json.dumps({"m_players": [dict(player_data(), m_weapons={"m_active": "ak47"}, m_health=100)]})

        def send(connection: ServerConnection) -> None:
            """Передаёт свежие кадры до отключения или имитации потери данных."""
            try:
                while not stopped.wait(0.008):
                    if not silent.is_set():
                        connection.send(message)
            except ConnectionClosed:
                pass

        with tempfile.TemporaryDirectory() as directory, serve(send, "127.0.0.1", 0) as server:
            path = Path(directory) / "settings.json"
            configured = replace(settings(), ws_url=f"ws://127.0.0.1:{server.socket.getsockname()[1]}",
                                 recoil=RecoilSettings(enabled=True, mouse_device="/dev/input/event999",
                                                       profiles={"ak47": (RecoilStep(5, 0, 100),)}))
            configured.save(path)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            first, second = RecoilService(path), RecoilService(path)
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory}), \
                    patch("perspective.recoil_linux.LinuxMouse", return_value=source) as constructor, \
                    patch("perspective.recoil_linux.game_focused", side_effect=focused.is_set):
                first.start()
                try:
                    self.wait_for(lambda: "пауза" in first.status)
                    second.start()
                    self.wait_for(lambda: "другим" in second.status)
                    self.assertEqual(constructor.call_count, 1)
                    source.toggle = True
                    self.wait_for(lambda: "готово" in first.status)
                    source.toggle = False
                    time.sleep(0.55)  # Compositor discovery delay; no physical events are sent.
                    source.pressed = True
                    self.wait_for(lambda: len(source.moves) >= 2)
                    focused.clear()
                    self.wait_for(lambda: "активной CS2" in first.status)
                    count = len(source.moves)
                    focused.set()
                    time.sleep(0.12)
                    self.assertEqual(len(source.moves), count, "Возврат фокуса продолжил удерживаемую очередь")
                    source.pressed = False
                    time.sleep(0.03)
                    source.pressed = True
                    self.wait_for(lambda: len(source.moves) > count)
                    silent.set()
                    self.wait_for(lambda: "свежих данных" in first.status)
                    count = len(source.moves)
                    silent.clear()
                    time.sleep(0.1)
                    self.assertEqual(len(source.moves), count, "Возврат кадров продолжил удерживаемую очередь")
                    # Stop the waiting client before testing the owner's config reload.
                    second.stop()
                    replace(configured, recoil=replace(configured.recoil, enabled=False)).save(path)
                    self.wait_for(lambda: first.status == "Отдача: выключена")
                    self.assertTrue(source.closed)
                    self.assertEqual(Settings.load(path).recoil.enabled, False)
                finally:
                    first.stop()
                    if second.thread.is_alive():
                        second.stop()
                    stopped.set()
                    server.shutdown()
                    thread.join(timeout=2)
            self.assertFalse(first.thread.is_alive())
            self.assertFalse(second.thread.is_alive())

    def test_disabled_service_never_opens_input_or_connects(self) -> None:
        """Сохраняет прежний режим перспективы без доступа к устройствам."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings().save(path)
            service = RecoilService(path)
            with patch("perspective.recoil_linux.LinuxMouse") as mouse, patch("perspective.recoil_linux.RadarConnection") as connection:
                service.start()
                time.sleep(0.04)
                service.stop()
                mouse.assert_not_called()
                connection.assert_not_called()

    @unittest.skipUnless(os.access("/dev/uinput", os.W_OK), "Нужен доступ к /dev/uinput")
    def test_kernel_creates_and_destroys_virtual_mouse_without_moving_cursor(self) -> None:
        """Проверяет настоящий uinput ABI и освобождение устройства без движения указателя."""
        keys = ((1 << BTN_LEFT) | (1 << 0x113)).to_bytes(96, "little")
        # The physical side is replaced; /dev/uinput and its ioctls are real.
        with patch("perspective.mouse_linux.device_bits", side_effect=[b"Test source\0", keys, (3).to_bytes(16, "little")]):
            mouse = LinuxMouse("/dev/null", "BTN_SIDE")
        try:
            name = bytearray(128)
            fcntl.ioctl(mouse.output_fd, 0x80000000 | (128 << 16) | 0x552C, name, True)  # UI_GET_SYSNAME
            node = Path("/sys/devices/virtual/input") / bytes(name).split(b"\0", 1)[0].decode()
            self.wait_for(lambda: (node / "name").exists())
            self.assertEqual((node / "name").read_text().strip(), VIRTUAL_NAME)
        finally:
            mouse.close()
        self.assertEqual(mouse.input_fd, -1)
        self.assertEqual(mouse.output_fd, -1)
        self.wait_for(lambda: not node.exists())

    @unittest.skipUnless(os.environ.get("DISPLAY"), "Нужен DISPLAY / XWayland")
    def test_real_settings_dialog_saves_mouse_sensitivity_and_toggle(self) -> None:
        """Применяет настройки через настоящие виджеты Tk без запуска службы ввода."""
        import tkinter as tk
        from tkinter import ttk
        from perspective.recoil_window import open_recoil_settings

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            configured = settings()
            configured.save(path)
            applied: list[Settings] = []
            root = tk.Tk()
            root.withdraw()
            identity = "bluetooth:11:22:33:44:55:66"
            try:
                with patch("perspective.recoil_window.mouse_choices", return_value=(MouseDevice("MX", "/dev/input/event42", identity),)):
                    open_recoil_settings(root, configured, path, applied.append)
                dialog = next(child for child in root.winfo_children() if isinstance(child, tk.Toplevel))
                controls = dialog.winfo_children()
                checkbox = next(child for child in controls if isinstance(child, ttk.Checkbutton))
                checkbox.invoke()
                combos = [child for child in controls if isinstance(child, ttk.Combobox)]
                combos[0].current(0)
                combos[1].set("Mouse5")
                sensitivity = next(child for child in controls if isinstance(child, ttk.Entry) and not isinstance(child, ttk.Combobox))
                sensitivity.delete(0, "end")
                sensitivity.insert(0, "2.5")
                apply = next(child for child in controls if isinstance(child, ttk.Button) and child.cget("text") == "Применить")
                apply.invoke()
                self.assertEqual(len(applied), 1)
                saved = Settings.load(path)
                self.assertTrue(saved.recoil.enabled)
                self.assertEqual(saved.recoil.mouse_device, identity)
                self.assertEqual(saved.recoil.sensitivity, 2.5)
                self.assertEqual(saved.recoil.toggle_button, "BTN_EXTRA")
            finally:
                root.destroy()
