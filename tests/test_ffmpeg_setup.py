from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mora_cutter import ffmpeg_setup


class FFmpegSetupTests(unittest.TestCase):
    def test_tool_folder_requires_all_three_programs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            self.assertFalse(ffmpeg_setup.is_tool_folder(path))
            for name in ffmpeg_setup.REQUIRED_TOOLS:
                (path / name).write_bytes(b"test")
            self.assertTrue(ffmpeg_setup.is_tool_folder(path))

    def test_configured_folder_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tools = root / "bin"
            tools.mkdir()
            for name in ffmpeg_setup.REQUIRED_TOOLS:
                (tools / name).write_bytes(b"test")
            config = root / "config" / "ffmpeg.json"
            with mock.patch.object(ffmpeg_setup, "CONFIG_PATH", config):
                ffmpeg_setup.save_tool_folder(tools)
                self.assertEqual(ffmpeg_setup.configured_bin_dir(), tools.resolve())
                saved = json.loads(config.read_text(encoding="utf-8"))
                self.assertEqual(Path(saved["bin_dir"]), tools.resolve())

    def test_manifest_is_available_to_source_run(self):
        self.assertTrue(ffmpeg_setup.manifest_path().is_file())


if __name__ == "__main__":
    unittest.main()
