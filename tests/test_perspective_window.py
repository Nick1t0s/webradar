"""Real Tk + WebSocket integration. Requires a graphical DISPLAY (XWayland works)."""
from __future__ import annotations

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

from websockets.sync.server import ServerConnection, serve

from perspective.config import Settings
from perspective.window import PerspectiveWindow
from tests.test_perspective import player_data


@unittest.skipUnless(os.environ.get("DISPLAY"), "Tk integration needs DISPLAY / XWayland")
class WindowTests(unittest.TestCase):
    def test_real_stream_selection_resize_settings_and_disconnect(self) -> None:
        stop = Event()
        broken = Event()
        messages: list[str] = []
        def handle(connection: ServerConnection) -> None:
            local = player_data()
            target = dict(player_data(2, False), m_position={"x": 200, "y": 0, "z": 0})
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


if __name__ == "__main__":
    unittest.main()
