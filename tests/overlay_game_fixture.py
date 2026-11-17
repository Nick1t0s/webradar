"""Own Wayland test surface; never opens or operates the real game."""
from pathlib import Path
import sys

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk


def main() -> None:
    GLib.set_prgname("cs2")
    Gtk.init([])
    window = Gtk.Window(title="CS2 perspective integration test")
    window.set_default_size(800, 600)
    window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
    def click(widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        Path(sys.argv[1]).write_text("clicked", encoding="utf-8")
        return True
    def key(widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        Path(sys.argv[2]).write_text("key", encoding="utf-8")
        return True
    def draw(widget: Gtk.Widget, context: cairo.Context[cairo.Surface]) -> bool:
        context.set_source_rgb(0.1, 0.2, 0.4)
        context.paint()
        return True
    window.connect("button-press-event", click)
    window.connect("key-press-event", key)
    window.connect("draw", draw)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    window.fullscreen()
    Gtk.main()


if __name__ == "__main__":
    main()
