"""Проверки профилей, движения и границ управления без физического ввода."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import math
import sys
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from perspective.config import Settings
from perspective.recoil import RecoilMotion, RecoilSettings, RecoilStep
from perspective.scene import Frame
from tests.test_perspective import player_data, settings

if sys.platform.startswith("linux"):
    from perspective.mouse_linux import LinuxMouse, MouseDevice, MouseError, mouse_path
    from perspective.recoil_linux import controlled_weapon, game_focused, local_source


@unittest.skipUnless(sys.platform.startswith("linux"), "Управление мышью поддерживает Linux / Hyprland")
class RecoilTests(unittest.TestCase):
    """Проверяет компенсацию независимо от частоты кадров и случайных остановок."""

    def test_strict_settings_constructor_migration_and_roundtrip(self) -> None:
        """Отклоняет неверные данные при любом создании и сохраняет старые настройки."""
        invalid: tuple[dict[str, object], ...] = ({"enabled": 1}, {"enabled": True}, {"strength": "1"}, {"sensitivity": True},
                       {"sensitivity": 0}, {"strength": math.inf}, {"toggle_button": "BTN_LEFT"},
                       {"mouse_device": "/dev/input/../mem"}, {"mouse_device": "bluetooth:bad"},
                       {"profiles": {}}, {"profiles": {"ak47": []}}, {"unknown": 1})
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                RecoilSettings.parse(fields)
        with self.assertRaises(ValidationError):
            RecoilSettings(strength=0)
        with self.assertRaises(ValidationError):
            RecoilStep(math.nan, 0, 0)
        with self.assertRaises(ValidationError):
            RecoilSettings(profiles={"ak47": (RecoilStep(5, 0, 1),) * 3})
        old = asdict(settings())
        del old["recoil"]
        self.assertFalse(Settings.parse(old).recoil.enabled)
        configured = replace(settings(), recoil=RecoilSettings(enabled=True, mouse_device="bluetooth:11:22:33:44:55:66"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            configured.save(path)
            self.assertEqual(Settings.load(path), configured)

    def test_motion_preserves_fractional_counts_across_steps_and_rates(self) -> None:
        """Проверяет сумму смещений при разной частоте и смене направления профиля."""
        configured = RecoilSettings(sensitivity=2, strength=0.5, profiles={"ak47": (
            RecoilStep(0.4, -50, 100), RecoilStep(0.6, 25, 50))})
        for frequency in (50, 125, 250):
            motion = RecoilMotion()
            motion.advance(0, False, "ak47", configured, True)
            dx = dy = 0
            for index in range(frequency + 1):
                x, y = motion.advance(index / frequency, True, "ak47", configured, True)
                dx, dy = dx + x, dy + y
            self.assertEqual((dx, dy), (-1, 17))
            self.assertEqual(motion.advance(1 + 1 / frequency, True, "ak47", configured, True), (0, 0))

    def test_interrupts_do_not_resume_held_trigger_or_catch_up(self) -> None:
        """Блокирует ввод до отпускания ЛКМ после потери условий, смены оружия и задержки."""
        configured = RecoilSettings(profiles={"ak47": (RecoilStep(2, 0, 200),),
                                            "m4a1": (RecoilStep(2, 0, 100),)})
        motion = RecoilMotion()
        self.assertEqual(motion.advance(0, True, "ak47", configured, True), (0, 0))
        motion.advance(0, False, "ak47", configured, True)
        motion.advance(0.01, True, "ak47", configured, True)
        self.assertEqual(motion.advance(0.03, True, "ak47", configured, True), (0, 3))
        for weapon, permitted, next_time in (("ak47", False, 0.04), ("m4a1", True, 0.2), ("ak47", True, 1.0)):
            motion.advance(next_time, True, weapon, configured, permitted)
            self.assertEqual(motion.advance(next_time + 0.01, True, weapon, configured, True), (0, 0))
            motion.advance(next_time + 0.02, False, weapon, configured, True)
            motion.advance(next_time + 0.03, True, weapon, configured, True)
        self.assertEqual(motion.advance(2.0, True, "knife", configured, True), (0, 0))

    def test_frame_gate_rejects_remote_dead_old_and_unknown_weapon(self) -> None:
        """Не применяет профили к чужому игроку, старым кадрам или неподходящему оружию."""
        configured = settings()
        data = dict(player_data(), m_weapons={"m_active": "weapon_ak47"}, m_health=100)
        frame = Frame.parse(json.dumps({"m_players": [data]}))
        now = time.monotonic()
        self.assertEqual(controlled_weapon(frame, configured, now, now), "ak47")
        for changed in (dict(data, m_is_local=False), dict(data, m_is_dead=True), dict(data, m_health=0),
                        dict(data, m_team=1), dict(data, m_weapons={"m_active": "knife"}),
                        dict(data, m_weapons=None), dict(data, m_weapons={"m_active": 12})):
            rejected = Frame.parse(json.dumps({"m_players": [changed]}))
            self.assertEqual(controlled_weapon(rejected, configured, now, now), "")
        self.assertEqual(controlled_weapon(frame, configured, now - 0.251, now), "")
        self.assertEqual(controlled_weapon(frame, configured, now + 1, now), "")
        self.assertEqual(controlled_weapon(frame, replace(configured, ws_url="ws://192.168.1.2:22006"), now, now), "")
        self.assertEqual(controlled_weapon(replace(frame, status="menu"), configured, now, now), "")
        for url in ("ws://localhost:22006", "ws://127.0.0.1:22006", "ws://[::1]:22006"):
            self.assertTrue(local_source(url))
        self.assertFalse(local_source("ws://localhost.example:22006"))

    def test_focus_gate_fails_closed_for_locked_or_other_windows(self) -> None:
        """Разрешает ввод только при явной разблокировке и активной CS2."""
        active: dict[str, object] = {"class": "cs2", "mapped": True, "hidden": False}
        with patch("perspective.recoil_linux.query", side_effect=[{"locked": False}, active]):
            self.assertTrue(game_focused())
        for locked, client in ((True, active), (None, active), (False, dict(active, hidden=True)),
                               (False, dict(active, **{"class": "terminal"}))):
            with patch("perspective.recoil_linux.query", side_effect=[{"locked": locked}, client]):
                self.assertFalse(game_focused())

    def test_bluetooth_resolution_follows_mouse_not_event_number(self) -> None:
        """Находит только сохранённую Bluetooth-мышь после изменения event-узла."""
        identity = "bluetooth:11:22:33:44:55:66"
        with patch("perspective.mouse_linux.mouse_choices", return_value=(MouseDevice("MX", "/dev/input/event42", identity),)):
            self.assertEqual(mouse_path(identity), "/dev/input/event42")
            with self.assertRaises(MouseError):
                mouse_path("bluetooth:22:22:33:44:55:66")

    def test_uinput_packets_have_only_relative_movement_and_sync(self) -> None:
        """Проверяет пакет ядра и отсутствие синтетических кнопок или кликов."""
        from perspective.mouse_linux import EVENT
        mouse = LinuxMouse.__new__(LinuxMouse)
        mouse.output_fd = 9
        packets: list[bytes] = []

        def write(fd: int, data: bytes) -> int:
            """Принимает бинарный пакет вместо настоящего устройства."""
            self.assertEqual(fd, 9)
            packets.append(data)
            return len(data)

        with patch("perspective.mouse_linux.os.write", side_effect=write):
            mouse.move(-2, 3)
            mouse.move(0, 0)
        self.assertEqual(len(packets), 1)
        self.assertEqual(list(EVENT.iter_unpack(packets[0])), [(0, 0, 2, 0, -2), (0, 0, 2, 1, 3), (0, 0, 0, 0, 0)])
