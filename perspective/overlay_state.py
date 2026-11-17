"""Общие данные и настройки нативных оверлеев без зависимости от GUI."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import time

from .config import GameVideo, Settings, discover_cfg_dirs
from .connection import RadarConnection
from .geometry import Rect
from .overlay_scene import PlayerOutline, overlay_boxes
from .scene import Frame


class OverlayState:
    """Получает кадры, перечитывает настройки и готовит сцену оверлея."""

    def __init__(self, settings_path: Path, on_update: Callable[[], None] | None = None) -> None:
        """Загружает явные настройки источника и создаёт подписчика."""
        self.settings_path = settings_path
        self.settings = Settings.load(settings_path)
        self.settings_stamp = settings_path.stat().st_mtime_ns
        self.profiles = discover_cfg_dirs()
        self.video = GameVideo.read(None)
        self.video_identity = ""
        self.frame = Frame((), "")
        self.received_at = 0.0
        self.status = "Ожидание helper"
        self.on_update = on_update
        self.connection = RadarConnection(self.settings.ws_url, on_update)
        self._load_video()

    def start(self) -> None:
        """Запускает получение кадров."""
        self.connection.start()

    def close(self) -> None:
        """Останавливает подключение к источнику данных."""
        self.connection.stop()

    def poll(self) -> bool:
        """Принимает последний кадр и обновляет параметры выбранной камеры."""
        update = self.connection.latest()
        if update is None:
            return False
        self.frame = update.frame or Frame((), "")
        self.received_at = update.received_at
        self.status = update.status
        player = self.frame.selected(self.settings.player)
        if (player.identity if player else "") != self.video_identity:
            self._load_video()
        return True

    def reload(self) -> bool:
        """Применяет изменённые настройки и переподключает новый источник."""
        stamp = self.settings_path.stat().st_mtime_ns
        if stamp == self.settings_stamp:
            return False
        settings = Settings.load(self.settings_path)
        if settings.ws_url != self.settings.ws_url:
            self.connection.stop()
            self.frame = Frame((), "")
            self.received_at = 0.0
            self.status = "Подключение к helper…"
            self.connection = RadarConnection(settings.ws_url, self.on_update)
            self.connection.start()
        self.settings, self.settings_stamp = settings, stamp
        self._load_video()
        return True

    def _load_video(self) -> None:
        """Определяет параметры камеры выбранного игрока."""
        player = self.frame.selected(self.settings.player)
        self.video_identity = player.identity if player else ""
        try:
            self.video = GameVideo.for_player(self.settings, player, self.profiles)
        except OSError as exc:
            self.video = GameVideo(None, None, None, str(exc))

    @property
    def fresh(self) -> bool:
        """Проверяет наличие свежего кадра без сообщения об ошибке."""
        return not self.status and bool(self.frame.players) and time.monotonic() - self.received_at <= 2

    def boxes(self, game: Rect) -> tuple[PlayerOutline, ...]:
        """Возвращает видимые каркасы либо пустую сцену при потере данных."""
        if not self.fresh:
            return ()
        return overlay_boxes(self.frame, self.settings, self.video, game)
