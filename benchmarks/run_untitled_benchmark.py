"""Run the shared Japanese alignment benchmark without modifying a project.

Usage:
  python benchmarks/run_untitled_benchmark.py baseline
  python benchmarks/run_untitled_benchmark.py kotoba
  python benchmarks/run_untitled_benchmark.py mfa
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mora_cutter.detection import baseline_detect
from mora_cutter.domain import AudioSource
from mora_cutter.japanese import labels_for_unit
from mora_cutter.precision_detection import kotoba_reazon_silero_detect, mfa_detect
from mora_cutter.audio import probe


def main() -> None:
    reference = json.loads((Path(__file__).with_name("untitled_reference.json")).read_text(encoding="utf-8"))
    path = Path(reference["audio_path"])
    if not path.is_file():
        raise SystemExit(f"ベンチマーク音声が見つかりません: {path}")
    transcript = reference["transcript"]
    unit = reference["unit"]
    expected = labels_for_unit(transcript, unit)
    duration, rate = probe(str(path))
    source = AudioSource.create(str(path), duration, rate)
    kind = sys.argv[1].lower() if len(sys.argv) > 1 else "baseline"
    progress = lambda percent, message: print(f"{percent:5.1f}% {message}", flush=True)
    if kind == "baseline":
        result = baseline_detect(str(path), source.id, transcript, unit, progress)
    elif kind == "kotoba":
        result = kotoba_reazon_silero_detect(str(path), source.id, transcript, unit, True, ROOT / "models_cache", progress)
    elif kind == "mfa":
        result = mfa_detect(str(path), source.id, transcript, unit, ROOT / "models_cache", progress)
    else:
        raise SystemExit("モデルは baseline / kotoba / mfa のいずれかです。")
    labels = [segment.label for segment in result]
    correct_labels = sum(a == b for a, b in zip(labels, expected))
    valid_edges = all(0 <= s.start <= s.cue < s.end <= duration for s in result)
    summary = {
        "model": kind,
        "duration_seconds": round(duration, 3),
        "expected_labels": len(expected),
        "detected_segments": len(result),
        "label_matches_in_order": correct_labels,
        "all_edges_valid": valid_edges,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if len(result) != len(expected) or not valid_edges:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
