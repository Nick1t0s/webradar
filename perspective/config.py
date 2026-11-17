"""Local viewer settings and read-only discovery of CS2 video/convar files."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import cast
from urllib.parse import urlsplit

from .scene import FrameError, Player, number, object_fields


class SettingsError(ValueError):
    """Viewer or game settings cannot be used for a camera."""


def validate_ws_url(url: str) -> None:
    """Проверяет адрес источника данных до открытия сетевого соединения."""
    if not isinstance(url, str) or not url or any(char.isspace() for char in url):
        raise SettingsError("Адрес источника данных не должен быть пустым или содержать пробелы")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise SettingsError("Некорректный адрес или порт источника данных") from exc
    if (parsed.scheme not in ("ws", "wss") or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or parsed.fragment or port == 0):
        raise SettingsError("Нужен ws:// или wss:// адрес helper с корректным портом, без пароля и фрагмента")


@dataclass(frozen=True)
class Settings:
    ws_url: str
    cfg_dir: str | None
    player: str
    width: int | None
    height: int | None
    fov: float | None
    scale: float
    eye_height: float
    body_width: float
    body_height: float
    overlay_stretch: bool = False
    teammate_color: str = "#4ade80"
    enemy_color: str = "#ef4444"
    show_view_rays: bool = True

    def __post_init__(self) -> None:
        """Проверяет источник и показ лучей при любом способе создания настроек."""
        validate_ws_url(self.ws_url)
        if not isinstance(self.show_view_rays, bool):
            raise SettingsError("show_view_rays: нужно true или false")

    @classmethod
    def load(cls, path: Path) -> Settings:
        if not path.exists():
            path.write_text(Path(__file__).with_name("config.example.json").read_text(), encoding="utf-8")
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
            return cls.parse(raw)
        except (ValueError, KeyError) as exc:
            raise SettingsError(f"Настройки {path.name}: {exc}") from exc

    @classmethod
    def parse(cls, raw: object) -> Settings:
        """Читает настройки и добавляет новые поля старым сохранённым профилям."""
        try:
            fields = object_fields(raw)
            # Existing perspective preferences predate the overlay display mode.
            fields.setdefault("overlay_stretch", False)
            fields.setdefault("teammate_color", "#4ade80")
            fields.setdefault("enemy_color", "#ef4444")
            fields.setdefault("show_view_rays", True)
            if set(fields) != set(cls.__dataclass_fields__):
                raise SettingsError("Нужны все поля из config.example.json; неизвестные поля запрещены")
            url, cfg, player = fields["ws_url"], fields["cfg_dir"], fields["player"]
            if not isinstance(url, str) or not isinstance(player, str) or not player:
                raise SettingsError("Неверный адрес helper или игрок")
            if cfg is not None and not isinstance(cfg, str):
                raise SettingsError("cfg_dir: путь к папке cfg или null")
            dimensions: list[int | None] = []
            for key in ("width", "height"):
                value = fields[key]
                n = None if value is None else number(value)
                if n is not None and (not n.is_integer() or not 100 <= n <= 16384):
                    raise SettingsError("Разрешение: целые числа 100–16384")
                dimensions.append(None if n is None else int(n))
            if (dimensions[0] is None) != (dimensions[1] is None):
                raise SettingsError("Укажите обе стороны разрешения или оставьте обе пустыми")
            fov = None if fields["fov"] is None else number(fields["fov"])
            if fov is not None and not 1 <= fov <= 170:
                raise SettingsError("FOV: 1–170 градусов")
            scale = number(fields["scale"])
            eye, width, height = (number(fields[k]) for k in ("eye_height", "body_width", "body_height"))
            if not 0.1 <= scale <= 2 or not all(1 <= v <= 128 for v in (eye, width, height)):
                raise SettingsError("Масштаб: 0.1–2; размеры тела и высота глаз: 1–128")
            stretch = fields["overlay_stretch"]
            if not isinstance(stretch, bool):
                raise SettingsError("overlay_stretch: нужно true или false")
            colors: list[str] = []
            for key in ("teammate_color", "enemy_color"):
                color = fields[key]
                if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                    raise SettingsError(f"{key}: нужен цвет #RRGGBB")
                colors.append(color.lower())
            return cls(url, cfg, player, dimensions[0], dimensions[1], fov, scale, eye, width, height, stretch,
                       colors[0], colors[1], cast(bool, fields["show_view_rays"]))
        except (FrameError, KeyError, ValueError) as exc:
            raise SettingsError(str(exc)) from exc

    def save(self, path: Path) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def player_color(self, player: Player, viewer: Player) -> str:
        return self.teammate_color if viewer.team in (2, 3) and player.team == viewer.team else self.enemy_color


def discover_cfg_dirs() -> tuple[Path, ...]:
    home = Path.home()
    roots = [home / ".steam/steam", home / ".local/share/Steam",
             home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
             home / "snap/steam/common/.local/share/Steam"]
    for name in ("STEAM_DIR", "STEAM_ROOT", "STEAM_HOME"):
        if os.environ.get(name):
            roots.append(Path(os.environ[name]))
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                location: object = winreg.QueryValueEx(key, "SteamPath")[0]
                if isinstance(location, str):
                    roots.append(Path(location))
        except OSError:
            pass
        roots.extend(Path(f"{drive}:/Program Files (x86)/Steam") for drive in "CDEFG")
    directories: set[Path] = set()
    for root in roots:
        for path in (root / "userdata").glob("*/730/local/cfg"):
            if (path / "cs2_video.txt").is_file():
                directories.add(path.resolve())
    return tuple(sorted(directories))


def read_values(path: Path) -> dict[str, str]:
    # Read quoted KeyValues pairs only, stripping // comments outside strings.
    # Do not execute cfg commands or follow exec directives.
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    # Use a line parser for scalar pairs; vcfg/video files place pairs on a line.
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r'^\s*"([^"\n]+)"\s+"([^"\n]*)"', line)
        if match:
            result[match[1]] = match[2]
    return result


@dataclass(frozen=True)
class GameVideo:
    width: int | None
    height: int | None
    fov: float | None
    source: str

    @classmethod
    def for_player(cls, settings: Settings, player: Player | None, profiles: tuple[Path, ...]) -> GameVideo:
        directory = Path(settings.cfg_dir).expanduser() if settings.cfg_dir else None
        if directory is None and player and player.identity.startswith("steam:"):
            account = str(int(player.identity.removeprefix("steam:")) - 76561197960265728)
            directory = next((path for path in profiles if path.parents[2].name == account), None)
        if directory is None and not settings.cfg_dir and len(profiles) == 1:
            directory = profiles[0]
        return cls.read(directory)

    @classmethod
    def read(cls, directory: Path | None) -> GameVideo:
        if directory is None:
            return cls(None, None, None, "Файлы CS2 не выбраны")
        video = read_values(directory / "cs2_video.txt")
        values = read_values(directory / "cs2_machine_convars.vcfg")
        values.update(read_values(directory / "cs2_user_convars_0_slot0.vcfg"))
        def scalar(value: str | None, minimum: float, maximum: float) -> float | None:
            try:
                parsed = number(float(value)) if value is not None else None
                return parsed if parsed is not None and minimum <= parsed <= maximum else None
            except ValueError:
                return None
        width = scalar(video.get("setting.defaultres"), 100, 16384)
        height = scalar(video.get("setting.defaultresheight"), 100, 16384)
        fov = scalar(values.get("default_fov"), 1, 170) or scalar(values.get("fov_desired"), 1, 170)
        return cls(int(width) if width is not None and width.is_integer() else None,
                   int(height) if height is not None and height.is_integer() else None,
                   fov, str(directory))

    def resolution(self, settings: Settings) -> tuple[int, int]:
        width, height = (settings.width, settings.height) if settings.width is not None else (self.width, self.height)
        if width is None or height is None:
            raise SettingsError("Выберите папку cfg CS2 или введите разрешение в настройках")
        return width, height
