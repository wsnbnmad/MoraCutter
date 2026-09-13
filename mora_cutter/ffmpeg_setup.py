from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import threading
import urllib.request
import zipfile
from collections.abc import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .runtime import CACHE_DIR, CONFIG_DIR, INSTALL_DIR, TOOLS_DIR


REQUIRED_TOOLS = ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe")
CONFIG_PATH = CONFIG_DIR / "ffmpeg.json"


def manifest_path() -> Path:
    candidates = (
        INSTALL_DIR / "ffmpeg-manifest.json",
        INSTALL_DIR / "_internal" / "ffmpeg-manifest.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def configured_bin_dir() -> Path | None:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        path = Path(str(data.get("bin_dir", "")))
        return path if path.is_dir() else None
    except (OSError, ValueError, TypeError):
        return None


def is_tool_folder(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_file() for name in REQUIRED_TOOLS)


def resolve_tool_folder(path: Path) -> Path | None:
    """Accept either FFmpeg's bin folder or the folder directly above it."""
    for candidate in (path, path / "bin"):
        if is_tool_folder(candidate):
            return candidate
    return None


def save_tool_folder(path: Path) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps({"bin_dir": str(path.resolve())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def install_from_manifest(progress: Callable[[float, str], None]) -> Path:
    manifest = json.loads(manifest_path().read_text(encoding="utf-8"))
    source = str(manifest["source"])
    expected = {str(name): str(value).upper() for name, value in manifest["files"].items()}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    archive = CACHE_DIR / "ffmpeg-download.zip"
    partial = archive.with_suffix(".zip.part")

    request = urllib.request.Request(source, headers={"User-Agent": "MoraCutter/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            received += len(chunk)
            ratio = received / total if total else 0.0
            progress(min(0.82, ratio * 0.82), f"FFmpegをダウンロード中 {ratio * 100:.0f}%" if total else "FFmpegをダウンロード中")
    partial.replace(archive)

    extract_root = CACHE_DIR / "ffmpeg-extracted"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)
    progress(0.85, "FFmpegを展開中")
    with zipfile.ZipFile(archive) as package:
        package.extractall(extract_root)

    matches = list(extract_root.rglob("ffmpeg.exe"))
    if not matches:
        raise RuntimeError("ダウンロードしたファイルにffmpeg.exeがありません。")
    source_bin = matches[0].parent
    if not is_tool_folder(source_bin):
        raise RuntimeError("FFmpegの必要なファイルが揃っていません。")
    for index, name in enumerate(REQUIRED_TOOLS, 1):
        if _sha256(source_bin / name) != expected[name]:
            raise RuntimeError(f"{name}のSHA-256が一致しません。")
        progress(0.85 + index * 0.03, f"{name}を確認中")

    destination = TOOLS_DIR / "ffmpeg" / "bin"
    staging = TOOLS_DIR / "ffmpeg-new" / "bin"
    if staging.parent.exists():
        shutil.rmtree(staging.parent)
    staging.mkdir(parents=True)
    for name in REQUIRED_TOOLS:
        shutil.copy2(source_bin / name, staging / name)
    if destination.parent.exists():
        shutil.rmtree(destination.parent)
    staging.parent.replace(destination.parent)
    save_tool_folder(destination)
    shutil.rmtree(extract_root, ignore_errors=True)
    archive.unlink(missing_ok=True)
    progress(1.0, "FFmpegの準備が完了しました")
    return destination


class _DownloadDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.title("FFmpegを準備")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result: Path | None = None
        self.error: BaseException | None = None
        self._updates: list[tuple[float, str]] = []
        self._lock = threading.Lock()
        self.status = tk.StringVar(value="ダウンロードを開始しています")
        self.value = tk.DoubleVar(value=0.0)
        ttk.Label(self, textvariable=self.status, width=46).pack(padx=18, pady=(16, 8))
        ttk.Progressbar(self, maximum=100, variable=self.value, length=380).pack(padx=18, pady=(0, 16))
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        threading.Thread(target=self._run, daemon=True).start()
        self.after(80, self._poll)

    def _progress(self, ratio: float, status: str) -> None:
        with self._lock:
            self._updates.append((ratio, status))

    def _run(self) -> None:
        try:
            self.result = install_from_manifest(self._progress)
        except BaseException as exc:
            self.error = exc

    def _poll(self) -> None:
        with self._lock:
            updates, self._updates = self._updates, []
        if updates:
            ratio, status = updates[-1]
            self.value.set(ratio * 100)
            self.status.set(status)
        if self.result is not None or self.error is not None:
            self.after(120, self.destroy)
            return
        self.after(80, self._poll)


def _select_existing_ffmpeg(parent: tk.Misc) -> bool:
    folder = filedialog.askdirectory(
        title="FFmpegのフォルダー（またはbinフォルダー）を選択",
        parent=parent,
    )
    if not folder:
        return False
    selected = resolve_tool_folder(Path(folder))
    if selected is None:
        messagebox.showerror(
            "FFmpeg",
            "ffmpeg.exe、ffprobe.exe、ffplay.exeが揃っているフォルダーを選択してください。",
            parent=parent,
        )
        return False
    save_tool_folder(selected)
    return True


def ensure_ffmpeg(parent: tk.Misc) -> bool:
    installed = TOOLS_DIR / "ffmpeg" / "bin"
    configured = configured_bin_dir()
    if is_tool_folder(installed) or (configured is not None and is_tool_folder(configured)):
        return True
    if all(shutil.which(name.removesuffix(".exe")) for name in REQUIRED_TOOLS):
        return True

    download = messagebox.askyesno(
        "FFmpegが必要です",
        "PC内を自動検索しましたが、FFmpegが見つかりませんでした。\n"
        "音声の読み込み・再生・書き出しにはFFmpegが必要です。\n\n"
        "FFmpegをダウンロードしますか？\n"
        "［いいえ］を選ぶと、既存のFFmpegフォルダーを自分で指定できます。",
        parent=parent,
    )
    if not download:
        return _select_existing_ffmpeg(parent)

    dialog = _DownloadDialog(parent)
    parent.wait_window(dialog)
    if dialog.error is not None:
        choose = messagebox.askyesno(
            "FFmpegの準備に失敗しました",
            f"{dialog.error}\n\n既存のFFmpegフォルダーを指定しますか？",
            parent=parent,
        )
        return _select_existing_ffmpeg(parent) if choose else False
    return dialog.result is not None
