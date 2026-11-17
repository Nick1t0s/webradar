"""Run from the repository root: python -m perspective."""
from pathlib import Path
import argparse
import sys

from .config import Settings, SettingsError


def main() -> int:
    """Запускает обычное окно или нативный оверлей выбранной платформы."""
    parser = argparse.ArgumentParser(description="CS2 perspective viewer")
    parser.add_argument("--overlay", action="store_true", help="Native transparent overlay for Windows or Linux/Hyprland")
    arguments = parser.parse_args()
    try:
        path = Path(__file__).with_name("settings.json")
        if arguments.overlay:
            if sys.platform == "win32":
                from .overlay_windows import run as run_windows
                run_windows(path)
            elif sys.platform.startswith("linux"):
                from .overlay import run as run_linux
                run_linux(path)
            else:
                raise SettingsError("Оверлей поддерживает Windows 10/11 и Linux/Hyprland")
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
            detail = ("Windows: нужен Python с Tk; CS2 должна быть в оконном или оконном полноэкранном режиме."
                      if sys.platform == "win32" else
                      "Linux/Hyprland: нужны GTK3, PyGObject, Cairo и GtkLayerShell-0.1.")
            print(f"{detail} См. perspective/README.md", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
