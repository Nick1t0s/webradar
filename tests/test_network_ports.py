"""Проверки независимого HTTP-сервера и правил доступа к WebSocket без CS2."""
from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
import http.client
import http.server
import logging
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from typing import cast
import unittest


ROOT = Path(__file__).resolve().parent.parent


def helper_functions(platform: str) -> dict[str, object]:
    """Загружает серверные функции без запуска платформенного чтения памяти."""
    path = ROOT / "helper" / platform / "src" / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {"_hostname", "_host_ok", "_ws_origin_ok", "_is_loopback", "_ws_can_control", "_start_http"}
    functions: list[ast.stmt] = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace: dict[str, object] = {
        "Path": Path, "http": http, "threading": threading, "sys": sys,
        "HTTP_PORT": 0, "WS_PORT": 22006, "log": logging.getLogger(__name__),
        "load_config": lambda: {"allowed_hosts": ["radar.example.test"]},
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class NetworkPortsTests(unittest.TestCase):
    """Проверяет обе реализации helper на настоящем локальном HTTP-сокете."""

    def test_http_serves_site_and_maps_but_rejects_websocket_upgrade(self) -> None:
        """HTTP обслуживает файлы и отклоняет WebSocket без обращения к WS-порту."""
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                static, maps = root / "static", root / "maps"
                static.mkdir()
                (maps / "de_test").mkdir(parents=True)
                (static / "index.html").write_text("radar site", encoding="utf-8")
                (maps / "de_test" / "data.json").write_text('{"scale":1}', encoding="utf-8")
                start = cast(Callable[[str, Path], http.server.HTTPServer], helper_functions(platform)["_start_http"])
                server = start(str(static), maps)
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                try:
                    connection.request("GET", "/")
                    response = connection.getresponse()
                    self.assertEqual((response.status, response.read()), (200, b"radar site"))
                    connection.request("GET", "/data/de_test/data.json")
                    response = connection.getresponse()
                    self.assertEqual((response.status, response.read()), (200, b'{"scale":1}'))
                    connection.request("GET", "/cs2_webradar", headers={
                        "Connection": "Upgrade", "Upgrade": "websocket",
                        "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==", "Sec-WebSocket-Version": "13",
                    })
                    response = connection.getresponse()
                    self.assertEqual(response.status, 426)
                    self.assertIn(b"22006", response.read())
                finally:
                    connection.close()
                    server.shutdown()
                    server.server_close()

    def test_origin_allows_separate_ports_without_trusting_other_sites(self) -> None:
        """Разные порты одного хоста разрешены, чужой Origin и неизвестный Host запрещены."""
        for platform in ("linux", "windows"):
            origin_ok = cast(Callable[[Mapping[str, str]], bool], helper_functions(platform)["_ws_origin_ok"])
            for host in ("localhost", "127.0.0.1", "[::1]", "radar.example.test"):
                with self.subTest(platform=platform, host=host):
                    self.assertTrue(origin_ok({"Host": f"{host}:22006", "Origin": f"http://{host}:5173"}))
                    self.assertFalse(origin_ok({"Host": f"{host}:22006", "Origin": "http://attacker.test:5173"}))
            self.assertTrue(origin_ok({"Host": "192.168.1.5:22006"}))
            self.assertFalse(origin_ok({"Host": "untrusted.example:22006", "Origin": "http://untrusted.example:5173"}))

    def test_remote_connections_cannot_gain_local_control_by_headers(self) -> None:
        """Удалённый клиент не получает локальные команды через подставленный заголовок."""
        for platform in ("linux", "windows"):
            can_control = cast(Callable[[object, Mapping[str, str]], bool], helper_functions(platform)["_ws_can_control"])
            local = SimpleNamespace(remote_address=("127.0.0.1", 44000))
            remote = SimpleNamespace(remote_address=("192.168.1.8", 44000))
            with self.subTest(platform=platform):
                self.assertTrue(can_control(local, {"Host": "localhost:22006"}))
                self.assertFalse(can_control(remote, {"Host": "localhost:22006", "X-Radar-Peer": "127.0.0.1"}))
                self.assertFalse(can_control(local, {"Host": "radar.example.test:22006"}))
                self.assertFalse(can_control(local, {"Host": "localhost:22006", "X-Forwarded-For": "192.168.1.8"}))
