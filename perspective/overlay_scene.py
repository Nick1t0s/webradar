"""Projection into the actual game rectangle; independent of the GUI toolkit."""
from __future__ import annotations

from dataclasses import dataclass, replace
from .config import GameVideo, Settings, SettingsError
from .geometry import Rect
from .scene import Camera, Frame, MatrixCamera, Segment, Vec3, fit_viewport, project_view_ray


@dataclass(frozen=True)
class PlayerOutline:
    color: str
    segments: tuple[Segment, ...]
    health: float
    view_ray: Segment | None = None


def overlay_boxes(frame: Frame, settings: Settings, video: GameVideo,
                  game: Rect) -> tuple[PlayerOutline, ...]:
    """Строит каркасы и лучи взгляда игроков в отображаемой области игры."""
    player = frame.selected(settings.player)
    if player is None or player.dead:
        return ()
    source_width, source_height = video.resolution(settings)
    matrix = frame.local_camera(player, settings.fov)
    camera: Camera | MatrixCamera
    width, height = float(source_width), float(source_height)
    if matrix is not None:
        camera = replace(matrix, maximum_width=width)
        aspect = matrix.aspect
        height = width / aspect
    else:
        if player.pitch is None:
            return ()
        fov = settings.fov if settings.fov is not None else player.fov or video.fov
        if fov is None:
            raise SettingsError("FOV не найден: задайте его в окне настроек перспективы")
        aspect = width / height
        eye = player.eye or player.position.add(Vec3(0, 0, settings.eye_height))
        camera = Camera(eye, player.yaw, player.pitch, fov, aspect, width)
    # Project at the source resolution, then map into the game's displayed image.
    # The small-window scale is deliberately irrelevant to aligned overlay mode.
    if settings.overlay_stretch:
        x, y, w, h = 0.0, 0.0, game.width, game.height
    else:
        x, y, w, h = fit_viewport(game.width, game.height, aspect, game.width)
    def transform(segment: Segment) -> Segment:
        """Переносит проекцию в отображаемый прямоугольник игры."""
        a, b = segment
        return ((game.x + x + a[0] * w / width, game.y + y + a[1] * h / height),
                (game.x + x + b[0] * w / width, game.y + y + b[1] * h / height))
    outlines: list[PlayerOutline] = []
    for other in frame.players:
        if other.dead or other.identity == player.identity:
            continue
        ray = (project_view_ray(camera.project_edge, other, width, height, settings.eye_height)
               if settings.show_view_rays else None)
        outlines.append(PlayerOutline(settings.player_color(other, player),
                                      tuple(transform(segment) for segment in camera.box(
                                          other, width, height, settings.body_width, settings.body_height)),
                                      other.health, transform(ray) if ray is not None else None))
    return tuple(outlines)
