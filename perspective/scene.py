"""Validated radar frames and a Source-style perspective camera."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import math
from typing import cast


class FrameError(ValueError):
    """The helper sent an incomplete or invalid frame."""


def object_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise FrameError("Expected an object")
    fields = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in fields):
        raise FrameError("Expected string keys")
    return {str(key): item for key, item in fields.items()}


def number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FrameError("Expected a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise FrameError("Number out of range") from exc
    if not math.isfinite(result):
        raise FrameError("Expected a finite number")
    return result


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    @classmethod
    def parse(cls, value: object) -> Vec3:
        fields = object_fields(value)
        return cls(*(number(fields.get(key)) for key in ("x", "y", "z")))

    def add(self, other: Vec3) -> Vec3:
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)


@dataclass(frozen=True)
class Player:
    identity: str
    name: str
    team: int
    local: bool
    dead: bool
    position: Vec3
    yaw: float
    pitch: float | None
    eye: Vec3 | None
    fov: float | None
    bounds: tuple[Vec3, Vec3] | None
    health: float = 100.0
    active_weapon: str = ""

    @classmethod
    def parse(cls, value: object) -> Player:
        fields = object_fields(value)
        name, steam = fields.get("m_name"), fields.get("m_steam_id")
        if not isinstance(name, str) or not isinstance(steam, str):
            raise FrameError("Player name/Steam ID missing")
        slot = number(fields.get("m_idx"))
        team = number(fields.get("m_team"))
        if not slot.is_integer() or slot < 0 or not team.is_integer():
            raise FrameError("Invalid player slot/team")
        if not steam.isascii() or not steam.isdecimal() or len(steam) > 20:
            raise FrameError("Invalid Steam ID")
        identity = f"steam:{steam}" if int(steam) > 0 else f"slot:{int(slot)}:{name}"
        local, dead = fields.get("m_is_local"), fields.get("m_is_dead")
        if not isinstance(local, bool) or not isinstance(dead, bool):
            raise FrameError("Player flags missing")
        pitch_value, fov_value = fields.get("m_eye_pitch"), fields.get("m_camera_fov")
        pitch = None if pitch_value is None else number(pitch_value)
        fov = None if fov_value is None else number(fov_value)
        if pitch is not None and not -90 <= pitch <= 90:
            raise FrameError("Invalid vertical view angle")
        if fov is not None and not 1 <= fov < 179:
            raise FrameError("Invalid camera FOV")
        eye_value = fields.get("m_eye_position")
        eye = None if eye_value is None else Vec3.parse(eye_value)
        low_value, high_value = fields.get("m_bounds_min"), fields.get("m_bounds_max")
        bounds = None
        if low_value is not None and high_value is not None:
            low, high = Vec3.parse(low_value), Vec3.parse(high_value)
            if not all(0 < hi - lo <= 128 for lo, hi in zip((low.x, low.y, low.z), (high.x, high.y, high.z))):
                raise FrameError("Invalid player bounds")
            bounds = (low, high)
        try:
            health = max(0.0, min(100.0, number(fields.get("m_health"))))
        except FrameError:
            # Match the radar's full-color fallback for older/malformed HP data.
            health = 100.0
        weapons = fields.get("m_weapons")
        active_weapon = ""
        if isinstance(weapons, dict):
            active = object_fields(weapons).get("m_active")
            if isinstance(active, str):
                active_weapon = active.removeprefix("weapon_")
        return cls(identity, name, int(team), local, dead, Vec3.parse(fields.get("m_position")),
                   number(fields.get("m_eye_angle")), pitch, eye, fov, bounds, health, active_weapon)


@dataclass(frozen=True)
class Frame:
    players: tuple[Player, ...]
    status: str
    view_matrix: MatrixCamera | None = None

    @classmethod
    def parse(cls, message: str | bytes) -> Frame:
        try:
            value: object = json.loads(message)
        except (ValueError, UnicodeError) as exc:
            raise FrameError("Invalid helper JSON") from exc
        fields = object_fields(value)
        if fields.get("type") == "status":
            detail = fields.get("detail")
            return cls((), detail if isinstance(detail, str) else "Waiting for a game frame")
        items = fields.get("m_players")
        if not isinstance(items, list):
            raise FrameError("Frame has no player list")
        players = tuple(Player.parse(item) for item in cast(list[object], items))
        if len({p.identity for p in players}) != len(players):
            raise FrameError("Duplicate player identities")
        matrix = None
        raw_matrix = fields.get("m_view_matrix")
        if isinstance(raw_matrix, list):
            try:
                matrix = MatrixCamera(tuple(number(value) for value in cast(list[object], raw_matrix)))
            except FrameError:
                pass  # Optional projection data must not discard otherwise usable players.
        return cls(players, "", matrix)

    def local_camera(self, player: Player, manual_fov: float | None) -> MatrixCamera | None:
        """Выбирает матрицу только для локальной камеры без ручного FOV."""
        return self.view_matrix if player.local and not player.dead and manual_fov is None else None

    def selected(self, identity: str) -> Player | None:
        if identity == "helper":
            return next((p for p in self.players if p.local), None)
        return next((p for p in self.players if p.identity == identity), None)


Point = tuple[float, float]
Segment = tuple[Point, Point]


@dataclass(frozen=True)
class LineStroke:
    segment: Segment
    color: str


def player_health_strokes(segments: tuple[Segment, ...], health: float, color: str) -> tuple[LineStroke, ...]:
    """Split visible wireframe edges at an upright, bottom-up HP level."""
    if not segments:
        return ()
    if health >= 100:
        return tuple(LineStroke(segment, color) for segment in segments)
    if health <= 0:
        return tuple(LineStroke(segment, "#ffffff") for segment in segments)
    top = min(point[1] for segment in segments for point in segment)
    bottom = max(point[1] for segment in segments for point in segment)
    boundary = bottom - (bottom - top) * health / 100
    strokes: list[LineStroke] = []
    for a, b in segments:
        a_color = color if a[1] >= boundary else "#ffffff"
        b_color = color if b[1] >= boundary else "#ffffff"
        if a_color == b_color:
            strokes.append(LineStroke((a, b), a_color))
        else:
            t = (boundary - a[1]) / (b[1] - a[1])
            cut = (a[0] + (b[0] - a[0]) * t, boundary)
            strokes.extend((LineStroke((a, cut), a_color), LineStroke((cut, b), b_color)))
    return tuple(strokes)


BOX_EDGES = ((0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3),
             (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7))


def fit_viewport(width: float, height: float, aspect: float,
                 maximum_width: float) -> tuple[float, float, float, float]:
    w = min(width, height * aspect, maximum_width)
    h = w / aspect
    return (width - w) / 2, (height - h) / 2, w, h


def clip_edge(a: Vec3, b: Vec3, tan_x: float, tan_y: float) -> tuple[Vec3, Vec3] | None:
    """Обрезает ребро перед камерой и по четырём сторонам видимой области."""
    for normal, offset in ((Vec3(0, 0, 1), -1), (Vec3(1, 0, tan_x), 0),
                           (Vec3(-1, 0, tan_x), 0), (Vec3(0, 1, tan_y), 0),
                           (Vec3(0, -1, tan_y), 0)):
        da = a.x * normal.x + a.y * normal.y + a.z * normal.z + offset
        db = b.x * normal.x + b.y * normal.y + b.z * normal.z + offset
        if da < 0 and db < 0:
            return None
        if (da < 0) != (db < 0):
            t = da / (da - db)
            cut = Vec3(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, a.z + (b.z - a.z) * t)
            if da < 0:
                a = cut
            else:
                b = cut
    return a, b


def project_view_ray(project: Callable[[Vec3, Vec3, float, float], Segment | None],
                     player: Player, width: float, height: float,
                     eye_height: float) -> Segment | None:
    """Проецирует направление взгляда живого игрока с обрезкой выбранной камерой."""
    if player.dead or player.pitch is None:
        return None
    start = player.eye or player.position.add(Vec3(0, 0, eye_height))
    yaw, pitch = math.radians(player.yaw), math.radians(player.pitch)
    horizontal = 1024 * math.cos(pitch)
    end = start.add(Vec3(horizontal * math.cos(yaw), horizontal * math.sin(yaw),
                         -1024 * math.sin(pitch)))
    return project(start, end, width, height)


def project_box(project: Callable[[Vec3, Vec3, float, float], Segment | None],
                player: Player, width: float, height: float,
                body_width: float, body_height: float) -> tuple[Segment, ...]:
    """Проецирует общую топологию каркаса выбранной камерой."""
    low, high = player.bounds or (Vec3(-body_width / 2, -body_width / 2, 0),
                                 Vec3(body_width / 2, body_width / 2, body_height))
    corners = tuple(player.position.add(Vec3(x, y, z)) for x in (low.x, high.x)
                    for y in (low.y, high.y) for z in (low.z, high.z))
    segments = (project(corners[a], corners[b], width, height) for a, b in BOX_EDGES)
    return tuple(segment for segment in segments if segment is not None)


@dataclass(frozen=True)
class MatrixCamera:
    """Проекция действующей камеры из матрицы рендера helper."""

    values: tuple[float, ...]
    maximum_width: float = math.inf

    def __post_init__(self) -> None:
        """Проверяет конечные значения и независимость трёх проекционных осей."""
        if len(self.values) != 16:
            raise FrameError("View matrix must contain 16 numbers")
        for value in self.values:
            number(value)
        x, y, w = (self.values[offset:offset + 3] for offset in (0, 4, 12))
        lengths = tuple(math.hypot(*row) for row in (x, y, w))
        determinant = (x[0] * (y[1] * w[2] - y[2] * w[1])
                       - x[1] * (y[0] * w[2] - y[2] * w[0])
                       + x[2] * (y[0] * w[1] - y[1] * w[0]))
        if (not all(math.isfinite(length) and length > 1e-9 for length in lengths)
                or not math.isfinite(determinant)
                or abs(determinant) <= 1e-6 * math.prod(lengths)):
            raise FrameError("Degenerate view matrix")
        if self.maximum_width <= 0 or math.isnan(self.maximum_width):
            raise FrameError("Invalid camera viewport width")

    @property
    def aspect(self) -> float:
        """Возвращает соотношение сторон действующей проекции."""
        return math.hypot(*self.values[4:7]) / math.hypot(*self.values[:3])

    @property
    def fov(self) -> float:
        """Возвращает эквивалентный горизонтальный FOV при соотношении 4:3."""
        tangent = math.hypot(*self.values[12:15]) / math.hypot(*self.values[4:7])
        return math.degrees(2 * math.atan(tangent * 4 / 3))

    def viewport(self, width: float, height: float) -> tuple[float, float, float, float]:
        """Вписывает действующее изображение в доступную поверхность."""
        return fit_viewport(width, height, self.aspect, self.maximum_width)

    def to_clip(self, point: Vec3) -> Vec3:
        """Переводит мировую точку в однородные координаты X, Y и W."""
        m = self.values
        scale = math.hypot(*m[12:15])
        return Vec3(*((m[i] * point.x + m[i + 1] * point.y + m[i + 2] * point.z + m[i + 3]) / scale
                      for i in (0, 4, 12)))

    def project_edge(self, a: Vec3, b: Vec3, width: float, height: float) -> Segment | None:
        """Проецирует ребро с обрезкой до деления на глубину W."""
        clipped = clip_edge(self.to_clip(a), self.to_clip(b), 1, 1)
        if clipped is None:
            return None
        left, top, w, h = self.viewport(width, height)
        def project(point: Vec3) -> Point:
            """Делит видимые координаты на W и переводит их в пиксели."""
            return left + w / 2 * (1 + point.x / point.z), top + h / 2 * (1 - point.y / point.z)
        return project(clipped[0]), project(clipped[1])

    def box(self, player: Player, width: float, height: float,
            body_width: float, body_height: float) -> tuple[Segment, ...]:
        """Строит каркас тела в действующей проекции игры."""
        return project_box(self.project_edge, player, width, height, body_width, body_height)


@dataclass(frozen=True)
class Camera:
    eye: Vec3
    yaw: float
    pitch: float
    fov: float  # horizontal FOV at 4:3, as used by Source; not viewmodel_fov
    aspect: float
    maximum_width: float

    def to_view(self, point: Vec3) -> Vec3:
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        dx, dy, dz = point.x - self.eye.x, point.y - self.eye.y, point.z - self.eye.z
        along = dx * math.cos(yaw) + dy * math.sin(yaw)
        # Source: yaw 0 = +X, yaw 90 = +Y; positive pitch looks down.
        return Vec3(dx * math.sin(yaw) - dy * math.cos(yaw),
                    along * math.sin(pitch) + dz * math.cos(pitch),
                    along * math.cos(pitch) - dz * math.sin(pitch))

    def viewport(self, width: float, height: float) -> tuple[float, float, float, float]:
        return fit_viewport(width, height, self.aspect, self.maximum_width)

    def project_edge(self, a: Vec3, b: Vec3, width: float, height: float) -> Segment | None:
        """Проецирует ребро реконструированной камеры с обрезкой по её границам."""
        tan_y = math.tan(math.radians(self.fov) / 2) / (4 / 3)
        tan_x = tan_y * self.aspect
        clipped = clip_edge(self.to_view(a), self.to_view(b), tan_x, tan_y)
        if clipped is None:
            return None
        left, top, w, h = self.viewport(width, height)
        def project(p: Vec3) -> Point:
            """Переводит видимую точку камеры в координаты поверхности."""
            return left + w / 2 * (1 + p.x / (p.z * tan_x)), top + h / 2 * (1 - p.y / (p.z * tan_y))
        return project(clipped[0]), project(clipped[1])

    def box(self, player: Player, width: float, height: float,
            body_width: float, body_height: float) -> tuple[Segment, ...]:
        """Строит каркас тела по углам выбранного игрока."""
        return project_box(self.project_edge, player, width, height, body_width, body_height)
