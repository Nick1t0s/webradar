"""Read-only Hyprland geometry tracking in logical Wayland coordinates."""
from __future__ import annotations

from dataclasses import dataclass
import json
from queue import Empty, Full, Queue
import subprocess
from threading import Event, Thread
from typing import cast

from .geometry import Rect as Rect
from .scene import FrameError, number, object_fields


class HyprlandError(RuntimeError):
    """The compositor's IPC is unavailable or returned invalid geometry."""


@dataclass(frozen=True)
class GameTarget:
    monitor: str
    output: Rect
    game: Rect

    @classmethod
    def parse(cls, active: object, monitors: object) -> GameTarget | None:
        client = object_fields(active)
        if client.get("class") not in ("cs2", "cs2.exe", "steam_app_730"):
            return None
        if not client.get("mapped") or client.get("hidden"):
            return None
        if not isinstance(monitors, list):
            raise FrameError("Expected monitor list")
        monitor = next((object_fields(item) for item in cast(list[object], monitors)
                        if object_fields(item).get("id") == client.get("monitor")), None)
        if monitor is None:
            raise FrameError("CS2 monitor not found")
        name = monitor.get("name")
        if not isinstance(name, str):
            raise FrameError("Monitor has no connector name")
        scale = number(monitor.get("scale"))
        width, height = number(monitor.get("width")), number(monitor.get("height"))
        if scale <= 0 or width <= 0 or height <= 0:
            raise FrameError("Invalid monitor size/scale")
        transform = number(monitor.get("transform"))
        if not transform.is_integer() or not 0 <= transform <= 7:
            raise FrameError("Invalid monitor transform")
        if int(transform) % 2:
            width, height = height, width
        output = Rect(number(monitor.get("x")), number(monitor.get("y")), width / scale, height / scale)
        at, size = client.get("at"), client.get("size")
        if not isinstance(at, list) or not isinstance(size, list) or len(at) != 2 or len(size) != 2:
            raise FrameError("Invalid CS2 geometry")
        at_items, size_items = cast(list[object], at), cast(list[object], size)
        game = Rect(number(at_items[0]) - output.x, number(at_items[1]) - output.y,
                    number(size_items[0]), number(size_items[1]))
        if game.width <= 0 or game.height <= 0:
            raise FrameError("Empty CS2 window")
        return cls(name, output, game)


def query(command: str) -> object:
    try:
        result = subprocess.run(["hyprctl", "-j", command], capture_output=True,
                                text=True, timeout=1, check=True)
        value: object = json.loads(result.stdout)
        return value
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise HyprlandError(f"Hyprland IPC: {exc}") from exc


@dataclass(frozen=True)
class DesktopUpdate:
    target: GameTarget | None
    error: str


class HyprlandTracker:
    def __init__(self) -> None:
        self.stopped = Event()
        self.updates: Queue[DesktopUpdate] = Queue(maxsize=1)
        self.thread = Thread(target=self._run, daemon=True, name="perspective-hyprland")

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=3)

    def latest(self) -> DesktopUpdate | None:
        try:
            return self.updates.get_nowait()
        except Empty:
            return None

    def _run(self) -> None:
        while not self.stopped.is_set():
            try:
                active = query("activewindow")
                fields = object_fields(active)
                monitors = query("monitors") if fields.get("class") in ("cs2", "cs2.exe", "steam_app_730") else []
                update = DesktopUpdate(GameTarget.parse(active, monitors), "")
            except (HyprlandError, FrameError) as exc:
                update = DesktopUpdate(None, str(exc))
            try:
                self.updates.put_nowait(update)
            except Full:
                self.latest()
                self.updates.put_nowait(update)
            self.stopped.wait(0.1)
