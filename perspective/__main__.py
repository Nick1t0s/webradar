"""Run from the repository root: python -m perspective."""
from pathlib import Path
import argparse
import sys

from .config import Settings, SettingsError


def main() -> int:
    parser = argparse.ArgumentParser(description="CS2 perspective viewer")
    parser.add_argument("--overlay", action="store_true", help="Native Wayland overlay for Hyprland")
    arguments = parser.parse_args()
    try:
        path = Path(__file__).with_name("settings.json")
        if arguments.overlay:
            if not sys.platform.startswith("linux"):
                raise SettingsError("Прозрачный оверлей пока доступен только на Linux/Hyprland")
            from .overlay import run
            run(path)
            return 0
        import tkinter as tk
        from .window import PerspectiveWindow
        settings = Settings.load(path)
        try:
            root = tk.Tk()
            PerspectiveWindow(root, settings, path)
            root.mainloop()
        except tk.TclError as exc:
            raise SettingsError(f"Не удалось создать окно Tk: {exc}") from exc
        return 0
    except (OSError, SettingsError, ImportError, ValueError) as exc:
        print(f"Perspective: {exc}", file=sys.stderr)
        if arguments.overlay:
            print("Оверлею нужны GTK3, PyGObject, Cairo и GtkLayerShell-0.1. См. perspective/README.md", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
