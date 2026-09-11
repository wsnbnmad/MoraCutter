from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import numpy as np

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    AppBase = TkinterDnD.Tk
except ImportError:
    DND_FILES = None
    AppBase = tk.Tk

from . import __version__
from .audio import AudioError, decode_mono, estimate_pitch, export_segment, play, probe, quality_metrics, safe_filename
# 自動音声認識は手入力版へ戻す間、UI・起動経路から外している。
# from .detection import DISPLAY_RATE, baseline_detect, discover_models, external_detect
from .detection import DISPLAY_RATE
from .domain import AudioSource, Project, Segment
from .history import History
from .japanese import labels_for_unit
# from .precision_detection import mfa_detect, kotoba_reazon_silero_detect
from .project_io import load_project, save_project
# from .whisper_detection import WhisperCancelled, whisper_detect


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
UNIT_LABELS = {"モーラ": "mora", "一文字": "character", "音素": "phoneme"}
UNIT_NAMES = {value: key for key, value in UNIT_LABELS.items()}

# Canonical spelling used by the shared collection list.  Manual labels may be
# entered in either kana or romaji, so counting must not treat あ and a as
# different sounds.
KANA_TO_ROMAJI = {
    kana: roman
    for kana_row, roman_row in (
        (("あ", "い", "う", "え", "お"), ("a", "i", "u", "e", "o")),
        (("か", "き", "く", "け", "こ"), ("ka", "ki", "ku", "ke", "ko")),
        (("さ", "し", "す", "せ", "そ"), ("sa", "shi", "su", "se", "so")),
        (("た", "ち", "つ", "て", "と"), ("ta", "chi", "tsu", "te", "to")),
        (("な", "に", "ぬ", "ね", "の"), ("na", "ni", "nu", "ne", "no")),
        (("は", "ひ", "ふ", "へ", "ほ"), ("ha", "hi", "fu", "he", "ho")),
        (("ま", "み", "む", "め", "も"), ("ma", "mi", "mu", "me", "mo")),
        (("や", "ゆ", "よ"), ("ya", "yu", "yo")), (("ら", "り", "る", "れ", "ろ"), ("ra", "ri", "ru", "re", "ro")),
        (("わ", "を", "ん"), ("wa", "wo", "n")), (("が", "ぎ", "ぐ", "げ", "ご"), ("ga", "gi", "gu", "ge", "go")),
        (("ざ", "じ", "ず", "ぜ", "ぞ"), ("za", "ji", "zu", "ze", "zo")), (("だ", "ぢ", "づ", "で", "ど"), ("da", "ji", "zu", "de", "do")),
        (("ば", "び", "ぶ", "べ", "ぼ"), ("ba", "bi", "bu", "be", "bo")), (("ぱ", "ぴ", "ぷ", "ぺ", "ぽ"), ("pa", "pi", "pu", "pe", "po")),
        (("きゃ", "きゅ", "きょ"), ("kya", "kyu", "kyo")), (("ぎゃ", "ぎゅ", "ぎょ"), ("gya", "gyu", "gyo")),
        (("しゃ", "しゅ", "しょ"), ("sha", "shu", "sho")), (("じゃ", "じゅ", "じょ"), ("ja", "ju", "jo")),
        (("ちゃ", "ちゅ", "ちょ"), ("cha", "chu", "cho")), (("にゃ", "にゅ", "にょ"), ("nya", "nyu", "nyo")),
        (("ひゃ", "ひゅ", "ひょ"), ("hya", "hyu", "hyo")), (("びゃ", "びゅ", "びょ"), ("bya", "byu", "byo")),
        (("ぴゃ", "ぴゅ", "ぴょ"), ("pya", "pyu", "pyo")), (("みゃ", "みゅ", "みょ"), ("mya", "myu", "myo")),
        (("りゃ", "りゅ", "りょ"), ("rya", "ryu", "ryo")),
    )
    for kana, roman in zip(kana_row, roman_row)
}
ROMAJI_ALIASES = {"si": "shi", "ti": "chi", "tu": "tsu", "hu": "fu", "zi": "ji", "di": "ji", "du": "zu"}


def _canonical_pronunciation(value: str) -> str:
    value = value.strip().lower()
    return KANA_TO_ROMAJI.get(value, ROMAJI_ALIASES.get(value, value))


def _peak_envelope(samples: np.ndarray, bins: int) -> np.ndarray:
    """Return one absolute peak per screen column without Python-level loops."""
    absolute = np.abs(np.asarray(samples, dtype=np.float32))
    if len(absolute) == 0 or bins <= 0:
        return np.empty(0, dtype=np.float32)
    bins = min(int(bins), len(absolute))
    if bins == len(absolute):
        return absolute
    edges = np.linspace(0, len(absolute), bins + 1, dtype=np.int64)
    return np.maximum.reduceat(absolute, edges[:-1])


'''
class FlickKanaPad(tk.Toplevel):
    """Small smartphone-style kana flick pad for one-character labelling."""

    GROUPS = (
        ("あ", "い", "う", "え", "お"), ("か", "き", "く", "け", "こ"), ("さ", "し", "す", "せ", "そ"),
        ("た", "ち", "つ", "て", "と"), ("な", "に", "ぬ", "ね", "の"), ("は", "ひ", "ふ", "へ", "ほ"),
        ("ま", "み", "む", "め", "も"), ("や", "ゃ", "ゆ", "ゅ", "よ"), ("ら", "り", "る", "れ", "ろ"),
        ("わ", "を", "ん", "ー", "っ"), ("ぁ", "ぃ", "ぅ", "ぇ", "ぉ"), ("が", "ぎ", "ぐ", "げ", "ご"),
        ("ざ", "じ", "ず", "ぜ", "ぞ"), ("だ", "ぢ", "づ", "で", "ど"), ("ば", "び", "ぶ", "べ", "ぼ"),
        ("ぱ", "ぴ", "ぷ", "ぺ", "ぽ"), ("ゔ", "ゐ", "ゔ", "ゑ", "を"), ("小", "ゃ", "ゅ", "ょ", "っ"),
    )
    ROMAJI = {
        "a":"あ", "i":"い", "u":"う", "e":"え", "o":"お", "ka":"か", "ki":"き", "ku":"く", "ke":"け", "ko":"こ",
        "sa":"さ", "shi":"し", "si":"し", "su":"す", "se":"せ", "so":"そ", "ta":"た", "chi":"ち", "ti":"ち", "tsu":"つ", "tu":"つ", "te":"て", "to":"と",
        "na":"な", "ni":"に", "nu":"ぬ", "ne":"ね", "no":"の", "ha":"は", "hi":"ひ", "fu":"ふ", "hu":"ふ", "he":"へ", "ho":"ほ",
        "ma":"ま", "mi":"み", "mu":"む", "me":"め", "mo":"も", "ya":"や", "yu":"ゆ", "yo":"よ", "ra":"ら", "ri":"り", "ru":"る", "re":"れ", "ro":"ろ",
        "wa":"わ", "wo":"を", "n":"ん", "nn":"ん", "ga":"が", "gi":"ぎ", "gu":"ぐ", "ge":"げ", "go":"ご", "za":"ざ", "ji":"じ", "zi":"じ", "zu":"ず", "ze":"ぜ", "zo":"ぞ",
        "da":"だ", "di":"ぢ", "du":"づ", "de":"で", "do":"ど", "ba":"ば", "bi":"び", "bu":"ぶ", "be":"べ", "bo":"ぼ", "pa":"ぱ", "pi":"ぴ", "pu":"ぷ", "pe":"ぺ", "po":"ぽ",
        "xa":"ぁ", "xi":"ぃ", "xu":"ぅ", "xe":"ぇ", "xo":"ぉ", "xya":"ゃ", "xyu":"ゅ", "xyo":"ょ", "xtsu":"っ", "ltsu":"っ", "-":"ー",
    }

    def __init__(self, parent: tk.Misc, on_select: callable) -> None:
        super().__init__(parent)
        self.title("発音を選択")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.on_select = on_select
        self.page = 0
        self.cell_size = 86
        self.pressed: tuple[int, float, float] | None = None
        self.keyboard_group = 0
        ttk.Label(self, text="スマホのフリック入力  |  クリック＝中央、ドラッグ＝方向  |  1–9/0＋矢印でも選択").pack(padx=8, pady=(8, 3))
        self.canvas = tk.Canvas(self, width=self.cell_size * 3, height=self.cell_size * 4, bg="#20252c", highlightthickness=0)
        self.canvas.pack(padx=8, pady=4)
        lower = ttk.Frame(self)
        lower.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Button(lower, text="濁音・小文字", command=self._toggle_page).pack(side="left")
        ttk.Button(lower, text="取消", command=self.destroy).pack(side="right")
        self.ime_var = tk.StringVar()
        entry = ttk.Entry(lower, textvariable=self.ime_var, width=8)
        entry.pack(side="right", padx=(0, 5))
        ttk.Label(lower, text="IME/ローマ字 ").pack(side="right")
        entry.bind("<Return>", self._ime_commit)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<KeyPress>", self._key)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._draw()
        self.after(20, self.focus_force)

    def _groups(self) -> tuple[tuple[str, ...], ...]:
        return self.GROUPS[:12] if self.page == 0 else self.GROUPS[6:18]

    def _draw(self) -> None:
        self.canvas.delete("all")
        groups = self._groups()
        for index, group in enumerate(groups):
            col, row = index % 3, index // 3
            x, y = col * self.cell_size, row * self.cell_size
            fill = "#3b6f8e" if index == self.keyboard_group else "#313b47"
            self.canvas.create_rectangle(x + 2, y + 2, x + self.cell_size - 2, y + self.cell_size - 2, fill=fill, outline="#7aa6bd")
            self.canvas.create_text(x + self.cell_size / 2, y + self.cell_size / 2, text=group[0], fill="white", font=("Yu Gothic UI", 22, "bold"))
            self.canvas.create_text(x + 9, y + self.cell_size / 2, text=group[1], fill="#b6d8e8", anchor="w", font=("Yu Gothic UI", 9))
            self.canvas.create_text(x + self.cell_size / 2, y + 9, text=group[2], fill="#b6d8e8", anchor="n", font=("Yu Gothic UI", 9))
            self.canvas.create_text(x + self.cell_size - 9, y + self.cell_size / 2, text=group[3], fill="#b6d8e8", anchor="e", font=("Yu Gothic UI", 9))
            self.canvas.create_text(x + self.cell_size / 2, y + self.cell_size - 9, text=group[4], fill="#b6d8e8", anchor="s", font=("Yu Gothic UI", 9))

    def _cell_at(self, x: float, y: float) -> int | None:
        col, row = int(x // self.cell_size), int(y // self.cell_size)
        index = row * 3 + col
        return index if 0 <= col < 3 and 0 <= row < 4 and index < len(self._groups()) else None

    def _press(self, event: tk.Event) -> None:
        index = self._cell_at(event.x, event.y)
        if index is not None:
            self.pressed = (index, float(event.x), float(event.y))
            self.keyboard_group = index
            self._draw()

    def _release(self, event: tk.Event) -> None:
        if self.pressed is None:
            return
        index, x, y = self.pressed
        dx, dy = float(event.x) - x, float(event.y) - y
        threshold = 18
        variant = 0 if max(abs(dx), abs(dy)) < threshold else (1 if abs(dx) >= abs(dy) and dx < 0 else 3 if abs(dx) >= abs(dy) else 2 if dy < 0 else 4)
        self._select(self._groups()[index][variant])

    def _key(self, event: tk.Event) -> str | None:
        if event.char.isdigit() and event.char != "0":
            self.keyboard_group = int(event.char) - 1
            self._draw()
            return "break"
        if event.char == "0":
            self.keyboard_group = 9
            self._draw()
            return "break"
        variants = {"Left": 1, "Up": 2, "Right": 3, "Down": 4, "Return": 0, "space": 0}
        if event.keysym in variants and self.keyboard_group < len(self._groups()):
            self._select(self._groups()[self.keyboard_group][variants[event.keysym]])
            return "break"
        if event.keysym == "Escape":
            self.destroy()
            return "break"
        return None

    def _ime_commit(self, _event: tk.Event) -> str:
        value = self.ime_var.get().strip()
        if value:
            normalized = value.lower().replace(" ", "")
            self._select(self.ROMAJI.get(normalized, value[-1]))
        return "break"

    def _toggle_page(self) -> None:
        self.page = 1 - self.page
        self.keyboard_group = 0
        self._draw()

    def _select(self, label: str) -> None:
        self.grab_release()
        self.destroy()
        self.on_select(label)


'''


class MoraCutterApp(AppBase):
    def __init__(self) -> None:
        super().__init__()
        self.title("Mora Cutter MVP")
        self.geometry("1420x880")
        self.minsize(1050, 680)

        self.project = Project()
        self.project_path: str | None = None
        self.current_source_id: str | None = None
        self.current_samples: np.ndarray | None = None
        self.current_segment_id: str | None = None
        self.draft_segment: Segment | None = None
        self.manual_next_start = 0.0
        self.selection = (0.0, 0.0)
        self.drag_mode = ""
        self.drag_anchor = 0.0
        self.zoom_level = 1.0
        self.viewport_start = 0.0
        self.spectrum_expanded = False
        self._viewport_redraw_job: str | None = None
        self._suppress_viewport_command = False
        self.pan_anchor_x = 0.0
        self.pan_start_viewport = 0.0
        self.pan_visual_dx = 0.0
        self.canvas_press_x = 0.0
        self.canvas_dragged = False
        self._scrub_was_playing = False
        self._pointer_resume_end = 0.0
        self._pointer_resume_loop = False
        self.history = History(100)
        self.player: subprocess.Popen[bytes] | None = None
        self.playhead_time = 0.0
        self._playback_started_at = 0.0
        self._playback_start = 0.0
        self._playback_end = 0.0
        self._playback_speed = 1.0
        self._playback_loop = False
        self._playback_path = ""
        self._playback_gain_db = 0.0
        self.jobs: queue.Queue[tuple[str, object]] = queue.Queue()
        self._spectrogram_photo: tk.PhotoImage | None = None
        self._wave_cache_key: tuple[object, ...] | None = None
        self._wave_cache_peaks: np.ndarray | None = None
        self._wave_render_key: tuple[object, ...] | None = None
        self._spectrogram_cache_key: tuple[object, ...] | None = None
        self._viewport_interacting = False
        self._dirty = False
        # 自動音声認識は現在保留（手入力切り出しに専念する版）。
        self._detection_running = False
        self._detection_cancel_event: threading.Event | None = None
        self._detail_apply_job: str | None = None
        self._suppress_detail_apply = False
        self.list_sort_key = "start"
        self.list_sort_reverse = False
        self._coverage_filter_labels: set[str] | None = None

        # self.models = discover_models(APP_DIR / "models")  # 自動認識を再開するまで保留
        self._build_style()
        self._build_menu()
        self._build_ui()
        self._enable_file_drop()
        self._bind_keys()
        self.after(100, self._poll_jobs)
        self.after(1000, self._schedule_autosave)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._offer_recovery()

    def _build_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=25)
        style.configure("Accent.TButton", font=("TkDefaultFont", 10, "bold"))

    def _build_menu(self) -> None:
        bar = tk.Menu(self)
        self.file_menu = tk.Menu(bar, tearoff=False, postcommand=self._refresh_file_menu)
        self._refresh_file_menu()
        bar.add_cascade(label="ファイル", menu=self.file_menu)

        edit_menu = tk.Menu(bar, tearoff=False)
        edit_menu.add_command(label="元に戻す", command=self.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="やり直す", command=self.redo, accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="候補を削除", command=self.delete_segment, accelerator="Delete")
        bar.add_cascade(label="編集", menu=edit_menu)

        view_menu = tk.Menu(bar, tearoff=False)
        view_menu.add_command(label="五十音の収集状況", command=self.show_coverage)
        view_menu.add_command(label="設定", command=self.show_settings)
        bar.add_cascade(label="表示", menu=view_menu)

        help_menu = tk.Menu(bar, tearoff=False)
        help_menu.add_command(label="動作環境を確認", command=self.check_environment)
        help_menu.add_command(label="このアプリについて", command=lambda: messagebox.showinfo("Mora Cutter", f"Mora Cutter MVP {__version__}\nローカル・非破壊音声切り出し支援"))
        bar.add_cascade(label="ヘルプ", menu=help_menu)
        self.config(menu=bar)

    def _recent_projects_path(self) -> Path:
        return APP_DIR / "recent_projects.json"

    def _recent_projects(self) -> list[str]:
        try:
            values = json.loads(self._recent_projects_path().read_text(encoding="utf-8"))
            return [str(Path(value)) for value in values if Path(value).is_file()][:12]
        except (OSError, ValueError, TypeError):
            return []

    def _remember_project(self, path: str) -> None:
        target = str(Path(path).resolve())
        values = [value for value in self._recent_projects() if value != target]
        values.insert(0, target)
        try:
            self._recent_projects_path().write_text(json.dumps(values[:12], ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _refresh_file_menu(self) -> None:
        menu = self.file_menu
        menu.delete(0, "end")
        menu.add_command(label="新規プロジェクト", command=self.new_project, accelerator="Ctrl+N")
        menu.add_command(label="プロジェクトを開く…", command=self.open_project, accelerator="Ctrl+O")
        menu.add_command(label="保存", command=self.save, accelerator="Ctrl+S")
        menu.add_command(label="名前を付けて保存…", command=self.save_as)
        recent = self._recent_projects()
        if recent:
            menu.add_separator()
            menu.add_command(label="最近のプロジェクト", state="disabled")
            for index, path in enumerate(recent, 1):
                menu.add_command(label=f"{Path(path).name}\tAlt+{index}", command=lambda value=path: self._load_project_path(value))
        menu.add_separator()
        menu.add_command(label="音声を追加…", command=self.add_audio, accelerator="Ctrl+I")
        menu.add_command(label="復旧ファイルを開く…", command=self.open_recovery)
        menu.add_separator()
        menu.add_command(label="書き出し…", command=self.export_all, accelerator="Ctrl+E")
        menu.add_command(label="終了", command=self._on_close)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 7))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="＋ 音声を追加", command=self.add_audio).pack(side="left")
        self.play_button = ttk.Button(toolbar, text="▶ cueから再生 (C)", command=self.play_cue)
        self.play_button.pack(side="left", padx=(8, 0))
        self.stop_button = ttk.Button(toolbar, text="■ 停止", command=self.stop_audio)
        self.stop_button.pack(side="left", padx=(4, 0))
        ttk.Button(toolbar, text="↻ ループ", command=lambda: self.play_cue(loop=True)).pack(side="left", padx=(4, 0))
        ttk.Label(toolbar, text="速度").pack(side="left", padx=(16, 4))
        self.speed_var = tk.StringVar(value="1.0")
        ttk.Combobox(toolbar, textvariable=self.speed_var, values=("0.5", "0.75", "1.0", "1.25", "1.5", "2.0"), width=6, state="readonly").pack(side="left")
        ttk.Label(toolbar, text="波形表示").pack(side="left", padx=(12, 3))
        self.wave_gain_var = tk.DoubleVar(value=0.0)
        ttk.Scale(toolbar, from_=-18, to=18, variable=self.wave_gain_var, command=lambda _: self.draw_audio(), length=92).pack(side="left")
        self.wave_gain_label = ttk.Label(toolbar, text="0 dB", width=6)
        self.wave_gain_label.pack(side="left")
        self.wave_gain_var.trace_add("write", lambda *_: self.wave_gain_label.config(text=f"{self.wave_gain_var.get():+.0f} dB"))
        ttk.Label(toolbar, text="再生音量").pack(side="left", padx=(10, 3))
        self.playback_gain_var = tk.DoubleVar(value=0.0)
        ttk.Scale(toolbar, from_=-48, to=12, variable=self.playback_gain_var, length=92).pack(side="left")
        self.playback_gain_label = ttk.Label(toolbar, text="0 dB", width=6)
        self.playback_gain_label.pack(side="left")
        self.playback_gain_var.trace_add("write", lambda *_: self.playback_gain_label.config(text=f"{self.playback_gain_var.get():+.0f} dB"))
        ttk.Button(toolbar, text="五十音表", command=self.show_coverage).pack(side="right")
        ttk.Button(toolbar, text="書き出し", style="Accent.TButton", command=self.export_all).pack(side="right", padx=8)

        outer = ttk.Panedwindow(self, orient="horizontal")
        outer.pack(fill="both", expand=True, padx=8)

        left = ttk.Frame(outer, width=230)
        outer.add(left, weight=0)
        ttk.Label(left, text="素材ファイル", font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(4, 5))
        self.source_list = tk.Listbox(left, activestyle="dotbox", exportselection=False)
        self.source_list.pack(fill="both", expand=True)
        self.source_list.bind("<<ListboxSelect>>", self._source_selected)
        ttk.Button(left, text="選択した素材を除外", command=self.remove_source).pack(fill="x", pady=5)
        ttk.Separator(left).pack(fill="x", pady=8)
        self.manual_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(left, text="手動切り出しモード", variable=self.manual_mode_var, command=self._manual_mode_changed).pack(anchor="w", pady=(8, 0))

        center_right = ttk.Panedwindow(outer, orient="vertical")
        outer.add(center_right, weight=1)

        visual = ttk.Frame(center_right)
        center_right.add(visual, weight=3)
        title_row = ttk.Frame(visual)
        title_row.pack(fill="x", pady=(2, 3))
        self.source_title = ttk.Label(title_row, text="音声を追加してください", font=("TkDefaultFont", 11, "bold"))
        self.source_title.pack(side="left")
        self.time_label = ttk.Label(title_row, text="00:00.000")
        self.time_label.pack(side="right")

        self.wave_canvas = tk.Canvas(visual, height=205, bg="#11151b", highlightthickness=1, highlightbackground="#3a4653", cursor="crosshair")
        self.wave_canvas.pack(fill="x", expand=True)
        self.wave_canvas.bind("<ButtonPress-1>", self._canvas_press)
        self.wave_canvas.bind("<B1-Motion>", self._canvas_drag)
        self.wave_canvas.bind("<ButtonRelease-1>", self._canvas_release)
        self.wave_canvas.bind("<Double-Button-1>", self._canvas_double_click)
        self.wave_canvas.bind("<ButtonPress-3>", self._range_press)
        self.wave_canvas.bind("<B3-Motion>", self._range_drag)
        self.wave_canvas.bind("<ButtonRelease-3>", self._range_release)
        self.wave_canvas.bind("<Motion>", self._canvas_motion)
        self.wave_canvas.bind("<MouseWheel>", self._zoom_wheel)
        self.wave_canvas.bind("<Button-4>", self._zoom_wheel)
        self.wave_canvas.bind("<Button-5>", self._zoom_wheel)

        navigation = ttk.Frame(visual, padding=(0, 4))
        navigation.pack(fill="x")
        ttk.Button(navigation, text="－", width=3, command=lambda: self.change_zoom(-1)).pack(side="left")
        self.zoom_label = ttk.Label(navigation, text="1×", width=6, anchor="center")
        self.zoom_label.pack(side="left")
        ttk.Button(navigation, text="＋", width=3, command=lambda: self.change_zoom(1)).pack(side="left")
        ttk.Label(navigation, text=" 表示位置 ").pack(side="left")
        self.viewport_back_button = ttk.Button(navigation, command=lambda: self.move_viewport(-self._viewport_step()))
        self.viewport_back_button.pack(side="left", padx=(2, 3))
        self.viewport_var = tk.DoubleVar(value=0.0)
        self.viewport_scale = ttk.Scale(navigation, from_=0.0, to=1.0, variable=self.viewport_var, command=self._viewport_changed)
        self.viewport_scale.pack(side="left", fill="x", expand=True)
        self.viewport_scale.bind("<ButtonRelease-1>", self._viewport_released)
        self.viewport_forward_button = ttk.Button(navigation, command=lambda: self.move_viewport(self._viewport_step()))
        self.viewport_forward_button.pack(side="left", padx=(3, 2))
        self._update_viewport_step_buttons()
        ttk.Button(navigation, text="全体表示", command=self.reset_zoom).pack(side="left", padx=(5, 0))

        self.spectrum_button = ttk.Button(visual, text="▶ スペクトログラムを展開", command=self.toggle_spectrum)
        self.spectrum_button.pack(fill="x", pady=(1, 0))
        self.spec_canvas = tk.Canvas(visual, height=130, bg="#07090d", highlightthickness=1, highlightbackground="#3a4653")

        action_row = ttk.Frame(visual, padding=(0, 6))
        self.action_row = action_row
        action_row.pack(fill="x")
        self.wave_help_label = ttk.Label(action_row, text="左ドラッグ: 再生位置 / 右ドラッグ: 範囲選択 / 詳細の発音欄でEnter: 候補追加")
        self.wave_help_label.pack(side="left")

        lower = ttk.Panedwindow(center_right, orient="horizontal")
        center_right.add(lower, weight=2)

        candidates = ttk.Frame(lower)
        lower.add(candidates, weight=3)
        search_row = ttk.Frame(candidates)
        search_row.pack(fill="x", pady=(2, 4))
        ttk.Label(search_row, text="リスト", font=("TkDefaultFont", 11, "bold")).pack(side="left")
        self.search_var = tk.StringVar()
        search = ttk.Entry(search_row, textvariable=self.search_var, width=22)
        search.pack(side="right")
        ttk.Label(search_row, text="検索 ").pack(side="right")
        ttk.Button(search_row, text="全表示", command=self._clear_coverage_filter).pack(side="right", padx=(0, 5))
        self.search_var.trace_add("write", self._search_changed)

        columns = ("label", "pitch", "start", "end")
        self.segment_tree = ttk.Treeview(candidates, columns=columns, show="headings", selectmode="browse")
        headings = {"label":"発音", "pitch":"音程", "start":"開始", "end":"終了"}
        widths = {"label":120, "pitch":70, "start":95, "end":95}
        for key in columns:
            command = (lambda column=key: self._sort_list(column)) if key in {"label", "pitch", "start"} else None
            if command is None:
                self.segment_tree.heading(key, text=headings[key])
            else:
                self.segment_tree.heading(key, text=headings[key], command=command)
            self.segment_tree.column(key, width=widths[key], anchor="center", stretch=key == "label")
        self.segment_tree.pack(fill="both", expand=True)
        self.segment_tree.bind("<<TreeviewSelect>>", self._segment_selected)
        self.segment_tree.bind("<Double-1>", lambda _: self.play_cue())

        detail = ttk.LabelFrame(lower, text="候補の詳細", padding=9)
        lower.add(detail, weight=1)
        self.detail_vars = {
            "label": tk.StringVar(), "pitch": tk.StringVar(value="--"),
            "start": tk.StringVar(value="0.000"), "cue": tk.StringVar(value="0.000"), "end": tk.StringVar(value="0.000"),
        }
        self.detail_entries: dict[str, ttk.Entry] = {}
        for row, (key, label) in enumerate((("label", "発音"), ("pitch", "音程"), ("start", "開始 (秒)"), ("cue", "cue (秒)"), ("end", "終了 (秒)"))):
            ttk.Label(detail, text=label).grid(row=row, column=0, sticky="w", pady=3)
            entry = ttk.Entry(detail, textvariable=self.detail_vars[key], width=16)
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=3)
            self.detail_entries[key] = entry
        detail.columnconfigure(1, weight=1)
        for variable in self.detail_vars.values():
            variable.trace_add("write", self._queue_detail_apply)
        ttk.Label(detail, text="入力内容は自動で反映されます", foreground="#68727d").grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 3))
        self.breath_var = tk.BooleanVar()
        self.sigh_var = tk.BooleanVar()
        self.detail_entries["label"].bind("<Return>", self._detail_label_enter)
        ttk.Checkbutton(detail, text="ブレス", variable=self.breath_var, command=lambda: self.apply_voice_type("breath")).grid(row=6, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(detail, text="息", variable=self.sigh_var, command=lambda: self.apply_voice_type("sigh")).grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Button(detail, text="候補を削除", command=self.delete_segment).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 3))

        transcript_frame = ttk.LabelFrame(lower, text="収集用リスト（, で区切る）", padding=7)
        lower.add(transcript_frame, weight=2)
        self.transcript_text = tk.Text(transcript_frame, width=28, height=8, wrap="word", undo=True)
        self.transcript_text.pack(fill="both", expand=True)
        self.transcript_text.bind("<FocusOut>", lambda _: self._save_transcript())
        self.mora_preview = ttk.Label(transcript_frame, text="収集用リスト: 0件", wraplength=280, justify="left")
        self.mora_preview.pack(fill="x", pady=(5, 0))
        self.transcript_text.bind("<KeyRelease>", lambda _: self._update_mora_preview())

        status = ttk.Frame(self, relief="sunken", padding=(7, 3))
        status.pack(fill="x", side="bottom")
        primary = ttk.Frame(status)
        primary.pack(fill="x")
        self.status_var = tk.StringVar(value="準備完了")
        ttk.Label(primary, textvariable=self.status_var, anchor="w").pack(side="left", fill="x", expand=True)
        self.progress_value = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(primary, variable=self.progress_value, maximum=100, length=210)
        self.progress_bar.pack(side="left", padx=(8, 5))
        self.progress_percent_var = tk.StringVar(value="0%")
        ttk.Label(primary, textvariable=self.progress_percent_var, width=5, anchor="e").pack(side="left")
        self.secondary_status_var = tk.StringVar(value="自動保存: 待機中")
        ttk.Label(status, textvariable=self.secondary_status_var, anchor="w", foreground="#68727d").pack(fill="x")

    def _bind_keys(self) -> None:
        self.bind_all("<Button-1>", self._release_text_focus_on_outer_click, add="+")
        self.bind_all("<Button-3>", self._release_text_focus_on_outer_click, add="+")
        self.bind_all("<Control-n>", lambda _: self.new_project())
        self.bind_all("<Control-o>", lambda _: self.open_project())
        self.bind_all("<Control-s>", lambda _: self.save())
        self.bind_all("<Control-i>", lambda _: self.add_audio())
        self.bind_all("<Control-e>", lambda _: self.export_all())
        self.bind_all("<Control-z>", lambda _: self.undo())
        self.bind_all("<Control-y>", lambda _: self.redo())
        self.bind_all("<Delete>", lambda _: self.delete_segment())
        self.bind_all("<Left>", lambda e: self.nudge_cue(-0.001 if not (e.state & 1) else -0.010))
        self.bind_all("<Right>", lambda e: self.nudge_cue(0.001 if not (e.state & 1) else 0.010))
        self.bind_all("<space>", self._toggle_playback)
        self.bind_all("<KeyPress-s>", lambda _e: self.set_draft_marker("start"))
        self.bind_all("<KeyPress-S>", lambda _e: self.set_draft_marker("start"))
        self.bind_all("<KeyPress-c>", self._play_cue_key)
        self.bind_all("<KeyPress-C>", self._play_cue_key)
        self.bind_all("<KeyPress-e>", lambda _e: self.set_draft_marker("end"))
        self.bind_all("<KeyPress-E>", lambda _e: self.set_draft_marker("end"))
        self.bind_all("<Return>", self._commit_key)

    def _text_input_active(self) -> bool:
        return isinstance(self.focus_get(), (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox))

    def _release_text_focus_on_outer_click(self, event: tk.Event) -> None:
        """Let transport shortcuts work again after clicking outside an entry."""
        widget = event.widget
        if widget.winfo_toplevel() is not self:
            return
        if isinstance(widget, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox)):
            return
        self.wave_canvas.focus_set()

    def _toggle_playback(self, _event: object = None) -> str | None:
        if self._text_input_active():
            return None
        self.wave_canvas.focus_set()
        if self.player and self.player.poll() is None:
            self.stop_audio()
        else:
            source = self.current_source()
            if source:
                self._play(source.path, self.playhead_time, min(source.duration, self.playhead_time + 8.0), False)
        return "break"

    def _play_cue_key(self, _event: object = None) -> str | None:
        if self._text_input_active():
            return None
        if self.drag_mode == "selection":
            source = self.current_source()
            start, end = sorted(self.selection)
            if source and end - start >= 0.005:
                self._play(source.path, start, end, False, preserve_pointer=True)
            return "break"
        self.play_cue()
        return "break"

    def _commit_key(self, _event: object = None) -> str | None:
        if self._text_input_active():
            return None
        self.commit_draft()
        return "break"

    def _record(self) -> None:
        self.history.record(self.project)
        self._dirty = True

    def _set_progress(self, percent: float, message: str) -> None:
        value = float(np.clip(percent, 0, 100))
        self.progress_value.set(value)
        self.progress_percent_var.set(f"{int(round(value))}%")
        self.status_var.set(message)

    def _queue_progress(self, percent: float, message: str) -> None:
        self.jobs.put(("progress", (percent, message)))

    def _enable_file_drop(self) -> None:
        if DND_FILES is None or not hasattr(self, "drop_target_register"):
            self.secondary_status_var.set("ドラッグ＆ドロップ: 利用不可（ファイル追加ボタンは使用可能）")
            return
        for widget in (self, self.source_list, self.wave_canvas):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._files_dropped)

    def _files_dropped(self, event: tk.Event) -> str:
        try:
            paths = [str(path) for path in self.tk.splitlist(event.data)]
        except (tk.TclError, AttributeError):
            paths = []
        self._add_audio_paths(paths)
        return "break"

    def undo(self) -> None:
        state = self.history.undo(self.project)
        if state is not None:
            self.project = state
            self._after_project_change("元に戻しました")

    def redo(self) -> None:
        state = self.history.redo(self.project)
        if state is not None:
            self.project = state
            self._after_project_change("やり直しました")

    def _after_project_change(self, status: str) -> None:
        self._dirty = True
        self.refresh_sources()
        self.refresh_segments()
        self._update_mora_preview()
        self.draw_audio()
        self.status_var.set(status)

    def current_source(self) -> AudioSource | None:
        return next((s for s in self.project.sources if s.id == self.current_source_id), None)

    def current_segment(self) -> Segment | None:
        return next((s for s in self.project.segments if s.id == self.current_segment_id), None)

    def add_audio(self) -> None:
        paths = filedialog.askopenfilenames(title="音声ファイルを追加", filetypes=[("音声", "*.wav *.mp3 *.flac *.m4a *.aac *.ogg *.mp4"), ("すべて", "*.*")])
        self._add_audio_paths(paths)

    def _add_audio_paths(self, paths: object) -> None:
        supported = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".mp4"}
        valid = [str(path) for path in paths if Path(str(path)).is_file() and Path(str(path)).suffix.lower() in supported]
        if not valid:
            if paths:
                messagebox.showwarning("追加できません", "対応する音声ファイルがありません。")
            return
        self._set_progress(0, f"{len(valid)}ファイルを確認しています")
        def worker() -> None:
            results: list[AudioSource] = []
            errors: list[str] = []
            for index, path in enumerate(valid, 1):
                self._queue_progress((index-1)/len(valid)*90, f"ファイル確認中: {Path(path).name}")
                try:
                    duration, rate = probe(path)
                    results.append(AudioSource.create(path, duration, rate))
                except Exception as exc:
                    errors.append(f"{Path(path).name}: {exc}")
            self.jobs.put(("audio_added", (results, errors)))
        threading.Thread(target=worker, daemon=True).start()

    def remove_source(self) -> None:
        source = self.current_source()
        if not source or not messagebox.askyesno("素材を除外", f"{source.display_name} と関連候補をプロジェクトから除外しますか？\n元ファイルは削除されません。"):
            return
        self._record()
        self.project.sources = [s for s in self.project.sources if s.id != source.id]
        self.project.segments = [s for s in self.project.segments if s.source_id != source.id]
        self.current_source_id = self.project.sources[0].id if self.project.sources else None
        self.current_samples = None
        self._after_project_change("素材を除外しました")
        self._load_current_audio()

    def refresh_sources(self) -> None:
        selected = self.current_source_id
        self.source_list.delete(0, "end")
        select_index = None
        for i, source in enumerate(self.project.sources):
            count = sum(s.source_id == source.id for s in self.project.segments)
            self.source_list.insert("end", f"{source.display_name}  ({count})")
            if source.id == selected:
                select_index = i
        if select_index is not None:
            self.source_list.selection_set(select_index)

    def _source_selected(self, _: object = None) -> None:
        indexes = self.source_list.curselection()
        if not indexes:
            return
        self._save_transcript()
        self.current_source_id = self.project.sources[indexes[0]].id
        self.current_segment_id = None
        self.draft_segment = None
        self.manual_next_start = 0.0
        self.playhead_time = 0.0
        self.current_samples = None
        self.selection = (0.0, 0.0)
        self.zoom_level = 1.0
        self.viewport_start = 0.0
        self.viewport_var.set(0.0)
        self.zoom_label.config(text="1×")
        self._load_current_audio()

    def _load_current_audio(self) -> None:
        self._clear_visual_cache()
        self._update_viewport_step_buttons()
        source = self.current_source()
        if not source:
            self.source_title.config(text="音声を追加してください")
            self.draw_audio()
            return
        self.source_title.config(text=f"{source.display_name}  •  {self._format_time(source.duration)}  •  {source.sample_rate} Hz")
        self.transcript_text.delete("1.0", "end")
        self.transcript_text.insert("1.0", self.project.collection_list)
        self._update_mora_preview()
        self._set_progress(0, f"表示準備: {source.display_name}")
        source_id = source.id
        def worker() -> None:
            try:
                self._queue_progress(10, f"音声を読み込み中: {source.display_name}")
                samples = decode_mono(source.path, DISPLAY_RATE)
                self.jobs.put(("decoded", (source_id, samples)))
            except Exception as exc:
                self.jobs.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.refresh_segments()

    def _poll_jobs(self) -> None:
        try:
            while True:
                kind, payload = self.jobs.get_nowait()
                if kind == "progress":
                    percent, message = payload  # type: ignore[misc]
                    self._set_progress(percent, message)
                elif kind == "audio_added":
                    sources, errors = payload  # type: ignore[misc]
                    if sources:
                        self._record()
                        self.project.sources.extend(sources)
                        self.current_source_id = sources[0].id
                        self.refresh_sources()
                        self._load_current_audio()
                    if errors:
                        messagebox.showwarning("一部のファイルを読めませんでした", "\n".join(errors))
                    self._set_progress(100, f"{len(sources)}ファイルを追加しました")
                elif kind == "decoded":
                    source_id, samples = payload  # type: ignore[misc]
                    if source_id == self.current_source_id:
                        self.current_samples = samples
                        self._clear_visual_cache()
                        self.draw_audio()
                        self._set_progress(100, "表示データを読み込みました")
                elif kind == "detected":
                    self._finish_detection()
                    source_id, segments = payload  # type: ignore[misc]
                    self._record()
                    removed = self._replace_auto_segments(source_id, segments)
                    if not segments:
                        self._set_progress(100, "候補を検出できませんでした")
                        self.refresh_sources()
                        self.refresh_segments()
                        self.draw_audio()
                        messagebox.showwarning("未検出", f"発声区間を検出できませんでした。以前の自動候補{removed}件は削除しました（元に戻せます）。")
                        continue
                    self.refresh_sources()
                    self.refresh_segments()
                    self.draw_audio()
                    self._set_progress(100, f"再解析完了: 自動候補{removed}件を{len(segments)}件に置換しました（元に戻せます）")
                elif kind == "detected_batch":
                    self._finish_detection()
                    batches, errors = payload  # type: ignore[misc]
                    self._record()
                    added = 0
                    removed = 0
                    for source_id, segments in batches:
                        removed += self._replace_auto_segments(source_id, segments)
                        added += len(segments)
                    self.refresh_sources()
                    self.refresh_segments()
                    self.draw_audio()
                    self._set_progress(100, f"全素材の再解析完了: {removed}件を{added}件に置換（元に戻せます）")
                    if errors:
                        messagebox.showwarning("一括解析（一部失敗）", "\n".join(errors[:15]))
                elif kind == "export_done":
                    exported, errors, folder = payload  # type: ignore[misc]
                    self._set_progress(100, f"{exported}件を書き出しました")
                    if errors:
                        messagebox.showwarning("書き出し完了（一部失敗）", f"{exported}件を書き出しました。\n\n" + "\n".join(errors[:10]))
                    else:
                        messagebox.showinfo("書き出し完了", f"{exported}件を保存しました。\n{folder}")
                elif kind == "error":
                    self._finish_detection()
                    self._set_progress(0, "エラー")
                    messagebox.showerror("エラー", str(payload))
                elif kind == "detection_cancelled":
                    self._finish_detection()
                    self._set_progress(0, "解析をキャンセルしました")
        except queue.Empty:
            pass
        self.after(100, self._poll_jobs)

    def draw_audio(self, interactive: bool = False) -> None:
        source = self.current_source()
        samples = self.current_samples
        if source is None or samples is None or len(samples) == 0:
            self.wave_canvas.delete("all")
            self.spec_canvas.delete("all")
            self.wave_canvas.create_text(self.wave_canvas.winfo_width()/2, 90, text="音声を選択してください", fill="#8e99a5")
            return
        self.update_idletasks()
        width = max(400, self.wave_canvas.winfo_width())
        height = max(160, self.wave_canvas.winfo_height())
        middle = height / 2
        view_start, view_end = self._visible_range()
        sample_start = max(0, int(view_start * DISPLAY_RATE))
        sample_end = min(len(samples), max(sample_start + 1, int(view_end * DISPLAY_RATE)))
        visible_samples = samples[sample_start:sample_end]
        # During scrollbar dragging a compact envelope is enough; a full-width
        # waveform and spectrogram are restored on release.
        bins = min(width if not interactive else 480, len(visible_samples))
        display_gain = float(10 ** (self.wave_gain_var.get() / 20))
        # Selection, cue and playhead updates call draw_audio too.  The waveform
        # itself is immutable until its visible range, size or gain changes, so
        # keep that expensive layer on the Canvas and redraw overlays only.
        render_key = (
            source.id, sample_start, sample_end, width, height,
            round(display_gain, 6), self.spectrum_expanded,
            self.spec_canvas.winfo_height() if self.spectrum_expanded else 0,
            bins, interactive,
        )
        if render_key == self._wave_render_key:
            self._draw_overlays()
            return
        cache_key = (source.id, sample_start, sample_end, bins)
        if cache_key == self._wave_cache_key and self._wave_cache_peaks is not None:
            peaks = self._wave_cache_peaks
        else:
            peaks = _peak_envelope(visible_samples, bins)
            self._wave_cache_key = cache_key
            self._wave_cache_peaks = peaks
        x = np.linspace(0, max(0, width-1), len(peaks), dtype=np.float32)
        amplitude = np.clip(peaks * display_gain, 0.0, 1.0) * (height * 0.43)
        upper = np.column_stack((x, middle-amplitude)).ravel().tolist()
        lower = np.column_stack((x, middle+amplitude)).ravel().tolist()
        # Two polylines replace hundreds or thousands of individual Canvas
        # objects, which keeps zooming and viewport changes responsive.
        self.wave_canvas.delete("all")
        if len(upper) >= 4:
            self.wave_canvas.create_line(*upper, fill="#70d6c7")
            self.wave_canvas.create_line(*lower, fill="#70d6c7")
        self.wave_canvas.create_line(0, middle, width, middle, fill="#34404a")
        for sec in self._timeline_ticks(view_start, view_end):
            x = self._time_to_x(float(sec), width)
            self.wave_canvas.create_line(x, 0, x, height, fill="#27313a")
            self.wave_canvas.create_text(x+3, 9, text=self._format_time(float(sec)), fill="#8e99a5", anchor="nw", font=("TkDefaultFont", 8))
        if self.spectrum_expanded and not interactive:
            spec_height = max(90, self.spec_canvas.winfo_height())
            spec_key = (source.id, sample_start, sample_end, width, spec_height)
            if spec_key != self._spectrogram_cache_key:
                self._draw_spectrogram(visible_samples, width, spec_height)
                self._spectrogram_cache_key = spec_key
        self._wave_render_key = render_key
        self._draw_overlays()

    def _clear_visual_cache(self) -> None:
        self._wave_cache_key = None
        self._wave_cache_peaks = None
        self._wave_render_key = None
        self._spectrogram_cache_key = None
        self._spectrogram_photo = None

    @staticmethod
    def _timeline_ticks(start: float, end: float) -> list[float]:
        """Generate stable absolute-time grid lines that move with the waveform."""
        span = max(end - start, 0.001)
        candidates = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 30, 60)
        interval = next((value for value in candidates if span / value <= 8), candidates[-1])
        first = math.ceil(start / interval) * interval
        ticks = [first + index * interval for index in range(int(span / interval) + 2)]
        return [value for value in ticks if start - 1e-9 <= value <= end + 1e-9]

    def _draw_spectrogram(self, samples: np.ndarray, width: int, height: int) -> None:
        fft_size = 256
        hops = max(1, (len(samples) - fft_size) // max(1, width - 1))
        frames = []
        for start in range(0, max(1, len(samples)-fft_size), hops):
            frame = samples[start:start+fft_size]
            if len(frame) < fft_size:
                break
            power = np.abs(np.fft.rfft(frame * np.hanning(fft_size)))
            frames.append(20*np.log10(power + 1e-5))
            if len(frames) >= width:
                break
        if not frames:
            self.spec_canvas.delete("all")
            return
        spec = np.array(frames).T
        spec = spec[: min(spec.shape[0], 112)]
        lo, hi = np.percentile(spec, (15, 99))
        norm = np.clip((spec-lo)/max(hi-lo, 1e-6), 0, 1)
        y_idx = np.linspace(norm.shape[0]-1, 0, height).astype(int)
        x_idx = np.linspace(0, norm.shape[1]-1, width).astype(int)
        image = norm[y_idx][:, x_idx]
        rgb = np.empty((height, width, 3), dtype=np.uint8)
        rgb[..., 0] = np.clip(255 * np.maximum(0, image-0.45) * 1.8, 0, 255)
        rgb[..., 1] = np.clip(255 * image ** 0.8, 0, 255)
        rgb[..., 2] = np.clip(255 * np.minimum(1, image*1.5), 0, 255)
        ppm = f"P6\n{width} {height}\n255\n".encode() + rgb.tobytes()
        self._spectrogram_photo = tk.PhotoImage(data=ppm, format="PPM")
        self.spec_canvas.delete("all")
        self.spec_canvas.create_image(0, 0, image=self._spectrogram_photo, anchor="nw")

    def _draw_overlays(self) -> None:
        self.wave_canvas.delete("overlay")
        source = self.current_source()
        if not source:
            return
        width = max(1, self.wave_canvas.winfo_width())
        height = self.wave_canvas.winfo_height()
        view_start, view_end = self._visible_range()
        a, b = sorted(self.selection)
        if b > a:
            self.wave_canvas.create_rectangle(
                self._time_to_x(a, width), 0, self._time_to_x(b, width), height,
                fill="#527aa0", stipple="gray25", outline="#78a9d1", width=1, tags=("overlay", "selection"),
            )
            if self.draft_segment is None and self.current_segment() is None:
                for value, color, label in ((a, "#ffd166", "開始予定"), (b, "#58c7f3", "終了予定")):
                    x = self._time_to_x(value, width)
                    self.wave_canvas.create_line(x, 0, x, height, fill=color, width=2, tags=("overlay", "selection_marker"))
                    self.wave_canvas.create_text(x+4, 26, text=label, fill=color, anchor="nw", tags=("overlay", "selection_marker"))
        segment = self.draft_segment or self.current_segment()
        if segment:
            markers = ((segment.start, "#ffd166", "開始"), (segment.cue, "#ff9f1c", "cue"), (segment.end, "#58c7f3", "終了"))
            for value, color, label in markers:
                x = self._time_to_x(value, width)
                line_width = 3 if label == "cue" else 2
                self.wave_canvas.create_line(x, 0, x, height, fill=color, width=line_width, tags=("overlay", label))
                self.wave_canvas.create_text(x+4, 26, text=label, fill=color, anchor="nw", tags=("overlay", label))
                if label == "cue":
                    self.wave_canvas.create_polygon(
                        x-8, 0, x+8, 0, x, 13, fill=color, outline="#fff0d0", tags=("overlay", "cue"),
                    )
        if view_start <= self.playhead_time <= view_end:
            x = self._time_to_x(self.playhead_time, width)
            self.wave_canvas.create_line(x, 0, x, height, fill="#ff4d6d", width=2, tags=("overlay", "playhead"))
            self.wave_canvas.create_polygon(x-5, 0, x+5, 0, x, 8, fill="#ff4d6d", tags=("overlay", "playhead"))

    def _time_to_x(self, value: float, width: int | None = None) -> float:
        view_start, view_end = self._visible_range()
        return (value - view_start) / max(view_end - view_start, 1e-9) * (width or self.wave_canvas.winfo_width())

    def _x_to_time(self, x: float) -> float:
        source = self.current_source()
        if not source:
            return 0.0
        view_start, view_end = self._visible_range()
        return float(np.clip(view_start + x / max(self.wave_canvas.winfo_width(), 1) * (view_end-view_start), 0, source.duration))

    def _visible_range(self) -> tuple[float, float]:
        source = self.current_source()
        if not source:
            return 0.0, 1.0
        visible = source.duration / max(self.zoom_level, 1.0)
        start = float(np.clip(self.viewport_start, 0.0, max(0.0, source.duration-visible)))
        return start, min(source.duration, start+visible)

    def change_zoom(self, direction: int, anchor_time: float | None = None, anchor_ratio: float = 0.5) -> None:
        source = self.current_source()
        if not source:
            return
        levels = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1028)
        current = min(range(len(levels)), key=lambda i: abs(levels[i]-self.zoom_level))
        target = levels[int(np.clip(current+direction, 0, len(levels)-1))]
        old_start, old_end = self._visible_range()
        if anchor_time is None:
            anchor_time = (old_start+old_end)/2
            anchor_ratio = 0.5
        self.zoom_level = float(target)
        visible = source.duration/self.zoom_level
        self.viewport_start = float(np.clip(anchor_time-anchor_ratio*visible, 0, max(0, source.duration-visible)))
        self._set_viewport_slider(source)
        self._update_viewport_step_buttons()
        self.zoom_label.config(text=f"{target}×")
        self.draw_audio()

    def reset_zoom(self) -> None:
        self.zoom_level = 1.0
        self.viewport_start = 0.0
        source = self.current_source()
        if source:
            self._set_viewport_slider(source)
        else:
            self.viewport_var.set(0.0)
        self.zoom_label.config(text="1×")
        self._update_viewport_step_buttons()
        self.draw_audio()

    def _viewport_step(self) -> float:
        """Use a smaller navigation increment as the waveform is magnified."""
        source = self.current_source()
        if source is None:
            return 0.1
        visible = source.duration / max(self.zoom_level, 1.0)
        return float(np.clip(visible / 12, 0.001, 0.1))

    def _update_viewport_step_buttons(self) -> None:
        milliseconds = max(1, round(self._viewport_step() * 1000))
        self.viewport_back_button.configure(text=f"◀ {milliseconds}ms")
        self.viewport_forward_button.configure(text=f"{milliseconds}ms ▶")

    def _viewport_changed(self, raw: str) -> None:
        if self._suppress_viewport_command:
            return
        source = self.current_source()
        if not source or self.zoom_level <= 1:
            self.viewport_start = 0.0
            return
        visible = source.duration/self.zoom_level
        self.viewport_start = float(raw) * max(0.0, source.duration-visible)
        if self._viewport_redraw_job is not None:
            self.after_cancel(self._viewport_redraw_job)
        # A short throttle tracks the scrollbar without scheduling a redraw for
        # every individual Tk scale event.
        self._viewport_interacting = True
        self._viewport_redraw_job = self.after(8, self._redraw_viewport)

    def _redraw_viewport(self) -> None:
        self._viewport_redraw_job = None
        self.draw_audio(interactive=True)

    def _viewport_released(self, _: tk.Event) -> None:
        if self._viewport_redraw_job is not None:
            self.after_cancel(self._viewport_redraw_job)
            self._viewport_redraw_job = None
        self._viewport_interacting = False
        self.draw_audio()

    def _set_viewport_slider(self, source: AudioSource) -> None:
        visible = source.duration/max(self.zoom_level, 1.0)
        fraction = self.viewport_start/max(source.duration-visible, 1e-9) if self.zoom_level > 1 else 0.0
        self._suppress_viewport_command = True
        try:
            self.viewport_var.set(float(np.clip(fraction, 0, 1)))
        finally:
            self._suppress_viewport_command = False

    def move_viewport(self, seconds: float) -> None:
        source = self.current_source()
        if not source or self.zoom_level <= 1:
            return
        visible = source.duration/self.zoom_level
        self.viewport_start = float(np.clip(self.viewport_start+seconds, 0, max(0, source.duration-visible)))
        self._set_viewport_slider(source)
        self.draw_audio()

    def _zoom_wheel(self, event: tk.Event) -> str:
        delta = getattr(event, "delta", 0)
        button = getattr(event, "num", 0)
        direction = 1 if delta > 0 or button == 4 else -1
        ratio = float(np.clip(event.x / max(self.wave_canvas.winfo_width(), 1), 0, 1))
        self.change_zoom(direction, anchor_time=self._x_to_time(event.x), anchor_ratio=ratio)
        return "break"

    def toggle_spectrum(self) -> None:
        self.spectrum_expanded = not self.spectrum_expanded
        if self.spectrum_expanded:
            self.spec_canvas.pack(fill="x", expand=True, pady=(4, 0), before=self.action_row)
            self.spectrum_button.config(text="▼ スペクトログラムを格納")
        else:
            self.spec_canvas.pack_forget()
            self.spectrum_button.config(text="▶ スペクトログラムを展開")
        self.draw_audio()

    def _canvas_press(self, event: tk.Event) -> None:
        self.wave_canvas.focus_set()
        self.canvas_press_x = float(event.x)
        self.canvas_dragged = False
        time = self._x_to_time(event.x)
        segment = self.draft_segment or self.current_segment()
        if segment:
            view_start, view_end = self._visible_range()
            tolerance = (view_end-view_start) * 10 / max(self.wave_canvas.winfo_width(), 1)
            # Start/end handles deliberately face outward: a click just left
            # of start edits start, and a click just right of end edits end.
            # That leaves the audio region itself available for scrubbing.
            marker = None
            if segment.start - tolerance <= time <= segment.start:
                marker = "start"
            elif segment.end <= time <= segment.end + tolerance:
                marker = "end"
            elif abs(time-segment.cue) <= tolerance:
                marker = "cue"
            if marker:
                if marker == "end":
                    self._suspend_playback_for_pointer_adjustment()
                self._record()
                self.drag_mode = marker
                self.wave_canvas.config(cursor="sb_h_double_arrow")
                return
        a, b = sorted(self.selection)
        if b - a >= 0.005:
            view_start, view_end = self._visible_range()
            tolerance = (view_end-view_start) * 10 / max(self.wave_canvas.winfo_width(), 1)
            if abs(time-a) <= tolerance or abs(time-b) <= tolerance:
                self.drag_mode = "selection_start" if abs(time-a) <= abs(time-b) else "selection_end"
                self.wave_canvas.config(cursor="sb_h_double_arrow")
                return
        self.drag_mode = "playhead"
        self._suspend_playback_for_pointer_adjustment()
        self._set_playhead_position(self._x_to_time(event.x))

    def _canvas_drag(self, event: tk.Event) -> None:
        if abs(float(event.x)-self.canvas_press_x) >= 3:
            self.canvas_dragged = True
        if self.drag_mode == "playhead":
            self._set_playhead_position(self._x_to_time(event.x))
        elif self.drag_mode in ("start", "cue", "end"):
            segment = self.draft_segment or self.current_segment()
            source = self.current_source()
            if segment and source:
                setattr(segment, self.drag_mode, self._x_to_time(event.x))
                segment.clamp(source.duration)
                self._fill_detail(segment)
                self._draw_overlays()
        elif self.drag_mode in ("selection_start", "selection_end"):
            a, b = sorted(self.selection)
            point = self._x_to_time(event.x)
            self.selection = (point, b) if self.drag_mode == "selection_start" else (a, point)
            self._draw_overlays()
        elif self.drag_mode in ("start", "cue", "end"):
            segment = self.draft_segment or self.current_segment()
            source = self.current_source()
            if segment and source:
                setattr(segment, self.drag_mode, self._x_to_time(event.x))
                segment.clamp(source.duration)
                self._fill_detail(segment)
                self._draw_overlays()

    def _canvas_release(self, event: tk.Event) -> None:
        if self.drag_mode == "playhead":
            self._set_playhead_position(self._x_to_time(event.x))
            source = self.current_source()
            if self._scrub_was_playing and source:
                self._resume_pointer_playback(source.path, self.playhead_time, self._pointer_resume_end)
        elif self.drag_mode in ("start", "cue", "end"):
            segment = self.draft_segment or self.current_segment()
            self._dirty = True
            self.refresh_segments()
            self.status_var.set("開始・cue・終了位置を調整しました")
            source = self.current_source()
            if self.drag_mode == "end" and self._scrub_was_playing and segment and source:
                self._resume_pointer_playback(source.path, self.playhead_time, segment.end)
        elif self.drag_mode in ("selection_start", "selection_end"):
            start, end = sorted(self.selection)
            self.status_var.set(f"切り出し範囲を調整: {start:.3f}–{end:.3f}秒。候補の詳細で発音を入力してEnterを押します")
        elif self.drag_mode in ("start", "cue", "end"):
            self._dirty = True
            self.refresh_segments()
            self.status_var.set("開始・cue・終了位置を調整しました")
        self.drag_mode = ""
        self._scrub_was_playing = False
        self.wave_canvas.config(cursor="crosshair")
        self._draw_overlays()

    def _suspend_playback_for_pointer_adjustment(self) -> None:
        """Stop the process without resetting the cue, ready to resume on release."""
        player = self.player
        self._scrub_was_playing = player is not None and player.poll() is None
        self._pointer_resume_end = self._playback_end
        self._pointer_resume_loop = self._playback_loop
        if self._scrub_was_playing:
            player.terminate()
            self.player = None
            self._playback_loop = False
            self._playback_path = ""

    def _resume_pointer_playback(self, path: str, start: float, end: float) -> None:
        """Resume a pointer-adjusted clip while keeping its original loop mode."""
        if end <= start + 0.001:
            self.playhead_time = max(0.0, end)
            self._draw_overlays()
            return
        self._play(path, start, end, self._pointer_resume_loop)

    def _range_press(self, event: tk.Event) -> None:
        self.wave_canvas.focus_set()
        self.canvas_press_x = float(event.x)
        self.canvas_dragged = False
        self.current_segment_id = None
        self.draft_segment = None
        self.drag_mode = "selection"
        self.drag_anchor = self._x_to_time(event.x)
        self.selection = (self.drag_anchor, self.drag_anchor)
        self._suppress_detail_apply = True
        try:
            self.detail_vars["label"].set("")
            self.detail_vars["pitch"].set("--")
        finally:
            self._suppress_detail_apply = False
        self.wave_canvas.config(cursor="crosshair")
        self._draw_overlays()

    def _range_drag(self, event: tk.Event) -> None:
        if abs(float(event.x)-self.canvas_press_x) >= 3:
            self.canvas_dragged = True
        if self.drag_mode == "selection":
            self.selection = (self.drag_anchor, self._x_to_time(event.x))
            self._draw_overlays()

    def _range_release(self, event: tk.Event) -> None:
        if self.drag_mode != "selection":
            return
        self.selection = (self.drag_anchor, self._x_to_time(event.x))
        self.drag_mode = ""
        self.wave_canvas.config(cursor="crosshair")
        self._draw_overlays()
        start, end = sorted(self.selection)
        if end - start >= 0.005:
            # A manually created range has no cue yet; its start is the cue
            # that will be used when a pronunciation is registered.
            self.playhead_time = start
            self._suppress_detail_apply = True
            try:
                self.detail_vars["start"].set(f"{start:.4f}")
                self.detail_vars["cue"].set(f"{start:.4f}")
                self.detail_vars["end"].set(f"{end:.4f}")
            finally:
                self._suppress_detail_apply = False
            self._draw_overlays()
            self.status_var.set(
                f"切り出し範囲: {start:.3f}–{end:.3f}秒（再生位置/cue: {start:.3f}秒）。"
                "候補の詳細で発音を入力してEnterを押します"
            )

    def _canvas_double_click(self, _event: tk.Event) -> str:
        """Dismiss a pending range, or only the selected saved candidate."""
        selected = self.draft_segment or self.current_segment()
        if selected is None:
            self.selection = (0.0, 0.0)
            self.status_var.set("未確定の切り出し範囲を解除しました")
        else:
            self.current_segment_id = None
            self.draft_segment = None
            self.segment_tree.selection_remove(self.segment_tree.selection())
            self.status_var.set("候補の選択を解除しました（切り出し範囲は残しています）")
        self._draw_overlays()
        return "break"

    def _seek_playhead(self, value: float) -> None:
        source = self.current_source()
        if source is None:
            return
        value = float(np.clip(value, 0, source.duration))
        was_playing = self.player is not None and self.player.poll() is None
        self.playhead_time = value
        if was_playing:
            self._play(source.path, value, source.duration, False)
        else:
            self._draw_overlays()
            self.status_var.set(f"再生位置: {value:.3f}秒")

    def _set_playhead_position(self, value: float) -> None:
        source = self.current_source()
        if source is None:
            return
        self.playhead_time = float(np.clip(value, 0, source.duration))
        self._draw_overlays()
        self.status_var.set(f"再生位置: {self.playhead_time:.3f}秒")

    def _set_cue_from_click(self, event: tk.Event) -> str:
        segment = self.current_segment()
        source = self.current_source()
        if segment and source:
            self._record()
            segment.cue = self._x_to_time(event.x)
            segment.clamp(source.duration)
            self._after_project_change("cueを移動しました")
        return "break"

    def _canvas_motion(self, event: tk.Event) -> None:
        time = self._x_to_time(event.x)
        self.time_label.config(text=self._format_time(time))

    def create_from_selection(self) -> None:
        self.begin_manual_entry()

    def begin_manual_entry(self) -> None:
        source = self.current_source()
        if not source:
            return
        start, end = sorted(self.selection)
        if end - start < 0.005:
            start = self.manual_next_start
            end = min(source.duration, start + 0.12)
            self.selection = (start, end)
        self._open_flick_pad(self._create_draft_from_label)

    def _show_flick_pad_key(self, _event: object = None) -> str | None:
        if self._text_input_active():
            return None
        self.show_flick_pad()
        return "break"

    def show_flick_pad(self) -> None:
        start, end = sorted(self.selection)
        if self.draft_segment is not None:
            self._open_flick_pad(self._change_draft_label)
        elif self.current_segment() is not None:
            self._open_flick_pad(self._change_saved_label)
        elif end - start >= 0.005:
            self.begin_manual_entry()
        else:
            self.begin_manual_entry()

    def _open_flick_pad(self, on_select: callable) -> None:
        existing = getattr(self, "_flick_pad", None)
        if existing is not None and existing.winfo_exists():
            existing.focus_force()
            return
        self._flick_pad = FlickKanaPad(self, on_select)

    def _create_draft_from_label(self, label: str) -> None:
        source = self.current_source()
        if not source:
            return
        start, end = sorted(self.selection)
        if end - start < 0.005:
            start = self.manual_next_start
            end = min(source.duration, start + 0.12)
        self.manual_label_var.set(label)
        segment = Segment.create(
            source.id, start, end, cue=start, label=label, unit="character",
            order=len(self.project.segments) + 1, origin="manual",
        )
        self._record()
        self._analyze_segment(segment)
        self.project.segments.append(segment)
        self.current_segment_id = segment.id
        self.draft_segment = None
        self.manual_next_start = segment.end
        self.selection = (segment.start, segment.end)
        self._fill_detail(segment)
        self.refresh_segments()
        self._draw_overlays()
        self.status_var.set(f"「{label}」を候補に追加しました。開始・cue・終了の線を左ドラッグで調整できます")

    def set_draft_marker(self, marker: str) -> str | None:
        if self._text_input_active():
            return None
        source = self.current_source()
        segment = self.draft_segment
        if not source or not segment:
            return None
        setattr(segment, marker, self.playhead_time)
        segment.clamp(source.duration)
        self.selection = (segment.start, segment.end)
        self._fill_detail(segment)
        self._draw_overlays()
        self.status_var.set(f"下書き「{segment.label}」: {marker} = {self.playhead_time:.3f}秒")
        return "break"

    def commit_draft(self) -> None:
        segment = self.draft_segment or self.current_segment()
        if segment is None:
            return
        self._record()
        self._analyze_segment(segment)
        if not any(existing.id == segment.id for existing in self.project.segments):
            self.project.segments.append(segment)
        self.current_segment_id = segment.id
        self.manual_next_start = segment.end
        self.draft_segment = None
        self._after_project_change(f"「{segment.label}」を更新しました")

    def change_selected_label(self) -> None:
        if self.draft_segment is not None:
            self._open_flick_pad(self._change_draft_label)
            return
        if self.current_segment() is None:
            self.status_var.set("変更する候補を選択してください")
            return
        self._open_flick_pad(self._change_saved_label)

    def _change_draft_label(self, label: str) -> None:
        if self.draft_segment is None:
            return
        self.draft_segment.label = label
        self.manual_label_var.set(label)
        self._fill_detail(self.draft_segment)
        self._draw_overlays()

    def _change_saved_label(self, label: str) -> None:
        segment = self.current_segment()
        if segment is None:
            return
        self._record()
        segment.label = label
        segment.unit = "character"
        self.manual_label_var.set(label)
        self._after_project_change(f"発音を「{label}」へ変更しました")

    def _manual_mode_changed(self) -> None:
        if self.manual_mode_var.get():
            self.wave_help_label.config(text="  左ドラッグ: 再生位置 / 右ドラッグ: 範囲選択 / 詳細の発音欄でEnter: 候補追加")
            self.wave_canvas.config(cursor="crosshair")
            self.status_var.set("手動切り出しモード: 右ドラッグで範囲を選び、候補の詳細で発音を入力してEnterを押します")
        else:
            self.wave_help_label.config(text="  左ドラッグ: 再生位置 / 右ドラッグ: 範囲選択 / 詳細の発音欄でEnter: 候補追加")

    def _replace_auto_segments(self, source_id: str, replacements: list[Segment]) -> int:
        removed = sum(
            segment.source_id == source_id and getattr(segment, "origin", "auto") != "manual"
            for segment in self.project.segments
        )
        self.project.segments = [
            segment for segment in self.project.segments
            if segment.source_id != source_id or getattr(segment, "origin", "auto") == "manual"
        ]
        self.project.segments.extend(replacements)
        self._dirty = True
        return removed

    def _analyze_segment(self, segment: Segment) -> None:
        if self.current_samples is None:
            return
        a = max(0, int(segment.cue * DISPLAY_RATE))
        b = min(len(self.current_samples), int(segment.end * DISPLAY_RATE))
        segment.pitch, stability = estimate_pitch(self.current_samples[a:b], DISPLAY_RATE)
        clarity, noise = quality_metrics(self.current_samples[a:b], DISPLAY_RATE)
        segment.quality_score = 0.45*clarity + 0.30*noise + 0.25*stability

    def refresh_segments(self) -> None:
        self.segment_tree.delete(*self.segment_tree.get_children())
        query = self.search_var.get().lower().strip()
        segments = [s for s in self.project.segments if s.source_id == self.current_source_id]
        key_functions = {
            "label": lambda item: (item.label.lower(), item.start, item.order),
            "pitch": lambda item: (item.pitch.lower(), item.start, item.order),
            "start": lambda item: (item.start, item.order),
        }
        segments = sorted(segments, key=key_functions[self.list_sort_key], reverse=self.list_sort_reverse)
        duplicate_numbers: dict[str, int] = {}
        for segment in segments:
            duplicate_numbers[segment.label] = duplicate_numbers.get(segment.label, 0) + 1
            haystack = f"{segment.label} {segment.pitch}".lower()
            if self._coverage_filter_labels is not None and segment.label not in self._coverage_filter_labels:
                continue
            if query and query not in haystack:
                continue
            occurrence = duplicate_numbers[segment.label]
            display_label = segment.label if occurrence == 1 else f"{segment.label} ({occurrence})"
            self.segment_tree.insert("", "end", iid=segment.id, values=(display_label, segment.pitch, f"{segment.start:.3f}", f"{segment.end:.3f}"))
        if self.current_segment_id and self.segment_tree.exists(self.current_segment_id):
            self.segment_tree.selection_set(self.current_segment_id)

    def _search_changed(self, *_: object) -> None:
        self._coverage_filter_labels = None
        self.refresh_segments()

    def _sort_list(self, column: str) -> None:
        if self.list_sort_key == column:
            self.list_sort_reverse = not self.list_sort_reverse
        else:
            self.list_sort_key = column
            self.list_sort_reverse = False
        self.refresh_segments()

    def _segment_selected(self, _: object = None) -> None:
        ids = self.segment_tree.selection()
        if not ids:
            return
        self.current_segment_id = ids[0]
        segment = self.current_segment()
        if segment:
            self._fill_detail(segment)
            self.selection = (segment.start, segment.end)
            self.draw_audio()

    def _fill_detail(self, segment: Segment) -> None:
        self._suppress_detail_apply = True
        try:
            self.detail_vars["label"].set(segment.label)
            self.detail_vars["pitch"].set(segment.pitch)
            self.detail_vars["start"].set(f"{segment.start:.4f}")
            self.detail_vars["cue"].set(f"{segment.cue:.4f}")
            self.detail_vars["end"].set(f"{segment.end:.4f}")
        finally:
            self._suppress_detail_apply = False
        self.breath_var.set(segment.breath)
        self.sigh_var.set(getattr(segment, "sigh", False))

    def _queue_detail_apply(self, *_: object) -> None:
        if self._suppress_detail_apply or self.current_segment() is None:
            return
        if self._detail_apply_job is not None:
            self.after_cancel(self._detail_apply_job)
        self._detail_apply_job = self.after(350, self._apply_detail_automatically)

    def _apply_detail_automatically(self) -> None:
        self._detail_apply_job = None
        self._apply_detail(show_error=False, status="候補を自動更新しました")

    def apply_detail(self) -> None:
        self._apply_detail(show_error=True, status="候補を更新しました")

    def _apply_detail(self, show_error: bool, status: str) -> bool:
        segment = self.current_segment()
        source = self.current_source()
        if not segment or not source:
            return False
        try:
            values = {key: float(self.detail_vars[key].get()) for key in ("start", "cue", "end")}
        except ValueError:
            if show_error:
                messagebox.showerror("入力エラー", "開始、cue、終了には秒数を入力してください。")
            return False
        label = self.detail_vars["label"].get().strip() or "未分類"
        pitch = self.detail_vars["pitch"].get().strip() or "--"
        unchanged = (segment.label == label and segment.pitch == pitch and
                     segment.start == values["start"] and segment.cue == values["cue"] and segment.end == values["end"])
        if unchanged:
            return True
        self._record()
        segment.label = label
        segment.pitch = pitch
        segment.start, segment.cue, segment.end = values["start"], values["cue"], values["end"]
        segment.clamp(source.duration)
        self._analyze_segment(segment)
        self._after_project_change(status)
        return True

    def _detail_label_enter(self, _event: object = None) -> str:
        """Create a candidate from the active range, or update the selected one."""
        label = self.detail_vars["label"].get().strip()
        if not label:
            return "break"
        segment = self.current_segment()
        source = self.current_source()
        if segment is not None:
            self._apply_detail(show_error=True, status="候補を更新しました")
            self.wave_canvas.focus_set()
            return "break"
        if source is None:
            return "break"
        start, end = sorted(self.selection)
        if end - start < 0.005:
            start = self.manual_next_start
            end = min(source.duration, start + 0.12)
        segment = Segment.create(source.id, start, end, cue=start, label=label, unit="character",
                                 order=len(self.project.segments) + 1, origin="manual")
        self._record()
        self._analyze_segment(segment)
        self.project.segments.append(segment)
        self.current_segment_id = segment.id
        self.selection = (start, end)
        self.manual_next_start = end
        self._after_project_change(f"「{label}」を候補に追加しました")
        self.wave_canvas.focus_set()
        return "break"

    def apply_voice_type(self, kind: str) -> None:
        segment = self.current_segment()
        if not segment:
            return
        self._record()
        if kind == "breath":
            segment.breath = self.breath_var.get()
            segment.sigh = False
            self.sigh_var.set(False)
            if segment.breath:
                segment.label = "(ブレス)"
            elif segment.label == "(ブレス)":
                segment.label = "未分類"
        else:
            segment.sigh = self.sigh_var.get()
            segment.breath = False
            self.breath_var.set(False)
            if segment.sigh:
                segment.label = "(息)"
            elif segment.label == "(息)":
                segment.label = "未分類"
        self._fill_detail(segment)
        self._after_project_change("発声種別を更新しました")

    def nudge_cue(self, amount: float) -> None:
        if isinstance(self.focus_get(), (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox)):
            return
        segment = self.current_segment()
        source = self.current_source()
        if not segment or not source:
            return
        self._record()
        segment.cue += amount
        segment.clamp(source.duration)
        self._after_project_change(f"cue: {segment.cue:.4f}秒")

    def delete_segment(self) -> None:
        segment = self.current_segment()
        if not segment:
            return
        self._record()
        self.project.segments = [s for s in self.project.segments if s.id != segment.id]
        self.current_segment_id = None
        self._after_project_change("候補を削除しました")

    def play_cue(self, loop: bool = False) -> None:
        self.wave_canvas.focus_set()
        self._finish_pointer_interaction()
        segment = self.current_segment()
        source = self.current_source()
        if segment and source:
            self._play(source.path, segment.cue, segment.end, loop)
            return
        a, b = sorted(self.selection)
        if source and b > a:
            self._play(source.path, a, b, loop)

    def play_context(self) -> None:
        self._finish_pointer_interaction()
        segment = self.current_segment()
        source = self.current_source()
        if segment and source:
            self._play(source.path, max(0, segment.start-0.15), min(source.duration, segment.end+0.15), False)

    def _play(self, path: str, start: float, end: float, loop: bool, preserve_pointer: bool = False) -> None:
        if preserve_pointer:
            player = self.player
            self.player = None
            self._playback_loop = False
            self._playback_path = ""
            if player and player.poll() is None:
                player.terminate()
        else:
            self.stop_audio(quiet=True)
        speed = float(self.speed_var.get())
        gain_db = float(self.playback_gain_var.get())
        try:
            # FFplay's -loop is not reliable for audio-only clips on every
            # build, so the application restarts each finished loop itself.
            self.player = play(path, start, end, False, speed, gain_db)
            self.playhead_time = start
            self._playback_started_at = time.monotonic()
            self._playback_start = start
            self._playback_end = end
            self._playback_speed = speed
            self._playback_loop = loop
            self._playback_path = path
            self._playback_gain_db = gain_db
            self._update_playhead()
            self.status_var.set(f"再生中: {start:.3f}–{end:.3f}秒")
        except Exception as exc:
            messagebox.showerror("再生できません", str(exc))

    def _finish_pointer_interaction(self) -> None:
        self.drag_mode = ""
        self._scrub_was_playing = False
        if hasattr(self, "wave_canvas"):
            self.wave_canvas.config(cursor="crosshair")

    def stop_audio(self, quiet: bool = False) -> None:
        self._finish_pointer_interaction()
        player = self.player
        self.player = None
        self._playback_loop = False
        self._playback_path = ""
        if player and player.poll() is None:
            player.terminate()
        segment = self.current_segment()
        source = self.current_source()
        if source:
            if segment is not None:
                self.playhead_time = segment.cue
            else:
                start, end = sorted(self.selection)
                if end - start >= 0.005:
                    self.playhead_time = start
            self._draw_overlays()
        if not quiet and hasattr(self, "status_var"):
            self.status_var.set(f"停止しました（cue: {self.playhead_time:.3f}秒）")

    def _update_playhead(self) -> None:
        player = self.player
        if player is None:
            self._draw_overlays()
            return
        if player.poll() is not None:
            if self._playback_loop and self._playback_path:
                try:
                    self.player = play(
                        self._playback_path, self._playback_start, self._playback_end,
                        False, self._playback_speed, self._playback_gain_db,
                    )
                    self.playhead_time = self._playback_start
                    self._playback_started_at = time.monotonic()
                    self.after(15, self._update_playhead)
                    return
                except Exception as exc:
                    self.status_var.set(f"ループ再生を続けられません: {exc}")
            self.player = None
            self.playhead_time = self._playback_start
            self._draw_overlays()
            return
        elapsed = (time.monotonic() - self._playback_started_at) * self._playback_speed
        length = max(0.001, self._playback_end - self._playback_start)
        if self._playback_loop:
            self.playhead_time = self._playback_start + (elapsed % length)
        else:
            self.playhead_time = min(self._playback_end, self._playback_start + elapsed)
        self._draw_overlays()
        self.after(33, self._update_playhead)

    def _save_transcript(self) -> None:
        value = self.transcript_text.get("1.0", "end-1c")
        if self.project.collection_list != value:
            self.project.collection_list = value
            self._dirty = True

    def _update_mora_preview(self) -> None:
        raw = self.transcript_text.get("1.0", "end-1c")
        requested: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in raw.replace("，", ",").split(","):
            label = item.strip()
            canonical = _canonical_pronunciation(label)
            if label and canonical not in seen:
                requested.append((label, canonical))
                seen.add(canonical)
        if not requested:
            self.mora_preview.config(text="収集用リスト: 0件\n発音を , で区切って入力します")
            return
        collected = {
            _canonical_pronunciation(segment.label)
            for segment in self.project.segments
            if segment.label.strip()
            and segment.label not in {"未分類", "(息)", "(ブレス)"}
        }
        missing = [label for label, canonical in requested if canonical not in collected]
        # A collection target represents one required pronunciation. Repeating
        # it in the comma-separated list does not require duplicate samples.
        if missing:
            shown = ", ".join(missing[:24]) + (" …" if len(missing) > 24 else "")
            self.mora_preview.config(text=f"不足: {len(missing)} / {len(requested)}\n{shown}")
        else:
            self.mora_preview.config(text=f"不足なし: {len(requested)}件すべて収集済み")

    '''
    # 自動音声認識は手入力ワークフローを安定させる間、保留。
    def run_detection(self) -> None:
        if self._detection_running:
            messagebox.showinfo("解析中", "現在の解析をキャンセルしてから、もう一度実行してください。")
            return
        source = self.current_source()
        if not source:
            messagebox.showinfo("音声がありません", "先に音声ファイルを追加してください。")
            return
        self._save_transcript()
        transcript = self.project.transcripts.get(source.id, "")
        unit = UNIT_LABELS[self.unit_var.get()]
        model = next((m for m in self.models if m.name == self.model_var.get()), self.models[0])
        if not self._confirm_model_run(model, transcript, unit):
            return
        self._begin_detection()
        use_gpu = self.gpu_var.get()
        self._set_progress(0, f"解析準備: {model.name}")
        source_id = source.id
        def worker() -> None:
            try:
                if model.kind == "whisper":
                    result = whisper_detect(
                        source.path, source.id, transcript, unit, model.model_id, use_gpu,
                        APP_DIR / "models_cache", self._queue_progress, self._detection_cancel_event, assist_only=True,
                    )
                elif model.kind == "mfa":
                    result = mfa_detect(source.path, source.id, transcript, unit, APP_DIR / "models_cache", self._queue_progress, self._detection_cancel_event)
                elif model.kind == "kotoba_reazon_silero":
                    result = kotoba_reazon_silero_detect(source.path, source.id, transcript, unit, use_gpu, APP_DIR / "models_cache", self._queue_progress, self._detection_cancel_event)
                elif model.command:
                    self._queue_progress(10, f"外部モデルを実行中: {model.name}")
                    result = external_detect(model, source.path, source.id, transcript, unit, use_gpu)
                else:
                    result = baseline_detect(source.path, source.id, transcript, unit, self._queue_progress)
                self.jobs.put(("detected", (source_id, result)))
            except WhisperCancelled:
                self.jobs.put(("detection_cancelled", None))
            except Exception as exc:
                self.jobs.put(("error", f"自動検出に失敗しました: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def run_batch_detection(self) -> None:
        if self._detection_running:
            messagebox.showinfo("解析中", "現在の解析をキャンセルしてから、もう一度実行してください。")
            return
        if not self.project.sources:
            messagebox.showinfo("音声がありません", "先に音声ファイルを追加してください。")
            return
        self._save_transcript()
        unit = UNIT_LABELS[self.unit_var.get()]
        model = next((m for m in self.models if m.name == self.model_var.get()), self.models[0])
        if not self._confirm_model_run(model, "batch", unit):
            return
        self._begin_detection()
        use_gpu = self.gpu_var.get()
        sources = list(self.project.sources)
        transcripts = dict(self.project.transcripts)
        self._set_progress(0, f"一括解析準備: {len(sources)}素材")
        def worker() -> None:
            batches: list[tuple[str, list[Segment]]] = []
            errors: list[str] = []
            total_sources = len(sources)
            for source_index, source in enumerate(sources):
                try:
                    transcript = transcripts.get(source.id, "")
                    def batch_progress(percent: float, message: str, index: int = source_index) -> None:
                        overall = (index + percent/100)/total_sources*100
                        self._queue_progress(overall, f"{source.display_name}: {message}")
                    if model.kind == "whisper":
                        result = whisper_detect(
                            source.path, source.id, transcript, unit, model.model_id, use_gpu,
                            APP_DIR / "models_cache", batch_progress, self._detection_cancel_event, assist_only=True,
                        )
                    elif model.kind == "mfa":
                        result = mfa_detect(source.path, source.id, transcript, unit, APP_DIR / "models_cache", batch_progress, self._detection_cancel_event)
                    elif model.kind == "kotoba_reazon_silero":
                        result = kotoba_reazon_silero_detect(source.path, source.id, transcript, unit, use_gpu, APP_DIR / "models_cache", batch_progress, self._detection_cancel_event)
                    elif model.command:
                        batch_progress(10, f"外部モデルを実行中: {model.name}")
                        result = external_detect(model, source.path, source.id, transcript, unit, use_gpu)
                    else:
                        result = baseline_detect(source.path, source.id, transcript, unit, batch_progress)
                    batches.append((source.id, result))
                except WhisperCancelled:
                    self.jobs.put(("detection_cancelled", None))
                    return
                except Exception as exc:
                    errors.append(f"{source.display_name}: {exc}")
            self.jobs.put(("detected_batch", (batches, errors)))
        threading.Thread(target=worker, daemon=True).start()

    def _begin_detection(self) -> None:
        self._detection_running = True
        self._detection_cancel_event = threading.Event()
        self.detect_button.configure(state="disabled")
        self.batch_detect_button.configure(state="disabled")
        self.cancel_detection_button.configure(state="normal")

    def _finish_detection(self) -> None:
        self._detection_running = False
        self._detection_cancel_event = None
        self.detect_button.configure(state="normal")
        self.batch_detect_button.configure(state="normal")
        self.cancel_detection_button.configure(state="disabled")

    def cancel_detection(self) -> None:
        if self._detection_cancel_event is None:
            return
        self._detection_cancel_event.set()
        self.cancel_detection_button.configure(state="disabled")
        self.status_var.set("解析をキャンセルしています…")

    def _model_selected(self) -> None:
        model = next((m for m in self.models if m.name == self.model_var.get()), self.models[0])
        if model.kind == "baseline":
            note = "音量境界＋仮名テキスト。発音認識はしません。"
        elif model.kind == "whisper":
            note = f"高精度Whisperで発声候補だけを表示します。発音ラベルは手入力です。{model.download_note}"
        elif model.kind == "mfa":
            note = f"入力テキストを強制アラインして境界を作ります。{model.download_note}"
        elif model.kind == "kotoba_reazon_silero":
            note = f"Kotoba認識をReazonSpeech CTCとSilero VADで境界補正します。{model.download_note}"
        else:
            note = "外部モデルプラグイン"
        self.model_note.config(text=note)

    def _confirm_model_run(self, model: object, transcript: str, unit: str) -> bool:
        if model.kind == "baseline":
            if transcript != "batch" and not transcript.strip():
                return messagebox.askyesno(
                    "ベースラインの仕様",
                    "内蔵ベースラインは発音を認識しません。テキストなしでは音のある区間を「未分類」として検出します。\n\nそのまま続けますか？",
                )
            if transcript != "batch" and not labels_for_unit(transcript, unit):
                messagebox.showwarning(
                    "仮名テキストが必要です",
                    "内蔵ベースラインは漢字を読みへ変換できません。テキストを仮名で入力するか、Whisperモデルを選択してください。",
                )
                return False
        if model.kind == "whisper":
            cache = APP_DIR / "models_cache"
            cache_has_files = cache.exists() and any(cache.iterdir())
            if not cache_has_files:
                return messagebox.askyesno(
                    "モデルをダウンロード",
                    f"{model.name}\n{model.download_note}\n\nダウンロード後の音声解析はローカルで完結します。続けますか？",
                )
        if model.kind == "mfa" and transcript != "batch" and not transcript.strip():
            messagebox.showwarning("テキストが必要です", "MFA Japanese v3.0.0には素材のテキストが必要です。")
            return False
        if model.kind in {"mfa", "kotoba_reazon_silero"}:
            return messagebox.askyesno(
                "モデルを準備",
                f"{model.name}\n{model.download_note}\n\n未導入の実行環境・モデルは初回に取得します。続けますか？",
            )
        return True

    '''

    def export_all(self) -> None:
        labelled = [s for s in self.project.segments if s.label and s.label != "未分類"]
        segments = labelled
        if not segments:
            messagebox.showinfo("候補がありません", "書き出す候補を作成してください。")
            return
        folder = filedialog.askdirectory(title="WAVの書き出し先")
        if not folder:
            return
        settings = self.project.settings
        self._set_progress(0, f"書き出し準備: {len(segments)}件")
        sources = {s.id: s for s in self.project.sources}
        def worker() -> None:
            numbers: dict[tuple[str, str, str], int] = {}
            exported = 0
            errors: list[str] = []
            for index, segment in enumerate(segments, 1):
                self._queue_progress((index-1)/len(segments)*95, f"WAV書き出し中: {index}/{len(segments)}")
                source = sources.get(segment.source_id)
                if not source or not Path(source.path).exists():
                    errors.append(f"{segment.label}: 元ファイルがありません")
                    continue
                key = (segment.label, segment.pitch, source.display_name)
                numbers[key] = numbers.get(key, 0) + 1
                filename = "_".join((safe_filename(segment.label), safe_filename(segment.pitch), safe_filename(source.display_name), f"{numbers[key]:03d}")) + ".wav"
                try:
                    export_segment(source.path, str(Path(folder)/filename), segment.cue, segment.end, settings.sample_rate, settings.bit_depth, settings.normalize)
                    exported += 1
                except Exception as exc:
                    errors.append(f"{filename}: {exc}")
            self.jobs.put(("export_done", (exported, errors, folder)))
        threading.Thread(target=worker, daemon=True).start()

    def show_coverage(self) -> None:
        window = tk.Toplevel(self)
        window.title("五十音表の収集状況")
        window.geometry("760x560")
        rows = (
            ("あいうえお", ("a", "i", "u", "e", "o")), ("かきくけこ", ("ka", "ki", "ku", "ke", "ko")),
            ("さしすせそ", ("sa", "shi", "su", "se", "so")), ("たちつてと", ("ta", "chi", "tsu", "te", "to")),
            ("なにぬねの", ("na", "ni", "nu", "ne", "no")), ("はひふへほ", ("ha", "hi", "fu", "he", "ho")),
            ("まみむめも", ("ma", "mi", "mu", "me", "mo")), ("やゆよ", ("ya", "yu", "yo")),
            ("らりるれろ", ("ra", "ri", "ru", "re", "ro")), ("わをん", ("wa", "wo", "n")),
            ("がぎぐげご", ("ga", "gi", "gu", "ge", "go")), ("ざじずぜぞ", ("za", "ji", "zu", "ze", "zo")),
            ("だぢづでど", ("da", "ji", "zu", "de", "do")), ("ばびぶべぼ", ("ba", "bi", "bu", "be", "bo")),
            ("ぱぴぷぺぽ", ("pa", "pi", "pu", "pe", "po")),
            # 拗音（ゃ・ゅ・ょ）。収集用リストのローマ字／かな両方を
            # 同じ候補として扱えるよう、標準的なローマ字を持たせる。
            (("きゃ", "きゅ", "きょ"), ("kya", "kyu", "kyo")), (("ぎゃ", "ぎゅ", "ぎょ"), ("gya", "gyu", "gyo")),
            (("しゃ", "しゅ", "しょ"), ("sha", "shu", "sho")), (("じゃ", "じゅ", "じょ"), ("ja", "ju", "jo")),
            (("ちゃ", "ちゅ", "ちょ"), ("cha", "chu", "cho")), (("にゃ", "にゅ", "にょ"), ("nya", "nyu", "nyo")),
            (("ひゃ", "ひゅ", "ひょ"), ("hya", "hyu", "hyo")), (("びゃ", "びゅ", "びょ"), ("bya", "byu", "byo")),
            (("ぴゃ", "ぴゅ", "ぴょ"), ("pya", "pyu", "pyo")), (("みゃ", "みゅ", "みょ"), ("mya", "myu", "myo")),
            (("りゃ", "りゅ", "りょ"), ("rya", "ryu", "ryo")),
        )
        kana_to_romaji = {kana: roman for kana_row, roman_row in rows for kana, roman in zip(kana_row, roman_row)}
        requested = {
            _canonical_pronunciation(item)
            for item in self.transcript_text.get("1.0", "end-1c").replace("，", ",").split(",")
            if item.strip()
        }
        counts: dict[str, int] = {}
        for segment in self.project.segments:
            key = _canonical_pronunciation(segment.label)
            counts[key] = counts.get(key, 0) + 1
        ttk.Label(window, text="ローマ字を優先表示（緑: リスト内・収集済み　黄: リスト内・未収集　青: 候補あり　灰: 未収集）", padding=10).pack(anchor="w")
        body = ttk.Frame(window)
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        grid = ttk.Frame(canvas, padding=10)
        grid_window = canvas.create_window((0, 0), window=grid, anchor="nw")
        grid.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(grid_window, width=event.width))

        def scroll(event: tk.Event) -> str:
            delta = getattr(event, "delta", 0)
            if delta:
                canvas.yview_scroll(-max(1, abs(delta) // 120) if delta > 0 else max(1, abs(delta) // 120), "units")
            elif getattr(event, "num", 0) == 4:
                canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", 0) == 5:
                canvas.yview_scroll(3, "units")
            return "break"

        canvas.bind("<MouseWheel>", scroll)
        canvas.bind("<Button-4>", scroll)
        canvas.bind("<Button-5>", scroll)
        for row, (kana_row, roman_row) in enumerate(rows):
            for col, (kana, roman) in enumerate(zip(kana_row, roman_row)):
                count = counts.get(roman, 0)
                if roman in requested:
                    color, foreground = ("#2e9c67", "white") if count else ("#f2c94c", "#1d242b")
                else:
                    color, foreground = ("#367ca5", "white") if count else ("#59616a", "white")
                button = tk.Button(grid, text=f"{roman}\n{kana}  {count}", width=7, height=2, bg=color, fg=foreground, relief="flat", command=lambda labels={kana, roman}: self._filter_label(labels, window))
                button.grid(row=row, column=col, padx=3, pady=3)
                button.bind("<MouseWheel>", scroll)
                button.bind("<Button-4>", scroll)
                button.bind("<Button-5>", scroll)
        # Keep the ordinary chart compact, but surface requested phonemes such
        # as "ye" that are not part of the built-in gojuon rows.
        built_in = set(kana_to_romaji.values())
        extras = sorted(requested - built_in)
        if extras:
            extra_row = len(rows) + 1
            ttk.Label(grid, text="収集用リストのみ", padding=(2, 9, 2, 2)).grid(row=extra_row, column=0, columnspan=5, sticky="w")
            for index, label in enumerate(extras):
                count = counts.get(label, 0)
                color, foreground = ("#2e9c67", "white") if count else ("#f2c94c", "#1d242b")
                button = tk.Button(
                    grid, text=f"{label}\n{count}", width=7, height=2, bg=color, fg=foreground,
                    relief="flat", command=lambda labels={label}: self._filter_label(labels, window),
                )
                button.grid(row=extra_row + 1 + index // 5, column=index % 5, padx=3, pady=3)
                button.bind("<MouseWheel>", scroll)
                button.bind("<Button-4>", scroll)
                button.bind("<Button-5>", scroll)
        breaths = sum(s.breath for s in self.project.segments)
        sighs = sum(getattr(s, "sigh", False) for s in self.project.segments)
        ttk.Label(window, text=f"ブレス: {breaths}　息: {sighs}　全候補: {len(self.project.segments)}", padding=10).pack(anchor="w")

    def _filter_label(self, labels: set[str], window: tk.Toplevel) -> None:
        self.search_var.set("")
        self._coverage_filter_labels = labels
        self.refresh_segments()
        window.destroy()

    def _clear_coverage_filter(self) -> None:
        """Return from a kana-table filter to the complete list."""
        self._coverage_filter_labels = None
        if self.search_var.get():
            self.search_var.set("")
        else:
            self.refresh_segments()

    def show_settings(self) -> None:
        window = tk.Toplevel(self)
        window.title("設定")
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=14)
        frame.pack()
        rate = tk.IntVar(value=self.project.settings.sample_rate)
        depth = tk.IntVar(value=self.project.settings.bit_depth)
        normalize = tk.BooleanVar(value=self.project.settings.normalize)
        minutes = tk.IntVar(value=self.project.settings.autosave_minutes)
        recovery = tk.StringVar(value=self.project.settings.recovery_folder or str(APP_DIR / "recovery"))
        ttk.Label(frame, text="出力サンプルレート").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(frame, textvariable=rate, values=(44100, 48000), state="readonly", width=12).grid(row=0, column=1, sticky="ew")
        ttk.Label(frame, text="出力ビット深度").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(frame, textvariable=depth, values=(16, 24), state="readonly", width=12).grid(row=1, column=1, sticky="ew")
        ttk.Checkbutton(frame, text="ピークをそろえる（ノーマライズ）", variable=normalize).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(frame, text="自動保存間隔（分）").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Spinbox(frame, from_=1, to=60, textvariable=minutes, width=10).grid(row=3, column=1, sticky="w")
        ttk.Label(frame, text="復旧ファイルの保存先").grid(row=4, column=0, sticky="w", pady=4)
        folder_row = ttk.Frame(frame)
        folder_row.grid(row=5, column=0, columnspan=2, sticky="ew")
        ttk.Entry(folder_row, textvariable=recovery, width=48).pack(side="left", fill="x", expand=True)
        ttk.Button(folder_row, text="選択", command=lambda: self._choose_folder(recovery)).pack(side="left", padx=(4, 0))
        def save_settings() -> None:
            self._record()
            self.project.settings.sample_rate = rate.get()
            self.project.settings.bit_depth = depth.get()
            self.project.settings.normalize = normalize.get()
            self.project.settings.autosave_minutes = max(1, minutes.get())
            self.project.settings.recovery_folder = recovery.get()
            window.destroy()
            self.status_var.set("設定を保存しました")
        ttk.Button(frame, text="保存", style="Accent.TButton", command=save_settings).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(14, 0))

    def _choose_folder(self, variable: tk.StringVar) -> None:
        value = filedialog.askdirectory(initialdir=variable.get() or str(APP_DIR))
        if value:
            variable.set(value)

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        self.stop_audio()
        self.project = Project()
        self.project_path = None
        self.current_source_id = None
        self.current_segment_id = None
        self.current_samples = None
        self.history = History(100)
        self._dirty = False
        self.refresh_sources()
        self.refresh_segments()
        self.draw_audio()
        self.title("Mora Cutter MVP")

    def open_project(self) -> None:
        path = filedialog.askopenfilename(title="プロジェクトを開く", filetypes=[("Mora Cutter project", "*.mcp.json"), ("JSON", "*.json")])
        if path:
            self._load_project_path(path)

    def _load_project_path(self, path: str) -> None:
        try:
            self.project = load_project(path)
            self.project_path = path
            self._remember_project(path)
            self.current_source_id = self.project.sources[0].id if self.project.sources else None
            self.current_segment_id = None
            self.current_samples = None
            self.history = History(100)
            self._dirty = False
            self.refresh_sources()
            self._load_current_audio()
            self.title(f"Mora Cutter MVP — {Path(path).name}")
            self.status_var.set("プロジェクトを開きました")
        except Exception as exc:
            messagebox.showerror("開けません", str(exc))

    def save(self) -> bool:
        if not self.project_path:
            return self.save_as()
        try:
            self._save_transcript()
            self._sync_settings()
            save_project(self.project, self.project_path)
            self._remember_project(self.project_path)
            self._dirty = False
            self.status_var.set("プロジェクトを保存しました")
            return True
        except Exception as exc:
            messagebox.showerror("保存できません", str(exc))
            return False

    def save_as(self) -> bool:
        path = filedialog.asksaveasfilename(title="プロジェクトを保存", defaultextension=".mcp.json", filetypes=[("Mora Cutter project", "*.mcp.json")])
        if not path:
            return False
        self.project_path = path
        self.project.name = Path(path).name.removesuffix(".mcp.json")
        self.title(f"Mora Cutter MVP — {Path(path).name}")
        return self.save()

    def _sync_settings(self) -> None:
        """Manual edition has no per-project automatic-recognition settings."""

    def _recovery_folder(self) -> Path:
        return Path(self.project.settings.recovery_folder or APP_DIR / "recovery")

    def _schedule_autosave(self) -> None:
        if self._dirty and self.project.sources:
            try:
                self._save_transcript()
                self._sync_settings()
                folder = self._recovery_folder()
                folder.mkdir(parents=True, exist_ok=True)
                save_project(self.project, str(folder / "autosave.mcp.json"))
                self.secondary_status_var.set(f"自動保存: 完了（{datetime.now():%H:%M:%S}）")
            except Exception as exc:
                self.secondary_status_var.set(f"自動保存: 失敗 — {exc}")
        delay = max(1, self.project.settings.autosave_minutes) * 60 * 1000
        self.after(delay, self._schedule_autosave)

    def _offer_recovery(self) -> None:
        recovery = self._recovery_folder() / "autosave.mcp.json"
        if recovery.exists() and messagebox.askyesno("復旧ファイル", "前回の自動復旧ファイルがあります。開きますか？"):
            self._load_project_path(str(recovery))
            self.project_path = None
            self._dirty = True

    def open_recovery(self) -> None:
        path = filedialog.askopenfilename(initialdir=str(self._recovery_folder()), filetypes=[("Mora Cutter project", "*.mcp.json"), ("JSON", "*.json")])
        if path:
            self._load_project_path(path)
            self.project_path = None
            self._dirty = True

    def check_environment(self) -> None:
        python_ok = f"Python {sys.version.split()[0]}"
        numpy_ok = f"NumPy {np.__version__}"
        ffmpeg = shutil.which("ffmpeg") or "見つかりません"
        ffplay = shutil.which("ffplay") or "見つかりません"
        messagebox.showinfo("動作環境", f"{python_ok}\n{numpy_ok}\nFFmpeg: {ffmpeg}\nFFplay: {ffplay}")

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        answer = messagebox.askyesnocancel("未保存の変更", "変更を保存しますか？")
        if answer is None:
            return False
        if answer:
            return self.save()
        return True

    def _on_close(self) -> None:
        if self._detection_cancel_event is not None:
            self._detection_cancel_event.set()
        if not self._confirm_discard():
            return
        self.stop_audio()
        self.destroy()

    @staticmethod
    def _format_time(seconds: float) -> str:
        minutes = int(seconds // 60)
        rest = seconds - minutes * 60
        return f"{minutes:02d}:{rest:06.3f}"


def main() -> None:
    app = MoraCutterApp()
    app.mainloop()
