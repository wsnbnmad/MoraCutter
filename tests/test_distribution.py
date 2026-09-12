from __future__ import annotations

import os
import json
from pathlib import Path
import tempfile
import unittest

from mora_cutter.crash_logging import MAX_LOG_BYTES, MAX_LOG_FILES, prune_logs
from mora_cutter.runtime import user_data_dir


class DistributionTests(unittest.TestCase):
    def test_distribution_metadata_is_complete(self):
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "LICENSE.txt", "お読みください.txt", "resources/moracutter.ico",
            "windows.manifest", "windows_version_info.txt", "ffmpeg-manifest.json",
        ):
            self.assertTrue((root / relative).is_file(), relative)
        manifest = json.loads((root / "ffmpeg-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["files"]), {"ffmpeg.exe", "ffprobe.exe", "ffplay.exe"})
        self.assertTrue(all(len(value) == 64 for value in manifest["files"].values()))

    def test_manual_spec_does_not_bundle_recognition_models(self):
        spec = (Path(__file__).resolve().parents[1] / "MoraCutter.spec").read_text(encoding="utf-8")
        self.assertNotIn("faster_whisper", spec)
        self.assertNotIn("nvidia.cublas", spec)

    def test_windows_user_data_is_not_install_directory(self):
        path = user_data_dir()
        self.assertEqual(path.name, "MoraCutter")
        if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
            self.assertTrue(str(path).lower().startswith(os.environ["LOCALAPPDATA"].lower()))

    def test_crash_logs_keep_only_ten_files(self):
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            for index in range(MAX_LOG_FILES + 3):
                path = log_dir / f"crash-{index:02d}.log"
                path.write_bytes(b"x")
                os.utime(path, (index, index))
            prune_logs(log_dir)
            self.assertEqual(len(list(log_dir.glob("crash-*.log"))), MAX_LOG_FILES)

    def test_crash_logs_respect_size_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder)
            for index in range(3):
                path = log_dir / f"crash-{index}.log"
                path.write_bytes(b"x" * (MAX_LOG_BYTES // 2))
                os.utime(path, (index, index))
            prune_logs(log_dir)
            total = sum(path.stat().st_size for path in log_dir.glob("crash-*.log"))
            self.assertLessEqual(total, MAX_LOG_BYTES)


if __name__ == "__main__":
    unittest.main()
