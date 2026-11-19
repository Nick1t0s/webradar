"""Настройки автонаводки прицела."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from .scene import FrameError, number, object_fields


class AimSettingsError(ValueError):
    """Ошибка валидации настроек автонаводки."""


@dataclass(frozen=True)
class AimSettings:
    """Неизменяемые проверенные настройки автонаводки."""

    enabled: bool = False
    mouse_device: str = ""
    sensitivity: float = 1.0
    button: Literal["BTN_SIDE", "BTN_EXTRA"] = "BTN_SIDE"
    radius_percent: float = 10.0
    target: Literal["head", "body"] = "head"
    include_teammates: bool = False

    def __post_init__(self) -> None:
        """Проверяет типы, диапазоны и допустимые значения параметров."""
        if type(self.enabled) is not bool:
            raise AimSettingsError("enabled: требуется логическое значение (bool)")
        if not isinstance(self.mouse_device, str):
            raise AimSettingsError("mouse_device: требуется строка")
        if self.enabled and not self.mouse_device:
            raise AimSettingsError("enabled требует заданного mouse_device")
        if self.mouse_device:
            bluetooth = re.fullmatch(r"bluetooth:(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", self.mouse_device)
            if bluetooth is None and (not self.mouse_device.startswith("/dev/input/") or ".." in self.mouse_device.split("/")):
                raise AimSettingsError("mouse_device: нужен путь внутри /dev/input или bluetooth:адрес")

        try:
            sens = number(self.sensitivity)
        except FrameError as exc:
            raise AimSettingsError("sensitivity: требуется конечное число") from exc
        if not 0 < sens <= 100:
            raise AimSettingsError("sensitivity: число в диапазоне (0, 100]")

        if self.button not in ("BTN_SIDE", "BTN_EXTRA"):
            raise AimSettingsError("button: допустимы только 'BTN_SIDE' или 'BTN_EXTRA'")

        try:
            rad = number(self.radius_percent)
        except FrameError as exc:
            raise AimSettingsError("radius_percent: требуется конечное число") from exc
        if not 1.0 <= rad <= 50.0:
            raise AimSettingsError("radius_percent: число от 1 до 50 (% от высоты)")

        if self.target not in ("head", "body"):
            raise AimSettingsError("target: допустимы только 'head' или 'body'")

        if type(self.include_teammates) is not bool:
            raise AimSettingsError("include_teammates: требуется логическое значение (bool)")

    @classmethod
    def parse(cls, raw: object) -> AimSettings:
        """Разбирает настройки автонаводки из словаря с проверкой полей."""
        try:
            fields = object_fields(raw)
        except FrameError as exc:
            raise AimSettingsError("Ожидался объект настроек aim") from exc
        allowed_keys = set(cls.__dataclass_fields__)
        unknown = set(fields) - allowed_keys
        if unknown:
            raise AimSettingsError(f"Неизвестные ключи в aim: {', '.join(sorted(unknown))}")

        enabled_raw = fields.get("enabled", False)
        if type(enabled_raw) is not bool:
            raise AimSettingsError("enabled: требуется логическое значение (bool)")

        device_raw = fields.get("mouse_device", "")
        if not isinstance(device_raw, str):
            raise AimSettingsError("mouse_device: требуется строка")

        sens_val = fields.get("sensitivity", 1.0)
        try:
            sens_num = number(sens_val)
        except FrameError as exc:
            raise AimSettingsError("sensitivity: требуется конечное число") from exc

        btn_raw = fields.get("button", "BTN_SIDE")
        if btn_raw not in ("BTN_SIDE", "BTN_EXTRA"):
            raise AimSettingsError("button: допустимы только 'BTN_SIDE' или 'BTN_EXTRA'")

        radius_val = fields.get("radius_percent", 10.0)
        try:
            radius_num = number(radius_val)
        except FrameError as exc:
            raise AimSettingsError("radius_percent: требуется конечное число") from exc

        target_raw = fields.get("target", "head")
        if target_raw not in ("head", "body"):
            raise AimSettingsError("target: допустимы только 'head' или 'body'")

        include_teammates_raw = fields.get("include_teammates", False)
        if type(include_teammates_raw) is not bool:
            raise AimSettingsError("include_teammates: требуется логическое значение (bool)")

        return cls(
            enabled=enabled_raw,
            mouse_device=device_raw,
            sensitivity=sens_num,
            button=btn_raw,
            radius_percent=radius_num,
            target=target_raw,
            include_teammates=include_teammates_raw,
        )
