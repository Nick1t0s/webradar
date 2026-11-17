"""Служба компенсации для локальной игры в Hyprland, независимая от рендерера."""
from __future__ import annotations

import fcntl
import ipaddress
from dataclasses import asdict
import json
import os
from pathlib import Path
from threading import Event, Thread
import time
from urllib.parse import urlsplit
from typing import Annotated

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError
from pydantic.dataclasses import dataclass

from .config import Settings, SettingsError
from .connection import RadarConnection
from .hyprland import HyprlandError, query
from .mouse_linux import LinuxMouse
from .recoil import RecoilFeedback, RecoilMotion
from .scene import Frame, FrameError, object_fields


@dataclass(frozen=True, config=ConfigDict(extra="forbid", allow_inf_nan=False))
class SharedStatus:
    """Передаёт актуальное состояние единственного исполнителя остальным окнам."""

    message: Annotated[str, Field(strict=True, min_length=1, max_length=4096)]
    updated_at: Annotated[float, Field(strict=True, ge=0)]


def publish_status(path: Path, message: str, now: float) -> None:
    """Атомарно публикует статус без раскрытия промежуточного JSON читателям."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(SharedStatus(message, now)), ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def owner_status(path: Path, now: float) -> str:
    """Показывает свежий статус владельца или сообщает об ожидании его состояния."""
    try:
        record = TypeAdapter(SharedStatus).validate_json(path.read_bytes())
        if 0 <= now - record.updated_at <= 2:
            return record.message
    except (OSError, ValidationError):
        pass
    return "Отдача: ожидание состояния другого окна перспективы/оверлея"


def local_source(url: str) -> bool:
    """Разрешает управление только с helper на loopback без удалённого источника."""
    host = urlsplit(url).hostname
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def game_focused() -> bool:
    """Проверяет активную CS2 и отсутствие блокировки сеанса через Hyprland."""
    locked = object_fields(query("locked")).get("locked")
    active = object_fields(query("activewindow"))
    return (locked is False and active.get("class") in ("cs2", "cs2.exe", "steam_app_730") and
            active.get("mapped") is True and not active.get("hidden"))


def controlled_weapon(frame: Frame, settings: Settings, received_at: float, now: float) -> str:
    """Допускает только живого локального игрока из свежего кадра helper."""
    player = frame.selected(settings.player)
    if (not local_source(settings.ws_url) or frame.status or not 0 <= now - received_at <= 0.25 or
            player is None or not player.local or player.dead or player.health <= 0 or player.team not in (2, 3)):
        return ""
    return player.active_weapon if player.active_weapon in settings.recoil.profiles else ""


class RecoilSession:
    """Обрабатывает ввод одной службы и отключает очередь при смене условий."""

    def __init__(self, settings: Settings) -> None:
        """Создаёт подписку и мышь, оставляя компенсацию на паузе."""
        self.settings = settings
        self.mouse = LinuxMouse(settings.recoil.mouse_device, settings.recoil.toggle_button)
        self.connection = RadarConnection(settings.ws_url)
        self.frame = Frame((), "")
        self.received_at = 0.0
        self.motion = RecoilMotion()
        self.feedback = RecoilFeedback()
        self.armed = False
        try:
            self.toggle_down = self.mouse.buttons()[1]
        except OSError:
            self.mouse.close()
            raise
        self.focused = False
        self.focus_checked = 0.0
        self.ready_at = time.monotonic() + 0.5  # Let the compositor discover the virtual mouse.
        self.context: tuple[bool, str, str] = (False, "", "")
        self.connection.start()

    def tick(self) -> str:
        """Обновляет ограничения, переключатель и движение в текущем такте."""
        update = self.connection.latest()
        if update is not None:
            self.frame = update.frame or Frame((), update.status)
            self.received_at = update.received_at
        now = time.monotonic()
        if now - self.focus_checked >= 0.05:
            try:
                self.focused = game_focused()
            except (HyprlandError, FrameError):
                self.focused = False
            self.focus_checked = time.monotonic()
        pressed, toggle = self.mouse.buttons()
        weapon = controlled_weapon(self.frame, self.settings, self.received_at, time.monotonic())
        player = self.frame.selected(self.settings.player)
        context = (self.focused, weapon, player.identity if player is not None else "")
        if context != self.context:
            self.motion.reset()
            self.feedback.reset()
            self.context = context
        if toggle and not self.toggle_down and self.focused:
            self.armed = not self.armed
            self.motion.reset()
            self.feedback.reset()
        self.toggle_down = toggle
        permitted = self.settings.recoil.enabled and self.armed and self.focused and now >= self.ready_at
        if self.settings.recoil.mode == "feedback":
            dx, dy = self.feedback.advance(time.monotonic(), pressed, player.recoil if player is not None else None,
                                           self.received_at, self.settings.recoil, permitted and bool(weapon))
        else:
            dx, dy = self.motion.advance(time.monotonic(), pressed, weapon, self.settings.recoil, permitted)
        self.mouse.move(dx, dy)
        button = "Mouse4" if self.settings.recoil.toggle_button == "BTN_SIDE" else "Mouse5"
        if not self.armed:
            return f"Отдача: пауза · {button} в игре — включить"
        if not self.focused:
            return f"Отдача: ожидание активной CS2 · {button} — пауза"
        if not weapon:
            return "Отдача: ожидание свежих данных локального игрока и оружия с профилем"
        if self.settings.recoil.mode == "feedback" and (player is None or player.recoil is None):
            return "Отдача: helper не передаёт угол отдачи; перезапустите обновлённый helper"
        if self.settings.recoil.mode == "feedback" and pressed and not self.feedback.active:
            return "Отдача: отпустите ЛКМ для начала новой очереди"
        return f"Отдача: {weapon} · {'компенсация' if dx or dy else 'готово'} · {button} — пауза"

    def close(self) -> None:
        """Останавливает ввод раньше закрытия WebSocket."""
        try:
            self.mouse.close()
        finally:
            self.connection.stop()


class RecoilService:
    """Перечитывает настройки и гарантирует один исполнитель на пользовательский сеанс."""

    def __init__(self, settings_path: Path) -> None:
        """Создаёт остановленную службу без открытия устройств."""
        self.settings_path = settings_path
        self.stopped = Event()
        self.status = "Отдача: выключена"
        self.thread = Thread(target=self._run, daemon=True, name="perspective-recoil")

    def start(self) -> None:
        """Запускает обработчик вне потока интерфейса."""
        self.thread.start()

    def stop(self) -> None:
        """Дожидается прекращения ввода и освобождения блокировки."""
        self.stopped.set()
        self.thread.join(timeout=6)

    def _run(self) -> None:
        """Запускает сессии и показывает ошибки без нарушения работы перспективы."""
        session: RecoilSession | None = None
        lock_fd = -1
        settings: Settings | None = None
        stamp = -1
        reload_at = 0.0
        publish_at = 0.0
        directory = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        status_path = directory / "cs2-perspective-recoil-status.json"
        try:
            while not self.stopped.is_set():
                try:
                    now = time.monotonic()
                    if now >= reload_at:
                        reload_at = now + 0.25
                        current_stamp = self.settings_path.stat().st_mtime_ns
                        if current_stamp != stamp:
                            if session is not None:
                                session.close()
                                session = None
                            settings = None
                            settings = Settings.load(self.settings_path)
                            stamp = current_stamp
                    if settings is None or not settings.recoil.enabled:
                        self.status = "Отдача: выключена"
                        if lock_fd >= 0:
                            os.close(lock_fd)
                            lock_fd = -1
                        self.stopped.wait(0.1)
                        continue
                    if not local_source(settings.ws_url):
                        self.status = "Отдача: нужен локальный helper (localhost / 127.0.0.1 / ::1)"
                        self.stopped.wait(0.1)
                        continue
                    if lock_fd < 0:
                        # Independent of checkout/settings path: preview + overlay never double compensation.
                        lock_fd = os.open(directory / "cs2-perspective-recoil.lock", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            os.close(lock_fd)
                            lock_fd = -1
                            self.status = owner_status(status_path, time.monotonic())
                            self.stopped.wait(0.25)
                            continue
                    if session is None:
                        session = RecoilSession(settings)
                    self.status = session.tick()
                    now = time.monotonic()
                    if now >= publish_at:
                        publish_status(status_path, self.status, now)
                        publish_at = now + 0.1
                    self.stopped.wait(0.008)
                except (OSError, SettingsError) as exc:
                    self.status = f"Отдача остановлена: {exc}"
                    if session is not None:
                        session.close()
                        session = None
                    if lock_fd >= 0:
                        os.close(lock_fd)
                        lock_fd = -1
                    self.stopped.wait(1)
        finally:
            try:
                if session is not None:
                    session.close()
            finally:
                if lock_fd >= 0:
                    os.close(lock_fd)
