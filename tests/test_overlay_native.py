"""Opt-in integration against a real Hyprland session, own full-screen test app."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event, Thread
import time
from typing import cast
import unittest

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve

from perspective.hyprland import query
from perspective.config import GameVideo
from perspective.geometry import Rect
from perspective.overlay_scene import overlay_boxes
from perspective.scene import Frame, object_fields
from tests.test_perspective import player_data, settings


def wait_until(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for compositor state")
        time.sleep(0.03)


def overlay_layers() -> list[dict[str, object]]:
    result = []
    for monitor in object_fields(query("layers")).values():
        for level, items in object_fields(object_fields(monitor)["levels"]).items():
            if not isinstance(items, list):
                continue
            for item in cast(list[object], items):
                fields = object_fields(item)
                if fields.get("namespace") == "cs2-perspective":
                    result.append(dict(fields, level=level))
    return result


@unittest.skipUnless(os.environ.get("WEBRADAR_HYPRLAND_TEST") == "1", "Set WEBRADAR_HYPRLAND_TEST=1 for compositor integration")
class NativeOverlayTests(unittest.TestCase):
    def test_fullscreen_transparency_focus_clickthrough_and_hide(self) -> None:
        import cairo
        stop = Event()
        players = [player_data(), dict(player_data(2, False), m_health=25,
                                      m_position={"x": 200, "y": -70, "z": 0},
                                      m_eye_position={"x": 200, "y": -70, "z": 64},
                                      m_eye_angle=90, m_eye_pitch=-20),
                   dict(player_data(3, False), m_health=50, m_team=2,
                        m_position={"x": 200, "y": 70, "z": 0},
                        m_eye_position={"x": 200, "y": 70, "z": 64},
                        m_eye_angle=90, m_eye_pitch=-20)]
        payload = json.dumps({"m_players": players, "m_view_matrix": [
            0, -1, 0, 0, 0, 0, 4 / 3, -64 * 4 / 3,
            1, 0, 0, 0, 1, 0, 0, 0,
        ]})
        def send(connection: ServerConnection) -> None:
            """Передаёт каркасы и наклонённые лучи с действующей матрицей игры."""
            try:
                while not stop.wait(0.03):
                    connection.send(payload)
            except ConnectionClosed:
                pass
        original = object_fields(query("activewindow")).get("address")
        cursor = object_fields(query("cursorpos"))
        env = dict(os.environ, GDK_BACKEND="wayland")
        with tempfile.TemporaryDirectory() as directory, serve(send, "127.0.0.1", 0) as server:
            root = Path(directory)
            config, click, key = root / "settings.json", root / "click", root / "key"
            configured = replace(settings(), width=1280, height=960,
                                 teammate_color="#00ff00", enemy_color="#ff0000",
                                 ws_url=f"ws://127.0.0.1:{server.socket.getsockname()[1]}/cs2_webradar")
            configured.save(config)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            game = subprocess.Popen([sys.executable, "tests/overlay_game_fixture.py", str(click), str(key)], env=env)
            overlay: subprocess.Popen[bytes] | None = None
            with (root / "overlay.log").open("wb") as log:
                try:
                    def game_mapped() -> bool:
                        """Ждёт отображения только собственного тестового окна."""
                        clients = query("clients")
                        assert isinstance(clients, list)
                        return any(object_fields(client).get("pid") == game.pid and object_fields(client).get("mapped") is True
                                   for client in cast(list[object], clients))
                    def game_active() -> bool:
                        """Проверяет фокус полноэкранного тестового окна."""
                        active = object_fields(query("activewindow"))
                        return active.get("pid") == game.pid and active.get("fullscreen") != 0
                    wait_until(game_mapped)
                    subprocess.run(["hyprctl", "dispatch", "focuswindow", f"pid:{game.pid}"], check=True, capture_output=True)
                    wait_until(game_active)
                    target = object_fields(query("activewindow"))
                    self.assertEqual(target["class"], "cs2")
                    self.assertFalse(target["xwayland"])
                    overlay = subprocess.Popen([sys.executable, "-c", "from pathlib import Path; from perspective.overlay import run; import sys; run(Path(sys.argv[1]))", str(config)],
                                               env=env, stderr=log)
                    wait_until(lambda: bool(overlay_layers()))
                    self.assertEqual(overlay_layers()[0]["level"], "3")
                    time.sleep(0.3)
                    self.assertTrue(game_active(), "Overlay stole the game's keyboard focus")
                    # Capture only the monitor occupied by our own full-screen app.
                    target_monitors = query("monitors")
                    assert isinstance(target_monitors, list)
                    monitor = next(object_fields(item) for item in cast(list[object], target_monitors)
                                   if object_fields(item)["id"] == target["monitor"])
                    screenshot = Path("/tmp/codex-perspective-overlay.png")
                    subprocess.run(["grim", "-o", str(monitor["name"]), str(screenshot)], check=True)
                    surface = cairo.ImageSurface.create_from_png(str(screenshot))
                    data = bytes(surface.get_data())
                    stride = surface.get_stride()
                    blue, green, red = data[20 * stride + 20 * 4:20 * stride + 20 * 4 + 3]
                    self.assertTrue(blue > green > red, "Overlay background is opaque")
                    green_pixels = sum(1 for i in range(0, len(data) - 3, 4)
                                       if data[i + 1] > 200 and data[i + 2] < 100 and data[i] < 150)
                    self.assertGreater(green_pixels, 100, "No boxes visible over the full-screen app")
                    red_pixels = sum(1 for i in range(0, len(data) - 3, 4)
                                     if data[i + 2] > 200 and data[i + 1] < 100 and data[i] < 150)
                    self.assertGreater(red_pixels, 100, "Enemy boxes aren't drawn in their own color")
                    white_pixels = sum(1 for i in range(0, len(data) - 3, 4)
                                       if min(data[i:i + 3]) > 240)
                    self.assertGreater(white_pixels, 100, "Missing HP isn't shown in white")
                    center = surface.get_height() // 2 * stride + surface.get_width() // 2 * 4
                    self.assertEqual(data[center:center + 3], data[20 * stride + 20 * 4:20 * stride + 20 * 4 + 3],
                                     "The center crosshair is still drawn")
                    game_at = cast(list[object], target["at"])
                    game_size = cast(list[object], target["size"])
                    game_rect = Rect(float(str(game_at[0])) - float(str(monitor["x"])),
                                     float(str(game_at[1])) - float(str(monitor["y"])),
                                     float(str(game_size[0])), float(str(game_size[1])))
                    outlines = overlay_boxes(Frame.parse(payload), configured, GameVideo.read(None), game_rect)
                    ray = outlines[0].view_ray
                    assert ray is not None
                    scale = float(str(monitor["scale"]))
                    ray_x, ray_y = (round((ray[0][axis] + ray[1][axis]) / 2 * scale) for axis in (0, 1))
                    def ray_visible() -> bool:
                        """Проверяет цвет середины луча вдали от каркаса на настоящем снимке экрана."""
                        subprocess.run(["grim", "-o", str(monitor["name"]), str(screenshot)], check=True)
                        current = cairo.ImageSurface.create_from_png(str(screenshot))
                        pixels = bytes(current.get_data())
                        for y in range(ray_y - 2, ray_y + 3):
                            for x in range(ray_x - 2, ray_x + 3):
                                offset = y * current.get_stride() + x * 4
                                if pixels[offset + 2] > 180 and pixels[offset + 1] < 100 and pixels[offset] < 150:
                                    return True
                        return False
                    wait_until(ray_visible)
                    replace(configured, show_view_rays=False).save(config)
                    wait_until(lambda: not ray_visible())
                    self.assertTrue(game_active(), "Reloading ray settings stole focus")
                    configured.save(config)
                    wait_until(ray_visible)
                    # Actual pointer and keyboard events go only to our own test surface.
                    tool = os.environ.get("WEBRADAR_WLRCTL", "wlrctl")
                    x, y = int(str(game_at[0])) + int(str(game_size[0])) // 2, int(str(game_at[1])) + int(str(game_size[1])) // 2
                    subprocess.run(["hyprctl", "dispatch", "movecursor", str(x), str(y)], check=True, capture_output=True)
                    self.assertTrue(game_active())
                    subprocess.run([tool, "pointer", "click"], check=True)
                    wait_until(click.exists)
                    subprocess.run([tool, "keyboard", "type", "x"], check=True)
                    wait_until(key.exists)
                    game.terminate()
                    game.wait(timeout=3)
                    wait_until(lambda: not overlay_layers())
                    overlay.terminate()
                    self.assertEqual(overlay.wait(timeout=6), 0)
                finally:
                    for process in (overlay, game):
                        if process is not None and process.poll() is None:
                            process.terminate()
                            process.wait(timeout=6)
                    stop.set()
                    server.shutdown()
                    thread.join(timeout=2)
                    if isinstance(original, str) and original:
                        subprocess.run(["hyprctl", "dispatch", "focuswindow", f"address:{original}"], capture_output=True)
                    if isinstance(cursor.get("x"), int) and isinstance(cursor.get("y"), int):
                        subprocess.run(["hyprctl", "dispatch", "movecursor", str(cursor["x"]), str(cursor["y"])], capture_output=True)
                    log.flush()
                    diagnostic = (root / "overlay.log").read_text()
                    if "Traceback" in diagnostic:
                        self.fail(diagnostic)


if __name__ == "__main__":
    unittest.main()
