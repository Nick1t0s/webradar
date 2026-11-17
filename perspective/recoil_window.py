"""Настройки мыши и профилей компенсации в управляющем Tk-окне."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, replace
import json
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .config import Settings
from .mouse_linux import mouse_choices
from .recoil import RecoilSettings


def open_recoil_settings(root: tk.Tk, settings: Settings, settings_path: Path,
                         on_apply: Callable[[Settings], None]) -> None:
    """Открывает отдельные параметры Linux-ввода и сохраняет их атомарно."""
    dialog = tk.Toplevel(root)
    dialog.title("Контроль отдачи · Linux / Hyprland")
    dialog.transient(root)
    dialog.grab_set()
    choices = {mouse.label: mouse.identity for mouse in mouse_choices()}
    configured = settings.recoil
    selected = next((label for label, path in choices.items() if path == configured.mouse_device), configured.mouse_device)
    enabled = tk.BooleanVar(value=configured.enabled)
    ttk.Checkbutton(dialog, text="Разрешить компенсацию (при запуске всегда на паузе)", variable=enabled).grid(
        row=0, column=0, columnspan=2, padx=10, pady=8, sticky="w")
    mouse = tk.StringVar(value=selected)
    sensitivity = tk.StringVar(value=str(configured.sensitivity))
    strength = tk.StringVar(value=str(configured.strength))
    toggle = tk.StringVar(value="Mouse4" if configured.toggle_button == "BTN_SIDE" else "Mouse5")
    ttk.Label(dialog, text="Физическая мышь").grid(row=1, column=0, padx=10, sticky="w")
    ttk.Combobox(dialog, textvariable=mouse, values=tuple(choices), width=65).grid(row=1, column=1, padx=10, pady=5)
    for row, label, variable in ((2, "Sensitivity в CS2", sensitivity), (3, "Сила компенсации (0.1–2)", strength)):
        ttk.Label(dialog, text=label).grid(row=row, column=0, padx=10, sticky="w")
        ttk.Entry(dialog, textvariable=variable).grid(row=row, column=1, padx=10, pady=5, sticky="ew")
    ttk.Label(dialog, text="Кнопка включения / паузы").grid(row=4, column=0, padx=10, sticky="w")
    ttk.Combobox(dialog, textvariable=toggle, values=("Mouse4", "Mouse5"), state="readonly").grid(
        row=4, column=1, padx=10, pady=5, sticky="ew")
    ttk.Label(dialog, text="Профили оружия (JSON)").grid(row=5, column=0, columnspan=2, padx=10, pady=5, sticky="w")
    editor = tk.Text(dialog, height=12, width=85, wrap="none")
    editor.grid(row=6, column=0, columnspan=2, padx=10, sticky="nsew")
    editor.insert("1.0", json.dumps(asdict(configured)["profiles"], indent=2))
    ttk.Label(dialog, text=("Mouse4/Mouse5 переключает компенсацию только в активной CS2. Затем удерживайте ЛКМ.\n"
                           "duration — секунды, x/y — отсчёты мыши в секунду при sensitivity=1; y>0 — вниз.\n"
                           "Начальные профили — приблизительная вертикальная компенсация, нужна калибровка.\n"
                           "Нужен локальный helper. Чужой игрок, нож и гранаты не включают компенсацию.\n"
                           "После потери фокуса/связи отпустите ЛКМ. Боковая кнопка также поступает в игру."),
              wraplength=750).grid(row=7, column=0, columnspan=2, padx=10, pady=8, sticky="w")
    dialog.rowconfigure(6, weight=1)
    dialog.columnconfigure(1, weight=1)

    def apply() -> None:
        """Проверяет весь профиль до сохранения и применения настроек."""
        try:
            raw: object = json.loads(editor.get("1.0", "end"))
            recoil = RecoilSettings.parse({
                "enabled": enabled.get(), "mouse_device": choices.get(mouse.get(), mouse.get().strip()),
                "sensitivity": float(sensitivity.get().replace(",", ".")),
                "strength": float(strength.get().replace(",", ".")),
                "toggle_button": "BTN_SIDE" if toggle.get() == "Mouse4" else "BTN_EXTRA", "profiles": raw,
            })
            # Re-read to preserve camera changes made in another settings dialog.
            updated = replace(Settings.load(settings_path), recoil=recoil)
            updated.save(settings_path)
            on_apply(updated)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Компенсация не настроена", str(exc), parent=dialog)
            return
        dialog.destroy()

    ttk.Button(dialog, text="Применить", command=apply).grid(row=8, column=1, padx=10, pady=10, sticky="e")
