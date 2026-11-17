"""Чтение кнопок одной мыши и относительный ввод через Linux evdev/uinput."""
from __future__ import annotations

import fcntl
from dataclasses import dataclass
import os
from pathlib import Path
import struct


class MouseError(OSError):
    """Устройство мыши недоступно или не поддерживает нужный ввод."""


# linux/input.h and linux/uinput.h, using the native Linux ABI.
EVENT = struct.Struct("@llHHi")
SETUP = struct.Struct("@HHHH80sI")
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_DEV_SETUP = 0x40000000 | (SETUP.size << 16) | 0x5503
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
BTN_LEFT = 0x110
BUTTONS = {"BTN_SIDE": 0x113, "BTN_EXTRA": 0x114}
VIRTUAL_NAME = "CS2 Perspective Recoil"


@dataclass(frozen=True)
class MouseDevice:
    """Хранит имя, текущий узел и сохраняемый идентификатор физической мыши."""

    name: str
    path: str
    identity: str

    @property
    def label(self) -> str:
        """Добавляет текущий event-узел к названию устройства в списке."""
        return f"{self.name} — {Path(self.path).name}"


def mouse_choices() -> tuple[MouseDevice, ...]:
    """Перечисляет мыши по sysfs без чтения нажатий и открытия клавиатур."""
    choices: list[MouseDevice] = []
    for path in sorted(Path("/sys/class/input").glob("event*")):
        try:
            name = (path / "device/name").read_text().strip()
            # Capability bitmaps are native-word chunks, highest word first.
            words = (path / "device/capabilities/rel").read_text().split()
            keys = (path / "device/capabilities/key").read_text().split()
            word_bits = struct.calcsize("L") * 8
            mask = sum(int(word, 16) << (index * word_bits) for index, word in enumerate(reversed(keys)))
            if words and int(words[-1], 16) & 3 == 3 and mask & (1 << BTN_LEFT) and name != VIRTUAL_NAME:
                device = f"/dev/input/{path.name}"
                stable = next((str(link) for link in sorted(Path("/dev/input/by-id").glob("*event-mouse"))
                               if link.resolve() == Path(device)), device)
                if (path / "device/id/bustype").read_text().strip() == "0005":
                    unique = (path / "device/uniq").read_text().strip()
                    if unique:
                        stable = f"bluetooth:{unique.lower()}"
                choices.append(MouseDevice(name, device, stable))
        except (OSError, ValueError):
            continue
    return tuple(choices)


def mouse_path(device: str) -> str:
    """Находит актуальный event-узел Bluetooth-мыши после её переподключения."""
    if not device.startswith("bluetooth:"):
        return device
    for mouse in mouse_choices():
        if mouse.identity.lower() == device.lower():
            return mouse.path
    raise MouseError("Выбранная Bluetooth-мышь не подключена")


def device_bits(fd: int, request: int, size: int) -> bytes:
    """Читает битовую маску или имя через ioctl без очереди событий."""
    buffer = bytearray(size)
    fcntl.ioctl(fd, 0x80000000 | (size << 16) | request, buffer, True)
    return bytes(buffer)


class LinuxMouse:
    """Владеет дескрипторами физической и виртуальной мышей без захвата ввода."""

    def __init__(self, device: str, toggle_button: str) -> None:
        """Проверяет выбранную мышь и создаёт устройство только для движений."""
        self.input_fd = -1
        self.output_fd = -1
        self.created = False
        self.toggle_code = BUTTONS[toggle_button]
        try:
            self.input_fd = os.open(mouse_path(device), os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            name = device_bits(self.input_fd, 0x4506, 256).split(b"\0", 1)[0].decode(errors="replace")
            keys = int.from_bytes(device_bits(self.input_fd, 0x4521, 96), "little")
            axes = int.from_bytes(device_bits(self.input_fd, 0x4522, 16), "little")
            if name == VIRTUAL_NAME or not keys & (1 << BTN_LEFT) or axes & 3 != 3:
                raise MouseError("Выбранное устройство не является физической относительной мышью")
            if not keys & (1 << self.toggle_code):
                raise MouseError(f"Мышь не поддерживает {toggle_button}; выберите другую боковую кнопку")
            self.output_fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            fcntl.ioctl(self.output_fd, UI_SET_EVBIT, 1)  # EV_KEY
            fcntl.ioctl(self.output_fd, UI_SET_KEYBIT, BTN_LEFT)
            fcntl.ioctl(self.output_fd, UI_SET_EVBIT, 2)  # EV_REL
            for axis in (0, 1):
                fcntl.ioctl(self.output_fd, UI_SET_RELBIT, axis)
            fcntl.ioctl(self.output_fd, UI_DEV_SETUP, SETUP.pack(3, 0x1, 0x1, 1, VIRTUAL_NAME.encode(), 0))
            fcntl.ioctl(self.output_fd, UI_DEV_CREATE)
            self.created = True
        except OSError as exc:
            self.close()
            raise MouseError(f"Ввод мыши: {exc}. Нужны чтение выбранного устройства и запись в /dev/uinput") from exc

    def buttons(self) -> tuple[bool, bool]:
        """Возвращает состояние ЛКМ и выбранной боковой кнопки без записи событий."""
        mask = int.from_bytes(device_bits(self.input_fd, 0x4518, 96), "little")  # EVIOCGKEY
        return bool(mask & (1 << BTN_LEFT)), bool(mask & (1 << self.toggle_code))

    def move(self, x: int, y: int) -> None:
        """Отправляет только относительное перемещение, не создавая нажатий."""
        if not x and not y:
            return
        events = EVENT.pack(0, 0, 2, 0, x) + EVENT.pack(0, 0, 2, 1, y) + EVENT.pack(0, 0, 0, 0, 0)
        if os.write(self.output_fd, events) != len(events):
            raise MouseError("Неполная запись движения мыши")

    def close(self) -> None:
        """Удаляет виртуальную мышь и закрывает только собственные дескрипторы."""
        try:
            if self.output_fd >= 0:
                try:
                    if self.created:
                        fcntl.ioctl(self.output_fd, UI_DEV_DESTROY)
                finally:
                    os.close(self.output_fd)
                    self.output_fd = -1
                    self.created = False
        finally:
            if self.input_fd >= 0:
                os.close(self.input_fd)
                self.input_fd = -1
