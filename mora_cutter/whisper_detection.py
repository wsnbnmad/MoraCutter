from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
import queue
import time
from typing import Any, Callable

import numpy as np

from .audio import decode_mono, estimate_pitch, quality_metrics
from .detection import DISPLAY_RATE, _valley_boundaries
from .domain import Segment
from .japanese import labels_for_unit


class WhisperUnavailable(RuntimeError):
    pass


class WhisperCancelled(RuntimeError):
    pass


class WhisperStalled(RuntimeError):
    pass


GPU_STALL_TIMEOUT_SECONDS = 120
CPU_STALL_TIMEOUT_SECONDS = 600
MAX_INITIAL_PROMPT_CHARACTERS = 120


def _is_gpu_runtime_error(error: Exception) -> bool:
    message = str(error).lower()
    markers = ("cuda", "cublas", "cudnn", "nvrtc", "gpu", "device", "compute type")
    return any(marker in message for marker in markers)


def _reading(text: str) -> str:
    try:
        import pyopenjtalk

        return str(pyopenjtalk.g2p(text, kana=True))
    except ImportError:
        return text


def _recognized_words(segments: Any) -> list[tuple[float, float, str, float]]:
    words: list[tuple[float, float, str, float]] = []
    for segment in segments:
        timed_words = list(segment.words or [])
        if timed_words:
            for word in timed_words:
                if word.start is None or word.end is None:
                    continue
                words.append((float(word.start), float(word.end), str(word.word).strip(), float(word.probability or 0.0)))
        elif segment.end > segment.start:
            words.append((float(segment.start), float(segment.end), str(segment.text).strip(), float(segment.avg_logprob + 1.0)))
    return words


def _transcribe_with_progress(
    model: Any,
    path: str,
    options: dict[str, Any],
    report: Callable[[float, str], None],
    start_percent: float,
    end_percent: float,
    device_label: str,
) -> list[tuple[float, float, str, float]]:
    generated, info = model.transcribe(path, **options)
    duration = max(float(getattr(info, "duration", 0.0)), 0.001)
    segments: list[Any] = []
    report(start_percent, f"Whisper: {device_label}認識開始 0:00/{int(duration)//60}:{int(duration)%60:02d}")
    last_reported = -1
    for segment in generated:
        segments.append(segment)
        completed = float(np.clip(float(segment.end)/duration, 0, 1))
        percent = start_percent + completed*(end_percent-start_percent)
        whole_percent = int(percent)
        if whole_percent != last_reported:
            elapsed = min(duration, float(segment.end))
            report(
                percent,
                f"Whisper: {device_label}認識中 {int(elapsed)//60}:{int(elapsed)%60:02d}/{int(duration)//60}:{int(duration)%60:02d}",
            )
            last_reported = whole_percent
    report(end_percent, f"Whisper: {device_label}認識完了")
    return _recognized_words(segments)


def _segment_words(segment: Any) -> list[tuple[float, float, str, float]]:
    return _recognized_words([segment])


def _prompt_excerpt(transcript: str, limit: int = MAX_INITIAL_PROMPT_CHARACTERS) -> str | None:
    compact = " ".join(transcript.split())
    return compact[:limit] if compact else None


def _local_model_snapshot(cache_root: Path, model_id: str) -> Path | None:
    repository = cache_root / f"models--Systran--faster-whisper-{model_id.replace('/', '--')}"
    snapshots = repository / "snapshots"
    if not snapshots.is_dir():
        return None
    required = ("config.json", "model.bin", "tokenizer.json")
    candidates = sorted(
        (folder for folder in snapshots.iterdir() if folder.is_dir()),
        key=lambda folder: folder.stat().st_mtime,
        reverse=True,
    )
    return next((folder for folder in candidates if all((folder / name).stat().st_size > 0 for name in required if (folder / name).is_file()) and all((folder / name).is_file() for name in required)), None)


def _whisper_process_worker(
    messages: Any,
    path: str,
    model_id: str,
    cache_root: str,
    device: str,
    compute_type: str,
    options: dict[str, Any],
) -> None:
    """Run CTranslate2 in an expendable process so a stalled GPU call can be stopped."""
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(model_id, device=device, compute_type=compute_type, download_root=cache_root)
        messages.put(("model_ready", None))
        generated, info = model.transcribe(path, **options)
        duration = max(float(getattr(info, "duration", 0.0)), 0.001)
        messages.put(("started", duration))
        for segment in generated:
            messages.put(("segment", (float(segment.end), _segment_words(segment))))
        messages.put(("done", None))
    except BaseException as exc:
        messages.put(("error", (type(exc).__name__, str(exc))))


def _stop_process(process: Any) -> None:
    if process.is_alive():
        process.terminate()
    process.join(timeout=5)
    if process.is_alive() and hasattr(process, "kill"):
        process.kill()
        process.join(timeout=2)


def _transcribe_in_subprocess(
    path: str,
    model_id: str,
    cache_root: Path,
    device: str,
    compute_type: str,
    options: dict[str, Any],
    report: Callable[[float, str], None],
    start_percent: float,
    end_percent: float,
    device_label: str,
    stall_timeout: int,
    cancel_event: Any = None,
) -> list[tuple[float, float, str, float]]:
    context = mp.get_context("spawn")
    messages = context.Queue()
    process = context.Process(
        target=_whisper_process_worker,
        args=(messages, path, model_id, str(cache_root), device, compute_type, options),
        daemon=True,
    )
    process.start()
    words: list[tuple[float, float, str, float]] = []
    duration = 0.0
    last_audio_position = 0.0
    last_activity = started_at = time.monotonic()
    phase = "モデルを読み込み中"
    normal_exit = False
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise WhisperCancelled("認識をキャンセルしました")
            try:
                kind, payload = messages.get(timeout=1.0)
            except queue.Empty:
                now = time.monotonic()
                inactive = int(now - last_activity)
                total_elapsed = int(now - started_at)
                if not process.is_alive():
                    raise RuntimeError(f"Whisperの処理プロセスが終了しました（終了コード: {process.exitcode}）")
                if inactive >= stall_timeout:
                    raise WhisperStalled(
                        f"{device_label.rstrip('で')}処理が{stall_timeout}秒間応答しませんでした"
                    )
                position = (
                    f"{int(last_audio_position)//60}:{int(last_audio_position)%60:02d}/"
                    f"{int(duration)//60}:{int(duration)%60:02d}"
                    if duration else "音声位置を取得中"
                )
                percent = start_percent if duration else max(8.0, start_percent - 17.0)
                report(
                    percent,
                    f"Whisper: {device_label}{phase} — 経過 {total_elapsed//60}:{total_elapsed%60:02d}、"
                    f"応答待ち {inactive}秒（{position}）",
                )
                continue

            last_activity = time.monotonic()
            if kind == "model_ready":
                phase = "音声を準備中"
                report(max(12.0, start_percent - 13.0), f"Whisper: {device_label}モデル読込完了、音声を準備中")
            elif kind == "started":
                duration = max(float(payload), 0.001)
                phase = "認識中"
                report(start_percent, f"Whisper: {device_label}認識開始 0:00/{int(duration)//60}:{int(duration)%60:02d}")
            elif kind == "segment":
                segment_end, segment_words = payload
                last_audio_position = min(duration, float(segment_end))
                words.extend(segment_words)
                completed = float(np.clip(last_audio_position / max(duration, 0.001), 0, 1))
                percent = start_percent + completed * (end_percent - start_percent)
                report(
                    percent,
                    f"Whisper: {device_label}認識中 {int(last_audio_position)//60}:{int(last_audio_position)%60:02d}/"
                    f"{int(duration)//60}:{int(duration)%60:02d}",
                )
            elif kind == "done":
                normal_exit = True
                process.join(timeout=5)
                report(end_percent, f"Whisper: {device_label}認識完了")
                return words
            elif kind == "error":
                error_type, error_message = payload
                raise RuntimeError(f"{error_type}: {error_message}")
    finally:
        if not normal_exit:
            _stop_process(process)
        messages.close()
        messages.cancel_join_thread()


def _merge_word_intervals(words: list[tuple[float, float, str, float]], duration: float) -> list[tuple[float, float, float]]:
    merged: list[list[float]] = []
    for start, end, _text, probability in words:
        start = max(0.0, min(start, duration))
        end = max(start + 0.001, min(end, duration))
        if merged and start <= merged[-1][1] + 0.08:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2] = max(merged[-1][2], probability)
        else:
            merged.append([start, end, probability])
    return [(item[0], item[1], item[2]) for item in merged]


def _transcript_units(
    words: list[tuple[float, float, str, float]],
    transcript: str,
    unit: str,
    samples: np.ndarray,
    duration: float,
) -> list[tuple[float, float, str, float]]:
    labels = labels_for_unit(_reading(transcript), unit)
    recognized: list[tuple[float, float, float, list[str]]] = []
    observed_labels: list[str] = []
    observed_word_indexes: list[int] = []
    for start, end, text, probability in words:
        word_labels = labels_for_unit(_reading(text), unit)
        if not word_labels:
            continue
        word_index = len(recognized)
        recognized.append((max(0.0, start), min(duration, end), probability, word_labels))
        observed_labels.extend(word_labels)
        observed_word_indexes.extend([word_index] * len(word_labels))
    if not labels or not observed_labels:
        return []

    # Align the expected transcript with Whisper's recognized mora sequence.
    # Each expected label is then split inside its matched Whisper word rather
    # than being proportionally spread across the whole recording.
    target_count = len(labels)
    observed_count = len(observed_labels)
    width = observed_count + 1
    directions = bytearray((target_count + 1) * width)  # diagonal=0, up=1, left=2
    previous = list(range(observed_count + 1))
    for column in range(1, observed_count + 1):
        directions[column] = 2
    for row in range(1, target_count + 1):
        current = [row] + [0] * observed_count
        directions[row * width] = 1
        for column in range(1, observed_count + 1):
            diagonal = previous[column - 1] + (labels[row - 1] != observed_labels[column - 1])
            up = previous[column] + 1
            left = current[column - 1] + 1
            best = min(diagonal, up, left)
            current[column] = best
            directions[row * width + column] = 0 if diagonal == best else (1 if up == best else 2)
        previous = current

    assigned_words: list[int | None] = [None] * target_count
    row, column = target_count, observed_count
    while row > 0 or column > 0:
        direction = directions[row * width + column]
        if row > 0 and column > 0 and direction == 0:
            assigned_words[row - 1] = observed_word_indexes[column - 1]
            row -= 1
            column -= 1
        elif row > 0 and (column == 0 or direction == 1):
            row -= 1
        else:
            column -= 1

    anchors = [index for index, value in enumerate(assigned_words) if value is not None]
    if not anchors:
        return []
    for index, value in enumerate(assigned_words):
        if value is None:
            nearest = min(anchors, key=lambda anchor: abs(anchor - index))
            assigned_words[index] = assigned_words[nearest]

    by_word: dict[int, list[int]] = {}
    for label_index, word_index in enumerate(assigned_words):
        if word_index is not None:
            by_word.setdefault(word_index, []).append(label_index)
    timed: dict[int, tuple[float, float, str, float]] = {}
    for word_index, label_indexes in by_word.items():
        start, end, probability, _word_labels = recognized[word_index]
        if end <= start:
            continue
        boundaries = _valley_boundaries(samples, len(label_indexes), start, end)
        for local_index, label_index in enumerate(label_indexes):
            timed[label_index] = (boundaries[local_index], boundaries[local_index + 1], labels[label_index], probability)
    return [timed[index] for index in range(target_count) if index in timed]


def whisper_detect(
    path: str,
    source_id: str,
    transcript: str,
    unit: str,
    model_id: str,
    use_gpu: bool,
    cache_root: Path,
    progress: Callable[[float, str], None] | None = None,
    cancel_event: Any = None,
    assist_only: bool = False,
) -> list[Segment]:
    report = progress or (lambda _percent, _message: None)
    report(2, "Whisper: 推論コンポーネントを確認中")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise WhisperUnavailable(
            "高精度モデル用コンポーネントがありません。requirements-whisper.txtを導入するか、対応EXE版を使用してください。"
        ) from exc

    cache_root.mkdir(parents=True, exist_ok=True)
    device = "cuda" if use_gpu else "cpu"
    compute_type = "int8_float16" if use_gpu else "int8"
    transcribe_options = dict(
        language="ja",
        beam_size=3,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=120, speech_pad_ms=80),
        condition_on_previous_text=True,
        initial_prompt=_prompt_excerpt(transcript),
        # Passing the same long text as both initial_prompt and hotwords can
        # concatenate two ~223-token prompts and exceed Whisper's 448-token
        # text context. The full transcript is still used below for alignment.
        hotwords=None,
    )
    try:
        report(8, f"Whisper: {model_id}を準備中（初回はダウンロード）")
        local_snapshot = _local_model_snapshot(cache_root, model_id)
        model_source = str(local_snapshot) if local_snapshot else model_id
        if local_snapshot:
            report(9, f"Whisper: 完成済みのローカル{model_id}モデルを使用")
        device_label = "GPUで" if use_gpu else "CPUで"
        words = _transcribe_in_subprocess(
            path, model_source, cache_root, device, compute_type, transcribe_options,
            report, 25, 68, device_label,
            GPU_STALL_TIMEOUT_SECONDS if use_gpu else CPU_STALL_TIMEOUT_SECONDS,
            cancel_event,
        )
    except Exception as first_error:
        if isinstance(first_error, WhisperCancelled):
            raise
        if not use_gpu or not (_is_gpu_runtime_error(first_error) or isinstance(first_error, WhisperStalled)):
            raise
        try:
            reason = "GPUが応答しない" if isinstance(first_error, WhisperStalled) else "GPUを使用できない"
            report(30, f"Whisper: {reason}ため停止し、CPUへ切り替え中")
            words = _transcribe_in_subprocess(
                path, model_source, cache_root, "cpu", "int8", transcribe_options,
                report, 40, 68, "CPUで", CPU_STALL_TIMEOUT_SECONDS, cancel_event,
            )
        except WhisperCancelled:
            raise
        except Exception as fallback_error:
            raise RuntimeError(f"GPU処理とCPUフォールバックの両方に失敗しました: {fallback_error}") from first_error

    report(70, "Whisper: モーラ境界を計算中")
    samples = decode_mono(path, DISPLAY_RATE)
    duration = len(samples) / DISPLAY_RATE
    if assist_only:
        intervals = _merge_word_intervals(words, duration)
        result: list[Segment] = []
        for order, (start, end, probability) in enumerate(intervals, 1):
            a = max(0, int(start * DISPLAY_RATE))
            b = min(len(samples), int(end * DISPLAY_RATE))
            pitch, stability = estimate_pitch(samples[a:b], DISPLAY_RATE)
            clarity, noise = quality_metrics(samples[a:b], DISPLAY_RATE)
            quality = 0.45 * clarity + 0.30 * noise + 0.15 * stability + 0.10 * np.clip(probability, 0, 1)
            result.append(Segment.create(
                source_id, start, end, cue=min(end - 0.001, start + 0.012),
                label="発声候補", unit="character", pitch=pitch,
                confidence=float(np.clip(quality, 0, 1)), quality_score=float(np.clip(quality, 0, 1)), order=order,
            ))
        # Whisper's VAD does not label breaths. Short non-silent gaps between
        # recognized speech intervals are therefore shown only as low-priority
        # breath hints; the user decides whether to keep them.
        energy_floor = float(np.percentile(np.abs(samples), 35)) if len(samples) else 0.0
        for index, ((_, left_end, _), (right_start, _, _)) in enumerate(zip(intervals, intervals[1:]), 1):
            gap_start, gap_end = left_end, right_start
            gap_length = gap_end - gap_start
            if not 0.06 <= gap_length <= 0.55:
                continue
            a = max(0, int(gap_start * DISPLAY_RATE))
            b = min(len(samples), int(gap_end * DISPLAY_RATE))
            gap = samples[a:b]
            if len(gap) == 0 or float(np.sqrt(np.mean(gap * gap))) <= max(0.003, energy_floor * 1.25):
                continue
            start = gap_start + gap_length * 0.15
            end = gap_end - gap_length * 0.10
            if end - start < 0.025:
                continue
            result.append(Segment.create(
                source_id, start, end, cue=start, label="ブレス候補", unit="character",
                confidence=0.25, quality_score=0.20, breath=True, order=len(intervals) + index,
            ))
        result.sort(key=lambda segment: (segment.start, segment.end))
        for order, segment in enumerate(result, 1):
            segment.order = order
        report(100, f"Whisper: 発声候補 {len(result)}件")
        return result
    expected_units = _transcript_units(words, transcript, unit, samples, duration) if transcript.strip() else []
    timed_units: list[tuple[float, float, str, float]] = []
    if expected_units:
        timed_units = expected_units
    else:
        for start, end, text, word_probability in words:
            start = max(0.0, min(start, duration))
            end = max(start + 0.001, min(end, duration))
            labels = labels_for_unit(_reading(text), unit)
            if not labels:
                continue
            boundaries = _valley_boundaries(samples, len(labels), start, end)
            timed_units.extend(
                (boundaries[index], boundaries[index+1], label, word_probability)
                for index, label in enumerate(labels)
            )
    result: list[Segment] = []
    for order, (left, right, label, word_probability) in enumerate(timed_units, 1):
        report_step = max(1, len(timed_units)//100)
        if order == 1 or order == len(timed_units) or order % report_step == 0:
            report(72 + order/max(len(timed_units), 1)*27, f"Whisper: 候補を評価中 {order}/{len(timed_units)}")
        a = max(0, int(left * DISPLAY_RATE))
        b = min(len(samples), int(right * DISPLAY_RATE))
        pitch, stability = estimate_pitch(samples[a:b], DISPLAY_RATE)
        clarity, noise = quality_metrics(samples[a:b], DISPLAY_RATE)
        quality = 0.40 * clarity + 0.25 * noise + 0.20 * stability + 0.15 * np.clip(word_probability, 0, 1)
        result.append(Segment.create(
            source_id,
            left,
            right,
            cue=min(right - 0.001, left + 0.012),
            label=label,
            unit=unit,
            pitch=pitch,
            confidence=float(np.clip(0.55 * word_probability + 0.45 * quality, 0, 1)),
            quality_score=float(np.clip(quality, 0, 1)),
            order=order,
        ))
    report(100, "Whisper: 完了")
    return result
