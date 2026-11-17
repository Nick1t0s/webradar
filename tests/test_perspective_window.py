"""Real Tk + WebSocket integration. Requires a graphical DISPLAY (XWayland works)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
from threading import Event, Thread
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve

from perspective.config import Settings
from perspective.scene import Camera, MatrixCamera, Vec3, project_view_ray
from perspective.window import PerspectiveWindow
from tests.test_matrix_projection import render_matrix
from tests.test_perspective import player_data


@unittest.skipUnless(os.environ.get("DISPLAY"), "Tk integration needs DISPLAY / XWayland")
class WindowTests(unittest.TestCase):
    def test_view_rays_follow_camera_toggle_and_clear_with_invalid_players(self) -> None:
        """Проверяет геометрию лучей, сохранение переключателя и очистку настоящего окна."""
        stop, dead, no_pitch, empty, silent = (Event() for _ in range(5))
        local = player_data()
        target = dict(player_data(2, False), m_health=25,
                      m_position={"x": 200, "y": -45, "z": 0},
                      m_eye_position={"x": 200, "y": -45, "z": 64},
                      m_eye_angle=90, m_eye_pitch=-12)
        def handle(connection: ServerConnection) -> None:
            """Передаёт живого, мёртвого и потерявшего угол игрока через WebSocket."""
            try:
                while not stop.wait(0.02):
                    if silent.is_set():
                        continue
                    other = dict(target)
                    if dead.is_set():
                        other["m_health"] = 0
                        other["m_is_dead"] = True
                    if no_pitch.is_set():
                        other.pop("m_eye_pitch")
                    connection.send(json.dumps({"m_players": [] if empty.is_set() else [local, other],
                                                "m_view_matrix": render_matrix()}))
            except (OSError, ConnectionClosed):
                pass
        with tempfile.TemporaryDirectory() as directory, serve(handle, "127.0.0.1", 0) as server:
            path = Path(directory) / "settings.json"
            configured = replace(Settings.load(path), width=1280, height=800, scale=0.5,
                                 teammate_color="#123456", enemy_color="#abcdef", overlay_stretch=True,
                                 ws_url=f"ws://127.0.0.1:{server.socket.getsockname()[1]}/cs2_webradar")
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            root = tk.Tk()
            window = PerspectiveWindow(root, configured, path)
            def pump_until(predicate: Callable[[], bool]) -> None:
                """Обрабатывает реальные события до нужного состояния сцены."""
                deadline = time.monotonic() + 4
                while not predicate():
                    root.update()
                    if time.monotonic() >= deadline:
                        self.fail(f"Не дождались состояния: {window.status.get()}")
                    time.sleep(0.005)
            def check_geometry() -> None:
                """Сверяет нарисованный луч с активной камерой каркасов."""
                selected = window.frame.selected(window.settings.player)
                assert selected is not None
                matrix = window.frame.local_camera(selected, window.settings.fov)
                camera: Camera | MatrixCamera
                if matrix is not None:
                    camera = replace(matrix, maximum_width=1280 * window.settings.scale)
                else:
                    camera = Camera(selected.eye or selected.position.add(Vec3(0, 0, window.settings.eye_height)),
                                    selected.yaw, selected.pitch or 0, window.settings.fov or 90,
                                    1280 / 800, 1280 * window.settings.scale)
                ray = project_view_ray(camera.project_edge, window.frame.players[1],
                                       window.canvas.winfo_width(), window.canvas.winfo_height(),
                                       window.settings.eye_height)
                assert ray is not None
                items = window.canvas.find_withtag("view-ray")
                self.assertEqual(len(items), 2, "Должен быть только луч другого игрока с обводкой")
                for actual, expected in zip(window.canvas.coords(items[1]), (*ray[0], *ray[1])):
                    self.assertAlmostEqual(actual, expected)
                color: object = root.tk.call(str(window.canvas), "itemcget", items[1], "-fill")
                self.assertEqual(color, configured.enemy_color)
                self.assertLess(items[-1], window.canvas.find_withtag("scene")[-1], "Луч закрывает каркас")
            def toggle_rays() -> None:
                """Нажимает переключатель и применяет настоящий диалог настроек."""
                window.open_settings()
                root.update()
                dialog = next(widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel))
                checkbox = next(widget for widget in dialog.winfo_children()
                                if isinstance(widget, ttk.Checkbutton) and widget.cget("text") == "Направление взгляда игроков")
                checkbox.invoke()
                button = next(widget for widget in dialog.winfo_children()
                              if isinstance(widget, ttk.Button) and widget.cget("text") == "Применить")
                button.invoke()
            try:
                pump_until(lambda: len(window.canvas.find_withtag("view-ray")) == 2)
                self.assertIn("матрица игры", window.status.get())
                check_geometry()
                toggle_rays()
                self.assertFalse(window.canvas.find_withtag("view-ray"))
                self.assertEqual(Settings.load(path), replace(configured, show_view_rays=False))
                toggle_rays()
                pump_until(lambda: len(window.canvas.find_withtag("view-ray")) == 2)
                self.assertEqual(Settings.load(path), configured)
                check_geometry()
                window._apply_settings(replace(window.settings, fov=75))
                root.update()
                self.assertIn("вручную", window.status.get())
                check_geometry()
                dead.set()
                pump_until(lambda: not window.canvas.find_withtag("view-ray"))
                dead.clear()
                pump_until(lambda: bool(window.canvas.find_withtag("view-ray")))
                no_pitch.set()
                pump_until(lambda: not window.canvas.find_withtag("view-ray"))
                no_pitch.clear()
                pump_until(lambda: bool(window.canvas.find_withtag("view-ray")))
                empty.set()
                pump_until(lambda: not window.canvas.find_withtag("view-ray"))
                empty.clear()
                pump_until(lambda: bool(window.canvas.find_withtag("view-ray")))
                silent.set()
                pump_until(lambda: window.status.get() == "Нет свежих данных helper")
                self.assertFalse(window.canvas.find_withtag("view-ray"))
            finally:
                stop.set()
                window.close()
                server.shutdown()
                thread.join(timeout=2)

    def test_live_matrix_replaces_stale_cfg_fov_and_does_not_leak_to_remote_player(self) -> None:
        """Использует матрицу локальной камеры, сохраняя удалённую перспективу и ручной FOV."""
        stop = Event()
        local = dict(player_data(), m_camera_fov=None)
        remote = dict(player_data(2, False), m_position={"x": 300, "y": 0, "z": 0},
                      m_eye_position={"x": 300, "y": 0, "z": 64}, m_eye_angle=180, m_camera_fov=50)
        def handle(connection: ServerConnection) -> None:
            """Передаёт действующую матрицу вместе с двумя игроками."""
            try:
                while not stop.wait(0.02):
                    connection.send(json.dumps({"m_players": [local, remote], "m_view_matrix": render_matrix()}))
            except (OSError, ConnectionClosed):
                pass
        with tempfile.TemporaryDirectory() as directory, serve(handle, "127.0.0.1", 0) as server:
            folder = Path(directory)
            account = 76561198000000001 - 76561197960265728
            cfg = folder / "userdata" / str(account) / "730" / "local" / "cfg"
            cfg.mkdir(parents=True)
            (cfg / "cs2_video.txt").write_text('"setting.defaultres" "1280"\n"setting.defaultresheight" "800"\n')
            (cfg / "cs2_user_convars_0_slot0.vcfg").write_text('"fov_desired" "75"\n')
            path = folder / "settings.json"
            configured = replace(Settings.load(path), width=1280, height=800,
                                 ws_url=f"ws://127.0.0.1:{server.socket.getsockname()[1]}/cs2_webradar")
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            root = tk.Tk()
            with patch("perspective.window.discover_cfg_dirs", return_value=(cfg,)):
                window = PerspectiveWindow(root, configured, path)
            def pump_until(predicate: Callable[[], bool]) -> None:
                """Обрабатывает реальные события окна до проверяемого состояния."""
                deadline = time.monotonic() + 4
                while not predicate():
                    root.update()
                    if time.monotonic() >= deadline:
                        self.fail(f"Не дождались состояния: {window.status.get()}")
                    time.sleep(0.005)
            try:
                pump_until(lambda: "матрица игры" in window.status.get())
                self.assertIn("FOV 90", window.status.get())
                self.assertEqual(window.video.fov, 75)
                self.assertGreater(len(window.canvas.find_withtag("scene")), 3)
                label = next(label for label, identity in window.labels.items() if identity.endswith("000002"))
                window.selected.set(label)
                window.selector.event_generate("<<ComboboxSelected>>")
                pump_until(lambda: "Player 2" in window.status.get())
                self.assertIn("FOV 50", window.status.get())
                self.assertNotIn("матрица игры", window.status.get())
                window.selected.set("Главный игрок helper")
                window.selector.event_generate("<<ComboboxSelected>>")
                pump_until(lambda: "матрица игры" in window.status.get())
                window.open_settings()
                root.update()
                dialog = next(widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel))
                field = next(widget for widget in dialog.winfo_children()
                             if isinstance(widget, ttk.Entry) and widget.grid_info()["row"] == 4)
                field.delete(0, "end")
                field.insert(0, "75")
                button = next(widget for widget in dialog.winfo_children()
                              if isinstance(widget, ttk.Button) and widget.cget("text") == "Применить")
                button.invoke()
                pump_until(lambda: "вручную" in window.status.get())
                self.assertIn("FOV 75", window.status.get())
                self.assertNotIn("матрица игры", window.status.get())
            finally:
                stop.set()
                window.close()
                server.shutdown()
                thread.join(timeout=2)

    def test_helper_status_precedes_missing_cfg_and_match_selects_profile(self) -> None:
        """Показывает статус helper до разрешения и выбирает cfg по живому Steam ID."""
        stop, playing, unknown_player, silent, broken = (Event() for _ in range(5))
        menu = "In CS2 but not playing a match"
        def handle(connection: ServerConnection) -> None:
            """Передаёт состояния меню, матча, тишины и разрыва настоящего соединения."""
            try:
                while not stop.wait(0.02):
                    if broken.is_set():
                        connection.close()
                        return
                    if silent.is_set():
                        continue
                    payload: dict[str, object]
                    if playing.is_set():
                        slot = 2 if unknown_player.is_set() else 1
                        payload = {"m_players": [player_data(slot)]}
                    else:
                        payload = {"type": "status", "state": "menu", "detail": menu}
                    connection.send(json.dumps(payload))
            except (OSError, ConnectionClosed):
                pass
        with tempfile.TemporaryDirectory() as directory, serve(handle, "127.0.0.1", 0) as server:
            folder = Path(directory)
            profiles: list[Path] = []
            account = 76561198000000001 - 76561197960265728
            for number, resolution in ((account + 10, (800, 600)), (account, (1600, 900)), (account + 20, (1024, 768))):
                cfg = folder / "userdata" / str(number) / "730" / "local" / "cfg"
                cfg.mkdir(parents=True)
                (cfg / "cs2_video.txt").write_text(
                    f'"setting.defaultres" "{resolution[0]}"\n"setting.defaultresheight" "{resolution[1]}"\n',
                    encoding="utf-8")
                profiles.append(cfg)
            path = folder / "settings.json"
            configured = replace(Settings.load(path), ws_url=f"ws://127.0.0.1:{server.socket.getsockname()[1]}/cs2_webradar")
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            root = tk.Tk()
            with patch("perspective.window.discover_cfg_dirs", return_value=tuple(profiles)):
                window = PerspectiveWindow(root, configured, path)
            def pump_until(predicate: Callable[[], bool]) -> None:
                """Обрабатывает события Tk до нужного состояния либо тайм-аута."""
                deadline = time.monotonic() + 4
                while not predicate():
                    root.update()
                    if time.monotonic() >= deadline:
                        self.fail(f"Не дождались состояния: {window.status.get()}")
                    time.sleep(0.005)
            try:
                pump_until(lambda: window.status.get() == menu)
                self.assertIsNone(window.video.width)
                text: object = root.tk.call(str(window.canvas), "itemcget", window.canvas.find_withtag("scene")[0], "-text")
                self.assertEqual(text, menu)
                playing.set()
                pump_until(lambda: "1600×900" in window.status.get())
                self.assertEqual(window.video.source, str(profiles[1]))
                self.assertEqual((window.video.width, window.video.height), (1600, 900))
                unknown_player.set()
                pump_until(lambda: "Выберите папку cfg" in window.status.get())
                self.assertIsNone(window.video.width)
                window.settings = replace(window.settings, player="steam:999")
                pump_until(lambda: window.status.get().startswith("Ожидание выбранного"))
                silent.set()
                pump_until(lambda: window.status.get() == "Нет свежих данных helper")
                broken.set()
                pump_until(lambda: window.status.get().startswith("Нет связи с helper"))
                self.assertEqual(window.frame.players, ())
            finally:
                stop.set()
                window.close()
                server.shutdown()
                thread.join(timeout=2)

    def test_real_stream_selection_resize_settings_and_disconnect(self) -> None:
        stop = Event()
        broken = Event()
        messages: list[str] = []
        def handle(connection: ServerConnection) -> None:
            local = player_data()
            target = dict(player_data(2, False), m_position={"x": 200, "y": 0, "z": 0}, m_health=25)
            observer = dict(player_data(3, False), m_position={"x": 0, "y": 200, "z": 0},
                            m_eye_position={"x": 0, "y": 200, "z": 64}, m_eye_angle=-90)
            try:
                while not stop.is_set():
                    if broken.is_set():
                        connection.close()
                        break
                    connection.send(json.dumps({"m_players": [local, target, observer]}))
                    try:
                        # This viewer must never send helper control messages.
                        message = connection.recv(timeout=0.03)
                        messages.append(str(message))
                    except TimeoutError:
                        pass
            except OSError:
                pass

        with tempfile.TemporaryDirectory() as directory, serve(handle, "127.0.0.1", 0) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            path = Path(directory) / "settings.json"
            settings = replace(Settings.load(path), width=1280, height=960, scale=0.5,
                               ws_url=f"ws://127.0.0.1:{server.socket.getsockname()[1]}/cs2_webradar")
            root = tk.Tk()
            window = PerspectiveWindow(root, settings, path)
            def pump(duration: float = 0.15) -> None:
                end = time.monotonic() + duration
                while time.monotonic() < end:
                    root.update()
                    time.sleep(0.005)
            try:
                pump(0.5)
                self.assertEqual(len(window.frame.players), 3)
                self.assertIn("FOV 90", window.status.get())
                self.assertEqual(window.canvas.cget("background"), "black")
                self.assertGreater(len(window.canvas.find_withtag("scene")), 3)
                visible_colors: set[str] = set()
                for item in window.canvas.find_withtag("scene"):
                    fill: object = root.tk.call(str(window.canvas), "itemcget", item, "-fill")
                    if isinstance(fill, str):
                        visible_colors.add(fill)
                self.assertIn("#ffffff", visible_colors)
                self.assertIn(settings.enemy_color, visible_colors)
                self.assertIn("black", visible_colors)
                # Under a tiling WM geometry requests can be ignored. The viewport
                # itself must still obey the modifier and retain the game aspect.
                bounds = window.canvas.coords(window.canvas.find_withtag("scene")[0])
                self.assertLessEqual(bounds[2] - bounds[0], 640)
                self.assertLessEqual(bounds[3] - bounds[1], 480)
                # Now force sizes to exercise both orientations independent of WM.
                root.overrideredirect(True)
                for geometry in ("1100x430", "420x920"):
                    root.geometry(geometry)
                    pump()
                    white = window.canvas.find_withtag("scene")[0]
                    left, top, right, bottom = window.canvas.coords(white)
                    self.assertAlmostEqual((right - left) / (bottom - top), 4 / 3)
                    self.assertAlmostEqual(left + right, window.canvas.winfo_width())
                    self.assertAlmostEqual(top + bottom, window.canvas.winfo_height())
                    self.assertTrue(left > 0 or top > 0)
                # Choose a different perspective through the actual combobox event.
                label = next(label for label, identity in window.labels.items() if identity.endswith("000003"))
                window.selected.set(label)
                window.selector.event_generate("<<ComboboxSelected>>")
                pump()
                self.assertIn("Player 3", window.status.get())
                self.assertEqual(Settings.load(path).player, window.settings.player)
                # Open the real settings dialog and submit a new size modifier.
                window.open_settings()
                pump()
                dialog = next(widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel))
                entry = next(widget for widget in dialog.winfo_children()
                             if isinstance(widget, ttk.Entry) and widget.grid_info()["row"] == 5)
                entry.delete(0, "end")
                entry.insert(0, "0.4")
                for row, color in ((9, "#123456"), (10, "#abcdef")):
                    color_entry = next(widget for widget in dialog.winfo_children()
                                       if isinstance(widget, ttk.Entry) and widget.grid_info()["row"] == row)
                    color_entry.delete(0, "end")
                    color_entry.insert(0, color)
                button = next(widget for widget in dialog.winfo_children()
                              if isinstance(widget, ttk.Button) and widget.cget("text") == "Применить")
                button.invoke()
                pump()
                self.assertEqual(window.settings.scale, 0.4)
                self.assertEqual(window.settings.teammate_color, "#123456")
                self.assertEqual(window.settings.enemy_color, "#abcdef")
                self.assertEqual(Settings.load(path).enemy_color, "#abcdef")
                bounds = window.canvas.coords(window.canvas.find_withtag("scene")[0])
                self.assertAlmostEqual(bounds[2] - bounds[0], 512, delta=3)
                self.assertAlmostEqual(bounds[3] - bounds[1], 384, delta=3)
                # A missing identity cannot fall back to the helper's own player.
                window.settings = replace(window.settings, player="steam:999")
                pump()
                self.assertEqual(len(window.canvas.find_withtag("scene")), 1)
                self.assertIn("Ожидание выбранного", window.status.get())
                broken.set()
                pump(0.5)
                self.assertEqual(window.frame.players, ())
                self.assertIn("Нет связи", window.status.get())
                self.assertEqual(messages, [])
            finally:
                stop.set()
                window.close()
                server.shutdown()
                thread.join(timeout=2)


    def test_settings_dialog_switches_source_and_clears_old_frame(self) -> None:
        """Меняет источник через интерфейс и исключает кадры предыдущего helper."""
        stopped = Event()
        received: list[str] = []
        def stream(connection: ServerConnection, name: str) -> None:
            """Передаёт узнаваемые кадры и проверяет отсутствие команд от клиента."""
            try:
                while not stopped.is_set():
                    connection.send(json.dumps({"m_players": [dict(player_data(), m_name=name)]}))
                    try:
                        received.append(str(connection.recv(timeout=0.03)))
                    except TimeoutError:
                        pass
            except (OSError, ConnectionClosed):
                pass
        def first(connection: ServerConnection) -> None:
            """Публикует данные первого источника."""
            stream(connection, "First helper")
        def second(connection: ServerConnection) -> None:
            """Публикует данные второго источника."""
            stream(connection, "Second helper")
        with tempfile.TemporaryDirectory() as directory, serve(first, "127.0.0.1", 0) as one, serve(second, "127.0.0.1", 0) as two:
            threads = [Thread(target=server.serve_forever, daemon=True) for server in (one, two)]
            for thread in threads:
                thread.start()
            path = Path(directory) / "settings.json"
            first_url = f"ws://127.0.0.1:{one.socket.getsockname()[1]}/cs2_webradar"
            second_url = f"ws://127.0.0.1:{two.socket.getsockname()[1]}/cs2_webradar"
            configured = replace(Settings.load(path), ws_url=first_url, width=1280, height=720)
            root = tk.Tk()
            window = PerspectiveWindow(root, configured, path)
            def pump(duration: float = 0.3) -> None:
                """Обрабатывает настоящие события Tk и входящие сетевые кадры."""
                end = time.monotonic() + duration
                while time.monotonic() < end:
                    root.update()
                    time.sleep(0.005)
            try:
                pump()
                self.assertEqual(window.frame.players[0].name, "First helper")
                window.open_settings()
                pump(0.05)
                dialog = next(widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel))
                entry = next(widget for widget in dialog.winfo_children()
                             if isinstance(widget, ttk.Entry) and widget.grid_info()["row"] == 0)
                entry.delete(0, "end")
                entry.insert(0, second_url)
                button = next(widget for widget in dialog.winfo_children()
                              if isinstance(widget, ttk.Button) and widget.cget("text") == "Применить")
                button.invoke()
                self.assertEqual(window.frame.players, ())
                self.assertEqual(window.last_frame_at, 0)
                self.assertIn(second_url, window.source.get())
                self.assertEqual(Settings.load(path).ws_url, second_url)
                pump(0.5)
                self.assertEqual(window.frame.players[0].name, "Second helper")
                self.assertEqual(received, [])
            finally:
                stopped.set()
                window.close()
                for server in (one, two):
                    server.shutdown()
                for thread in threads:
                    thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
