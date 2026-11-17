"""Hyprland geometry, letterboxing and independent overlay scale regression checks."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import unittest

from perspective.config import GameVideo, Settings
from perspective.hyprland import GameTarget, Rect
from perspective.overlay_scene import overlay_boxes
from perspective.scene import Frame, FrameError
from tests.test_perspective import player_data, settings


class OverlayTests(unittest.TestCase):
    def test_scaled_rotated_monitor_uses_logical_window_coordinates(self) -> None:
        client = {"class": "cs2", "mapped": True, "hidden": False, "monitor": 1,
                  "at": [1000, 200], "size": [640, 480]}
        monitors = [{"id": 1, "name": "DP-1", "x": 960, "y": 120, "width": 2560,
                     "height": 1440, "scale": 2, "transform": 1}]
        target = GameTarget.parse(client, monitors)
        assert target
        self.assertEqual(target.output, Rect(960, 120, 720, 1280))
        self.assertEqual(target.game, Rect(40, 80, 640, 480))
        self.assertIsNone(GameTarget.parse(dict(client, hidden=True), monitors))
        self.assertIsNone(GameTarget.parse(dict(client, **{"class": "other"}), monitors))
        with self.assertRaises(FrameError):
            GameTarget.parse(client, [dict(monitors[0], scale=0)])

    def test_overlay_projects_to_full_game_rect_even_when_preview_is_small(self) -> None:
        target = dict(player_data(2, False), m_position={"x": 200, "y": -80, "z": 0})
        frame = Frame.parse(json.dumps({"m_players": [player_data(), target]}))
        video = GameVideo(1280, 960, 90, "test")
        game = Rect(10, 20, 1920, 1080)
        small, large = replace(settings(), scale=0.2), replace(settings(), scale=1.5)
        boxes = overlay_boxes(frame, small, video, game)
        self.assertEqual(boxes, overlay_boxes(frame, large, video, game))
        segments = boxes[0].segments
        self.assertEqual(len(segments), 12)
        for edge in segments:
            for x, y in edge:
                self.assertGreaterEqual(x, game.x + 240)
                self.assertLessEqual(x, game.x + game.width - 240)
                self.assertGreaterEqual(y, game.y)
                self.assertLessEqual(y, game.y + game.height)
        stretched = overlay_boxes(frame, replace(small, overlay_stretch=True), video, game)
        self.assertGreater(stretched[0].segments[0][0][0], segments[0][0][0])

    def test_missing_camera_draws_nothing_and_existing_preferences_migrate(self) -> None:
        frame = Frame.parse(json.dumps({"m_players": [player_data()]}))
        video = GameVideo(1280, 960, 90, "test")
        self.assertEqual(overlay_boxes(frame, replace(settings(), player="steam:999"), video, Rect(0, 0, 800, 600)), ())
        old = asdict(settings())
        del old["overlay_stretch"]
        self.assertFalse(Settings.parse(old).overlay_stretch)

    def test_colors_follow_selected_team_and_no_center_crosshair_is_added(self) -> None:
        ally = dict(player_data(2, False), m_team=2, m_position={"x": 200, "y": 70, "z": 0})
        enemy = dict(player_data(3, False), m_position={"x": 200, "y": -70, "z": 0})
        frame = Frame.parse(json.dumps({"m_players": [player_data(), ally, enemy]}))
        custom = replace(settings(), teammate_color="#123456", enemy_color="#abcdef")
        boxes = overlay_boxes(frame, custom, GameVideo(1280, 960, 90, "test"), Rect(0, 0, 1280, 960))
        self.assertEqual([box.color for box in boxes], ["#123456", "#abcdef"])
        self.assertEqual(sum(len(box.segments) for box in boxes), 24)
        selected = frame.players[2]
        self.assertEqual(custom.player_color(frame.players[1], selected), "#abcdef")
        self.assertEqual(custom.player_color(selected, selected), "#123456")
        no_others = Frame.parse(json.dumps({"m_players": [player_data()]}))
        self.assertEqual(overlay_boxes(no_others, custom, GameVideo(1280, 960, 90, "test"), Rect(0, 0, 1280, 960)), ())

    def test_colors_are_validated_and_saved_settings_keep_defaults(self) -> None:
        old = asdict(settings())
        del old["teammate_color"], old["enemy_color"]
        self.assertEqual(Settings.parse(old).enemy_color, "#ef4444")
        for value in ("red", "#12345", "#123456;", 42):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Settings.parse(dict(old, enemy_color=value))


if __name__ == "__main__":
    unittest.main()
