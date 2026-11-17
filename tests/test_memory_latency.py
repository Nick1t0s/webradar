"""Linux-память: быстрый proc-путь, резервное чтение и завершение процесса."""
from __future__ import annotations

import ast
from collections.abc import Callable
import ctypes
import errno
import logging
import os
from pathlib import Path
import struct
import subprocess
import sys
from typing import cast
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def linux_memory_class(source: Path | None = None) -> type[object]:
    """Загружает настоящую Linux Memory без запуска серверов и настройки окружения."""
    path = source or ROOT / "helper/linux/src/main.py"
    nodes: list[ast.stmt] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ClassDef):
            continue
        methods = {method.name for method in node.body if isinstance(method, ast.FunctionDef)}
        if node.name in ("_MemoryPrimitives", "_IOVec") or (node.name == "Memory" and "_read_process_vm" in methods):
            nodes.append(node)
    namespace: dict[str, object] = {"ctypes": ctypes, "errno": errno, "os": os,
        "struct": struct, "Path": Path, "log": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return cast(type[object], namespace["Memory"])


def read_memory(memory: object, address: int, size: int) -> bytes:
    """Вызывает исходный метод чтения у динамически загруженного объекта."""
    read = cast(Callable[[int, int], bytes], getattr(memory, "_read"))
    return read(address, size)


def open_memory(memory: object, pid: int) -> bool:
    """Открывает тестовый процесс штатным способом helper."""
    open_process = cast(Callable[[int], bool], getattr(memory, "open"))
    return open_process(pid)


def close_memory(memory: object) -> None:
    """Освобождает proc-дескриптор тестового объекта."""
    close = cast(Callable[[], None], getattr(memory, "close"))
    close()


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux /proc memory tests")
class MemoryLatencyTests(unittest.TestCase):
    """Проверяет исходные методы на настоящей памяти и управляемых ошибках ядра."""

    def setUp(self) -> None:
        """Создаёт объект Memory и собственный живой участок памяти."""
        self.memory = linux_memory_class()()
        self.buffer = ctypes.create_string_buffer(bytes(range(256)))
        self.address = ctypes.addressof(self.buffer)
        self.assertTrue(open_memory(self.memory, os.getpid()))

    def tearDown(self) -> None:
        """Закрывает созданный только этим тестом дескриптор."""
        close_memory(self.memory)

    def test_proc_descriptor_is_preferred_and_every_read_sees_current_bytes(self) -> None:
        """Читает через proc без ctypes-вызова и не кэширует изменяющуюся память."""
        self.assertIsNotNone(getattr(self.memory, "_mem_fd"))
        with patch.object(self.memory, "_read_process_vm", side_effect=AssertionError("unexpected vm read")):
            for size in (4, 8, 256):
                self.assertEqual(read_memory(self.memory, self.address, size), bytes(range(size)))
            self.buffer[0] = b"X"
            self.assertEqual(read_memory(self.memory, self.address, 4), b"X\x01\x02\x03")

    def test_vm_reader_is_used_when_proc_cannot_be_opened(self) -> None:
        """Сохраняет резервный process_vm_readv без доступа к proc-файлу."""
        close_memory(self.memory)
        denied = PermissionError(errno.EACCES, "proc access denied")
        with patch("os.open", side_effect=denied):
            self.assertTrue(open_memory(self.memory, os.getpid()))
            self.assertIsNone(getattr(self.memory, "_mem_fd"))
            with patch.object(self.memory, "_read_mem_file", side_effect=AssertionError("unexpected proc read")):
                self.assertEqual(read_memory(self.memory, self.address, 8), bytes(range(8)))

    def test_proc_reader_remains_available_without_vm_function(self) -> None:
        """Работает при недоступном process_vm_readv."""
        setattr(self.memory, "_process_vm_readv", None)
        self.assertEqual(read_memory(self.memory, self.address, 4), bytes(range(4)))

    def test_short_reads_and_unmapped_addresses_are_zero_padded(self) -> None:
        """Сохраняет размер результата для частично доступной или отсутствующей области."""
        with patch("os.pread", return_value=b"ab"):
            self.assertEqual(read_memory(self.memory, self.address, 4), b"ab\x00\x00")
        for error in (errno.EIO, errno.EINVAL):
            with self.subTest(error=error), patch("os.pread", side_effect=OSError(error, "invalid range")):
                self.assertEqual(read_memory(self.memory, self.address, 4), b"\x00" * 4)
        self.assertEqual(read_memory(self.memory, 1, 4), b"\x00" * 4)

    def test_permissions_and_process_loss_are_not_hidden_by_zero_padding(self) -> None:
        """Передаёт отказ доступа и завершение процесса существующему watchdog."""
        for error in (errno.EPERM, errno.EACCES):
            with self.subTest(error=error), patch("os.pread", side_effect=OSError(error, "denied")):
                with self.assertRaises(PermissionError):
                    read_memory(self.memory, self.address, 4)
        for outcome in (b"", OSError(errno.ESRCH, "process gone")):
            with self.subTest(outcome=outcome):
                options = {"side_effect": outcome} if isinstance(outcome, OSError) else {"return_value": outcome}
                with patch("os.pread", **options), self.assertRaises(OSError) as raised:
                    read_memory(self.memory, self.address, 4)
                self.assertEqual(raised.exception.errno, errno.ESRCH)

    def test_null_address_zero_size_and_closed_process_keep_existing_contract(self) -> None:
        """Различает пустой запрос, нулевой указатель и закрытый процесс."""
        self.assertEqual(read_memory(self.memory, self.address, 0), b"")
        self.assertEqual(read_memory(self.memory, 0, 4), b"\x00" * 4)
        close_memory(self.memory)
        self.assertEqual(read_memory(self.memory, 0, 4), b"\x00" * 4)
        with self.assertRaises(OSError) as raised:
            read_memory(self.memory, self.address, 4)
        self.assertEqual(raised.exception.errno, errno.ESRCH)

    def test_actual_exited_child_produces_process_loss_instead_of_a_zero_frame(self) -> None:
        """Распознаёт EOF настоящего proc-дескриптора после завершения дочернего процесса."""
        child_code = ("import ctypes,sys; buffer=ctypes.create_string_buffer(b'child'); "
                      "print(ctypes.addressof(buffer),flush=True); sys.stdin.readline()")
        with subprocess.Popen([sys.executable, "-u", "-c", child_code], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True) as child:
            assert child.stdout is not None
            address = int(child.stdout.readline())
            memory = linux_memory_class()()
            try:
                self.assertTrue(open_memory(memory, child.pid))
                self.assertEqual(read_memory(memory, address, 5), b"child")
                child.communicate(input="\n", timeout=3)
                self.assertEqual(child.returncode, 0)
                with self.assertRaises(OSError) as raised:
                    read_memory(memory, address, 5)
                self.assertEqual(raised.exception.errno, errno.ESRCH)
            finally:
                close_memory(memory)
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
