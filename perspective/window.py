"""Tk window: player boxes, gaze rays and an aspect-preserving white viewport."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from functools import partial
import subprocess
import sys
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from .config import GameVideo, Settings, SettingsError, discover_cfg_dirs
from .connection import RadarConnection
from .scene import Camera, Frame, MatrixCamera, Vec3, player_health_strokes, project_view_ray


class PerspectiveWindow:
    def __init__(self, root: tk.Tk, settings: Settings, settings_path: Path) -> None:
        self.root, self.settings, self.settings_path = root, settings, settings_path
        self.frame = Frame((), "Ожидание helper")
        self.last_frame_at = 0.0
        self.connection_status = "Подключение к helper…"
        self.profiles = discover_cfg_dirs()
        self.video = GameVideo.read(None)
        self.profile_key = ""
        self.overlay: subprocess.Popen[bytes] | None = None
        self.overlay_log = Path(__file__).with_name(".runtime") / "overlay.log"
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
        self.overlay_button = ttk.Button(root, text="Включить оверлей поверх CS2", command=self._toggle_overlay)
        self.overlay_button.pack(fill="x", padx=6)
        if not (sys.platform.startswith("linux") or sys.platform == "win32"):
            self.overlay_button.configure(state="disabled")
        self.source = tk.StringVar(value=f"Источник данных: {settings.ws_url}")
        source_bar = ttk.Frame(root, padding=(6, 3))
        source_bar.pack(fill="x")
        ttk.Label(source_bar, textvariable=self.source, wraplength=900).pack(side="left", fill="x", expand=True)
        ttk.Button(source_bar, text="Подключение…", command=self.open_settings).pack(side="right")
        self.status = tk.StringVar()
        ttk.Label(root, textvariable=self.status, padding=5, wraplength=1100).pack(side="bottom", fill="x")
        self.canvas = tk.Canvas(root, background="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_configure)
        self._update_players()
        self._load_video()
        self.resize()
        self.timer = root.after(8, self._tick)

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
        player = self.frame.selected(self.settings.player)
        try:
            self.video = GameVideo.for_player(self.settings, player, self.profiles)
        except OSError as exc:
            self.video = GameVideo(None, None, None, f"Не удалось прочитать cfg: {exc}")
        self.profile_key = player.identity if player else ""

    def _stop_overlay(self) -> None:
        if self.overlay is not None:
            if self.overlay.poll() is None:
                self.overlay.terminate()
                try:
                    self.overlay.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.overlay.kill()
                    self.overlay.wait()
            self.overlay = None
        self.overlay_button.configure(text="Включить оверлей поверх CS2")

    def _toggle_overlay(self) -> None:
        if self.overlay is not None and self.overlay.poll() is None:
            self._stop_overlay()
            return
        try:
            self.settings.save(self.settings_path)
            self.overlay_log.parent.mkdir(exist_ok=True)
            with self.overlay_log.open("wb") as log:
                self.overlay = subprocess.Popen([sys.executable, "-m", "perspective", "--overlay"],
                                                cwd=Path(__file__).resolve().parent.parent,
                                                stdout=subprocess.DEVNULL, stderr=log)
            self.overlay_button.configure(text="Выключить оверлей")
        except OSError as exc:
            messagebox.showerror("Оверлей не запущен", str(exc), parent=self.root)

    def resize(self) -> None:
        try:
            width, height = self.video.resolution(self.settings)
        except SettingsError:
            width, height = 1280, 720  # Only the window shell; no guessed projection.
        self.root.update_idletasks()
        chrome = max(65, self.root.winfo_height() - self.canvas.winfo_height())
        self.root.geometry(f"{round(width * self.settings.scale)}x{round(height * self.settings.scale) + chrome}")

    def _tick(self) -> None:
        if self.overlay is not None and self.overlay.poll() is not None:
            code = self.overlay.returncode
            self._stop_overlay()
            if code:
                try:
                    detail = self.overlay_log.read_text(encoding="utf-8", errors="replace")[-1000:]
                except OSError:
                    detail = f"Код завершения: {code}"
                messagebox.showerror("Оверлей завершился", detail, parent=self.root)
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
        if update is not None or (self.frame.players and time.monotonic() - self.last_frame_at > 2):
            self.draw()
        self.timer = self.root.after(8, self._tick)

    def _show_status(self, message: str) -> None:
        """Показывает причину ожидания в строке состояния и на поле перспективы."""
        self.status.set(message)
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.canvas.create_text(width / 2, height / 2, text=message, fill="white",
                                width=max(100, width - 40), tags="scene")

    def draw(self) -> None:
        """Рисует перспективу, сохраняя приоритет состояния источника данных."""
        canvas = self.canvas
        canvas.delete("scene")
        width, height = float(canvas.winfo_width()), float(canvas.winfo_height())
        if width <= 1 or height <= 1:
            return
        if self.connection_status:
            self._show_status(self.connection_status)
            return
        if time.monotonic() - self.last_frame_at > 2:
            self._show_status("Нет свежих данных helper")
            return
        player = self.frame.selected(self.settings.player)
        if player is None or player.dead:
            self._show_status("Ожидание выбранного живого игрока; автоматической подмены игрока нет")
            return
        try:
            game_width, game_height = self.video.resolution(self.settings)
        except SettingsError as exc:
            self._show_status(str(exc))
            return
        matrix = self.frame.local_camera(player, self.settings.fov)
        camera: Camera | MatrixCamera
        fov: float | None
        if matrix is not None:
            camera = replace(matrix, maximum_width=game_width * self.settings.scale)
            fov = matrix.fov
            source = "матрица игры"
        else:
            if player.pitch is None:
                self._show_status("Helper не передаёт вертикальный угол. Перезапустите обновлённый helper")
                return
            fov = self.settings.fov if self.settings.fov is not None else player.fov or self.video.fov
            if fov is None:
                self._show_status("FOV не найден: задайте его вручную в настройках")
                return
            eye = player.eye or player.position.add(Vec3(0, 0, self.settings.eye_height))
            camera = Camera(eye, player.yaw, player.pitch, fov, game_width / game_height,
                            game_width * self.settings.scale)
            source = "вручную" if self.settings.fov is not None else "helper" if player.fov else "сохранённый cfg"
        left, top, view_width, view_height = camera.viewport(width, height)
        canvas.create_rectangle(left, top, left + view_width, top + view_height, fill="white", outline="", tags="scene")
        # All content is clipped to the same viewport; bars remain black under tiling.
        if self.settings.show_view_rays:
            for other in self.frame.players:
                if other.identity == player.identity or other.dead:
                    continue
                ray = project_view_ray(camera.project_edge, other, width, height, self.settings.eye_height)
                if ray is not None:
                    a, b = ray
                    canvas.create_line(*a, *b, fill="black", width=3, tags=("scene", "view-ray"))
                    canvas.create_line(*a, *b, fill=self.settings.player_color(other, player),
                                       width=1.5, tags=("scene", "view-ray"))
        for other in self.frame.players:
            if other.identity == player.identity or other.dead:
                continue
            segments = camera.box(other, width, height, self.settings.body_width, self.settings.body_height)
            for a, b in segments:
                canvas.create_line(*a, *b, fill="black", width=4, tags="scene")
            for stroke in player_health_strokes(segments, other.health, self.settings.player_color(other, player)):
                a, b = stroke.segment
                canvas.create_line(*a, *b, fill=stroke.color, width=2, tags="scene")
        missing = []
        if matrix is None and player.eye is None:
            missing.append("высота глаз вручную")
        if any(p.bounds is None for p in self.frame.players if not p.dead and p.identity != player.identity):
            missing.append("размеры тел вручную")
        suffix = f" · {', '.join(missing)}" if missing else ""
        self.status.set(f"{player.name} · {game_width}×{game_height} · FOV {fov:g}° ({source}) · ×{self.settings.scale:g}{suffix}")

    def _apply_settings(self, updated: Settings) -> None:
        """Применяет настройки и очищает старую сцену при смене источника."""
        old_url = self.settings.ws_url
        self.settings = updated
        self.source.set(f"Источник данных: {updated.ws_url}")
        if old_url != updated.ws_url:
            self.connection.stop()
            self.frame = Frame((), "")
            self.last_frame_at = 0.0
            self.connection_status = "Подключение к helper…"
            self.connection = RadarConnection(updated.ws_url)
            self.connection.start()
            self._update_players()
        self._load_video()
        self.resize()
        self.draw()

    def open_settings(self) -> None:
        """Открывает параметры источника данных и камеры."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Источник данных и параметры камеры")
        dialog.transient(self.root)
        dialog.grab_set()
        entries: dict[str, tk.StringVar] = {}
        fields = (("ws_url", "Источник данных (WebSocket helper)", self.settings.ws_url),
                  ("cfg_dir", "Папка cfg CS2 (пусто = поиск)", self.settings.cfg_dir),
                  ("width", "Ширина CS2 (пусто = из cfg)", self.settings.width),
                  ("height", "Высота CS2 (пусто = из cfg)", self.settings.height),
                  ("fov", "FOV при 4:3 (пусто = автоматически)", self.settings.fov),
                  ("scale", "Множитель размера окна", self.settings.scale),
                  ("eye_height", "Высота глаз без данных helper", self.settings.eye_height),
                  ("body_width", "Ширина тела без данных helper", self.settings.body_width),
                  ("body_height", "Высота тела без данных helper", self.settings.body_height),
                  ("teammate_color", "Цвет союзников", self.settings.teammate_color),
                  ("enemy_color", "Цвет врагов", self.settings.enemy_color))
        def choose_color(variable: tk.StringVar) -> None:
            _, color = colorchooser.askcolor(color=variable.get(), parent=dialog, title="Цвет рамок")
            if color is not None:
                variable.set(color)
        for row, (key, label, value) in enumerate(fields):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=5)
            variable = tk.StringVar(value="" if value is None else str(value))
            entries[key] = variable
            if key == "cfg_dir":
                ttk.Combobox(dialog, textvariable=variable, values=tuple(map(str, self.profiles)), width=48).grid(row=row, column=1, padx=10)
            else:
                ttk.Entry(dialog, textvariable=variable, width=50).grid(row=row, column=1, padx=10)
            if key in ("teammate_color", "enemy_color"):
                ttk.Button(dialog, text="Выбрать цвет…", command=partial(choose_color, variable)).grid(row=row, column=2, padx=5)
        def browse() -> None:
            directory = filedialog.askdirectory(parent=dialog, title="Выберите 730/local/cfg с cs2_video.txt")
            if directory:
                entries["cfg_dir"].set(directory)
        ttk.Button(dialog, text="Выбрать папку…", command=browse).grid(row=1, column=2, padx=5)
        stretch = tk.BooleanVar(value=self.settings.overlay_stretch)
        ttk.Checkbutton(dialog, text="Оверлей: CS2 растягивает картинку на всё окно (без полос)", variable=stretch).grid(
            row=len(fields), column=0, columnspan=3, padx=10, pady=5, sticky="w")
        view_rays = tk.BooleanVar(value=self.settings.show_view_rays)
        ttk.Checkbutton(dialog, text="Направление взгляда игроков", variable=view_rays).grid(
            row=len(fields) + 1, column=0, columnspan=3, padx=10, pady=5, sticky="w")
        ttk.Label(dialog, text=f"Адрес источника: ws://КОМПЬЮТЕР:22006/cs2_webradar (HTTP сайта — отдельно, 5173).\nНастройка действует и для оверлея поверх CS2.\nИсточник cfg: {self.video.source}\nЛокальная камера автоматически использует матрицу игры; ручной FOV отключает её.\nFOV cfg может отличаться от действующего FOV. viewmodel_fov не используется.\nМасштаб действует на отдельное окно; оверлей совмещается с полной игровой областью.",
                  wraplength=680).grid(row=len(fields) + 2, column=0, columnspan=3, padx=10, pady=10, sticky="w")
        def apply() -> None:
            raw: dict[str, object] = {key: variable.get().strip() for key, variable in entries.items()}
            raw["player"] = self.settings.player
            raw["overlay_stretch"] = stretch.get()
            raw["show_view_rays"] = view_rays.get()
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
            self._apply_settings(updated)
            dialog.destroy()
        ttk.Button(dialog, text="Применить", command=apply).grid(row=len(fields) + 3, column=1, pady=12)

    def close(self) -> None:
        self.root.after_cancel(self.timer)
        self._stop_overlay()
        self.connection.stop()
        self.root.destroy()
