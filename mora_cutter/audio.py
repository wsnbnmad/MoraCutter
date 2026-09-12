from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np


class AudioError(RuntimeError):
    pass


def _hidden_subprocess_kwargs() -> dict[str, object]:
    """Keep bundled FFmpeg tools from flashing a console window on Windows."""
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


@lru_cache(maxsize=None)
def executable(name: str) -> str:
    runtime_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    bundled = runtime_root / "bin" / (name + ".exe" if sys.platform == "win32" else name)
    if bundled.exists():
        return str(bundled)
    found = shutil.which(name)
    if not found:
        raise AudioError(f"{name} が見つかりません。PATHへFFmpegを追加してください。")
    return found


def probe(path: str) -> tuple[float, int]:
    command = [
        executable("ffprobe"), "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate:format=duration", "-of", "json", path,
    ]
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", **_hidden_subprocess_kwargs())
    if done.returncode:
        raise AudioError(done.stderr.strip() or f"音声を解析できません: {path}")
    raw = json.loads(done.stdout)
    duration = float(raw.get("format", {}).get("duration", 0.0))
    streams = raw.get("streams", [])
    sample_rate = int(streams[0].get("sample_rate", 48000)) if streams else 48000
    if duration <= 0:
        raise AudioError(f"音声の長さを取得できません: {path}")
    return duration, sample_rate


def decode_mono(path: str, sample_rate: int = 8000) -> np.ndarray:
    command = [
        executable("ffmpeg"), "-v", "error", "-i", path,
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-",
    ]
    done = subprocess.run(command, capture_output=True, **_hidden_subprocess_kwargs())
    if done.returncode:
        raise AudioError(done.stderr.decode("utf-8", "replace").strip())
    return np.frombuffer(done.stdout, dtype="<i2").astype(np.float32) / 32768.0


def play(path: str, start: float, end: float, loop: bool = False, speed: float = 1.0, gain_db: float = 0.0) -> subprocess.Popen[bytes]:
    duration = max(0.02, end - start)
    command = [
        executable("ffplay"), "-v", "error", "-nodisp", "-autoexit",
        "-probesize", "32768", "-analyzeduration", "0",
    ]
    command += ["-ss", f"{start:.6f}", "-t", f"{duration:.6f}"]
    filters: list[str] = []
    if speed != 1.0:
        filters.append(f"atempo={speed}")
    if abs(gain_db) > 0.001:
        filters.append(f"volume={gain_db:.3f}dB")
    if filters:
        command += ["-af", ",".join(filters)]
    command += [path]
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **_hidden_subprocess_kwargs(),
    )


def export_segment(
    source: str,
    destination: str,
    start: float,
    end: float,
    sample_rate: int,
    bit_depth: int,
    normalize: bool,
) -> None:
    codec = "pcm_s16le" if bit_depth == 16 else "pcm_s24le"
    command = [
        executable("ffmpeg"), "-y", "-v", "error", "-ss", f"{start:.6f}",
        "-i", source, "-t", f"{max(0.001, end-start):.6f}", "-vn", "-ac", "1",
        "-ar", str(sample_rate),
    ]
    filters: list[str] = []
    if normalize:
        filters.append("loudnorm=I=-16:TP=-1.0:LRA=11")
    if filters:
        command += ["-af", ",".join(filters)]
    command += ["-c:a", codec, destination]
    done = subprocess.run(command, capture_output=True, **_hidden_subprocess_kwargs())
    if done.returncode:
        raise AudioError(done.stderr.decode("utf-8", "replace").strip())


def estimate_pitch(samples: np.ndarray, sample_rate: int = 8000) -> tuple[str, float]:
    if len(samples) < sample_rate // 30:
        return "--", 0.0
    # A bounded central window is sufficient for a representative pitch and
    # avoids quadratic work on long selections.
    limit = max(sample_rate // 4, int(sample_rate * 0.75))
    if len(samples) > limit:
        offset = (len(samples) - limit) // 2
        samples = samples[offset:offset + limit]
    x = samples.astype(np.float32)
    x -= np.mean(x)
    rms = float(np.sqrt(np.mean(x * x)))
    if rms < 0.005:
        return "--", 0.0
    x *= np.hanning(len(x))
    fft_size = 1 << (2 * len(x) - 1).bit_length()
    spectrum = np.fft.rfft(x, n=fft_size)
    corr = np.fft.irfft(spectrum * np.conjugate(spectrum), n=fft_size)[:len(x)]
    lo = max(1, sample_rate // 1000)
    hi = min(len(corr) - 1, sample_rate // 60)
    if hi <= lo:
        return "--", 0.0
    region = corr[lo:hi]
    local_peaks = np.flatnonzero((region[1:-1] >= region[:-2]) & (region[1:-1] > region[2:])) + 1
    if len(local_peaks):
        strong = local_peaks[region[local_peaks] >= float(region.max()) * 0.80]
        peak_index = int(strong[0] if len(strong) else local_peaks[np.argmax(region[local_peaks])])
    else:
        peak_index = int(np.argmax(region))
    lag = lo + peak_index
    hz = sample_rate / lag
    midi = int(round(69 + 12 * math.log2(hz / 440.0)))
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    pitch = f"{names[midi % 12]}{midi // 12 - 1}"
    stability = float(np.clip(corr[lag] / max(corr[0], 1e-9), 0.0, 1.0))
    return pitch, stability


def quality_metrics(samples: np.ndarray, sample_rate: int = 8000) -> tuple[float, float]:
    if len(samples) < 32:
        return 0.0, 0.0
    frame = max(32, sample_rate // 100)
    usable = samples[: len(samples) // frame * frame]
    if len(usable) == 0:
        return 0.0, 0.0
    rms = np.sqrt(np.mean(usable.reshape(-1, frame) ** 2, axis=1) + 1e-12)
    floor = float(np.percentile(rms, 15))
    signal = float(np.percentile(rms, 75))
    snr = 20 * math.log10(max(signal, 1e-6) / max(floor, 1e-6))
    noise_score = float(np.clip(snr / 30.0, 0.0, 1.0))
    zcr = float(np.mean(np.abs(np.diff(np.signbit(samples)))))
    clarity = float(np.clip(1.0 - abs(zcr - 0.12) / 0.35, 0.0, 1.0))
    return clarity, noise_score


def safe_filename(value: str) -> str:
    forbidden = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in forbidden or ord(ch) < 32 else ch for ch in value.strip())
    return cleaned or "unknown"
