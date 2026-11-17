"""Направление взгляда, обрезка лучей и общая геометрия оверлеев."""
from __future__ import annotations

from dataclasses import asdict, replace
import math
from typing import cast
import unittest

from perspective.config import GameVideo, Settings, SettingsError
from perspective.geometry import Rect
from perspective.overlay_scene import overlay_boxes
from perspective.scene import Camera, Frame, MatrixCamera, Player, Segment, Vec3, project_view_ray
from tests.test_matrix_projection import render_matrix
from tests.test_perspective import player_data, settings


class ViewRayTests(unittest.TestCase):
    """Проверяет мировые направления и независимую от платформы проекцию."""

    def test_source_angles_and_eye_origin(self) -> None:
        """Проверяет оси Source, знак pitch, длину и выбор позиции глаз."""
        player = Player.parse(player_data(2, False))
        captured: list[tuple[Vec3, Vec3, float, float]] = []

        def capture(a: Vec3, b: Vec3, width: float, height: float) -> Segment:
            """Сохраняет мировой отрезок перед проекцией."""
            captured.append((a, b, width, height))
            return ((0, 0), (1, 1))

        for yaw, pitch, direction in ((0, 0, Vec3(1, 0, 0)),
                                      (90, 0, Vec3(0, 1, 0)),
                                      (180, 0, Vec3(-1, 0, 0)),
                                      (-90, 0, Vec3(0, -1, 0)),
                                      (0, 90, Vec3(0, 0, -1)),
                                      (0, -90, Vec3(0, 0, 1)),
                                      (90, 30, Vec3(0, math.sqrt(3) / 2, -0.5))):
            with self.subTest(yaw=yaw, pitch=pitch):
                project_view_ray(capture, replace(player, yaw=yaw, pitch=pitch,
                                                  eye=Vec3(12, 23, 45)), 800, 600, 70)
                start, end, width, height = captured[-1]
                self.assertEqual((start, width, height), (Vec3(12, 23, 45), 800, 600))
                for actual, expected in zip((end.x - start.x, end.y - start.y, end.z - start.z),
                                            (direction.x, direction.y, direction.z)):
                    self.assertAlmostEqual(actual, expected * 1024)
        project_view_ray(capture, replace(player, eye=None, position=Vec3(10, 20, 30)), 800, 600, 70)
        self.assertEqual(captured[-1][0], Vec3(10, 20, 100))
        count = len(captured)
        for omitted in (replace(player, dead=True), replace(player, pitch=None)):
            self.assertIsNone(project_view_ray(capture, omitted, 800, 600, 70))
        self.assertEqual(len(captured), count)

    def test_matrix_and_reconstructed_clipping(self) -> None:
        """Обрезает лучи по ближней плоскости и краям обеими камерами."""
        player = Player.parse(player_data(2, False))
        manual = Camera(Vec3(0, 0, 64), 0, 0, 90, 4 / 3, 800)
        matrix = MatrixCamera(render_matrix(aspect=4 / 3), 800)
        cases = ((Vec3(100, 0, 64), 90, 0, True),
                 (Vec3(100, 0, 64), 0, 90, True),
                 (Vec3(-100, 0, 64), 180, 0, False),
                 (Vec3(-100, 0, 64), 0, 0, True),
                 (Vec3(100, 200, 64), -90, 0, True),
                 (Vec3(0.5, 0, 64), 180, 0, False))
        for eye, yaw, pitch, visible in cases:
            with self.subTest(eye=eye, yaw=yaw, pitch=pitch):
                target = replace(player, eye=eye, yaw=yaw, pitch=pitch)
                expected = project_view_ray(manual.project_edge, target, 800, 600, 64)
                actual = project_view_ray(matrix.project_edge, target, 800, 600, 64)
                self.assertEqual(actual is not None, visible)
                self.assertEqual(expected is not None, visible)
                if actual is not None and expected is not None:
                    for point, reference in zip(actual, expected):
                        for coordinate, bound, wanted in zip(point, (800, 600), reference):
                            self.assertTrue(math.isfinite(coordinate))
                            self.assertGreaterEqual(coordinate, -1e-9)
                            self.assertLessEqual(coordinate, bound + 1e-9)
                            self.assertAlmostEqual(coordinate, wanted)

    def test_overlay_transform_and_camera_selection(self) -> None:
        """Сохраняет лучи при масштабе окна и учитывает матрицу, полосы и растяжение."""
        viewer = replace(Player.parse(player_data()), pitch=None, fov=None)
        target = replace(Player.parse(player_data(2, False)), eye=Vec3(200, -80, 90),
                         position=Vec3(200, -80, 0), yaw=90, pitch=15, health=1)
        frame = Frame((viewer, target, replace(target, identity="dead", dead=True)), "",
                      MatrixCamera(render_matrix(aspect=4 / 3)))
        video = GameVideo(800, 600, None, "test")
        base = settings()
        source = project_view_ray(frame.view_matrix.project_edge, target, 800, 600, 64) if frame.view_matrix else None
        assert source is not None
        for stretch in (False, True):
            custom = replace(base, overlay_stretch=stretch, scale=0.2)
            game = Rect(40, 80, 1600, 900)
            outlines = overlay_boxes(frame, custom, video, game)
            self.assertEqual(len(outlines), 1)
            self.assertEqual(outlines, overlay_boxes(frame, replace(custom, scale=1.5), video, game))
            ray = outlines[0].view_ray
            assert ray is not None
            for point, reference in zip(ray, source):
                self.assertAlmostEqual(point[0], 40 + (0 if stretch else 200) + reference[0] * (2 if stretch else 1.5))
                self.assertAlmostEqual(point[1], 80 + reference[1] * 1.5)
            self.assertEqual(outlines[0].color, custom.enemy_color)
            manual_frame = replace(frame, players=(replace(viewer, pitch=0), target))
            manual_ray = overlay_boxes(manual_frame, replace(custom, fov=90), video, game)[0].view_ray
            assert manual_ray is not None
            for point, reference in zip(manual_ray, ray):
                for coordinate, wanted in zip(point, reference):
                    self.assertAlmostEqual(coordinate, wanted)
            disabled = overlay_boxes(frame, replace(custom, show_view_rays=False), video, game)
            self.assertIsNone(disabled[0].view_ray)
            self.assertEqual(disabled[0].segments, outlines[0].segments)
        missing = replace(frame, players=(viewer, replace(target, pitch=None)))
        self.assertIsNone(overlay_boxes(missing, base, video, Rect(0, 0, 800, 600))[0].view_ray)
        remote = replace(target, identity="remote", eye=Vec3(0, 0, 64), position=Vec3(0, 0, 0),
                         yaw=0, pitch=0, fov=90)
        selected = replace(frame, players=(remote, target))
        self.assertEqual(overlay_boxes(selected, replace(base, player="remote"), video, Rect(0, 0, 800, 600)),
                         overlay_boxes(replace(selected, view_matrix=None), replace(base, player="remote"),
                                       video, Rect(0, 0, 800, 600)))

    def test_setting_migration_and_constructor_validation(self) -> None:
        """Поддерживает старые настройки и отклоняет флаги неверного типа при создании."""
        original = settings()
        old = asdict(original)
        del old["show_view_rays"]
        self.assertTrue(Settings.parse(old).show_view_rays)
        self.assertFalse(Settings.parse(dict(old, show_view_rays=False)).show_view_rays)
        invalid_values: tuple[object, ...] = (None, 0, 1, "true", [], {})
        for invalid in invalid_values:
            with self.subTest(value=invalid):
                with self.assertRaises(SettingsError):
                    Settings.parse(dict(old, show_view_rays=invalid))
                with self.assertRaises(SettingsError):
                    replace(original, show_view_rays=cast(bool, invalid))


if __name__ == "__main__":
    unittest.main()
