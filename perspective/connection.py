"""A read-only, reconnecting subscriber. No process handles or helper commands."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from queue import Empty, Full, Queue
from threading import Event, Thread
import time

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from .scene import Frame, FrameError


@dataclass(frozen=True)
class Update:
    frame: Frame | None
    status: str
    received_at: float


class RadarConnection:
    def __init__(self, url: str, on_update: Callable[[], None] | None = None) -> None:
        self.url = url
        self.on_update = on_update
        self.stopped = Event()
        self.updates: Queue[Update] = Queue(maxsize=1)
        self.thread = Thread(target=self._run, daemon=True, name="perspective-websocket")

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=5)

    def latest(self) -> Update | None:
        try:
            return self.updates.get_nowait()
        except Empty:
            return None

    def _publish(self, frame: Frame | None, status: str) -> None:
        update = Update(frame, status, time.monotonic())
        try:
            self.updates.put_nowait(update)
        except Full:
            self.latest()
            self.updates.put_nowait(update)
            return
        if self.on_update is not None:
            self.on_update()

    def _run(self) -> None:
        while not self.stopped.is_set():
            try:
                with connect(self.url, open_timeout=3, close_timeout=1, max_size=2**20,
                             max_queue=1, compression=None) as socket:
                    while not self.stopped.is_set():
                        try:
                            message = socket.recv(timeout=0.25)
                        except TimeoutError:
                            continue
                        try:
                            frame = Frame.parse(message)
                            self._publish(frame, frame.status)
                        except FrameError as exc:
                            self._publish(None, f"Некорректный кадр: {exc}")
            except (OSError, WebSocketException, TimeoutError) as exc:
                self._publish(None, f"Нет связи с helper: {exc}")
            self.stopped.wait(1)
