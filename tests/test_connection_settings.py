"""Проверки источника данных и переключения независимых WebSocket-соединений."""
from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest

from perspective.config import Settings, SettingsError
from tests.test_perspective import settings


class ConnectionSettingsTests(unittest.TestCase):
    """Проверяет адреса до соединения и сохранение выбранного источника."""

    def test_invalid_endpoints_are_rejected_by_parser_and_constructor(self) -> None:
        """Запрещает ошибки порта, пароли и неподходящие протоколы."""
        original = settings()
        for url in ("http://host:5173", "ws://", "ws://host:99999/x", "ws://host:invalid/x",
                    "ws://host:0/x", "ws://host/a b", "ws://user:pass@host/x", "ws://host/x#fragment"):
            with self.subTest(url=url):
                with self.assertRaises(SettingsError):
                    Settings.parse(dict(asdict(original), ws_url=url))
                with self.assertRaises(SettingsError):
                    replace(original, ws_url=url)

    def test_remote_and_ipv6_sources_survive_save_and_reload(self) -> None:
        """Сохраняет адрес helper независимо от HTTP сайта и выбранного игрока."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for url in ("ws://192.168.1.20:22006/cs2_webradar", "ws://[::1]:22006/cs2_webradar",
                        "wss://helper.example/cs2_webradar"):
                configured = replace(settings(), ws_url=url)
                configured.save(path)
                self.assertEqual(Settings.load(path).ws_url, url)
