"""Projection, configuration, protocol and reader regression checks."""
from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile
import unittest

from perspective.config import GameVideo, Settings, SettingsError
from perspective.scene import Camera, Frame, FrameError, Player, Vec3
from helper.linux.src.camera_telemetry import CameraOffsets, read_camera


def player_data(slot: int = 1, local: bool = True) -> dict[str, object]:
    return {"m_idx": slot, "m_name": f"Player {slot}", "m_steam_id": str(76561198000000000 + slot),
            "m_is_local": local, "m_is_dead": False, "m_team": 2 if local else 3,
            "m_position": {"x": 0, "y": 0, "z": 0}, "m_eye_angle": 0,
            "m_eye_pitch": 0, "m_camera_fov": 90,
            "m_eye_position": {"x": 0, "y": 0, "z": 64}}


def settings() -> Settings:
    raw: object = json.loads(Path("perspective/config.example.json").read_text())
    return Settings.parse(raw)


class ProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.camera = Camera(Vec3(0, 0, 64), 0, 0, 90, 4 / 3, 800)

    def test_direction_and_horizon(self) -> None:
        point = Vec3(100, 0, 64)
        center = self.camera.project_edge(point, point, 800, 600)
        self.assertEqual(center, ((400, 300), (400, 300)))
        right = self.camera.project_edge(Vec3(100, -50, 64), Vec3(100, -50, 64), 800, 600)
        assert right is not None
        self.assertAlmostEqual(right[0][0], 600)
        turned = replace(self.camera, yaw=90)
        forward = turned.to_view(Vec3(0, 100, 64))
        self.assertAlmostEqual(forward.x, 0)
        self.assertAlmostEqual(forward.z, 100)
        # Positive Source pitch looks down. A lower target lies on the crosshair.
        down = replace(self.camera, pitch=45)
        result = down.project_edge(Vec3(100, 0, -36), Vec3(100, 0, -36), 800, 600)
        assert result is not None
        self.assertAlmostEqual(result[0][1], 300)
        up = replace(self.camera, pitch=-45)
        self.assertAlmostEqual(up.to_view(Vec3(100, 0, 164)).y, 0)

    def test_projection_size_depends_on_distance_and_zoom(self) -> None:
        near = self.camera.project_edge(Vec3(100, -16, 64), Vec3(100, 16, 64), 800, 600)
        far = self.camera.project_edge(Vec3(200, -16, 64), Vec3(200, 16, 64), 800, 600)
        zoom = replace(self.camera, fov=45).project_edge(Vec3(100, -16, 64), Vec3(100, 16, 64), 800, 600)
        assert near and far and zoom
        self.assertAlmostEqual(abs(near[0][0] - near[1][0]), 2 * abs(far[0][0] - far[1][0]))
        self.assertGreater(abs(zoom[0][0] - zoom[1][0]), abs(near[0][0] - near[1][0]))

    def test_frustum_clipping(self) -> None:
        self.assertIsNone(self.camera.project_edge(Vec3(-100, 0, 0), Vec3(-200, 0, 0), 800, 600))
        # An edge crossing the near plane and a side plane remains finite and clipped.
        result = self.camera.project_edge(Vec3(-10, -100, 64), Vec3(100, 0, 64), 800, 600)
        assert result is not None
        for x, y in result:
            self.assertTrue(math.isfinite(x) and math.isfinite(y))
            self.assertTrue(-1e-8 <= x <= 800 + 1e-8)
            self.assertTrue(-1e-8 <= y <= 600 + 1e-8)

    def test_hyprland_resize_preserves_game_aspect_and_center(self) -> None:
        for aspect in (4 / 3, 16 / 9, 16 / 10):
            camera = replace(self.camera, aspect=aspect)
            for width, height in ((400, 900), (1900, 500), (700, 700)):
                x, y, w, h = camera.viewport(width, height)
                self.assertAlmostEqual(w / h, aspect)
                self.assertAlmostEqual(x + w / 2, width / 2)
                self.assertAlmostEqual(y + h / 2, height / 2)
                self.assertLessEqual(w, width)
                self.assertLessEqual(h, height)

    def test_box_uses_real_height_and_excludes_behind_camera(self) -> None:
        player = replace(Player.parse(player_data(2, False)), position=Vec3(200, 0, 0))
        full = self.camera.box(player, 800, 600, 32, 72)
        crouched = replace(player, bounds=(Vec3(-16, -16, 0), Vec3(16, 16, 54)))
        short = self.camera.box(crouched, 800, 600, 32, 72)
        self.assertEqual(len(full), 12)
        self.assertGreater(min(p[1] for edge in short for p in edge), min(p[1] for edge in full for p in edge))
        self.assertEqual(self.camera.box(replace(player, position=Vec3(-200, 0, 0)), 800, 600, 32, 72), ())


class FrameTests(unittest.TestCase):
    def test_identity_selection_and_older_helper(self) -> None:
        data = player_data()
        del data["m_eye_pitch"]
        frame = Frame.parse(json.dumps({"m_players": [data]}))
        selected = frame.selected("helper")
        assert selected
        self.assertIsNone(selected.pitch)
        self.assertIs(frame.selected(selected.identity), selected)
        self.assertIsNone(frame.selected("steam:999"))
        changed = dict(data, m_name="Renamed", m_idx=12)
        self.assertEqual(Player.parse(changed).identity, selected.identity)

    def test_invalid_frames_are_rejected_and_status_clears_players(self) -> None:
        for data in ("broken", "[]", '{"m_players": null}',
                     json.dumps({"m_players": [dict(player_data(), m_eye_pitch=math.nan)]}),
                     json.dumps({"m_players": [dict(player_data(), m_eye_pitch=True)]}),
                     json.dumps({"m_players": [player_data(), player_data()]})):
            with self.subTest(data=data), self.assertRaises(FrameError):
                Frame.parse(data)
        frame = Frame.parse('{"type":"status","state":"menu","detail":"In menu"}')
        self.assertEqual(frame.players, ())
        self.assertEqual(frame.status, "In menu")


class SettingsTests(unittest.TestCase):
    def test_cfg_reads_resolution_and_camera_fov_but_not_viewmodel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "cs2_video.txt").write_text('"video.cfg"\n{\n"setting.defaultres" "1280"\n"setting.defaultresheight" "960"\n}')
            (path / "cs2_user_convars_0_slot0.vcfg").write_text('"viewmodel_fov" "68"\n')
            video = GameVideo.read(path)
            self.assertEqual(video.resolution(settings()), (1280, 960))
            self.assertIsNone(video.fov)
            (path / "cs2_machine_convars.vcfg").write_text('"fov_desired" "75"\n')
            self.assertEqual(GameVideo.read(path).fov, 75)
            manual = replace(settings(), width=1920, height=1080)
            self.assertEqual(video.resolution(manual), (1920, 1080))

    def test_settings_roundtrip_and_no_guessed_game_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            initial = Settings.load(path)
            updated = replace(initial, scale=0.3, width=1280, height=960, fov=90)
            updated.save(path)
            self.assertEqual(Settings.load(path), updated)
            with self.assertRaises(SettingsError):
                GameVideo.read(None).resolution(initial)
            raw: object = json.loads(path.read_text().replace('"scale": 0.3', '"scale": 0'))
            with self.assertRaises(SettingsError):
                Settings.parse(raw)


class FakeMemory:
    def __init__(self) -> None:
        self.values: dict[int, float] = {}

    def f32(self, address: int) -> float:
        return self.values.get(address, 0)

    def ptr(self, address: int) -> int:
        return int(self.values.get(address, 0))

    def u32(self, address: int) -> int:
        return int(self.values.get(address, 0))


class ReaderTests(unittest.TestCase):
    def test_unavailable_optional_camera_memory_does_not_break_radar(self) -> None:
        class UnreadableMemory(FakeMemory):
            def f32(self, address: int) -> float:
                raise OSError("unmapped memory")
        result = read_camera(UnreadableMemory(), 10000, CameraOffsets(100, 200, 300, 400, 500, 64, 76), (1, 2, 3))
        self.assertTrue(all(value is None for value in result.values()))

    def test_pitch_network_eye_offset_fov_and_crouch_bounds(self) -> None:
        memory = FakeMemory()
        pawn, services, collision = 10000, 20000, 30000
        offsets = CameraOffsets(100, 200, 300, 400, 500, 64, 76)
        memory.values = {pawn + 100: -35, pawn + 200 + 0x10: 0,
                         pawn + 200 + 0x18: 0, pawn + 200 + 0x20: 46,
                         pawn + 300: services, services + 400: 40, pawn + 500: collision,
                         collision + 64: -16, collision + 68: -16, collision + 72: 0,
                         collision + 76: 16, collision + 80: 16, collision + 84: 54}
        result = read_camera(memory, pawn, offsets, (1, 2, 3))
        self.assertEqual(result["m_eye_pitch"], -35)
        self.assertEqual(result["m_eye_position"], {"x": 1, "y": 2, "z": 49})
        self.assertEqual(result["m_camera_fov"], 40)
        self.assertEqual(result["m_bounds_max"], {"x": 16, "y": 16, "z": 54})
        empty = read_camera(memory, pawn, CameraOffsets(0, 0, 0, 0, 0, 0, 0), (1, 2, 3))
        self.assertTrue(all(value is None for value in empty.values()))

    def test_platform_readers_ship_the_same_camera_contract(self) -> None:
        self.assertEqual(Path("helper/linux/src/camera_telemetry.py").read_bytes(),
                         Path("helper/windows/src/camera_telemetry.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
