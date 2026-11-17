"""Health encoding uses the radar's bottom-up colored/white convention."""
from __future__ import annotations

from dataclasses import replace
import json
import math
import unittest

from perspective.config import GameVideo
from perspective.hyprland import Rect
from perspective.overlay_scene import overlay_boxes
from perspective.scene import Frame, Player, Segment, player_health_strokes
from tests.test_perspective import player_data, settings


class HealthTests(unittest.TestCase):
    def test_frame_health_clamps_and_unknown_values_keep_full_color(self) -> None:
        for value, expected in ((25, 25), (0, 0), (-5, 0), (200, 100),
                                (None, 100), (True, 100), ("25", 100), (math.nan, 100)):
            with self.subTest(value=value):
                self.assertEqual(Player.parse(dict(player_data(), m_health=value)).health, expected)
        self.assertEqual(Player.parse(player_data()).health, 100)

    def test_quarter_hp_splits_diagonal_edges_at_screen_bottom_quarter(self) -> None:
        segments: tuple[Segment, ...] = (((10, 20), (30, 120)), ((30, 120), (50, 120)), ((10, 20), (50, 20)))
        result = player_health_strokes(segments, 25, "#ff0000")
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0].segment, ((10, 20), (25, 95)))
        self.assertEqual(result[0].color, "#ffffff")
        self.assertEqual(result[1].segment, ((25, 95), (30, 120)))
        self.assertEqual(result[1].color, "#ff0000")
        self.assertEqual(result[2].color, "#ff0000")
        self.assertEqual(result[3].color, "#ffffff")
        for health, color in ((100, "#ff0000"), (0, "#ffffff")):
            self.assertTrue(all(stroke.color == color for stroke in player_health_strokes(segments, health, "#ff0000")))
        self.assertEqual(player_health_strokes((), 50, "#ff0000"), ())

    def test_projected_hp_stays_upright_when_looking_up_and_down(self) -> None:
        for pitch in (-25, 0, 25):
            for health in (1, 25, 50, 100):
                own = dict(player_data(), m_eye_pitch=pitch)
                other = dict(player_data(2, False), m_health=health, m_position={"x": 300, "y": 20, "z": 0})
                frame = Frame.parse(json.dumps({"m_players": [own, other]}))
                boxes = overlay_boxes(frame, replace(settings(), enemy_color="#ef4444"),
                                      GameVideo(1280, 960, 90, "test"), Rect(100, 50, 1280, 960))
                box = boxes[0]
                self.assertEqual(box.health, health)
                top = min(point[1] for segment in box.segments for point in segment)
                bottom = max(point[1] for segment in box.segments for point in segment)
                boundary = bottom - (bottom - top) * health / 100
                for stroke in player_health_strokes(box.segments, box.health, box.color):
                    for _, y in stroke.segment:
                        if stroke.color == box.color:
                            self.assertGreaterEqual(y + 1e-8, boundary)
                        else:
                            self.assertLessEqual(y - 1e-8, boundary)


if __name__ == "__main__":
    unittest.main()
