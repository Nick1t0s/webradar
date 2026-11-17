"""Projection into the actual game rectangle; independent of the GUI toolkit."""
from __future__ import annotations

from dataclasses import dataclass
from .config import GameVideo, Settings, SettingsError
from .hyprland import Rect
from .scene import Camera, Frame, Segment, Vec3, fit_viewport


@dataclass(frozen=True)
class PlayerOutline:
    color: str
    segments: tuple[Segment, ...]
    health: float


def overlay_boxes(frame: Frame, settings: Settings, video: GameVideo,
                  game: Rect) -> tuple[PlayerOutline, ...]:
    player = frame.selected(settings.player)
    if player is None or player.dead or player.pitch is None:
        return ()
    width, height = video.resolution(settings)
    fov = settings.fov if settings.fov is not None else player.fov or video.fov
    if fov is None:
        raise SettingsError("FOV не найден: задайте его в окне настроек перспективы")
    aspect = width / height
    eye = player.eye or player.position.add(Vec3(0, 0, settings.eye_height))
    # Project at the source resolution, then map into the game's displayed image.
    # The small-window scale is deliberately irrelevant to aligned overlay mode.
    camera = Camera(eye, player.yaw, player.pitch, fov, aspect, width)
    if settings.overlay_stretch:
        x, y, w, h = 0.0, 0.0, game.width, game.height
    else:
        x, y, w, h = fit_viewport(game.width, game.height, aspect, game.width)
    def transform(segment: Segment) -> Segment:
        a, b = segment
        return ((game.x + x + a[0] * w / width, game.y + y + a[1] * h / height),
                (game.x + x + b[0] * w / width, game.y + y + b[1] * h / height))
    return tuple(PlayerOutline(settings.player_color(other, player),
                               tuple(transform(segment) for segment in camera.box(
                                   other, width, height, settings.body_width, settings.body_height)), other.health)
                 for other in frame.players if not other.dead and other.identity != player.identity)
