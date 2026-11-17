"""Профили компенсации и расчёт относительных движений без доступа к устройствам."""
from __future__ import annotations

from dataclasses import field
import math
import re
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, TypeAdapter, model_validator
from pydantic.dataclasses import dataclass


@dataclass(frozen=True, config=ConfigDict(extra="forbid", allow_inf_nan=False))
class RecoilStep:
    """Задаёт длительность участка и скорость мыши при sensitivity=1."""

    duration: Annotated[float, Field(strict=True, gt=0, le=5)]
    x: Annotated[float, Field(strict=True, ge=-2000, le=2000)]
    y: Annotated[float, Field(strict=True, ge=-2000, le=2000)]


def initial_profiles() -> dict[str, tuple[RecoilStep, ...]]:
    """Возвращает начальные вертикальные профили для ручной калибровки."""
    return {
        "ak47": (RecoilStep(0.1, 0, 0), RecoilStep(0.6, 0, 80), RecoilStep(0.8, 0, 110), RecoilStep(1.5, 0, 50)),
        "m4a1": (RecoilStep(0.1, 0, 0), RecoilStep(0.6, 0, 65), RecoilStep(0.8, 0, 85), RecoilStep(1.5, 0, 40)),
        "m4a1_silencer": (RecoilStep(0.1, 0, 0), RecoilStep(0.6, 0, 55), RecoilStep(0.8, 0, 70), RecoilStep(1.5, 0, 35)),
    }


@dataclass(frozen=True, config=ConfigDict(extra="forbid", allow_inf_nan=False))
class RecoilSettings:
    """Проверяет настройки ввода при загрузке JSON и прямом создании."""

    enabled: Annotated[bool, Field(strict=True)] = False
    mouse_device: Annotated[str, Field(strict=True)] = ""
    sensitivity: Annotated[float, Field(strict=True, ge=0.05, le=20)] = 1.0
    strength: Annotated[float, Field(strict=True, ge=0.1, le=2)] = 1.0
    toggle_button: Literal["BTN_SIDE", "BTN_EXTRA"] = "BTN_SIDE"
    profiles: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")],
                   Annotated[tuple[RecoilStep, ...], Field(min_length=1, max_length=100)]] = field(default_factory=initial_profiles)

    @model_validator(mode="after")
    def validate_profiles(self) -> RecoilSettings:
        """Ограничивает пути устройств и продолжительность одной очереди."""
        if self.enabled and not self.mouse_device:
            raise ValueError("Выберите физическую мышь в /dev/input")
        bluetooth = re.fullmatch(r"bluetooth:(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", self.mouse_device)
        if self.mouse_device and bluetooth is None and (not self.mouse_device.startswith("/dev/input/") or
                                                       ".." in self.mouse_device.split("/")):
            raise ValueError("mouse_device: нужен путь внутри /dev/input или bluetooth:адрес")
        if not 1 <= len(self.profiles) <= 64:
            raise ValueError("Нужно от 1 до 64 профилей оружия")
        if any(sum(step.duration for step in profile) > 10 for profile in self.profiles.values()):
            raise ValueError("Профиль не должен превышать 10 секунд")
        return self

    @classmethod
    def parse(cls, raw: object) -> RecoilSettings:
        """Читает внешний объект без преобразования строк в числа и флаги."""
        return TypeAdapter(cls).validate_python(raw)


class RecoilMotion:
    """Ведёт одну очередь, сохраняя доли отсчётов и блокируя повтор после прерывания."""

    def __init__(self) -> None:
        """Начинает с ожидания отпущенной кнопки стрельбы."""
        self.released = False
        self.started: float | None = None
        self.previous = 0.0
        self.weapon = ""
        self.sent_x = 0
        self.sent_y = 0

    def reset(self) -> None:
        """Останавливает очередь до нового отпускания ЛКМ."""
        self.released = False
        self.started = None
        self.weapon = ""
        self.sent_x = self.sent_y = 0

    def advance(self, now: float, pressed: bool, weapon: str,
                settings: RecoilSettings, permitted: bool) -> tuple[int, int]:
        """Рассчитывает движение или останавливается при нарушении условий."""
        if not pressed:
            self.reset()
            self.released = True
            return 0, 0
        if not permitted or weapon not in settings.profiles:
            self.reset()
            return 0, 0
        if self.started is None:
            if not self.released:
                return 0, 0
            self.started = self.previous = now
            self.weapon = weapon
        if weapon != self.weapon or not 0 <= now - self.previous <= 0.05:
            self.reset()
            return 0, 0
        self.previous = now
        elapsed = now - self.started
        x, y = 0.0, 0.0
        for step in settings.profiles[weapon]:
            duration = min(step.duration, max(0.0, elapsed))
            x += step.x * duration
            y += step.y * duration
            elapsed -= step.duration
        factor = settings.strength / settings.sensitivity
        target_x, target_y = math.trunc(x * factor), math.trunc(y * factor)
        dx, dy = target_x - self.sent_x, target_y - self.sent_y
        # Never catch up with a large jump after an unusually delayed tick.
        if abs(dx) > 100 or abs(dy) > 100:
            self.reset()
            return 0, 0
        self.sent_x, self.sent_y = target_x, target_y
        return dx, dy
