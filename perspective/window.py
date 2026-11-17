"""Tk window: white 3D view, crosshair, and aspect-preserving black bars."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .config import GameVideo, Settings, SettingsError, discover_cfg_dirs
from .connection import RadarConnection
from .scene import Camera, Frame, Vec3, fit_viewport


class PerspectiveWindow:
    def __init__(self, root: tk.Tk, settings: Settings, settings_path: Path) -> None:
        self.root, self.settings, self.settings_path = root, settings, settings_path
        self.frame = Frame((), "Ожидание helper")
        self.last_frame_at = 0.0
        self.connection_status = "Подключение к helper…"
        self.profiles = discover_cfg_dirs()
        self.video = GameVideo.read(None)
        self.profile_key = ""
        self.labels: dict[str, str] = {"Главный игрок helper": "helper"}
        self.connection = RadarConnection(settings.ws_url)
        self.connection.start()
        root.title("CS2 — Perspective")
        root.minsize(360, 280)
        root.protocol("WM_DELETE_WINDOW", self.close)
        toolbar = ttk.Frame(root, padding=6)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Главный игрок:").pack(side="left")
        self.selected = tk.StringVar()
        self.selector = ttk.Combobox(toolbar, textvariable=self.selected, state="readonly", width=36)
        self.selector.pack(side="left", padx=6, fill="x", expand=True)
        self.selector.bind("<<ComboboxSelected>>", self._select_player)
        ttk.Button(toolbar, text="Настройки", command=self.open_settings).pack(side="left")
        ttk.Button(toolbar, text="Размер × масштаб", command=self.resize).pack(side="left", padx=(6, 0))
        self.status = tk.StringVar()
        ttk.Label(root, textvariable=self.status, padding=5, wraplength=1100).pack(side="bottom", fill="x")
        self.canvas = tk.Canvas(root, background="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_configure)
        self._update_players()
        self._load_video()
        self.resize()
        self.timer = root.after(33, self._tick)

    def _on_configure(self, event: tk.Event[tk.Canvas]) -> None:
        self.draw()

    def _select_player(self, event: tk.Event[ttk.Combobox]) -> None:
        self.settings = replace(self.settings, player=self.labels[self.selected.get()])
        self._save()
        self._load_video()
        self.draw()

    def _save(self) -> None:
        try:
            self.settings.save(self.settings_path)
        except OSError as exc:
            messagebox.showerror("Настройки не сохранены", str(exc), parent=self.root)

    def _update_players(self) -> None:
        labels = {"Главный игрок helper": "helper"}
        labels.update({f"{p.name} · {p.identity}": p.identity for p in self.frame.players})
        if self.settings.player not in labels.values():
            labels[f"{self.settings.player} (вне матча)"] = self.settings.player
        if labels != self.labels or not self.selected.get():
            self.labels = labels
            self.selector["values"] = tuple(labels)
            self.selected.set(next(label for label, identity in labels.items() if identity == self.settings.player))

    def _load_video(self) -> None:
        directory = Path(self.settings.cfg_dir).expanduser() if self.settings.cfg_dir else None
        player = self.frame.selected(self.settings.player)
        if directory is None and player and player.identity.startswith("steam:"):
            account = str(int(player.identity.removeprefix("steam:")) - 76561197960265728)
            directory = next((path for path in self.profiles if path.parents[2].name == account), None)
        if directory is None and not self.settings.cfg_dir and len(self.profiles) == 1:
            directory = self.profiles[0]
        try:
            self.video = GameVideo.read(directory)
        except OSError as exc:
            self.video = GameVideo(None, None, None, f"Не удалось прочитать cfg: {exc}")
        self.profile_key = player.identity if player else ""

    def resize(self) -> None:
        try:
            width, height = self.video.resolution(self.settings)
        except SettingsError:
            width, height = 1280, 720  # Only the window shell; no guessed projection.
        self.root.update_idletasks()
        chrome = max(65, self.root.winfo_height() - self.canvas.winfo_height())
        self.root.geometry(f"{round(width * self.settings.scale)}x{round(height * self.settings.scale) + chrome}")

    def _tick(self) -> None:
        update = self.connection.latest()
        if update is not None:
            self.frame = update.frame or Frame((), "")
            self.connection_status = update.status
            self.last_frame_at = update.received_at
            self._update_players()
            player = self.frame.selected(self.settings.player)
            if (player.identity if player else "") != self.profile_key:
                previous_size = self.video.width, self.video.height
                self._load_video()
                if previous_size != (self.video.width, self.video.height):
                    self.resize()
        self.draw()
        self.timer = self.root.after(33, self._tick)

    def draw(self) -> None:
        canvas = self.canvas
        canvas.delete("scene")
        width, height = float(canvas.winfo_width()), float(canvas.winfo_height())
        if width <= 1 or height <= 1:
            return
        try:
            game_width, game_height = self.video.resolution(self.settings)
        except SettingsError as exc:
            self.status.set(str(exc))
            canvas.create_text(width / 2, height / 2, text=str(exc), fill="white", width=max(100, width - 40), tags="scene")
            return
        aspect = game_width / game_height
        left, top, view_width, view_height = fit_viewport(width, height, aspect, game_width * self.settings.scale)
        canvas.create_rectangle(left, top, left + view_width, top + view_height, fill="white", outline="", tags="scene")
        # All content is clipped to the same viewport; bars remain black under tiling.
        canvas.create_line(width / 2 - 7, height / 2, width / 2 + 7, height / 2, fill="black", tags="scene")
        canvas.create_line(width / 2, height / 2 - 7, width / 2, height / 2 + 7, fill="black", tags="scene")
        player = self.frame.selected(self.settings.player)
        if self.connection_status:
            self.status.set(self.connection_status)
            return
        if time.monotonic() - self.last_frame_at > 2:
            self.status.set("Нет свежих данных helper")
            return
        if player is None or player.dead:
            self.status.set("Ожидание выбранного живого игрока; автоматической подмены игрока нет")
            return
        if player.pitch is None:
            self.status.set("Helper не передаёт вертикальный угол. Перезапустите обновлённый helper")
            return
        fov = self.settings.fov if self.settings.fov is not None else player.fov or self.video.fov
        if fov is None:
            self.status.set("FOV не найден: задайте его вручную в настройках")
            return
        eye = player.eye or player.position.add(Vec3(0, 0, self.settings.eye_height))
        camera = Camera(eye, player.yaw, player.pitch, fov, aspect, game_width * self.settings.scale)
        for other in self.frame.players:
            if other.identity == player.identity or other.dead:
                continue
            for a, b in camera.box(other, width, height, self.settings.body_width, self.settings.body_height):
                canvas.create_line(*a, *b, fill="black", width=2, tags="scene")
        source = "вручную" if self.settings.fov is not None else "helper" if player.fov else "сохранённый cfg"
        missing = []
        if player.eye is None:
            missing.append("высота глаз вручную")
        if any(p.bounds is None for p in self.frame.players if not p.dead and p.identity != player.identity):
            missing.append("размеры тел вручную")
        suffix = f" · {', '.join(missing)}" if missing else ""
        self.status.set(f"{player.name} · {game_width}×{game_height} · FOV {fov:g}° ({source}) · ×{self.settings.scale:g}{suffix}")

    def open_settings(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Параметры камеры")
        dialog.transient(self.root)
        dialog.grab_set()
        entries: dict[str, tk.StringVar] = {}
        fields = (("ws_url", "WebSocket helper", self.settings.ws_url),
                  ("cfg_dir", "Папка cfg CS2 (пусто = поиск)", self.settings.cfg_dir),
                  ("width", "Ширина CS2 (пусто = из cfg)", self.settings.width),
                  ("height", "Высота CS2 (пусто = из cfg)", self.settings.height),
                  ("fov", "FOV при 4:3 (пусто = helper/cfg)", self.settings.fov),
                  ("scale", "Множитель размера окна", self.settings.scale),
                  ("eye_height", "Высота глаз без данных helper", self.settings.eye_height),
                  ("body_width", "Ширина тела без данных helper", self.settings.body_width),
                  ("body_height", "Высота тела без данных helper", self.settings.body_height))
        for row, (key, label, value) in enumerate(fields):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=5)
            variable = tk.StringVar(value="" if value is None else str(value))
            entries[key] = variable
            if key == "cfg_dir":
                ttk.Combobox(dialog, textvariable=variable, values=tuple(map(str, self.profiles)), width=48).grid(row=row, column=1, padx=10)
            else:
                ttk.Entry(dialog, textvariable=variable, width=50).grid(row=row, column=1, padx=10)
        def browse() -> None:
            directory = filedialog.askdirectory(parent=dialog, title="Выберите 730/local/cfg с cs2_video.txt")
            if directory:
                entries["cfg_dir"].set(directory)
        ttk.Button(dialog, text="Выбрать папку…", command=browse).grid(row=1, column=2, padx=5)
        ttk.Label(dialog, text=f"Источник: {self.video.source}\nFOV cfg может отличаться от действующего FOV. viewmodel_fov не используется.\nПропорции берутся из разрешения CS2. При растяжении окна появляются чёрные полосы.",
                  wraplength=680).grid(row=len(fields), column=0, columnspan=3, padx=10, pady=10, sticky="w")
        def apply() -> None:
            raw: dict[str, object] = {key: variable.get().strip() for key, variable in entries.items()}
            raw["player"] = self.settings.player
            try:
                for key in ("width", "height", "fov", "scale", "eye_height", "body_width", "body_height"):
                    text = entries[key].get().strip().replace(",", ".")
                    raw[key] = None if not text else float(text)
                raw["cfg_dir"] = entries["cfg_dir"].get().strip() or None
                updated = Settings.parse(raw)
                updated.save(self.settings_path)
            except (ValueError, OSError) as exc:
                messagebox.showerror("Не удалось применить настройки", str(exc), parent=dialog)
                return
            old_url = self.settings.ws_url
            self.settings = updated
            if old_url != updated.ws_url:
                self.connection.stop()
                self.frame = Frame((), "")
                self.connection_status = "Подключение к helper…"
                self.connection = RadarConnection(updated.ws_url)
                self.connection.start()
                self._update_players()
            self._load_video()
            self.resize()
            dialog.destroy()
            self.draw()
        ttk.Button(dialog, text="Применить", command=apply).grid(row=len(fields) + 1, column=1, pady=12)

    def close(self) -> None:
        self.root.after_cancel(self.timer)
        self.connection.stop()
        self.root.destroy()
