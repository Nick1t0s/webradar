"""Тесты службы автонаводки Linux/Hyprland без реальных устройств ввода."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection, serve

from perspective.aim import AimTarget
from perspective.aim_settings import AimSettings
from perspective.config import Settings
from perspective.connection import Update
from tests.test_perspective import player_data, settings

if sys.platform.startswith("linux"):
    from perspective.aim_linux import AimService, AimSession, owner_status, publish_status
    from perspective.mouse_linux import EVENT, LinuxMouse


@dataclass
class FakeMouse:
    """Имитирует кнопки мыши и накапливает относительные движения."""

    is_held: bool = False
    closed: bool = False
    moves: list[tuple[int, int]] = field(default_factory=list)

    def held(self) -> bool:
        """Возвращает текущее состояние боковой кнопки."""
        return self.is_held

    def move(self, dx: int, dy: int) -> None:
        """Запоминает относительное движение."""
        if dx or dy:
            self.moves.append((dx, dy))

    def close(self) -> None:
        """Помечает мышь закрытой."""
        self.closed = True


@unittest.skipUnless(sys.platform.startswith("linux"), "Управление мышью поддерживает Linux / Hyprland")
class AimServiceTests(unittest.TestCase):
    """Проверяет поведение автонаводки: удержание, отпускание, фокус, устаревание данных и singleton."""

    def wait_for(self, predicate: Callable[[], bool]) -> None:
        """Дожидается выполнения условия с таймаутом."""
        deadline = time.monotonic() + 3
        while not predicate():
            if time.monotonic() > deadline:
                self.fail("Служба не достигла ожидаемого состояния")
            time.sleep(0.005)

    def test_disabled_service_does_not_open_devices(self) -> None:
        """Выключенная служба не открывает устройства и не соединяется."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            cfg = replace(settings(), aim=AimSettings(enabled=False))
            cfg.save(path)
            service = AimService(path)
            with patch("perspective.aim_linux.LinuxMouse") as mock_mouse, \
                    patch("perspective.aim_linux.RadarConnection") as mock_conn:
                service.start()
                time.sleep(0.04)
                service.stop()
                mock_mouse.assert_not_called()
                mock_conn.assert_not_called()

    def test_owner_status_reporting(self) -> None:
        """Проверяет чтение статуса владельца блокировки."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            now = time.monotonic()
            self.assertIn("занят другим процессом", owner_status(path, now))
            publish_status(path, "Автонаводка: Enemy1", now)
            self.assertEqual(owner_status(path, now + 0.1), "Автонаводка: Enemy1")
            # Stale after 2 seconds
            self.assertIn("занят другим процессом", owner_status(path, now + 2.5))

    def test_aim_service_workflow(self) -> None:
        """Проверяет полный цикл: удержание, отпускание, потерю фокуса, просрочку и одно движение на кадр."""
        stopped, silent = Event(), Event()
        fake_mouse = FakeMouse()
        focused_flag = [True]
        aspect_val = [None]

        def get_game_state() -> tuple[bool, float | None]:
            return focused_flag[0], aspect_val[0]

        message = json.dumps({"m_players": [dict(player_data(), m_health=100)]})

        def send(connection: ServerConnection) -> None:
            try:
                while not stopped.wait(0.008):
                    if not silent.is_set():
                        connection.send(message)
            except ConnectionClosed:
                pass

        target_call_count = [0]

        def mock_select_target(frame: object, s: object, aspect: float | None = None) -> AimTarget | None:
            target_call_count[0] += 1
            return AimTarget(identity="enemy_1", name="Enemy1", dx=5, dy=-3)

        with tempfile.TemporaryDirectory() as directory, serve(send, "127.0.0.1", 0) as server:
            path = Path(directory) / "settings.json"
            cfg = replace(
                settings(),
                ws_url=f"ws://127.0.0.1:{server.socket.getsockname()[1]}",
                aim=AimSettings(enabled=True, mouse_device="/dev/input/event999"),
            )
            cfg.save(path)

            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()

            first = AimService(path)
            second = AimService(path)

            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory}), \
                    patch("perspective.aim_linux.select_target", side_effect=mock_select_target), \
                    patch("perspective.aim_linux.LinuxMouse", return_value=fake_mouse) as mouse_ctor, \
                    patch("perspective.aim_linux.game_state", side_effect=get_game_state):
                first.start()
                try:
                    # Initially, button is not held -> should be "Автонаводка: готова"
                    self.wait_for(lambda: "готова" in first.status)

                    # Second service should be blocked by flock
                    second.start()
                    self.wait_for(lambda: "занят другим процессом" in second.status or "готова" in second.status)
                    self.assertEqual(mouse_ctor.call_count, 1)

                    # Now hold button -> target detected and moved
                    fake_mouse.is_held = True
                    self.wait_for(lambda: len(fake_mouse.moves) >= 4)
                    self.wait_for(lambda: "Enemy1" in first.status)
                    self.assertEqual(fake_mouse.moves[:4], [(8, -1), (2, -1), (2, -5), (8, -5)])

                    # Verify one motion per frame: motions count increases smoothly over several updates
                    initial_moves = len(fake_mouse.moves)
                    initial_calls = target_call_count[0]
                    time.sleep(0.04)
                    subsequent_moves = len(fake_mouse.moves)
                    subsequent_calls = target_call_count[0]
                    self.assertGreater(subsequent_moves, initial_moves)
                    self.assertEqual(subsequent_moves - initial_moves, subsequent_calls - initial_calls)

                    # Release button -> immediately stops movement
                    fake_mouse.is_held = False
                    self.wait_for(lambda: "готова" in first.status)
                    stopped_count = len(fake_mouse.moves)
                    time.sleep(0.03)
                    self.assertEqual(len(fake_mouse.moves), stopped_count)

                    # Hold again -> movement resumes
                    fake_mouse.is_held = True
                    self.wait_for(lambda: len(fake_mouse.moves) > stopped_count)

                    # Lose focus while held
                    focused_flag[0] = False
                    self.wait_for(lambda: "ожидание активной CS2" in first.status)
                    focus_lost_moves = len(fake_mouse.moves)
                    time.sleep(0.03)
                    self.assertEqual(len(fake_mouse.moves), focus_lost_moves)

                    # Regain focus while still holding -> MUST require releasing button first!
                    focused_flag[0] = True
                    time.sleep(0.03)
                    self.wait_for(lambda: "отпустите кнопку мыши" in first.status)
                    self.assertEqual(len(fake_mouse.moves), focus_lost_moves, "Движение не должно возобновляться без отпускания")

                    # Release button to re-arm
                    fake_mouse.is_held = False
                    self.wait_for(lambda: "готова" in first.status)

                    # Press again -> movements resume
                    fake_mouse.is_held = True
                    self.wait_for(lambda: len(fake_mouse.moves) > focus_lost_moves)

                    # Stale frames test: pause server transmissions
                    silent.set()
                    self.wait_for(lambda: "ожидание свежих данных" in first.status)
                    stale_moves = len(fake_mouse.moves)
                    time.sleep(0.03)
                    self.assertEqual(len(fake_mouse.moves), stale_moves)

                    # Resume frames while still holding -> latch was cleared, must require release!
                    silent.clear()
                    time.sleep(0.03)
                    self.wait_for(lambda: "отпустите кнопку мыши" in first.status)
                    self.assertEqual(len(fake_mouse.moves), stale_moves)

                    # Release and press again
                    fake_mouse.is_held = False
                    self.wait_for(lambda: "готова" in first.status)
                    fake_mouse.is_held = True
                    self.wait_for(lambda: len(fake_mouse.moves) > stale_moves)

                finally:
                    first.stop()
                    if second.thread.is_alive():
                        second.stop()
                    stopped.set()
                    server.shutdown()
                    thread.join(timeout=2)
            self.assertTrue(fake_mouse.closed)

    def test_move_payload_only_contains_rel_and_syn(self) -> None:
        """Проверяет, что move() генерирует ровно EV_REL (X, Y) и SYN_REPORT, без EV_KEY."""
        writes: list[bytes] = []

        def fake_write(fd: int, data: bytes) -> int:
            writes.append(data)
            return len(data)

        # Create mouse with mocked descriptors
        with patch("perspective.mouse_linux.os.open", side_effect=[100, 101]), \
                patch("perspective.mouse_linux.os.close"), \
                patch("perspective.mouse_linux.device_bits", side_effect=[
                    b"Test Mouse\0",
                    ((1 << 0x110) | (1 << 0x113)).to_bytes(96, "little"),
                    (3).to_bytes(16, "little"),
                ]), \
                patch("perspective.mouse_linux.fcntl.ioctl"), \
                patch("perspective.mouse_linux.os.write", side_effect=fake_write):
            mouse = LinuxMouse("/dev/input/event0", "BTN_SIDE")
            try:
                mouse.move(10, -5)
                self.assertEqual(len(writes), 1)
                payload = writes[0]
                self.assertEqual(len(payload), EVENT.size * 3)
                ev0 = EVENT.unpack_from(payload, 0)
                ev1 = EVENT.unpack_from(payload, EVENT.size)
                ev2 = EVENT.unpack_from(payload, EVENT.size * 2)

                # EV_REL = 2, code 0 (REL_X), value 10
                self.assertEqual((ev0[2], ev0[3], ev0[4]), (2, 0, 10))
                # EV_REL = 2, code 1 (REL_Y), value -5
                self.assertEqual((ev1[2], ev1[3], ev1[4]), (2, 1, -5))
                # EV_SYN = 0, code 0 (SYN_REPORT), value 0
                self.assertEqual((ev2[2], ev2[3], ev2[4]), (0, 0, 0))
            finally:
                mouse.close()

    def test_jitter_reset_and_no_target_tick(self) -> None:
        """Проверяет отсутствие движения без цели и сброс фазы при повторном захвате."""
        stopped = Event()
        fake_mouse = FakeMouse(is_held=True)
        cfg = replace(settings(), aim=AimSettings(enabled=True, mouse_device="/dev/input/event0", sensitivity=1.0))
        target_holder: list[AimTarget | None] = [None]

        with patch("perspective.aim_linux.LinuxMouse", return_value=fake_mouse), \
                patch("perspective.aim_linux.RadarConnection") as mock_conn_cls, \
                patch("perspective.aim_linux.game_state", return_value=(True, None)), \
                patch("perspective.aim_linux.select_target", side_effect=lambda frame, s, asp=None: target_holder[0]):
            mock_conn = mock_conn_cls.return_value
            mock_conn.latest.side_effect = lambda: Update(None, "", time.monotonic())
            session = AimSession(cfg, stopped)
            try:
                # Взводим latched при наличии свежего кадра с отпущенной кнопкой
                fake_mouse.is_held = False
                session.tick()
                fake_mouse.is_held = True

                # 1. Зажата кнопка, но цель не обнаружена -> нет вызовов move
                status = session.tick()
                self.assertEqual(status, "Автонаводка: поиск цели")
                self.assertEqual(len(fake_mouse.moves), 0)

                # 2. Появилась первая цель: fake target (5, -3) -> 2 кадра
                target_holder[0] = AimTarget(identity="enemy_1", name="Enemy1", dx=5, dy=-3)
                session.tick()
                session.tick()
                self.assertEqual(fake_mouse.moves, [(8, -1), (2, -1)])

                # 3. Цель потеряна
                target_holder[0] = None
                status = session.tick()
                self.assertEqual(status, "Автонаводка: поиск цели")
                self.assertEqual(len(fake_mouse.moves), 2)

                # 4. Повторный захват цели -> фаза сброшена в 0, первый шаг снова (+3, +2)
                target_holder[0] = AimTarget(identity="enemy_1", name="Enemy1", dx=5, dy=-3)
                session.tick()
                self.assertEqual(fake_mouse.moves[-1], (8, -1))

                # 5. Смена identity цели -> фаза также сбрасывается в 0
                target_holder[0] = AimTarget(identity="enemy_2", name="Enemy2", dx=5, dy=-3)
                session.tick()
                self.assertEqual(fake_mouse.moves[-1], (8, -1))
            finally:
                session.close()
