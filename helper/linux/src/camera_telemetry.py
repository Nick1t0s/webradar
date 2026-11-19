"""Optional camera data; all memory access stays inside the existing reader."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import struct
from typing import Protocol, TypedDict


class MemoryReader(Protocol):
    def f32(self, address: int) -> float: ...
    def u32(self, address: int) -> int: ...
    def ptr(self, address: int) -> int: ...


class Position(TypedDict):
    x: float
    y: float
    z: float


class CameraData(TypedDict):
    m_eye_pitch: float | None
    m_eye_position: Position | None
    m_camera_fov: float | None
    m_bounds_min: Position | None
    m_bounds_max: Position | None


@dataclass(frozen=True)
class CameraOffsets:
    angles: int
    view: int
    services: int
    fov: int
    collision: int
    mins: int
    maxs: int


def _vector(memory: MemoryReader, address: int) -> Position | None:
    x, y, z = (memory.f32(address + delta) for delta in (0, 4, 8))
    return {"x": x, "y": y, "z": z} if all(map(isfinite, (x, y, z))) else None


def read_camera(memory: MemoryReader, pawn: int, offsets: CameraOffsets,
                origin: tuple[float, float, float]) -> CameraData:
    result: CameraData = {"m_eye_pitch": None, "m_eye_position": None,
                          "m_camera_fov": None, "m_bounds_min": None, "m_bounds_max": None}
    try:
        if offsets.angles:
            pitch = memory.f32(pawn + offsets.angles)
            if isfinite(pitch) and -90 <= pitch <= 90:
                result["m_eye_pitch"] = pitch
        if offsets.view:
            # CNetworkViewOffsetVector contains three CNetworkedQuantizedFloat
            # values at +0x10/+0x18/+0x20, not a packed Vector at +0/+4/+8.
            x, y, z = (memory.f32(pawn + offsets.view + delta) for delta in (0x10, 0x18, 0x20))
            if all(map(isfinite, (x, y, z))) and abs(x) <= 64 and abs(y) <= 64 and 1 <= z <= 128:
                result["m_eye_position"] = {"x": origin[0] + x, "y": origin[1] + y, "z": origin[2] + z}
        if offsets.services and offsets.fov:
            services = memory.ptr(pawn + offsets.services)
            if services:
                fov = memory.u32(services + offsets.fov)
                if 1 <= fov < 179:
                    result["m_camera_fov"] = float(fov)
        if offsets.collision and offsets.mins and offsets.maxs:
            collision = memory.ptr(pawn + offsets.collision)
            if collision:
                low = _vector(memory, collision + offsets.mins)
                high = _vector(memory, collision + offsets.maxs)
                if low and high and all(0 < high[k] - low[k] <= 128 for k in ("x", "y", "z")):
                    result["m_bounds_min"], result["m_bounds_max"] = low, high
    except (OSError, struct.error):
        # Optional camera reads must never drop a working radar player/frame.
        pass
    return result
