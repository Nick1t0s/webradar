"""Матрица рендера, края экрана и выбор камеры локального/удалённого игрока."""
from __future__ import annotations

from dataclasses import replace
import json
import math
import unittest

from perspective.config import GameVideo
from perspective.geometry import Rect
from perspective.overlay_scene import overlay_boxes
from perspective.scene import Camera, Frame, FrameError, MatrixCamera, Vec3
from tests.test_perspective import player_data, settings


def render_matrix(eye: Vec3 = Vec3(0, 0, 64), yaw: float = 0, pitch: float = 0,
                  fov: float = 90, aspect: float = 1.6) -> tuple[float, ...]:
    """Составляет известную матрицу камеры из независимых ортогональных осей."""
    yaw_r, pitch_r = math.radians(yaw), math.radians(pitch)
    forward = (math.cos(yaw_r) * math.cos(pitch_r), math.sin(yaw_r) * math.cos(pitch_r), -math.sin(pitch_r))
    right = (math.sin(yaw_r), -math.cos(yaw_r), 0.0)
    up = (math.cos(yaw_r) * math.sin(pitch_r), math.sin(yaw_r) * math.sin(pitch_r), math.cos(pitch_r))
    tangent = math.tan(math.radians(fov) / 2) * 3 / 4
    rows = (tuple(value / (tangent * aspect) for value in right),
            tuple(value / tangent for value in up), forward, forward)
    return tuple(value for row in rows for value in (*row, -sum(a * b for a, b in zip(row, (eye.x, eye.y, eye.z)))))


def reference_screen(matrix: tuple[float, ...], point: Vec3, width: float, height: float) -> tuple[float, float]:
    """Вычисляет эталонный world-to-screen напрямую как существующий браузерный ESP."""
    homogeneous = (point.x, point.y, point.z, 1)
    x, y, w = (sum(matrix[row + i] * coordinate for i, coordinate in enumerate(homogeneous)) for row in (0, 4, 12))
    return width / 2 * (1 + x / w), height / 2 * (1 - y / w)


class MatrixProjectionTests(unittest.TestCase):
    """Проверяет проекцию независимо от сохранённого FOV и положения камеры."""

    def test_off_axis_points_match_render_reference_and_cfg_75_does_not(self) -> None:
        """Не даёт расти ошибке при удалении цели от центра экрана."""
        matrix = render_matrix()
        camera = MatrixCamera(matrix)
        previous_error = -1.0
        for angle in (0, 15, 30, 40):
            for side in (-1, 1):
                point = Vec3(500, -side * 500 * math.tan(math.radians(angle)), 64)
                projected = camera.project_edge(point, point, 1920, 1200)
                self.assertIsNotNone(projected)
                assert projected is not None
                expected_x = 960 * (1 + side * math.tan(math.radians(angle)) / 1.2)
                self.assertAlmostEqual(projected[0][0], expected_x)
                self.assertAlmostEqual(projected[0][1], 600)
                reference = reference_screen(matrix, point, 1920, 1200)
                self.assertAlmostEqual(projected[0][0], reference[0])
            old = Camera(Vec3(0, 0, 64), 0, 0, 75, 1.6, 1920).project_edge(point, point, 1920, 1200)
            assert old is not None and projected is not None
            error = abs(old[0][0] - projected[0][0])
            self.assertGreater(error, previous_error)
            previous_error = error
        self.assertGreater(previous_error, 200)
        self.assertAlmostEqual(camera.aspect, 1.6)
        self.assertAlmostEqual(camera.fov, 90)
        for angle in (-30, -15, 0, 15, 30):
            point = Vec3(500, 0, 64 + 500 * math.tan(math.radians(angle)))
            projected = camera.project_edge(point, point, 1920, 1200)
            assert projected is not None
            self.assertAlmostEqual(projected[0][1], 600 * (1 - math.tan(math.radians(angle)) / 0.75))

    def test_translated_rotated_camera_and_scaled_matrix_match_reference(self) -> None:
        """Сохраняет положение при повороте, переносе камеры и общем множителе матрицы."""
        eye = Vec3(100, -200, 80)
        for yaw, pitch in ((25, -20), (-130, 35)):
            matrix = render_matrix(eye, yaw, pitch, 70, 16 / 9)
            camera = MatrixCamera(matrix)
            forward = matrix[12:15]
            center = eye.add(Vec3(*(coordinate * 500 for coordinate in forward)))
            for shift in (Vec3(0, 0, 0), Vec3(20, 30, 50), Vec3(-50, 10, -20)):
                point = center.add(shift)
                expected = reference_screen(matrix, point, 1600, 900)
                segment = camera.project_edge(point, point, 1600, 900)
                scaled = MatrixCamera(tuple(value * 3 for value in matrix)).project_edge(point, point, 1600, 900)
                assert segment is not None and scaled is not None
                for actual, reference in zip(segment[0], expected):
                    self.assertAlmostEqual(actual, reference)
                for actual, reference in zip(scaled[0], expected):
                    self.assertAlmostEqual(actual, reference)
            self.assertAlmostEqual(camera.fov, 70)

    def test_homogeneous_clipping_keeps_edges_bounded_and_rejects_behind_camera(self) -> None:
        """Обрезает пересечения с передней плоскостью и краями до деления на W."""
        camera = MatrixCamera(render_matrix(Vec3(0, 0, 0)))
        self.assertIsNone(camera.project_edge(Vec3(-10, 0, 0), Vec3(-2, 0, 1), 1920, 1200))
        for a, b in ((Vec3(-10, 0, 0), Vec3(50, 20, 10)),
                     (Vec3(10, -1000, 0), Vec3(10, 1000, 0)),
                     (Vec3(10, 0, -1000), Vec3(10, 0, 1000))):
            segment = camera.project_edge(a, b, 1920, 1200)
            assert segment is not None
            for x, y in segment:
                self.assertTrue(math.isfinite(x) and math.isfinite(y))
                self.assertGreaterEqual(x, -1e-9)
                self.assertLessEqual(x, 1920 + 1e-9)
                self.assertGreaterEqual(y, -1e-9)
                self.assertLessEqual(y, 1200 + 1e-9)
        self.assertIsNone(camera.project_edge(Vec3(10, -1000, 0), Vec3(20, -1000, 0), 1920, 1200))

    def test_invalid_optional_matrices_do_not_discard_players(self) -> None:
        """Отклоняет повреждённую матрицу отдельно от остального кадра."""
        invalid: tuple[object, ...] = (None, "matrix", [], [0] * 16, [1] * 16,
            list(render_matrix())[:15], [True] * 16,
            [math.nan, *render_matrix()[1:]], [math.inf, *render_matrix()[1:]], ["0", *render_matrix()[1:]])
        for value in invalid:
            with self.subTest(value=value):
                frame = Frame.parse(json.dumps({"m_players": [player_data()], "m_view_matrix": value}))
                self.assertEqual(len(frame.players), 1)
                self.assertIsNone(frame.view_matrix)
        for value in ((), (0.0,) * 16, (1.0,) * 16):
            with self.assertRaises(FrameError):
                MatrixCamera(value)
        frame = Frame.parse(json.dumps({"m_players": [player_data()], "m_view_matrix": render_matrix()}))
        self.assertIsNotNone(frame.view_matrix)

    def test_local_matrix_ignores_missing_estimates_but_remote_and_manual_use_reconstruction(self) -> None:
        """Не переносит локальную матрицу на другого игрока или ручной FOV."""
        local = dict(player_data(), m_eye_pitch=None, m_camera_fov=None, m_eye_position=None)
        remote = dict(player_data(2, False), m_position={"x": 300, "y": -100, "z": 0}, m_eye_angle=180)
        frame = Frame.parse(json.dumps({"m_players": [local, remote], "m_view_matrix": render_matrix()}))
        configured = settings()
        video = GameVideo(1920, 1200, 75, "cfg")
        game = Rect(0, 0, 1920, 1200)
        self.assertTrue(overlay_boxes(frame, configured, video, game))
        self.assertEqual(overlay_boxes(replace(frame, view_matrix=None), configured, video, game), ())
        remote_settings = replace(configured, player=frame.players[1].identity)
        self.assertEqual(overlay_boxes(frame, remote_settings, video, game),
                         overlay_boxes(replace(frame, view_matrix=None), remote_settings, video, game))
        frame = Frame.parse(json.dumps({"m_players": [player_data(), remote], "m_view_matrix": render_matrix()}))
        manual = replace(configured, fov=75)
        self.assertEqual(overlay_boxes(frame, manual, video, game),
                         overlay_boxes(replace(frame, view_matrix=None), manual, video, game))
        self.assertNotEqual(overlay_boxes(frame, configured, video, game), overlay_boxes(frame, manual, video, game))
        self.assertIsNone(frame.local_camera(replace(frame.players[0], dead=True), None))

    def test_matrix_aspect_letterbox_stretch_logical_offset_and_preview_scale(self) -> None:
        """Совмещает матрицу с игровой областью независимо от cfg и масштаба окна."""
        target = dict(player_data(2, False), m_position={"x": 300, "y": -100, "z": 0})
        matrix = render_matrix(aspect=4 / 3)
        frame = Frame.parse(json.dumps({"m_players": [player_data(), target], "m_view_matrix": matrix}))
        configured = settings()
        video = GameVideo(1920, 1200, 75, "cfg")
        game = Rect(10, 20, 1920, 1080)
        boxes = overlay_boxes(frame, configured, video, game)
        self.assertEqual(boxes, overlay_boxes(frame, replace(configured, scale=0.1), video, game))
        stretched = overlay_boxes(frame, replace(configured, overlay_stretch=True), video, game)
        reference = Camera(Vec3(0, 0, 64), 0, 0, 90, 4 / 3, 1440).box(frame.players[1], 1440, 1080, 32, 72)
        for actual, expected, full in zip(boxes[0].segments, reference, stretched[0].segments):
            for point, truth, full_point in zip(actual, expected, full):
                self.assertAlmostEqual(point[0], 10 + 240 + truth[0])
                self.assertAlmostEqual(point[1], 20 + truth[1])
                self.assertAlmostEqual(full_point[0], 10 + truth[0] * 1920 / 1440)
                self.assertAlmostEqual(full_point[1], 20 + truth[1])
        camera = MatrixCamera(matrix, maximum_width=640)
        self.assertEqual(camera.viewport(1000, 800), (180, 160, 640, 480))


if __name__ == "__main__":
    unittest.main()
