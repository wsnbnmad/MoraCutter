from __future__ import annotations

import gc
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .audio import decode_mono, estimate_pitch, executable, quality_metrics
from .detection import DISPLAY_RATE
from .domain import Segment
from .japanese import labels_for_unit
from .whisper_detection import WhisperCancelled

KOTOBA_MODEL = "kotoba-tech/kotoba-whisper-v2.2"
REAZON_MODEL = "reazon-research/japanese-wav2vec2-large-rs35kh"


def _hidden_subprocess_kwargs() -> dict[str, object]:
    if sys.platform != "win32":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": startup, "creationflags": subprocess.CREATE_NO_WINDOW}


def _cancel(event: Any) -> None:
    if event is not None and event.is_set():
        raise WhisperCancelled("解析をキャンセルしました")


def _segments(source_id: str, samples: np.ndarray, unit: str,
              timed: list[tuple[float, float, str, float]]) -> list[Segment]:
    result = []
    for order, (start, end, label, confidence) in enumerate(timed, 1):
        a, b = max(0, int(start*DISPLAY_RATE)), min(len(samples), int(end*DISPLAY_RATE))
        pitch, stability = estimate_pitch(samples[a:b], DISPLAY_RATE)
        clarity, noise = quality_metrics(samples[a:b], DISPLAY_RATE)
        score = .42*clarity + .28*noise + .2*stability + .1*confidence
        result.append(Segment.create(source_id, start, end, cue=min(end-.001, start+.012),
            label=label, unit=unit, pitch=pitch, confidence=float(np.clip(confidence, 0, 1)),
            quality_score=float(np.clip(score, 0, 1)), order=order))
    return result


def _write_wav(source: str, target: Path) -> None:
    command = [executable("ffmpeg"), "-y", "-v", "error", "-i", source, "-vn", "-ac", "1",
               "-ar", "16000", "-c:a", "pcm_s16le", str(target)]
    done = subprocess.run(command, capture_output=True, **_hidden_subprocess_kwargs())
    if done.returncode:
        raise RuntimeError(done.stderr.decode("utf-8", "replace"))


def _mfa_command() -> list[str]:
    """Find a working MFA command, preferring the dedicated Conda environment."""
    direct = shutil.which("mfa") or shutil.which("mfa.exe")
    candidates: list[list[str]] = [[direct]] if direct else []
    conda = shutil.which("conda") or shutil.which("conda.exe")
    if not conda:
        for candidate in (Path.home()/"miniforge3"/"Scripts"/"conda.exe", Path.home()/"mambaforge"/"Scripts"/"conda.exe"):
            if candidate.is_file():
                conda = str(candidate)
                break
    if conda:
        candidates.append([conda, "run", "-n", "moracutter-mfa", "mfa"])
    for command in candidates:
        done = subprocess.run(command + ["--version"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", **_hidden_subprocess_kwargs())
        if done.returncode == 0:
            return command
    raise RuntimeError(
        "MFAの実行環境がありません。Python 3.13へpipで入れたMFAはKalpyを含まないため使用できません。"
        "Miniforge/Condaを導入後、setup_mfa.batを実行してください。"
    )


def _mfa_intervals(path: Path) -> list[tuple[float, float, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    tier = next((p for p in re.split(r"(?=\s*item \[\d+\]:)", text)
                 if re.search(r'name\s*=\s*"phones?"', p, re.I)), "")
    pattern = re.compile(r"intervals \[\d+\]:\s*xmin\s*=\s*([\d.eE+-]+)\s*xmax\s*=\s*([\d.eE+-]+)\s*text\s*=\s*\"([^\"]*)\"", re.S)
    return [(float(a), float(b), p) for a, b, p in pattern.findall(tier)
            if p.strip().lower() not in {"", "sil", "sp", "spn", "<eps>"}]


def _group_phones(phones: list[tuple[float, float, str]], labels: list[str]) -> list[tuple[float, float, str, float]]:
    if not phones or not labels:
        return []
    edges = [phones[0][0]] + [p[1] for p in phones]
    result = []
    for i, label in enumerate(labels):
        left = min(len(phones)-1, math.floor(i*len(phones)/len(labels)))
        right = min(len(phones), max(left+1, math.floor((i+1)*len(phones)/len(labels))))
        result.append((edges[left], edges[right], label, .92))
    return result


def mfa_detect(path: str, source_id: str, transcript: str, unit: str, cache_root: Path,
               progress: Callable[[float, str], None] | None = None, cancel_event: Any = None) -> list[Segment]:
    report = progress or (lambda _p, _m: None)
    labels = labels_for_unit(transcript, unit)
    if not labels:
        raise RuntimeError("MFA解析には素材のテキストが必要です。")
    mfa = _mfa_command()
    def run(args: list[str]) -> None:
        done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", **_hidden_subprocess_kwargs())
        if done.returncode:
            raise RuntimeError((done.stderr or done.stdout).strip())
    report(5, "MFA: Japanese v3.0.0を確認中")
    # MFA resolves the Japanese v3.0.0 acoustic model and dictionary under
    # the stable japanese_mfa model name.  The CLI does not accept a version
    # flag for this command on every supported MFA 3.x release.
    for kind in ("acoustic", "dictionary"):
        run(mfa + ["model", "download", kind, "japanese_mfa"])
    _cancel(cancel_event)
    with tempfile.TemporaryDirectory(prefix="moracutter_mfa_") as folder:
        root = Path(folder); corpus = root/"corpus"; output = root/"aligned"
        corpus.mkdir(); output.mkdir(); _write_wav(path, corpus/"material.wav")
        (corpus/"material.lab").write_text(transcript.strip(), encoding="utf-8")
        report(22, "MFA: 強制アライン中")
        run(mfa + ["align", str(corpus), "japanese_mfa", "japanese_mfa", str(output),
             "--clean", "--output_format", "long_textgrid", "--single_speaker"])
        grids = list(output.rglob("*.TextGrid"))
        if not grids:
            raise RuntimeError("MFAがTextGridを出力しませんでした。")
        timed = _group_phones(_mfa_intervals(grids[0]), labels)
    report(100, f"MFA: 候補 {len(timed)}件")
    return _segments(source_id, decode_mono(path, DISPLAY_RATE), unit, timed)


def _ctc_edges(blank: np.ndarray, count: int, start: float, end: float) -> list[float]:
    if count <= 1 or len(blank) < 2:
        return [start, end]
    edges = [start]
    for i in range(1, count):
        target = i*len(blank)/count
        radius = max(2, int(len(blank)/count*.42))
        lo, hi = max(1, int(target)-radius), min(len(blank)-1, int(target)+radius+1)
        frame = lo + int(np.argmax(blank[lo:hi])) if hi > lo else int(target)
        point = start + frame/len(blank)*(end-start)
        edges.append(max(edges[-1]+.008, min(point, end-(count-i)*.008)))
    return edges + [end]


def _ctc_safe_input(samples: np.ndarray, minimum_samples: int = 8_000) -> np.ndarray:
    """Pad a short CTC input without changing its external timestamps."""
    if len(samples) >= minimum_samples:
        return samples
    return np.pad(samples, (0, minimum_samples-len(samples)))


def _ctc_viterbi_token_frames(log_probs: np.ndarray, tokens: list[int], blank_id: int) -> list[tuple[int, int, float]]:
    """Forced-align CTC token ids and return frame spans for every token."""
    if not tokens or len(log_probs) == 0:
        return []
    extended = np.empty(len(tokens) * 2 + 1, dtype=np.int32)
    extended[::2] = blank_id
    extended[1::2] = tokens
    state_count = len(extended)
    scores = np.full(state_count, -np.inf, dtype=np.float32)
    scores[0] = log_probs[0, blank_id]
    if state_count > 1:
        scores[1] = log_probs[0, extended[1]]
    parents = np.zeros((len(log_probs), state_count), dtype=np.int8)
    for frame in range(1, len(log_probs)):
        next_scores = np.full(state_count, -np.inf, dtype=np.float32)
        for state in range(state_count):
            best, parent = scores[state], 0
            if state and scores[state-1] > best:
                best, parent = scores[state-1], 1
            if state > 1 and extended[state] != blank_id and extended[state] != extended[state-2] and scores[state-2] > best:
                best, parent = scores[state-2], 2
            next_scores[state] = best + log_probs[frame, extended[state]]
            parents[frame, state] = parent
        scores = next_scores
    state = state_count - 1 if scores[-1] >= scores[-2] else state_count - 2
    states = np.zeros(len(log_probs), dtype=np.int32)
    for frame in range(len(log_probs)-1, -1, -1):
        states[frame] = state
        if frame:
            state -= int(parents[frame, state])
    result: list[tuple[int, int, float]] = []
    for token_index in range(len(tokens)):
        frames = np.flatnonzero(states == 2*token_index+1)
        if len(frames) == 0:
            result.append((0, 0, -20.0))
        else:
            result.append((int(frames[0]), int(frames[-1])+1, float(np.mean(log_probs[frames, tokens[token_index]]))))
    return result


def _ctc_forced_mora_timing(log_probs: np.ndarray, tokenizer: Any, labels: list[str], duration: float) -> list[tuple[float, float, str, float]]:
    """Align each kana inside a mora against the ReazonSpeech CTC lattice."""
    vocabulary = tokenizer.get_vocab()
    unknown = int(getattr(tokenizer, "unk_token_id", -1))
    token_ids: list[int] = []
    mora_ranges: list[tuple[int, int]] = []
    for label in labels:
        left = len(token_ids)
        for character in label:
            token_id = int(vocabulary.get(character, unknown))
            if token_id < 0 or token_id == unknown:
                return []
            token_ids.append(token_id)
        mora_ranges.append((left, len(token_ids)))
    frames = _ctc_viterbi_token_frames(log_probs, token_ids, int(tokenizer.pad_token_id))
    if not frames:
        return []
    step = duration / len(log_probs)
    timed: list[tuple[float, float, str, float]] = []
    previous_end = 0.0
    for label, (left, right) in zip(labels, mora_ranges):
        selected = frames[left:right]
        starts = [row[0] for row in selected if row[1] > row[0]]
        ends = [row[1] for row in selected if row[1] > row[0]]
        if not starts:
            start, end, confidence = previous_end, previous_end + step, 0.05
        else:
            start, end = min(starts)*step, max(ends)*step
            confidence = float(np.clip(np.exp(np.mean([row[2] for row in selected])), 0.05, 0.98))
        start = max(previous_end, start)
        end = max(start + 0.008, end)
        timed.append((start, min(duration, end), label, confidence))
        previous_end = timed[-1][1]
    return timed


def _sequence_map(target: list[str], observed: list[str]) -> list[int | None]:
    """Levenshtein-align labels; each target index points at its observed counterpart."""
    n, m = len(target), len(observed)
    cost = [[0]*(m+1) for _ in range(n+1)]
    step = [[""]*(m+1) for _ in range(n+1)]
    for i in range(1, n+1): cost[i][0], step[i][0] = i, "del"
    for j in range(1, m+1): cost[0][j], step[0][j] = j, "ins"
    for i in range(1, n+1):
        for j in range(1, m+1):
            choices = ((cost[i-1][j-1] + (target[i-1] != observed[j-1]), "diag"),
                       (cost[i-1][j]+1, "del"), (cost[i][j-1]+1, "ins"))
            cost[i][j], step[i][j] = min(choices, key=lambda value: value[0])
    result: list[int | None] = [None]*n
    i, j = n, m
    while i or j:
        direction = step[i][j]
        if direction == "diag": result[i-1] = j-1; i -= 1; j -= 1
        elif direction == "del": i -= 1
        else: j -= 1
    return result


def _retime_target(target: list[str], observed: list[tuple[float, float, str, float]], duration: float) -> list[tuple[float, float, str, float]]:
    if not target:
        return observed
    if not observed:
        step = duration/max(1, len(target))
        return [(i*step, (i+1)*step, label, .25) for i, label in enumerate(target)]
    mapping = _sequence_map(target, [item[2] for item in observed])
    anchors = [i for i, value in enumerate(mapping) if value is not None]
    for i, value in enumerate(mapping):
        if value is None:
            left = next((mapping[k] for k in range(i-1, -1, -1) if mapping[k] is not None), None)
            right = next((mapping[k] for k in range(i+1, len(mapping)) if mapping[k] is not None), None)
            if left is None and right is None: mapping[i] = round(i*(len(observed)-1)/max(1, len(target)-1))
            elif left is None: mapping[i] = right
            elif right is None: mapping[i] = left
            else: mapping[i] = round((left+right)/2)
    grouped: dict[int, list[int]] = {}
    for i, value in enumerate(mapping): grouped.setdefault(int(value or 0), []).append(i)
    result: list[tuple[float, float, str, float] | None] = [None]*len(target)
    for observed_index, indexes in grouped.items():
        start, end, _label, confidence = observed[min(observed_index, len(observed)-1)]
        width = (end-start)/len(indexes)
        for local, target_index in enumerate(indexes):
            result[target_index] = (start+local*width, start+(local+1)*width, target[target_index], confidence)
    return [item for item in result if item is not None]


def _vad_outer_edges(timed: list[tuple[float, float, str, float]], speech: list[dict[str, Any]]) -> list[tuple[float, float, str, float]]:
    if not timed or not speech:
        return timed
    result = list(timed)
    for span in speech:
        a, b = float(span["start"]), float(span["end"])
        indexes = [i for i, item in enumerate(result) if min(b, item[1]) > max(a, item[0])]
        if not indexes: continue
        first, last = indexes[0], indexes[-1]
        s, e, label, confidence = result[first]; result[first] = (max(a, min(s, b)), e, label, confidence)
        s, e, label, confidence = result[last]; result[last] = (s, min(b, max(e, a)), label, confidence)
    return result


def kotoba_reazon_silero_detect(path: str, source_id: str, transcript: str, unit: str,
        use_gpu: bool, cache_root: Path, progress: Callable[[float, str], None] | None = None,
        cancel_event: Any = None) -> list[Segment]:
    report = progress or (lambda _p, _m: None)
    try:
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, Wav2Vec2ForCTC, pipeline
        from silero_vad import get_speech_timestamps, load_silero_vad
    except ImportError as exc:
        raise RuntimeError("高精度連結モデル用コンポーネントがありません。setup_high_accuracy.batを一度実行してください。Silero VADにはonnxruntimeが必要です。") from exc
    cache_root.mkdir(parents=True, exist_ok=True)
    device = "cuda:0" if use_gpu and torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device.startswith("cuda") else torch.float32
    audio = decode_mono(path, 16000); duration = len(audio)/16000
    if use_gpu and not device.startswith("cuda"):
        report(5, "Kotoba: GPUが利用できないためCPUで実行中。setup_gpu_acceleration.batでCUDA版PyTorchを導入できます")
    else:
        report(5, f"Kotoba: v2.2を準備中（{'GPU' if device.startswith('cuda') else 'CPU'}）")
    processor = AutoProcessor.from_pretrained(KOTOBA_MODEL, cache_dir=str(cache_root))
    model = AutoModelForSpeechSeq2Seq.from_pretrained(KOTOBA_MODEL, cache_dir=str(cache_root), torch_dtype=dtype).to(device)
    asr = pipeline("automatic-speech-recognition", model=model, tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor, torch_dtype=dtype,
        device=0 if device.startswith("cuda") else -1, chunk_length_s=28, stride_length_s=4)
    report(18, "Kotoba: 文字と大区間を認識中")
    output = asr({"array": audio, "sampling_rate": 16000}, return_timestamps=True,
                 generate_kwargs={"language": "ja", "task": "transcribe"})
    chunks = []
    for raw in output.get("chunks", []) or []:
        stamp = raw.get("timestamp") or (None, None)
        start = 0.0 if stamp[0] is None else float(stamp[0]); end = duration if stamp[1] is None else float(stamp[1])
        text = str(raw.get("text", "")).strip()
        if text and end > start: chunks.append((start, end, text))
    if not chunks and str(output.get("text", "")).strip(): chunks = [(0., duration, str(output["text"]).strip())]
    del asr, model, processor; gc.collect()
    if device.startswith("cuda"): torch.cuda.empty_cache()
    _cancel(cancel_event); report(46, "ReazonSpeech: CTCモデルを準備中")
    cproc = AutoProcessor.from_pretrained(REAZON_MODEL, cache_dir=str(cache_root))
    cmodel = Wav2Vec2ForCTC.from_pretrained(REAZON_MODEL, cache_dir=str(cache_root), torch_dtype=dtype).to(device).eval()
    blank_id = int(getattr(cmodel.config, "pad_token_id", 0) or 0)
    observed: list[tuple[float, float, str, float]] = []
    target = labels_for_unit(transcript, unit) if transcript.strip() else []
    if target:
        # Do not distribute moras uniformly inside Kotoba chunks.  Force the
        # user-supplied transcript through the full ReazonSpeech CTC lattice,
        # which makes every mora compete for the frames where it is spoken.
        _cancel(cancel_event)
        values = cproc(_ctc_safe_input(audio), sampling_rate=16000, return_tensors="pt").input_values.to(device=device, dtype=dtype)
        with torch.inference_mode(): logits = cmodel(values).logits[0].float().cpu()
        timed = _ctc_forced_mora_timing(torch.log_softmax(logits, dim=-1).numpy(), cproc.tokenizer, target, duration)
        report(80, f"ReazonSpeech: 歌詞のCTC強制アラインメント完了 {len(timed)}/{len(target)}モーラ")
        if not timed:
            raise RuntimeError("ReazonSpeech CTCで歌詞をアラインできませんでした。素材テキストをひらがなで確認してください。")
    else:
        for index, (start, end, text) in enumerate(chunks, 1):
            _cancel(cancel_event)
            labels = labels_for_unit(text, unit)
            if not labels or end <= start:
                continue
            clip = audio[max(0, int(start*16000)):min(len(audio), int(end*16000))]
            values = cproc(_ctc_safe_input(clip), sampling_rate=16000, return_tensors="pt").input_values.to(device=device, dtype=dtype)
            with torch.inference_mode(): logits = cmodel(values).logits[0].float().cpu()
            blank = torch.softmax(logits, dim=-1)[:, blank_id].numpy()
            edges = _ctc_edges(blank, len(labels), start, end)
            observed.extend((edges[i], edges[i+1], label, .86) for i, label in enumerate(labels))
            report(50+30*index/max(1, len(chunks)), f"ReazonSpeech: 認識結果のCTC境界を補正中 {index}/{len(chunks)}")
        timed = observed
    del cmodel, cproc; gc.collect()
    if device.startswith("cuda"): torch.cuda.empty_cache()
    report(84, "Silero VAD: 発声の前後端を補正中")
    vad = load_silero_vad(onnx=True)
    speech = get_speech_timestamps(torch.from_numpy(audio), vad, sampling_rate=16000, threshold=.35,
        min_speech_duration_ms=35, min_silence_duration_ms=55, speech_pad_ms=18, return_seconds=True)
    timed = _vad_outer_edges(timed, speech)
    report(100, f"高精度連結モデル: 候補 {len(timed)}件")
    return _segments(source_id, decode_mono(path, DISPLAY_RATE), unit, timed)
