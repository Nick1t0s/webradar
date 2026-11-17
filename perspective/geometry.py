"""Общая геометрия области игры в координатах окна оверлея."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    """Прямоугольник в координатах используемой платформой поверхности."""

    x: float
    y: float
    width: float
    height: float
