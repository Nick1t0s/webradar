"""Native, click-through GTK3 layer-shell overlay for Hyprland."""
from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
import signal
import sys
from typing import Protocol, cast

# The local typelib is optional; distro-installed typelibs work without it.
_local_typelibs = Path(__file__).with_name(".runtime") / "girepository-1.0"
os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(filter(None, (str(_local_typelibs), os.environ.get("GI_TYPELIB_PATH"))))
os.environ["GDK_BACKEND"] = "wayland"

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk

from .config import SettingsError
from .hyprland import GameTarget, HyprlandTracker
from .overlay_state import OverlayState
from .recoil_linux import RecoilService
from .scene import player_health_strokes


class LayerValues(Protocol):
    OVERLAY: int


class EdgeValues(Protocol):
    TOP: int
    BOTTOM: int
    LEFT: int
    RIGHT: int


class KeyboardValues(Protocol):
    NONE: int


class LayerShellAPI(Protocol):
    """Signatures of the small GI namespace not covered by PyGObject-stubs."""
    Layer: LayerValues
    Edge: EdgeValues
    KeyboardMode: KeyboardValues

    def is_supported(self) -> bool: ...
    def init_for_window(self, window: Gtk.Window) -> None: ...
    def set_namespace(self, window: Gtk.Window, namespace: str) -> None: ...
    def set_layer(self, window: Gtk.Window, layer: int) -> None: ...
    def set_keyboard_mode(self, window: Gtk.Window, mode: int) -> None: ...
    def set_exclusive_zone(self, window: Gtk.Window, zone: int) -> None: ...
    def set_anchor(self, window: Gtk.Window, edge: int, anchored: bool) -> None: ...
    def set_monitor(self, window: Gtk.Window, monitor: Gdk.Monitor) -> None: ...


LayerShell = cast(LayerShellAPI, import_module("gi.repository.GtkLayerShell"))


class Overlay:
    def __init__(self, settings_path: Path) -> None:
        """Создаёт прозрачную Wayland-поверхность и общую подписку."""
        Gtk.init([])
        if not LayerShell.is_supported():
            raise SettingsError("Нужен Wayland compositor с layer-shell (Hyprland)")
        self.state = OverlayState(settings_path, self._notify_frame)
        self.recoil_service = RecoilService(settings_path)
        self.last_recoil_status = ""
        self.desktop = HyprlandTracker()
        self.target: GameTarget | None = None
        self.last_message = ""
        self.output_name = ""
        self.closed = False
        self.fresh = False
        self.window = Gtk.Window(title="CS2 Perspective Overlay")
        self.window.set_name("cs2-perspective-overlay")
        self.window.set_decorated(False)
        self.window.set_app_paintable(True)
        self.window.set_accept_focus(False)
        self.window.set_focus_on_map(False)
        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual is None:
            raise SettingsError("Wayland display не предоставляет RGBA visual")
        self.window.set_visual(visual)
        self.window.set_default_size(1, 1)
        LayerShell.init_for_window(self.window)
        LayerShell.set_namespace(self.window, "cs2-perspective")
        LayerShell.set_layer(self.window, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self.window, LayerShell.KeyboardMode.NONE)
        # Do not reserve desktop space, and cover panels' reserved space too.
        LayerShell.set_exclusive_zone(self.window, -1)
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(self.window, edge, True)
        self.window.connect("draw", self._draw)
        self.window.connect("size-allocate", self._input_region)
        self.state.start()
        self.desktop.start()
        self.recoil_service.start()
        self.timer = GLib.timeout_add(16, self._tick)
        self.reload_timer = GLib.timeout_add(500, self._reload_settings)

    def _input_region(self, widget: Gtk.Widget, allocation: Gdk.Rectangle) -> None:
        """Пропускает указатель мыши в расположенную под слоем игру."""
        self.window.input_shape_combine_region(cairo.Region(cairo.RectangleInt(0, 0, 0, 0)))

    def _message(self, text: str) -> None:
        """Пишет изменившееся сообщение в журнал оверлея."""
        if text != self.last_message:
            print(f"Overlay: {text}", file=sys.stderr, flush=True)
            self.last_message = text

    def _notify_frame(self) -> None:
        """Будит главный цикл GTK при получении нового кадра."""
        # Called by the receiver thread only when its one-slot mailbox becomes
        # nonempty. Wake GTK directly instead of waiting for a polling timer.
        GLib.idle_add(self._frame_ready, priority=GLib.PRIORITY_HIGH_IDLE)

    def _frame_ready(self) -> bool:
        """Обновляет поверхность из главного потока GTK."""
        if not self.closed:
            self._tick()
        return False

    def _reload_settings(self) -> bool:
        """Перечитывает общие настройки и запрашивает перерисовку."""
        if self.recoil_service.status != self.last_recoil_status:
            self.last_recoil_status = self.recoil_service.status
            print(self.last_recoil_status, file=sys.stderr, flush=True)
        try:
            if self.state.reload():
                self.window.queue_draw()
        except (OSError, SettingsError) as exc:
            self._message(str(exc))
        return not self.closed

    def _monitor(self, target: GameTarget) -> Gdk.Monitor | None:
        """Находит монитор GDK, соответствующий области игры."""
        display = self.window.get_display()
        for i in range(display.get_n_monitors()):
            monitor = display.get_monitor(i)
            if monitor is None:
                continue
            geometry = monitor.get_geometry()
            if abs(geometry.x - target.output.x) < 2 and abs(geometry.y - target.output.y) < 2:
                return monitor
        return None

    def _tick(self) -> bool:
        """Обновляет данные, монитор и видимость слоя."""
        previous_target = self.target
        changed = self.state.poll()
        desktop = self.desktop.latest()
        if desktop is not None:
            self.target = desktop.target
            if desktop.error:
                self._message(desktop.error)
        fresh = self.state.fresh
        needs_draw = changed or previous_target != self.target or fresh != self.fresh
        self.fresh = fresh
        if self.target is None or not fresh:
            if self.window.get_visible():
                self.window.hide()
        else:
            monitor = self._monitor(self.target)
            if monitor is None:
                self.window.hide()
                self._message(f"GDK не нашёл монитор {self.target.monitor}")
            else:
                if self.output_name != self.target.monitor:
                    LayerShell.set_monitor(self.window, monitor)
                    self.output_name = self.target.monitor
                if not self.window.get_visible():
                    self.window.show_all()
                    self.window.input_shape_combine_region(cairo.Region(cairo.RectangleInt(0, 0, 0, 0)))
                    needs_draw = True
                if needs_draw:
                    self.window.queue_draw()
        return not self.closed

    def _draw(self, widget: Gtk.Widget, context: cairo.Context[cairo.Surface]) -> bool:
        """Рисует лучи и каркасы с прозрачным фоном и уровнем здоровья."""
        # Clear every frame to actual alpha=0, including unused letterbox areas.
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0, 0, 0, 0)
        context.paint()
        context.set_operator(cairo.OPERATOR_OVER)
        if self.target is None or not self.state.fresh:
            return True
        try:
            boxes = self.state.boxes(self.target.game)
        except SettingsError as exc:
            self._message(str(exc))
            return True
        game = self.target.game
        context.rectangle(game.x, game.y, game.width, game.height)
        context.clip()
        for box in boxes:
            if box.view_ray is None:
                continue
            a, b = box.view_ray
            context.set_line_width(3)
            context.set_source_rgb(0, 0, 0)
            context.move_to(*a)
            context.line_to(*b)
            context.stroke()
            context.set_line_width(1.5)
            context.set_source_rgb(*(int(box.color[i:i + 2], 16) / 255 for i in (1, 3, 5)))
            context.move_to(*a)
            context.line_to(*b)
            context.stroke()
        # Dark outer stroke keeps the bright inner line readable on light maps.
        for box in boxes:
            context.set_line_width(4)
            context.set_source_rgb(0, 0, 0)
            for a, b in box.segments:
                context.move_to(*a)
                context.line_to(*b)
            context.stroke()
            context.set_line_width(2)
            strokes = player_health_strokes(box.segments, box.health, box.color)
            for color in dict.fromkeys(stroke.color for stroke in strokes):
                context.set_source_rgb(*(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)))
                for stroke in strokes:
                    if stroke.color == color:
                        a, b = stroke.segment
                        context.move_to(*a)
                        context.line_to(*b)
                context.stroke()
        return True

    def close(self) -> bool:
        """Останавливает подписку, отслеживание игры и окно GTK."""
        if not self.closed:
            self.closed = True
            GLib.source_remove(self.timer)
            GLib.source_remove(self.reload_timer)
            self.recoil_service.stop()
            self.state.close()
            self.desktop.stop()
            self.window.destroy()
            Gtk.main_quit()
        return False


def run(settings_path: Path) -> None:
    """Запускает оверлей Hyprland с корректным завершением по сигналу."""
    overlay = Overlay(settings_path)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, overlay.close)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, overlay.close)
    try:
        Gtk.main()
    finally:
        overlay.close()
