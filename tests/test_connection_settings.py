"""Проверки источника данных и переключения независимых WebSocket-соединений."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

from perspective.config import Settings, SettingsError
from perspective.scene import Frame
from tests.test_perspective import player_data, settings


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

    def test_legacy_recoil_migration_and_unknown_keys_rejection(self) -> None:
        """Принимает старый ключ recoil с любым значением, игнорирует его при сохранении и отклоняет другие неизвестные ключи."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            base_dict = asdict(settings())
            legacy_values: tuple[object, ...] = (
                {"enabled": True, "mouse_device": "/dev/input/event0", "sensitivity": 2.5, "strength": 1.0,
                 "toggle_button": "BTN_SIDE", "mode": "profile"},
                {},
                None,
                "disabled",
                123,
                False,
                [1, 2, 3],
            )
            for value in legacy_values:
                with self.subTest(legacy_value=value):
                    payload = dict(base_dict, recoil=value)
                    parsed = Settings.parse(payload)
                    self.assertFalse(hasattr(parsed, "recoil"))
                    parsed.save(path)
                    saved_raw: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
                    self.assertNotIn("recoil", saved_raw)
            with self.assertRaises(SettingsError):
                Settings.parse(dict(base_dict, unknown_key="invalid"))
            with self.assertRaises(SettingsError):
                Settings.parse(dict(base_dict, recoil={"enabled": True}, unknown_key="invalid"))

    def test_legacy_helper_frame_with_m_recoil_is_accepted(self) -> None:
        """Кадр старого helper с переданным полем m_recoil читается без использования поля."""
        player = player_data()
        player["m_recoil"] = {"pitch": -0.5, "yaw": 0.1, "shots": 2}
        player["m_weapons"] = {"m_active": "weapon_ak47"}
        frame = Frame.parse(json.dumps({"m_players": [player]}))
        self.assertEqual(len(frame.players), 1)
        self.assertFalse(hasattr(frame.players[0], "recoil"))
        self.assertFalse(hasattr(frame.players[0], "active_weapon"))
