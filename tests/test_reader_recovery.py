"""Восстановление обоих helper на настоящем цикле с детерминированными кадрами."""
from __future__ import annotations

import ast
import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import cast
import unittest


ROOT = Path(__file__).resolve().parent.parent


def reader_functions(platform: str, namespace: dict[str, object]) -> None:
    """Загружает реальные методы без запуска чтения памяти или сетевых служб."""
    path = ROOT / "helper" / platform / "src" / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_async":
            nodes.append(node)
        if isinstance(node, ast.ClassDef) and node.name == "CS2Reader":
            nodes.extend(method for method in node.body
                         if isinstance(method, ast.FunctionDef) and method.name == "_find_lpc_fallback")
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in
                ("READER_RECOVERY_SEC", "OFFSET_RECHECK_SEC") for target in node.targets):
            nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)


class MemoryFixture:
    """Изображает процесс игры и контроллеры без доступа к реальной памяти."""

    def __init__(self) -> None:
        """Создаёт доступный процесс и карту значений контроллеров."""
        self.handle = False
        self.pid = 0
        self.live_pid = 111
        self.closed = 0
        self.values: dict[int, int] = {1010: 1, 1020: 0, 2010: 1, 2020: 3}
        self.unreadable = False

    def find_pid(self, process: str) -> int:
        """Возвращает текущую идентичность тестового процесса."""
        return self.live_pid

    def open(self, pid: int) -> bool:
        """Запоминает подключение к найденному процессу."""
        self.pid, self.handle = pid, True
        return True

    def close(self) -> None:
        """Освобождает тестовый дескриптор."""
        self.closed += 1
        self.handle = False

    def u32(self, address: int) -> int:
        """Читает тестовое значение либо изображает исчезнувшую область памяти."""
        if self.unreadable and address < 2000:
            raise OSError("controller allocation released")
        return self.values.get(address, 0)

    def bool8(self, address: int) -> bool:
        """Читает тестовый локальный флаг."""
        return bool(self.u32(address))


class ControllerFixture:
    """Изображает ложный кэш и настоящий контроллер после загрузки карты."""

    def __init__(self) -> None:
        """Подготавливает ложный контроллер с нулевой командой."""
        self.mem = MemoryFixture()
        self.steam_ids: set[int] = set()
        self._lpc_fallback = 1000
        self._lpc_via_steam = False
        self._last_lpc_scan = 100.0
        self.entity_system = 1
        self.old_class = ""

    def _off(self, classname: str, field: str) -> int:
        """Возвращает смещения двух проверяемых полей."""
        return {"m_bIsLocalPlayerController": 10, "m_iTeamNum": 20}.get(field, 0)

    def _nv_off(self, field: str) -> int:
        """Изображает отсутствие дополнительных schema-полей."""
        return 0

    def _class_name(self, entity: int) -> str:
        """Распознаёт только настоящий контроллер, если не задан переход команды."""
        return "CCSPlayerController" if entity == 2000 else self.old_class

    def _entity_ptr(self, index: int, cache: dict[int, int]) -> int:
        """Публикует настоящий контроллер в первом слоте сущностей."""
        return 2000 if index == 1 else 0


class ReaderFixture:
    """Изображает застрявший reader, исправляемый повторным setup."""

    def __init__(self, simulation: ReaderSimulation) -> None:
        """Запоминает время создания отдельного экземпляра."""
        self.simulation = simulation
        self.generation = len(simulation.created)
        simulation.created.append(simulation.now)

    def setup(self) -> bool:
        """Завершает тестовую инициализацию без настоящей игры."""
        return True

    def collect(self) -> dict[str, object] | None:
        """Отдаёт кадры согласно сценарию перехода из загрузки в матч."""
        simulation = self.simulation
        window = simulation.valid_window
        if ((simulation.recover_on_rebuild and self.generation > 0)
                or (window is not None and window[0] <= simulation.now < window[1])):
            return {"m_map": "invalid", "m_players": [{}]}
        return None


class ReaderSimulation:
    """Выполняет исходный async-цикл с управляемыми часами и reader."""

    def __init__(self, platform: str, step: float = 1.0) -> None:
        """Подготавливает зависимости без файлов, потоков и сетевых соединений."""
        self.now = 0.0
        self.step = step
        self.limit = 100.0
        self.created: list[float] = []
        self.offset_fetches: list[bool] = []
        self.statuses: list[tuple[float, str]] = []
        self.frames: list[str] = []
        self.memory = MemoryFixture()
        self.recover_on_rebuild = False
        self.valid_window: tuple[float, float] | None = None
        self.refresh_at: float | None = None
        self.namespace: dict[str, object] = {
            "asyncio": SimpleNamespace(get_event_loop=lambda: self, sleep=self.sleep),
            "time": SimpleNamespace(monotonic=lambda: self.now, time=lambda: self.now + 1000),
            "websockets": SimpleNamespace(serve=self.serve), "json": json,
            "log": logging.getLogger(__name__), "_refresh_requested": False,
            "load_config": lambda: {}, "_resolve_steam_id": lambda config: "",
            "_ensure_firewall_rules": lambda: None, "load_offsets": self.load_offsets,
            "_client_dll_mtime": lambda pid=None: 0.0, "Memory": lambda: self.memory,
            "CS2Reader": lambda mem, offsets, steam_id: ReaderFixture(self),
            "cs2_process_names": lambda: ["cs2"], "_ws_handler": lambda: None,
            "WS_PORT": 22006, "_static_path": lambda: None, "_maps_cache_path": lambda: Path("unused"),
            "MapExtractor": lambda path: SimpleNamespace(cs2_dir=None),
            "IS_LINUX": False, "IS_WINDOWS": platform == "windows", "POLL_INTERVAL": 1 / 60,
            "_broadcast_status": self.broadcast_status, "_broadcast": self.broadcast,
            "_set_status": lambda state, detail: self.statuses.append((self.now, state)),
            "_payload_status": lambda data: ("ok", "test frame"), "_status": {"state": "ok", "detail": ""},
            "_json_sanitize": lambda data: data,
        }
        reader_functions(platform, self.namespace)

    @asynccontextmanager
    async def serve(self, handler: object, host: object, port: int) -> AsyncIterator[None]:
        """Изображает срок жизни сервера без открытия сокета."""
        yield None

    def load_offsets(self, force: bool = False) -> dict[str, object]:
        """Учитывает обращения к обновлению offsets."""
        self.offset_fetches.append(force)
        return {}

    async def run_in_executor(self, executor: object, operation: Callable[[], object]) -> object:
        """Выполняет производственную операцию немедленно в тестовом потоке."""
        return operation()

    async def broadcast_status(self) -> None:
        """Принимает диагностическое сообщение без сети."""
        return None

    async def broadcast(self, frame: str) -> None:
        """Учитывает успешный кадр, завершая сценарий восстановления."""
        self.frames.append(frame)
        if self.recover_on_rebuild:
            raise asyncio.CancelledError()

    async def sleep(self, delay: float) -> None:
        """Продвигает монотонные часы без настоящего ожидания."""
        self.now += max(self.step, delay)
        if self.refresh_at is not None and self.now >= self.refresh_at:
            self.namespace["_refresh_requested"] = True
            self.refresh_at = None
        if self.now > self.limit:
            raise asyncio.CancelledError()

    def run(self) -> None:
        """Запускает настоящий основной цикл до предусмотренного завершения теста."""
        run = cast(Callable[[], Coroutine[object, object, None]], self.namespace["_run_async"])
        try:
            asyncio.run(run())
        except asyncio.CancelledError:
            pass


class ReaderRecoveryTests(unittest.TestCase):
    """Проверяет восстановление с первого запуска и ограничение повторных setup."""

    def test_initial_stuck_reader_recovers_without_offset_download_at_any_frame_rate(self) -> None:
        """Переинициализирует reader по времени, даже если ещё не было ни одного кадра."""
        for platform in ("linux", "windows"):
            for step in (0.1, 5.0):
                with self.subTest(platform=platform, step=step):
                    simulation = ReaderSimulation(platform, step)
                    simulation.recover_on_rebuild = True
                    simulation.run()
                    self.assertEqual(len(simulation.created), 2)
                    self.assertGreaterEqual(simulation.created[1], 30)
                    self.assertLessEqual(simulation.created[1], 30 + 2 * step)
                    self.assertEqual(simulation.offset_fetches, [False])
                    self.assertEqual(len(simulation.frames), 1)
                    self.assertIn("loading", [state for _, state in simulation.statuses])

    def test_real_menu_retries_are_bounded_and_do_not_fetch_offsets(self) -> None:
        """Не превращает длительное меню в непрерывное сканирование или скачивание."""
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform):
                simulation = ReaderSimulation(platform)
                simulation.run()
                self.assertEqual(len(simulation.created), 4)
                self.assertTrue(all(later - earlier >= 30 for earlier, later in
                                    zip(simulation.created, simulation.created[1:])))
                self.assertEqual(simulation.offset_fetches, [False])

    def test_successful_frames_and_manual_refresh_restart_missing_data_deadline(self) -> None:
        """Отсчитывает новые 30 секунд после данных или явной переинициализации."""
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform, reset="frame"):
                simulation = ReaderSimulation(platform)
                simulation.valid_window = (20, 21)
                simulation.limit = 55
                simulation.run()
                self.assertEqual(simulation.created, [0, 52])
                self.assertEqual(len(simulation.frames), 1)
            with self.subTest(platform=platform, reset="manual"):
                simulation = ReaderSimulation(platform)
                simulation.refresh_at = 20
                simulation.limit = 55
                simulation.run()
                self.assertEqual(simulation.created, [0, 20, 51])
                self.assertEqual(simulation.offset_fetches, [False, True])

    def test_flag_cache_discards_bogus_pointer_and_preserves_known_controller_during_team_change(self) -> None:
        """Отбрасывает ложный адрес, сохраняя настоящий контроллер при смене команды."""
        for platform in ("linux", "windows"):
            for unreadable in (False, True):
                with self.subTest(platform=platform, unreadable=unreadable):
                    clock = SimpleNamespace(monotonic=lambda: 100.5)
                    namespace: dict[str, object] = {"time": clock, "log": logging.getLogger(__name__),
                        "_cls_eq": lambda actual, *names: actual in names}
                    reader_functions(platform, namespace)
                    find = cast(Callable[[ControllerFixture], int], namespace["_find_lpc_fallback"])
                    fixture = ControllerFixture()
                    fixture.mem.unreadable = unreadable
                    self.assertEqual(find(fixture), 0)
                    self.assertEqual(fixture._lpc_fallback, 0)
                    clock.monotonic = lambda: 103.0
                    self.assertEqual(find(fixture), 2000)
                    self.assertEqual(fixture._lpc_fallback, 2000)
                    known = ControllerFixture()
                    known.old_class = "CCSPlayerController"
                    self.assertEqual(find(known), 1000)
                    self.assertEqual(known._lpc_fallback, 1000)
                    known.mem.values[1010] = 0
                    clock.monotonic = lambda: 100.5
                    self.assertEqual(find(known), 0)
                    self.assertEqual(known._lpc_fallback, 0)
