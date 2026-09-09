from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

import numpy as np

from .audio import decode_mono, estimate_pitch, quality_metrics
from .domain import Segment
from .japanese import labels_for_unit


DISPLAY_RATE = 8000


@dataclass
class ModelInfo:
    name: str
    command: list[str] | None = None
    supports_gpu: bool = False
    kind: str = "external"
    model_id: str = ""
    download_note: str = ""


def discover_models(root: Path) -> list[ModelInfo]:
    models = [
        ModelInfo(
            "Whisper large-v3（高精度・補助候補）", supports_gpu=True, kind="whisper",
            model_id="large-v3", download_note="初回に約3GBのモデルをダウンロードします。",
        ),
    ]
    if not root.exists():
        return models
    for manifest in root.glob("*/model.json"):
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
            command = raw.get("command")
            if raw.get("name") and isinstance(command, list):
                models.append(ModelInfo(raw["name"], [str(v) for v in command], bool(raw.get("supports_gpu")), kind="external"))
        except (OSError, ValueError, TypeError):
            continue
    return models


def _energy(samples: np.ndarray, frame: int = 160) -> tuple[np.ndarray, np.ndarray]:
    count = len(samples) // frame
    if count == 0:
        return np.array([]), np.array([])
    framed = samples[:count * frame].reshape(count, frame)
    rms = np.sqrt(np.mean(framed * framed, axis=1) + 1e-10)
    times = (np.arange(count) + 0.5) * frame / DISPLAY_RATE
    return times, rms


def _speech_span(samples: np.ndarray) -> tuple[float, float]:
    times, rms = _energy(samples)
    if len(rms) == 0:
        return 0.0, len(samples) / DISPLAY_RATE
    floor = float(np.percentile(rms, 20))
    peak = float(np.percentile(rms, 95))
    threshold = floor + (peak - floor) * 0.18
    active = np.flatnonzero(rms >= threshold)
    if len(active) == 0:
        return 0.0, len(samples) / DISPLAY_RATE
    return max(0.0, float(times[active[0]] - 0.04)), min(len(samples) / DISPLAY_RATE, float(times[active[-1]] + 0.04))


def _valley_boundaries(samples: np.ndarray, count: int, lo: float, hi: float) -> list[float]:
    if count <= 1:
        return [lo, hi]
    times, rms = _energy(samples)
    boundaries = [lo]
    spacing = (hi - lo) / count
    for index in range(1, count):
        target = lo + index * spacing
        radius = max(0.025, spacing * 0.35)
        choices = np.flatnonzero((times >= target - radius) & (times <= target + radius))
        if len(choices):
            picked = choices[int(np.argmin(rms[choices]))]
            candidate = float(times[picked])
        else:
            candidate = target
        candidate = max(boundaries[-1] + 0.02, min(candidate, hi - (count-index) * 0.02))
        boundaries.append(candidate)
    boundaries.append(hi)
    return boundaries


def baseline_detect(
    path: str,
    source_id: str,
    transcript: str,
    unit: str,
    progress: Callable[[float, str], None] | None = None,
) -> list[Segment]:
    report = progress or (lambda _percent, _message: None)
    report(5, "ベースライン: 音声を読み込み中")
    samples = decode_mono(path, DISPLAY_RATE)
    report(25, "ベースライン: 発声区間を解析中")
    labels = labels_for_unit(transcript, unit)
    lo, hi = _speech_span(samples)
    if labels:
        boundaries = _valley_boundaries(samples, len(labels), lo, hi)
        raw = [(boundaries[i], boundaries[i + 1], label) for i, label in enumerate(labels)]
    else:
        times, rms = _energy(samples)
        if len(rms) == 0:
            return []
        floor = float(np.percentile(rms, 20))
        peak = float(np.percentile(rms, 95))
        active = rms > floor + (peak-floor) * 0.22
        changes = np.diff(active.astype(np.int8), prepend=0, append=0)
        starts = np.flatnonzero(changes == 1)
        ends = np.flatnonzero(changes == -1)
        raw = []
        for a, b in zip(starts, ends):
            start, end = float(times[a]), float(times[min(b, len(times)-1)])
            if end - start >= 0.045:
                raw.append((max(0, start-0.03), min(len(samples)/DISPLAY_RATE, end+0.03), "未分類"))
    segments: list[Segment] = []
    for order, (start, end, label) in enumerate(raw, 1):
        report_step = max(1, len(raw)//100)
        if order == 1 or order == len(raw) or order % report_step == 0:
            report(35 + order/max(len(raw), 1)*60, f"ベースライン: 候補 {order}/{len(raw)}")
        a = max(0, int(start * DISPLAY_RATE))
        b = min(len(samples), int(end * DISPLAY_RATE))
        pitch, stability = estimate_pitch(samples[a:b], DISPLAY_RATE)
        clarity, noise = quality_metrics(samples[a:b], DISPLAY_RATE)
        score = 0.45 * clarity + 0.30 * noise + 0.25 * stability
        segments.append(Segment.create(
            source_id, start, end, cue=min(end-0.001, start+0.015), label=label, unit=unit,
            pitch=pitch, confidence=float(np.clip(score * 0.85, 0, 1)), quality_score=score, order=order,
        ))
    report(100, "ベースライン: 完了")
    return segments


def external_detect(model: ModelInfo, path: str, source_id: str, transcript: str, unit: str, use_gpu: bool) -> list[Segment]:
    if not model.command:
        raise ValueError("外部モデルのコマンドがありません")
    request = json.dumps({"audio_path": path, "transcript": transcript, "unit": unit, "use_gpu": use_gpu}, ensure_ascii=False)
    done = subprocess.run(model.command, input=request + "\n", capture_output=True, text=True, encoding="utf-8")
    if done.returncode:
        raise RuntimeError(done.stderr.strip() or f"{model.name} が失敗しました")
    response = json.loads(done.stdout.splitlines()[-1])
    result: list[Segment] = []
    for order, raw in enumerate(response.get("segments", []), 1):
        result.append(Segment.create(
            source_id, float(raw["start"]), float(raw["end"]), cue=float(raw.get("cue", raw["start"])),
            label=str(raw.get("label", "未分類")), unit=unit, pitch=str(raw.get("pitch", "--")),
            confidence=float(raw.get("confidence", 0)), quality_score=float(raw.get("quality_score", 0)), order=order,
        ))
    return result
