"""Проверки чтения угла отдачи и компенсации обеих осей без физического ввода."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import math
import unittest

from pydantic import ValidationError

from helper.linux.src.camera_telemetry import RecoilOffsets, read_recoil
from perspective.recoil import RecoilFeedback, RecoilSample, RecoilSettings
from perspective.scene import Frame
from tests.test_perspective import FakeMemory, player_data


class FeedbackTests(unittest.TestCase):
    """Проверяет направление, масштаб и прерывание обратной связи по углу."""

    def test_vertical_and_horizontal_reversals_follow_samples_not_time(self) -> None:
        """Компенсирует подъём и смену горизонтального направления без временного паттерна."""
        settings = RecoilSettings(mode="feedback", sensitivity=1.3)
        motion = RecoilFeedback()
        motion.advance(1, False, RecoilSample(0, 0, 0), 1, settings, True)
        readings = (RecoilSample(-0.22, -0.11, 1), RecoilSample(-0.66, -0.33, 2), RecoilSample(-1.1, 0.22, 3))
        total_x = total_y = 0
        for index, sample in enumerate(readings, 1):
            now = 1 + index * 0.02
            x, y = motion.advance(now, True, sample, now, settings, True)
            self.assertGreater(y, 0)
            if index < 3:
                self.assertLess(x, 0)
            else:
                self.assertGreater(x, 0)
            total_x, total_y = total_x + x, total_y + y
            self.assertEqual(motion.advance(now + 0.005, True, sample, now, settings, True), (0, 0))
        factor = 2 / (0.022 * settings.sensitivity)
        self.assertAlmostEqual(total_x, readings[-1].yaw * factor, delta=1)
        self.assertAlmostEqual(total_y, -readings[-1].pitch * factor, delta=1)

    def test_no_shots_and_counter_reset_do_not_pull_the_mouse(self) -> None:
        """Не создаёт движения от восстановления угла без выстрелов и сбрасывает старую очередь."""
        settings, motion = RecoilSettings(mode="feedback"), RecoilFeedback()
        motion.advance(1, False, RecoilSample(-1, 1, 0), 1, settings, True)
        self.assertEqual(motion.advance(1.01, True, RecoilSample(-0.5, 0.5, 0), 1.01, settings, True), (0, 0))
        dx, dy = motion.advance(1.02, True, RecoilSample(-0.7, 0.7, 1), 1.02, settings, True)
        self.assertGreater(dx, 0)
        self.assertGreater(dy, 0)
        self.assertEqual(motion.advance(1.03, True, RecoilSample(0, 0, 0), 1.03, settings, True), (0, 0))

    def test_pending_movement_is_bounded_and_interrupt_requires_release(self) -> None:
        """Дробит большой корректирующий шаг и отменяет остаток при прерывании."""
        settings, motion = RecoilSettings(mode="feedback"), RecoilFeedback()
        idle, shot = RecoilSample(0, 0, 0), RecoilSample(-2.2, 0, 1)
        motion.advance(1, False, idle, 1, settings, True)
        self.assertEqual(motion.advance(1.01, True, shot, 1.01, settings, True), (0, 80))
        self.assertEqual(motion.advance(1.02, True, shot, 1.01, settings, False), (0, 0))
        self.assertEqual(motion.advance(1.03, True, shot, 1.01, settings, True), (0, 0))
        motion.advance(1.04, False, idle, 1.04, settings, True)
        x, y = motion.advance(1.05, True, shot, 1.05, settings, True)
        self.assertEqual((x, y), (0, 80))
        self.assertEqual(motion.advance(2, True, shot, 1.05, settings, True), (0, 0))
        self.assertFalse(motion.active)

    def test_missing_samples_and_implausible_jumps_stop_without_profile_fallback(self) -> None:
        """Не двигает мышь без телеметрии и не воспроизводит скачок повреждённых углов."""
        settings, motion = RecoilSettings(mode="feedback"), RecoilFeedback()
        idle = RecoilSample(0, 0, 0)
        motion.advance(1, False, idle, 1, settings, True)
        self.assertEqual(motion.advance(1.01, True, None, 1.01, settings, True), (0, 0))
        self.assertEqual(motion.advance(1.02, True, idle, 1.02, settings, True), (0, 0))
        motion.advance(1.03, False, idle, 1.03, settings, True)
        self.assertEqual(motion.advance(1.04, True, RecoilSample(45, 45, 1), 1.04, settings, True), (0, 0))
        self.assertFalse(motion.active)

    def test_stronger_profiles_and_feedback_gain_have_distinct_limits(self) -> None:
        """Сохраняет прежние настройки и допускает усиление профиля выше двух."""
        self.assertEqual(RecoilSettings(strength=10).strength, 10)
        with self.assertRaises(ValidationError):
            RecoilSettings(mode="feedback", strength=3)
        old = asdict(RecoilSettings())
        del old["mode"]
        self.assertEqual(RecoilSettings.parse(old).mode, "profile")

    def test_invalid_optional_recoil_does_not_discard_radar_frame(self) -> None:
        """Отделяет ошибки новой телеметрии от существующего кадра игроков."""
        data = dict(player_data(), m_recoil={"pitch": -1, "yaw": 0.2, "shots": 3})
        frame = Frame.parse(json.dumps({"m_players": [data]}))
        self.assertEqual(frame.players[0].recoil, RecoilSample(-1, 0.2, 3))
        invalid: tuple[object, ...] = ({"pitch": math.nan, "yaw": 0, "shots": 1},
                                      {"pitch": 1, "yaw": 0, "shots": True},
                                      {"pitch": "1", "yaw": 0, "shots": 1}, None, [])
        for value in invalid:
            frame = Frame.parse(json.dumps({"m_players": [dict(data, m_recoil=value)]}))
            self.assertEqual(len(frame.players), 1)
            self.assertIsNone(frame.players[0].recoil)


class TelemetryTests(unittest.TestCase):
    """Проверяет чтение schema-полей через тот же интерфейс памяти, что использует helper."""

    def test_predictable_and_unpredictable_angles_are_summed(self) -> None:
        """Передаёт обе компоненты и проверенный счётчик выстрелов в одном значении."""
        pawn, service = 10000, 20000
        offsets = RecoilOffsets(100, 80, 164, 200)
        memory = FakeMemory()
        memory.values = {pawn + 100: service, pawn + 200: 3,
                         service + 80: -2, service + 84: 0.3, service + 88: 0,
                         service + 164: -0.1, service + 168: -0.2, service + 172: 0}
        result = read_recoil(memory, pawn, offsets)["m_recoil"]
        assert result is not None
        self.assertAlmostEqual(result["pitch"], -2.1)
        self.assertAlmostEqual(result["yaw"], 0.1)
        self.assertEqual(result["shots"], 3)
        self.assertIsNone(read_recoil(memory, pawn, replace(offsets, predictable=0))["m_recoil"])
        memory.values[service + 80] = math.nan
        self.assertIsNone(read_recoil(memory, pawn, offsets)["m_recoil"])

    def test_failed_memory_reads_remain_optional(self) -> None:
        """Возвращает отсутствие телеметрии при недоступной памяти вместо ложных углов."""
        class UnreadableMemory(FakeMemory):
            def u32(self, address: int) -> int:
                """Имитирует потерю доступа к процессу игры."""
                raise OSError("process unavailable")

        self.assertEqual(read_recoil(UnreadableMemory(), 10000, RecoilOffsets(100, 80, 164, 200)), {"m_recoil": None})
