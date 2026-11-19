"""Геометрия автонаводки и выбор ближайшей цели."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .config import Settings
from .scene import Frame, MatrixCamera, Player, Vec3

MAX_MOUSE_STEP: int = 320


@dataclass(frozen=True)
class AimTarget:
    """Выбранная цель автонаводки с готовыми относительными отсчётами мыши."""

    identity: str
    name: str
    dx: int
    dy: int


def _normalize_angle(angle_deg: float) -> float:
    """Нормализует угол в диапазон [-180, 180) градусов."""
    return (angle_deg + 180.0) % 360.0 - 180.0


def select_target(frame: Frame, settings: Settings,
                  stretched_aspect: float | None = None) -> AimTarget | None:
    """Выбирает ближайшего живого врага внутри круга прицела и считает отсчёты мыши."""
    if frame.status:
        return None

    # Кадр без матрицы не подходит
    if frame.view_matrix is None:
        return None

    # Настройки автонаводки
    aim_settings = settings.aim

    # Только выбранный наблюдатель по settings.player
    local_player = frame.selected(settings.player)
    if local_player is None or not local_player.local:
        return None

    if local_player.dead or local_player.health <= 0:
        return None

    if local_player.team not in (2, 3):
        return None

    camera = frame.view_matrix
    m = camera.values

    # aspect = реальный stretched_aspect, если передали, иначе matrix.aspect
    aspect = stretched_aspect if stretched_aspect is not None else camera.aspect

    # Радиус круга в единицах высоты: radius_percent от высоты (0.01 * radius_percent)
    radius_norm = aim_settings.radius_percent / 100.0

    # Строки матрицы для восстановления мирового вектора цели
    # row0: right, row1: up, row2: depth/z, row3: forward (w)
    r_right = (m[0], m[1], m[2])
    r_up = (m[4], m[5], m[6])
    r_fwd = (m[12], m[13], m[14])

    scale_x = math.hypot(*r_right)
    scale_y = math.hypot(*r_up)
    scale_w = math.hypot(*r_fwd)

    # Нормированные направления
    right_dir = (r_right[0] / scale_x, r_right[1] / scale_x, r_right[2] / scale_x)
    up_dir = (r_up[0] / scale_y, r_up[1] / scale_y, r_up[2] / scale_y)
    fwd_dir = (r_fwd[0] / scale_w, r_fwd[1] / scale_w, r_fwd[2] / scale_w)

    # Текущие углы направления камеры:
    # Source yaw: atan2(fwd.y, fwd.x), где поворот вправо уменьшает угол
    # Source pitch: -atan2(fwd.z, hypot(fwd.x, fwd.y)), где взгляд вниз положителен
    cam_yaw = math.degrees(math.atan2(fwd_dir[1], fwd_dir[0]))
    cam_pitch = math.degrees(math.atan2(-fwd_dir[2], math.hypot(fwd_dir[0], fwd_dir[1])))

    # Относительные масштабы строк относительно W
    scale_ratio_x = scale_x / scale_w
    scale_ratio_y = scale_y / scale_w

    best_target: Player | None = None
    best_dist: float = math.inf
    best_yaw_diff: float = 0.0
    best_pitch_diff: float = 0.0

    enemy_team = 2 if local_player.team == 3 else 3

    for enemy in frame.players:
        if enemy.identity == local_player.identity:
            continue
        if enemy.team != enemy_team or enemy.dead or enemy.health <= 0:
            continue

        # Определение точки цели: head или body
        if aim_settings.target == "head":
            if enemy.eye is not None:
                target_pt = enemy.eye
            else:
                eye_h = settings.eye_height
                if enemy.bounds is not None:
                    eye_h = max(enemy.bounds[0].z, min(enemy.bounds[1].z, eye_h))
                target_pt = enemy.position.add(Vec3(0, 0, eye_h))
        else:
            if enemy.bounds is not None:
                center_offset = Vec3(
                    (enemy.bounds[0].x + enemy.bounds[1].x) / 2.0,
                    (enemy.bounds[0].y + enemy.bounds[1].y) / 2.0,
                    (enemy.bounds[0].z + enemy.bounds[1].z) / 2.0,
                )
                target_pt = enemy.position.add(center_offset)
            else:
                target_pt = enemy.position.add(Vec3(0, 0, settings.body_height / 2.0))

        clip = camera.to_clip(target_pt)
        # Если clip не конечен или W < 0.1, исключить
        if not (math.isfinite(clip.x) and math.isfinite(clip.y) and math.isfinite(clip.z)):
            continue
        if clip.z < 0.1:
            continue

        ndc_x = clip.x / clip.z
        ndc_y = clip.y / clip.z

        # Вне видимой области исключить (NDC [-1, 1])
        if not (-1.0 <= ndc_x <= 1.0 and -1.0 <= ndc_y <= 1.0):
            continue

        # Смещения в единицах высоты = (X/W * aspect / 2, -Y/W / 2)
        offset_h_x = (ndc_x * aspect) / 2.0
        offset_h_y = -ndc_y / 2.0

        dist = math.hypot(offset_h_x, offset_h_y)
        # Граница круга включена (с допуском на точность float)
        if dist > radius_norm + 1e-9:
            continue

        if dist < best_dist:
            # Восстановление мирового вектора направления цели
            d_right = ndc_x / scale_ratio_x
            d_up = ndc_y / scale_ratio_y
            d_fwd = 1.0

            world_dir_x = d_right * right_dir[0] + d_up * up_dir[0] + d_fwd * fwd_dir[0]
            world_dir_y = d_right * right_dir[1] + d_up * up_dir[1] + d_fwd * fwd_dir[1]
            world_dir_z = d_right * right_dir[2] + d_up * up_dir[2] + d_fwd * fwd_dir[2]

            tgt_yaw = math.degrees(math.atan2(world_dir_y, world_dir_x))
            tgt_pitch = math.degrees(math.atan2(-world_dir_z, math.hypot(world_dir_x, world_dir_y)))

            # В Source поворот вправо уменьшает yaw, поэтому прицеливание вправо требует:
            # yaw_diff = cam_yaw - tgt_yaw > 0 -> dx > 0
            # pitch_diff = tgt_pitch - cam_pitch: цель выше -> tgt_pitch < cam_pitch -> pitch_diff < 0 -> dy < 0
            yaw_diff = _normalize_angle(cam_yaw - tgt_yaw)
            pitch_diff = tgt_pitch - cam_pitch

            best_dist = dist
            best_target = enemy
            best_yaw_diff = yaw_diff
            best_pitch_diff = pitch_diff

    if best_target is None:
        return None

    # Перевод углов в отсчёты мыши:
    # angle * 0.85 / 0.022 / sensitivity с clamp перед round (±320)
    # yaw_diff > 0 (цель правее) -> dx > 0
    # pitch_diff < 0 (цель выше) -> dy < 0
    if best_yaw_diff == 0.0:
        scaled_dx = 0.0
    else:
        scaled_dx = best_yaw_diff * 0.85 / 0.022 / aim_settings.sensitivity

    if best_pitch_diff == 0.0:
        scaled_dy = 0.0
    else:
        scaled_dy = best_pitch_diff * 0.85 / 0.022 / aim_settings.sensitivity

    limited_dx = max(-float(MAX_MOUSE_STEP), min(float(MAX_MOUSE_STEP), scaled_dx))
    limited_dy = max(-float(MAX_MOUSE_STEP), min(float(MAX_MOUSE_STEP), scaled_dy))

    dx = round(limited_dx)
    dy = round(limited_dy)

    return AimTarget(
        identity=best_target.identity,
        name=best_target.name,
        dx=dx,
        dy=dy,
    )
