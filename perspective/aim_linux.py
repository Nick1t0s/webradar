"""Служба автонаводки для локальной игры в Hyprland, независимая от оверлея."""
from __future__ import annotations

import fcntl
import ipaddress
import json
import os
from pathlib import Path
from threading import Event, Thread
import time
from urllib.parse import urlsplit

from .aim import MAX_MOUSE_STEP, select_target
from .config import Settings, SettingsError
from .connection import RadarConnection
from .hyprland import HyprlandError, query
from .mouse_linux import LinuxMouse
from .scene import Frame, FrameError, number, object_fields


def publish_status(path: Path, message: str, now: float) -> None:
    """Атомарно публикует статус без раскрытия промежуточного JSON читателям."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"message": message, "updated_at": now}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def owner_status(path: Path, now: float) -> str:
    """Показывает свежий статус владельца или сообщает об ожидании его состояния."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            message = raw.get("message")
            updated_at = raw.get("updated_at")
            if isinstance(message, str) and isinstance(updated_at, (int, float)) and 0 <= now - updated_at <= 2:
                return message
    except (OSError, ValueError):
        pass
    return "Автонаводка: ввод занят другим процессом"


def local_source(url: str) -> bool:
    """Разрешает управление только с helper на loopback без удалённого источника."""
    host = urlsplit(url).hostname
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def game_state() -> tuple[bool, float | None]:
    """Проверяет CS2, отсутствие блокировки Hyprland и возвращает stretched_aspect."""
    locked = object_fields(query("locked")).get("locked")
    active = object_fields(query("activewindow"))
    focused = (locked is False and active.get("class") in ("cs2", "cs2.exe", "steam_app_730") and
               active.get("mapped") is True and not active.get("hidden"))
    if not focused:
        return False, None
    size = active.get("size")
    if isinstance(size, list) and len(size) == 2:
        try:
            w, h = number(size[0]), number(size[1])
            if w > 0 and h > 0:
                return True, w / h
        except (ValueError, TypeError, FrameError):
            pass
    return True, None


class AimSession:
    """Обрабатывает кадры и удерживает автонаводку в пределах одной сессии."""

    def __init__(self, settings: Settings, stopped: Event) -> None:
        """Создаёт подключение к helper и виртуальную мышь."""
        self.settings = settings
        self.stopped = stopped
        self.mouse = LinuxMouse(settings.aim.mouse_device, settings.aim.button)
        self.connection = RadarConnection(settings.ws_url)
        self.frame = Frame((), "")
        self.frame_received_at = 0.0
        self.focused = False
        self.aspect: float | None = None
        self.focus_checked = 0.0
        self.held_latched = False
        self.target_name = ""
        self.target_identity = ""
        self.jitter_phase = 0
        sens = settings.aim.sensitivity
        if sens > 1.0:
            self.jitter_amp_x = round(3.0 / sens)
            self.jitter_amp_y = round(2.0 / sens)
        else:
            self.jitter_amp_x = 3
            self.jitter_amp_y = 2
        self.connection.start()

    def tick(self) -> str:
        """Выполняет один шаг проверки состояния, захвата цели и относительного смещения."""
        now = time.monotonic()
        if now - self.focus_checked >= 0.05:
            try:
                self.focused, self.aspect = game_state()
            except (HyprlandError, FrameError):
                self.focused, self.aspect = False, None
            self.focus_checked = time.monotonic()
            now = time.monotonic()

        update = self.connection.latest()
        is_fresh_update = False
        if update is not None:
            self.frame = update.frame or Frame((), update.status)
            self.frame_received_at = update.received_at
            is_fresh_update = True

        raw_held = self.mouse.held()
        now = time.monotonic()

        is_stale = not 0 <= now - self.frame_received_at <= 0.25
        has_error = bool(self.frame.status) or is_stale

        # Loss of focus, stale/error frame, or initial state requires button release.
        if not self.focused or has_error:
            self.held_latched = False
            self.target_name = ""
            self.target_identity = ""
            self.jitter_phase = 0
            if not self.focused:
                return "Автонаводка: ожидание активной CS2"
            if self.frame.status:
                return f"Автонаводка: {self.frame.status}"
            return "Автонаводка: ожидание свежих данных helper"

        # CS2 is active and frame is fresh without error.
        if not raw_held:
            self.held_latched = True
            self.target_name = ""
            self.target_identity = ""
            self.jitter_phase = 0
            return "Автонаводка: готова"

        if not self.held_latched:
            self.target_identity = ""
            self.jitter_phase = 0
            return "Автонаводка: отпустите кнопку мыши"

        # Button is currently held and armed.
        stretched = self.aspect if self.settings.overlay_stretch else None

        if is_fresh_update:
            target = select_target(self.frame, self.settings, stretched)
            now_after_select = time.monotonic()
            if target is not None:
                if target.identity != self.target_identity:
                    self.target_identity = target.identity
                    self.jitter_phase = 0
                self.target_name = target.name
                # Verify button, age and stop Event directly before movement
                if (not self.stopped.is_set()
                        and 0 <= now_after_select - self.frame_received_at <= 0.25
                        and self.mouse.held()):
                    signs = ((1, 1), (-1, 1), (-1, -1), (1, -1))
                    sx, sy = signs[self.jitter_phase]
                    self.jitter_phase = (self.jitter_phase + 1) % 4
                    move_x = max(-MAX_MOUSE_STEP, min(MAX_MOUSE_STEP, target.dx + sx * self.jitter_amp_x))
                    move_y = max(-MAX_MOUSE_STEP, min(MAX_MOUSE_STEP, target.dy + sy * self.jitter_amp_y))
                    self.mouse.move(move_x, move_y)
                else:
                    self.jitter_phase = 0
            else:
                self.target_name = ""
                self.target_identity = ""
                self.jitter_phase = 0

        if self.target_name:
            return f"Автонаводка: {self.target_name}"
        return "Автонаводка: поиск цели"

    def close(self) -> None:
        """Останавливает ввод раньше закрытия соединения."""
        try:
            self.mouse.close()
        finally:
            self.connection.stop()


class AimService:
    """Следит за файлом настроек и гарантирует один активный процесс на сеанс."""

    def __init__(self, settings_path: Path) -> None:
        """Создаёт остановленную службу без захвата ресурсов."""
        self.settings_path = settings_path
        self.stopped = Event()
        self.status = "Автонаводка: выключена"
        self.thread = Thread(target=self._run, daemon=True, name="perspective-aim")

    def start(self) -> None:
        """Запускает фоновый поток обработки."""
        self.thread.start()

    def stop(self) -> None:
        """Останавливает службу и дожидается освобождения ресурсов."""
        self.stopped.set()
        self.thread.join(timeout=6)

    def _run(self) -> None:
        """Запускает сессии автонаводки и обновляет статус."""
        session: AimSession | None = None
        lock_fd = -1
        settings: Settings | None = None
        stamp = -1
        reload_at = 0.0
        publish_at = 0.0
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        directory = Path(runtime_dir) if runtime_dir else Path(f"/run/user/{os.getuid()}")
        status_path = directory / "cs2-perspective-aim-status.json"

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

                    if settings is None or not settings.aim.enabled:
                        self.status = "Автонаводка: выключена"
                        if lock_fd >= 0:
                            os.close(lock_fd)
                            lock_fd = -1
                        self.stopped.wait(0.1)
                        continue

                    if not local_source(settings.ws_url):
                        self.status = "Автонаводка: нужен локальный helper (localhost / 127.0.0.1 / ::1)"
                        self.stopped.wait(0.1)
                        continue

                    if lock_fd < 0:
                        lock_fd = os.open(directory / "cs2-perspective-aim.lock", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
                        try:
                            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            os.close(lock_fd)
                            lock_fd = -1
                            self.status = owner_status(status_path, time.monotonic())
                            self.stopped.wait(0.25)
                            continue

                    if session is None:
                        session = AimSession(settings, self.stopped)
                    self.status = session.tick()
                    now = time.monotonic()
                    if now >= publish_at:
                        publish_status(status_path, self.status, now)
                        publish_at = now + 0.1
                    self.stopped.wait(0.008)
                except (OSError, SettingsError) as exc:
                    self.status = f"Автонаводка остановлена: {exc}"
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
