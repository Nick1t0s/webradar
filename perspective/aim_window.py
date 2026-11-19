"""Диалог настроек автонаводки в управляющем Tk-окне Linux."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .aim_settings import AimSettings
from .config import Settings
from .mouse_linux import mouse_choices


def open_aim_settings(root: tk.Tk, settings: Settings, settings_path: Path,
                      on_apply: Callable[[Settings], None]) -> None:
    """Открывает параметры автонаводки и сохраняет их атомарно."""
    dialog = tk.Toplevel(root)
    dialog.title("Автонаводка · Linux / Hyprland")
    dialog.transient(root)
    dialog.grab_set()

    choices = {mouse.label: mouse.identity for mouse in mouse_choices()}
    configured = settings.aim
    selected = next((label for label, path in choices.items() if path == configured.mouse_device), configured.mouse_device)

    enabled = tk.BooleanVar(value=configured.enabled)
    ttk.Checkbutton(dialog, text="Разрешить автонаводку (удержание кнопки)", variable=enabled).grid(
        row=0, column=0, columnspan=2, padx=10, pady=8, sticky="w")

    mouse = tk.StringVar(value=selected)
    ttk.Label(dialog, text="Физическая мышь").grid(row=1, column=0, padx=10, sticky="w")
    ttk.Combobox(dialog, textvariable=mouse, values=tuple(choices), width=65).grid(row=1, column=1, padx=10, pady=5)

    button = tk.StringVar(value="Mouse4" if configured.button == "BTN_SIDE" else "Mouse5")
    ttk.Label(dialog, text="Кнопка удержания").grid(row=2, column=0, padx=10, sticky="w")
    ttk.Combobox(dialog, textvariable=button, values=("Mouse4", "Mouse5"), state="readonly").grid(
        row=2, column=1, padx=10, pady=5, sticky="ew")

    sensitivity = tk.StringVar(value=str(configured.sensitivity))
    ttk.Label(dialog, text="Sensitivity в CS2").grid(row=3, column=0, padx=10, sticky="w")
    ttk.Entry(dialog, textvariable=sensitivity).grid(row=3, column=1, padx=10, pady=5, sticky="ew")

    radius_percent = tk.StringVar(value=str(configured.radius_percent))
    ttk.Label(dialog, text="Радиус захвата (% высоты кадра, 1–50)").grid(row=4, column=0, padx=10, sticky="w")
    ttk.Entry(dialog, textvariable=radius_percent).grid(row=4, column=1, padx=10, pady=5, sticky="ew")

    target_var = tk.StringVar(value="Голова" if configured.target == "head" else "Тело")
    ttk.Label(dialog, text="Точка прицеливания").grid(row=5, column=0, padx=10, sticky="w")
    ttk.Combobox(dialog, textvariable=target_var, values=("Голова", "Тело"), state="readonly").grid(
        row=5, column=1, padx=10, pady=5, sticky="ew")

    include_teammates = tk.BooleanVar(value=configured.include_teammates)
    ttk.Checkbutton(dialog, text="Наводиться и на союзников", variable=include_teammates).grid(
        row=6, column=0, columnspan=2, padx=10, pady=5, sticky="w")

    ttk.Label(dialog, text=("Автонаводка перемещает прицел к ближайшей цели внутри круга при удержании Mouse4/Mouse5.\n"
                           "Радиус круга задаётся в процентах от высоты игры (1–50%).\n"
                           "Требуются права доступа к выбранной мыши и /dev/uinput.\n"
                           "Стены и видимость не проверяются; приближение точек головы/тела по данным helper."),
              wraplength=750).grid(row=7, column=0, columnspan=2, padx=10, pady=8, sticky="w")
    dialog.columnconfigure(1, weight=1)

    def apply() -> None:
        """Проверяет введённые параметры до сохранения и применения настроек."""
        try:
            aim = AimSettings(
                enabled=enabled.get(),
                mouse_device=choices.get(mouse.get(), mouse.get().strip()),
                sensitivity=float(sensitivity.get().replace(",", ".")),
                button="BTN_SIDE" if button.get() == "Mouse4" else "BTN_EXTRA",
                radius_percent=float(radius_percent.get().replace(",", ".")),
                target="head" if target_var.get() == "Голова" else "body",
                include_teammates=include_teammates.get(),
            )
            # Re-read to preserve camera changes made in another settings dialog.
            updated = replace(Settings.load(settings_path), aim=aim)
            updated.save(settings_path)
            on_apply(updated)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Автонаводка не настроена", str(exc), parent=dialog)
            return
        dialog.destroy()

    ttk.Button(dialog, text="Применить", command=apply).grid(row=8, column=1, padx=10, pady=10, sticky="e")
