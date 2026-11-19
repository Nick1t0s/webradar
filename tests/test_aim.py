"""Тесты настроек автонаводки, выбора цели и расчёта движений мыши."""
from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest

from perspective.aim import select_target
from perspective.aim_settings import AimSettings, AimSettingsError
from perspective.config import Settings, SettingsError
from perspective.scene import Frame, MatrixCamera, Player, Vec3
from tests.test_matrix_projection import render_matrix
from tests.test_perspective import settings


class AimSettingsTests(unittest.TestCase):
    """Проверяет строгую валидацию AimSettings и интеграцию с Settings."""

    def test_default_values(self) -> None:
        """Проверяет значения по умолчанию."""
        aim = AimSettings()
        self.assertFalse(aim.enabled)
        self.assertEqual(aim.mouse_device, "")
        self.assertEqual(aim.sensitivity, 1.0)
        self.assertEqual(aim.button, "BTN_SIDE")
        self.assertEqual(aim.radius_percent, 10.0)
        self.assertEqual(aim.target, "head")
        self.assertFalse(aim.include_teammates)

    def test_validation_include_teammates(self) -> None:
        """include_teammates строго логическое значение bool."""
        with self.assertRaises(AimSettingsError):
            AimSettings.parse({"include_teammates": "true"})
        with self.assertRaises(AimSettingsError):
            AimSettings.parse({"include_teammates": 1})
        aim_true = AimSettings(include_teammates=True)
        self.assertTrue(aim_true.include_teammates)
        parsed = AimSettings.parse({"include_teammates": True})
        self.assertTrue(parsed.include_teammates)

    def test_validation_enabled_requires_mouse_device(self) -> None:
        """Включение требует заданного mouse_device."""
        with self.assertRaises(AimSettingsError):
            AimSettings(enabled=True, mouse_device="")
        with self.assertRaises(AimSettingsError):
            AimSettings.parse({"enabled": True, "mouse_device": ""})
        # С валидным устройством разрешено
        aim = AimSettings(enabled=True, mouse_device="/dev/input/event0")
        self.assertTrue(aim.enabled)

    def test_validation_mouse_device_path(self) -> None:
        """mouse_device должен быть внутри /dev/input или bluetooth-адресом."""
        with self.assertRaises(AimSettingsError):
            AimSettings(mouse_device="/dev/input/../etc/passwd")
        with self.assertRaises(AimSettingsError):
            AimSettings(mouse_device="/tmp/mouse")
        with self.assertRaises(AimSettingsError):
            AimSettings(mouse_device="invalid_bt:11:22")
        # Разрешённые:
        aim1 = AimSettings(mouse_device="/dev/input/event3")
        self.assertEqual(aim1.mouse_device, "/dev/input/event3")
        aim2 = AimSettings(mouse_device="bluetooth:00:11:22:33:44:55")
        self.assertEqual(aim2.mouse_device, "bluetooth:00:11:22:33:44:55")

    def test_validation_sensitivity(self) -> None:
        """sensitivity строго конечное число в диапазоне (0, 100]."""
        with self.assertRaises(AimSettingsError):
            AimSettings(sensitivity=0.0)
        with self.assertRaises(AimSettingsError):
            AimSettings(sensitivity=-1.0)
        with self.assertRaises(AimSettingsError):
            AimSettings(sensitivity=100.1)
        with self.assertRaises(AimSettingsError):
            AimSettings(sensitivity=float("nan"))
        with self.assertRaises(AimSettingsError):
            AimSettings(sensitivity=float("inf"))
        with self.assertRaises(AimSettingsError):
            AimSettings.parse({"sensitivity": True})
        with self.assertRaises(AimSettingsError):
            AimSettings.parse({"sensitivity": False})
        aim = AimSettings(sensitivity=0.01)
        self.assertEqual(aim.sensitivity, 0.01)
        aim_subnormal = AimSettings(sensitivity=5e-324)
        self.assertEqual(aim_subnormal.sensitivity, 5e-324)
        aim_max = AimSettings(sensitivity=100.0)
        self.assertEqual(aim_max.sensitivity, 100.0)

    def test_validation_radius_percent(self) -> None:
        """radius_percent в диапазоне [1, 50]."""
        with self.assertRaises(AimSettingsError):
            AimSettings(radius_percent=0.9)
        with self.assertRaises(AimSettingsError):
            AimSettings(radius_percent=50.1)
        with self.assertRaises(AimSettingsError):
            AimSettings(radius_percent=float("nan"))
        with self.assertRaises(AimSettingsError):
            AimSettings.parse({"radius_percent": True})
        with self.assertRaises(AimSettingsError):
            AimSettings.parse({"radius_percent": False})
        aim = AimSettings(radius_percent=1.0)
        self.assertEqual(aim.radius_percent, 1.0)
        aim50 = AimSettings(radius_percent=50.0)
        self.assertEqual(aim50.radius_percent, 50.0)

    def test_validation_button_and_target(self) -> None:
        """Разрешены только точные режимы button и target."""
        with self.assertRaises(AimSettingsError):
            AimSettings.parse({"button": "BTN_LEFT"})
        with self.assertRaises(AimSettingsError):
            AimSettings.parse({"target": "legs"})
        with self.assertRaises(AimSettingsError):
            AimSettings.parse(None)
        aim = AimSettings(button="BTN_EXTRA", target="body")
        self.assertEqual(aim.button, "BTN_EXTRA")
        self.assertEqual(aim.target, "body")

    def test_settings_load_save_and_legacy_recoil(self) -> None:
        """Settings поддерживает aim как вложенную настройку и продолжает игнорировать старый recoil."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            base_dict = asdict(settings())
            # Сохранение и перезагрузка с AimSettings, включая include_teammates=True
            custom_aim = AimSettings(
                enabled=True,
                mouse_device="/dev/input/event5",
                sensitivity=2.5,
                button="BTN_EXTRA",
                radius_percent=15.0,
                target="body",
                include_teammates=True,
            )
            cfg = replace(settings(), aim=custom_aim)
            cfg.save(path)
            loaded = Settings.load(path)
            self.assertEqual(loaded.aim, custom_aim)
            self.assertTrue(loaded.aim.include_teammates)

            # Совместимость со старыми конфигами без ключа include_teammates
            aim_dict_no_teammates = {
                "enabled": False,
                "mouse_device": "",
                "sensitivity": 1.0,
                "button": "BTN_SIDE",
                "radius_percent": 10.0,
                "target": "head",
            }
            parsed_legacy = Settings.parse(dict(base_dict, aim=aim_dict_no_teammates))
            self.assertFalse(parsed_legacy.aim.include_teammates)

            # Старый recoil игнорируется
            with_recoil = dict(base_dict, recoil={"enabled": True, "strength": 1.0})
            parsed = Settings.parse(with_recoil)
            self.assertEqual(parsed.aim, AimSettings())

            # Неизвестные ключи внутри aim или верхнего уровня отклоняются
            with self.assertRaises(SettingsError):
                Settings.parse(dict(base_dict, unknown_field="val"))
            with self.assertRaises(SettingsError):
                Settings.parse(dict(base_dict, aim={"unknown_aim_field": 1}))


def make_player(identity: str, team: int, pos: Vec3,
                eye: Vec3 | None = None, bounds: tuple[Vec3, Vec3] | None = None,
                dead: bool = False, health: float = 100.0,
                local: bool = False, name: str = "Player") -> Player:
    """Вспомогательная функция создания игрока."""
    return Player(
        identity=identity,
        name=name,
        team=team,
        local=local,
        dead=dead,
        position=pos,
        yaw=0.0,
        pitch=0.0,
        eye=eye,
        fov=90.0,
        bounds=bounds,
        health=health,
    )


class AimTargetSelectionTests(unittest.TestCase):
    """Проверяет геометрию выбора цели, круг, head/body и расчёт движений."""

    def setUp(self) -> None:
        self.eye = Vec3(0, 0, 64)
        # Камера смотрит вдоль +X (yaw=0, pitch=0), aspect=1.6, fov=90
        self.matrix_vals = render_matrix(self.eye, 0, 0, 90, 1.6)
        self.camera = MatrixCamera(self.matrix_vals)
        self.base_settings = settings()

    def test_no_target_when_invalid_local_player_or_frame(self) -> None:
        """Возвращает None при мертвом/отсутствующем локальном игроке, не T/CT, кадре со статусом или без матрицы."""
        local = make_player("local", team=2, pos=Vec3(0, 0, 0), eye=self.eye, local=True)
        enemy = make_player("enemy", team=3, pos=Vec3(500, 0, 0), eye=Vec3(500, 0, 64))

        # Кадр со статусом
        status_frame = Frame((local, enemy), "Waiting for players", self.camera)
        self.assertIsNone(select_target(status_frame, self.base_settings))

        # Кадр без матрицы
        no_matrix_frame = Frame((local, enemy), "", None)
        self.assertIsNone(select_target(no_matrix_frame, self.base_settings))

        # Локальный мёртв
        dead_local = replace(local, dead=True)
        self.assertIsNone(select_target(Frame((dead_local, enemy), "", self.camera), self.base_settings))

        # Локальный с нулевым HP
        zero_hp_local = replace(local, health=0.0)
        self.assertIsNone(select_target(Frame((zero_hp_local, enemy), "", self.camera), self.base_settings))

        # Локальный не T/CT (team=1 наблюдатель)
        spec_local = replace(local, team=1)
        self.assertIsNone(select_target(Frame((spec_local, enemy), "", self.camera), self.base_settings))

        # Локальный игрок отсутствует
        self.assertIsNone(select_target(Frame((enemy,), "", self.camera), self.base_settings))

        # Выбранный игрок не локальный
        other_settings = replace(self.base_settings, player="enemy")
        self.assertIsNone(select_target(Frame((local, enemy), "", self.camera), other_settings))

    def test_circle_boundary_and_closest_target(self) -> None:
        """Проверяет радиус круга, включение границы и выбор ближайшего к центру экрана."""
        local = make_player("local", team=2, pos=Vec3(0, 0, 0), eye=self.eye, local=True)
        cfg = replace(self.base_settings, aim=AimSettings(radius_percent=10.0))

        # Враг прямо по центру (dist = 0)
        enemy_center = make_player("center", team=3, pos=Vec3(500, 0, 0), eye=Vec3(500, 0, 64), name="Center")
        target = select_target(Frame((local, enemy_center), "", self.camera), cfg)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.identity, "center")
        self.assertEqual(target.dx, 0)
        self.assertEqual(target.dy, 0)

        # Проверка по центру с субнормальным sensitivity=5e-324
        cfg_subnormal = replace(self.base_settings, aim=AimSettings(sensitivity=5e-324, radius_percent=10.0))
        target_subnormal = select_target(Frame((local, enemy_center), "", self.camera), cfg_subnormal)
        self.assertIsNotNone(target_subnormal)
        assert target_subnormal is not None
        self.assertEqual((target_subnormal.dx, target_subnormal.dy), (0, 0))

        # Два врага в круге: один ближе к центру экрана, чем другой
        enemy_close = make_player("close", team=3, pos=Vec3(500, -10, 0), eye=Vec3(500, -10, 64), name="Close")
        enemy_far = make_player("far", team=3, pos=Vec3(500, -30, 0), eye=Vec3(500, -30, 64), name="Far")
        target = select_target(Frame((local, enemy_close, enemy_far), "", self.camera), cfg)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.identity, "close")

        # Враг вне круга
        enemy_outside = make_player("out", team=3, pos=Vec3(500, -200, 0), eye=Vec3(500, -200, 64), name="Out")
        self.assertIsNone(select_target(Frame((local, enemy_outside), "", self.camera), cfg))

        # Граница круга включена: ровно на границе dist == 0.1
        pt_boundary = Vec3(500, 0, -11)
        enemy_boundary = make_player("boundary", team=3, pos=Vec3(500, 0, 0), eye=pt_boundary)
        target_b = select_target(Frame((local, enemy_boundary), "", self.camera), cfg)
        self.assertIsNotNone(target_b)

        # Чуть дальше границы: z = -12
        pt_just_outside = Vec3(500, 0, -12)
        enemy_just_outside = make_player("just_out", team=3, pos=Vec3(500, 0, 0), eye=pt_just_outside)
        self.assertIsNone(select_target(Frame((local, enemy_just_outside), "", self.camera), cfg))

    def test_ignore_dead_teammates_and_behind_camera(self) -> None:
        """Игнорирует мертвых врагов, союзников, цели за камерой и при W < 0.1."""
        local = make_player("local", team=2, pos=Vec3(0, 0, 0), eye=self.eye, local=True)
        cfg = self.base_settings

        # Союзник по центру
        teammate = make_player("ally", team=2, pos=Vec3(500, 0, 0), eye=Vec3(500, 0, 64))
        self.assertIsNone(select_target(Frame((local, teammate), "", self.camera), cfg))

        # Мёртвый враг по центру
        dead_enemy = make_player("dead", team=3, pos=Vec3(500, 0, 0), eye=Vec3(500, 0, 64), dead=True)
        self.assertIsNone(select_target(Frame((local, dead_enemy), "", self.camera), cfg))

        # Враг с 0 HP
        zero_hp_enemy = make_player("zero_hp", team=3, pos=Vec3(500, 0, 0), eye=Vec3(500, 0, 64), health=0.0)
        self.assertIsNone(select_target(Frame((local, zero_hp_enemy), "", self.camera), cfg))

        # Враг за спиной (X = -500)
        behind_enemy = make_player("behind", team=3, pos=Vec3(-500, 0, 0), eye=Vec3(-500, 0, 64))
        self.assertIsNone(select_target(Frame((local, behind_enemy), "", self.camera), cfg))

        # Враг слишком близко (W < 0.1)
        close_enemy = make_player("too_close", team=3, pos=Vec3(0.05, 0, 0), eye=Vec3(0.05, 0, 64))
        self.assertIsNone(select_target(Frame((local, close_enemy), "", self.camera), cfg))

    def test_include_teammates_selection(self) -> None:
        """Проверяет наводку на союзников: переключение, исключение себя/наблюдателей/мертвых."""
        local = make_player("local", team=2, pos=Vec3(0, 0, 0), eye=self.eye, local=True)
        # Ближний союзник (dist меньше к центру экрана) и дальний противник
        ally_close = make_player("ally_close", team=2, pos=Vec3(500, -10, 0), eye=Vec3(500, -10, 64), name="AllyClose")
        enemy_far = make_player("enemy_far", team=3, pos=Vec3(500, -30, 0), eye=Vec3(500, -30, 64), name="EnemyFar")

        frame = Frame((local, ally_close, enemy_far), "", self.camera)

        # При выключенном флаге союзник игнорируется, выбирается противник
        cfg_off = replace(self.base_settings, aim=AimSettings(include_teammates=False, radius_percent=20.0))
        target_off = select_target(frame, cfg_off)
        self.assertIsNotNone(target_off)
        assert target_off is not None
        self.assertEqual(target_off.identity, "enemy_far")

        # При включении ближний союзник выигрывает у дальнего противника
        cfg_on = replace(self.base_settings, aim=AimSettings(include_teammates=True, radius_percent=20.0))
        target_on = select_target(frame, cfg_on)
        self.assertIsNotNone(target_on)
        assert target_on is not None
        self.assertEqual(target_on.identity, "ally_close")

        # Противник остаётся доступен, если союзников нет или противник ближе
        enemy_closer = make_player("enemy_closer", team=3, pos=Vec3(500, -5, 0), eye=Vec3(500, -5, 64), name="EnemyCloser")
        frame_enemy_closer = Frame((local, ally_close, enemy_closer), "", self.camera)
        target_enemy_closer = select_target(frame_enemy_closer, cfg_on)
        self.assertIsNotNone(target_enemy_closer)
        assert target_enemy_closer is not None
        self.assertEqual(target_enemy_closer.identity, "enemy_closer")

        # Сам игрок никогда не выбирается целью (даже если один в кадре)
        frame_self_only = Frame((local,), "", self.camera)
        self.assertIsNone(select_target(frame_self_only, cfg_on))

        # Наблюдатель (team=1) исключается даже при включённом include_teammates
        spectator = make_player("spec", team=1, pos=Vec3(500, 0, 0), eye=Vec3(500, 0, 64))
        frame_spec = Frame((local, spectator), "", self.camera)
        self.assertIsNone(select_target(frame_spec, cfg_on))

        # Мёртвый союзник и союзник с 0 HP исключаются
        dead_ally = make_player("dead_ally", team=2, pos=Vec3(500, 0, 0), eye=Vec3(500, 0, 64), dead=True)
        self.assertIsNone(select_target(Frame((local, dead_ally), "", self.camera), cfg_on))
        zero_hp_ally = make_player("zero_hp_ally", team=2, pos=Vec3(500, 0, 0), eye=Vec3(500, 0, 64), health=0.0)
        self.assertIsNone(select_target(Frame((local, zero_hp_ally), "", self.camera), cfg_on))

    def test_head_versus_body_target_points(self) -> None:
        """Проверяет различие позиций head и body при наличии и отсутствии bounds/eye."""
        local = make_player("local", team=2, pos=Vec3(0, 0, 0), eye=self.eye, local=True)
        # Враг на расстоянии 500
        # bounds: X: [-16, 16], Y: [-16, 16], Z: [0, 72]
        bounds = (Vec3(-16, -16, 0), Vec3(16, 16, 72))
        enemy = make_player("enemy", team=3, pos=Vec3(500, 0, 0), eye=Vec3(500, 0, 64), bounds=bounds)

        cfg_head = replace(self.base_settings, aim=AimSettings(target="head", radius_percent=20.0))
        target_head = select_target(Frame((local, enemy), "", self.camera), cfg_head)
        self.assertIsNotNone(target_head)
        assert target_head is not None
        # Head ровно на линии взгляда -> dy == 0
        self.assertEqual(target_head.dy, 0)

        cfg_body = replace(self.base_settings, aim=AimSettings(target="body", radius_percent=20.0))
        target_body = select_target(Frame((local, enemy), "", self.camera), cfg_body)
        self.assertIsNotNone(target_body)
        assert target_body is not None
        # Center of bounds по Z = 36 (ниже линии взгляда 64) -> dy > 0
        self.assertGreater(target_body.dy, 0)

        # Тест fallback clamp для head: eye отсутствуют, eye_height = 100 > bounds[1].z (72)
        no_eye_enemy = make_player("no_eye", team=3, pos=Vec3(500, 0, 0), bounds=bounds)
        cfg_high_eye = replace(self.base_settings, eye_height=100.0, aim=AimSettings(target="head", radius_percent=20.0))
        target_clamped = select_target(Frame((local, no_eye_enemy), "", self.camera), cfg_high_eye)
        self.assertIsNotNone(target_clamped)

    def test_movement_signs_and_limiting(self) -> None:
        """Проверяет правильные знаки поворота мыши, известное малое смещение и ограничение 320 counts за кадр."""
        local = make_player("local", team=2, pos=Vec3(0, 0, 0), eye=self.eye, local=True)
        # Враг справа: target is to the right -> dx > 0
        enemy_right = make_player("right", team=3, pos=Vec3(500, -20, 0), eye=Vec3(500, -20, 64))
        cfg = replace(self.base_settings, aim=AimSettings(sensitivity=1.0, radius_percent=30.0))
        target_right = select_target(Frame((local, enemy_right), "", self.camera), cfg)
        assert target_right is not None
        self.assertEqual(target_right.dx, 89)
        self.assertEqual(target_right.dy, 0)

        # Враг слева: target is to the left -> dx < 0
        enemy_left = make_player("left", team=3, pos=Vec3(500, 20, 0), eye=Vec3(500, 20, 64))
        target_left = select_target(Frame((local, enemy_left), "", self.camera), cfg)
        assert target_left is not None
        self.assertLess(target_left.dx, 0)

        # Враг выше: target is above -> dy < 0
        enemy_up = make_player("up", team=3, pos=Vec3(500, 0, 0), eye=Vec3(500, 0, 84))
        target_up = select_target(Frame((local, enemy_up), "", self.camera), cfg)
        assert target_up is not None
        self.assertLess(target_up.dy, 0)

        # Враг ниже: target is below -> dy > 0
        enemy_down = make_player("down", team=3, pos=Vec3(500, 0, 0), eye=Vec3(500, 0, 44))
        target_down = select_target(Frame((local, enemy_down), "", self.camera), cfg)
        assert target_down is not None
        self.assertGreater(target_down.dy, 0)

        # Ограничение движения (максимум 320 counts на ось):
        cfg_high_motion = replace(self.base_settings, aim=AimSettings(sensitivity=0.05, radius_percent=50.0))
        enemy_far_right = make_player("far_right", team=3, pos=Vec3(500, -80, 0), eye=Vec3(500, -80, 64))
        target_limited = select_target(Frame((local, enemy_far_right), "", self.camera), cfg_high_motion)
        assert target_limited is not None
        self.assertEqual(target_limited.dx, 320)


if __name__ == "__main__":
    unittest.main()
