"""Run from the repository root: python -m perspective."""
from pathlib import Path
import sys
import tkinter as tk

from .config import Settings, SettingsError
from .window import PerspectiveWindow


def main() -> int:
    try:
        path = Path(__file__).with_name("settings.json")
        settings = Settings.load(path)
        root = tk.Tk()
        PerspectiveWindow(root, settings, path)
        root.mainloop()
        return 0
    except (OSError, SettingsError, tk.TclError) as exc:
        print(f"Perspective: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
