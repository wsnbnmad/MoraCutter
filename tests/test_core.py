from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

from mora_cutter.app import MoraCutterApp, _build_peak_pyramid, _peak_envelope
from mora_cutter.audio import _hidden_subprocess_kwargs, estimate_pitch
from mora_cutter.domain import Project, Segment
from mora_cutter.detection import discover_models
from mora_cutter.history import History
from mora_cutter.japanese import labels_for_unit, split_moras
from mora_cutter.project_io import load_project, save_project
from mora_cutter.whisper_detection import (
    _is_gpu_runtime_error,
    _local_model_snapshot,
    _prompt_excerpt,
    _transcribe_with_progress,
    _transcript_units,
)


class JapaneseTests(unittest.TestCase):
    def test_mora_split(self):
        self.assertEqual(split_moras("キャット、ティー"), ["きゃ", "っ", "と", "てぃ", "ー"])
        self.assertEqual(split_moras("ヴァイオリン"), ["ゔぁ", "い", "お", "り", "ん"])

    def test_units(self):
        self.assertEqual(labels_for_unit("きゃ", "mora"), ["きゃ"])
        self.assertEqual(labels_for_unit("きゃ", "character"), ["き", "ゃ"])

    def test_transcript_overrides_recognition_labels(self):
        samples = np.sin(np.linspace(0, 100, 8000)).astype(np.float32)
        words = [(0.1, 0.9, "誤認識", 0.8)]
        units = _transcript_units(words, "こんにちは", "mora", samples, 1.0)
        self.assertEqual([unit[2] for unit in units], ["こ", "ん", "に", "ち", "わ"])

    def test_transcript_alignment_keeps_word_timing_anchors(self):
        samples = np.sin(np.linspace(0, 100, 24000)).astype(np.float32)
        words = [(0.1, 0.5, "あい", 0.9), (2.0, 2.4, "うえ", 0.8)]
        units = _transcript_units(words, "あいうえ", "mora", samples, 3.0)
        self.assertEqual([unit[2] for unit in units], ["あ", "い", "う", "え"])
        self.assertLessEqual(units[1][1], 0.5)
        self.assertGreaterEqual(units[2][0], 2.0)

    def test_long_prompt_is_bounded(self):
        self.assertEqual(len(_prompt_excerpt("あ" * 1000) or ""), 120)

    def test_complete_copied_model_snapshot_is_used(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / "models--Systran--faster-whisper-large-v3" / "snapshots" / "revision"
            snapshot.mkdir(parents=True)
            for name in ("config.json", "model.bin", "tokenizer.json"):
                (snapshot / name).write_bytes(b"ok")
            self.assertEqual(_local_model_snapshot(Path(folder), "large-v3"), snapshot)

    def test_whisper_progress_advances_while_segments_are_generated(self):
        class FakeModel:
            def transcribe(self, _path, **_options):
                segments = [
                    SimpleNamespace(start=0.0, end=2.0, text="あ", words=None, avg_logprob=-0.1),
                    SimpleNamespace(start=2.0, end=4.0, text="い", words=None, avg_logprob=-0.1),
                ]
                return iter(segments), SimpleNamespace(duration=4.0)

        updates = []
        words = _transcribe_with_progress(FakeModel(), "dummy.wav", {}, lambda p, m: updates.append((p, m)), 25, 68, "GPUで")
        self.assertEqual(len(words), 2)
        self.assertEqual(updates[0][0], 25)
        self.assertTrue(any(25 < percent < 68 for percent, _message in updates))
        self.assertEqual(updates[-1][0], 68)

    def test_only_gpu_errors_trigger_cpu_fallback(self):
        self.assertTrue(_is_gpu_runtime_error(RuntimeError("Could not load cublas64_12.dll")))
        self.assertFalse(_is_gpu_runtime_error(RuntimeError("No position encodings are defined for positions >= 448")))


class DomainTests(unittest.TestCase):
    def test_peak_envelope_uses_each_screen_bin(self):
        samples = np.array([0, -1, 0.25, -0.5, 0.1, 0.8, -0.3, 0.2], dtype=np.float32)
        peaks = _peak_envelope(samples, 4)
        np.testing.assert_allclose(peaks, [1.0, 0.5, 0.8, 0.3])

    def test_peak_pyramid_preserves_block_maxima(self):
        levels = _build_peak_pyramid(np.array([0.1, -0.8, 0.3, -0.2], dtype=np.float32))
        np.testing.assert_allclose(levels[1], [0.8, 0.3])

    def test_fft_pitch_estimation(self):
        rate = 8000
        samples = np.sin(2 * np.pi * 440 * np.arange(rate) / rate).astype(np.float32)
        pitch, stability = estimate_pitch(samples, rate)
        self.assertEqual(pitch, "A4")
        self.assertGreater(stability, 0.5)

    def test_windows_subprocesses_are_hidden(self):
        options = _hidden_subprocess_kwargs()
        if sys.platform == "win32":
            self.assertTrue(options["creationflags"])
            self.assertIsNotNone(options["startupinfo"])
        else:
            self.assertEqual(options, {})

    def test_high_accuracy_models_are_available(self):
        with tempfile.TemporaryDirectory() as folder:
            models = discover_models(Path(folder))
        names = [model.name for model in models]
        self.assertTrue(any("Whisper large-v3" in name for name in names))
        self.assertFalse(any("Whisper small" in name for name in names))

    def test_clamp(self):
        segment = Segment.create("source", -1, 9, cue=10)
        segment.clamp(3)
        self.assertEqual(segment.start, 0)
        self.assertLess(segment.cue, segment.end)
        self.assertEqual(segment.end, 3)

    def test_roundtrip(self):
        project = Project()
        project.segments.append(Segment.create("s", 0.1, 0.5, label="さ", gain_db=-3.5))
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "test.mcp.json")
            save_project(project, path)
            loaded = load_project(path)
        self.assertEqual(loaded.segments[0].label, "さ")
        self.assertEqual(loaded.segments[0].gain_db, -3.5)

    def test_old_projects_default_segments_to_auto_origin(self):
        segment = Segment.create("s", 0.1, 0.5, label="さ")
        raw = Project(segments=[segment]).to_dict()
        raw["segments"][0].pop("origin")
        loaded = Project.from_dict(raw)
        self.assertEqual(loaded.segments[0].origin, "auto")

    def test_reanalysis_replaces_auto_keeps_manual_and_can_undo(self):
        auto = Segment.create("s", 0.1, 0.2, label="あ")
        manual = Segment.create("s", 0.3, 0.4, label="い", origin="manual")
        project = Project(segments=[auto, manual])
        history = History(100)
        history.record(project)
        holder = SimpleNamespace(project=project, _dirty=False)
        replacement = Segment.create("s", 0.5, 0.6, label="う")
        removed = MoraCutterApp._replace_auto_segments(holder, "s", [replacement])
        self.assertEqual(removed, 1)
        self.assertEqual([segment.label for segment in project.segments], ["い", "う"])
        restored = history.undo(project)
        self.assertEqual([segment.label for segment in restored.segments], ["あ", "い"])

    def test_history_capacity_and_undo(self):
        history = History(100)
        project = Project(name="before")
        history.record(project)
        project.name = "after"
        restored = history.undo(project)
        self.assertEqual(restored.name, "before")
        redone = history.redo(restored)
        self.assertEqual(redone.name, "after")

    def test_history_coalesces_continuous_edits(self):
        history = History(100)
        project = Project(name="before")
        history.record(project, "detail:1")
        project.name = "middle"
        history.record(project, "detail:1")
        project.name = "after"
        restored = history.undo(project)
        self.assertEqual(restored.name, "before")


if __name__ == "__main__":
    unittest.main()
