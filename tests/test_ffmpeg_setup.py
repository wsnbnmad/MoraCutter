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

    def test_ffmpeg_root_or_bin_folder_can_be_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tools = root / "bin"
            tools.mkdir()
            for name in ffmpeg_setup.REQUIRED_TOOLS:
                (tools / name).write_bytes(b"test")
            self.assertEqual(ffmpeg_setup.resolve_tool_folder(root), tools)
            self.assertEqual(ffmpeg_setup.resolve_tool_folder(tools), tools)

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

    def test_path_is_searched_before_showing_download_prompt(self):
        with (
            mock.patch.object(ffmpeg_setup, "is_tool_folder", return_value=False),
            mock.patch.object(ffmpeg_setup, "configured_bin_dir", return_value=None),
            mock.patch.object(ffmpeg_setup.shutil, "which", return_value="C:/ffmpeg/tool.exe"),
            mock.patch.object(ffmpeg_setup.messagebox, "askyesno") as prompt,
        ):
            self.assertTrue(ffmpeg_setup.ensure_ffmpeg(mock.Mock()))
            prompt.assert_not_called()

    def test_rejected_download_opens_manual_folder_selection(self):
        with (
            mock.patch.object(ffmpeg_setup, "is_tool_folder", return_value=False),
            mock.patch.object(ffmpeg_setup, "configured_bin_dir", return_value=None),
            mock.patch.object(ffmpeg_setup.shutil, "which", return_value=None),
            mock.patch.object(ffmpeg_setup.messagebox, "askyesno", return_value=False),
            mock.patch.object(ffmpeg_setup, "_select_existing_ffmpeg", return_value=True) as select,
        ):
            self.assertTrue(ffmpeg_setup.ensure_ffmpeg(mock.Mock()))
            select.assert_called_once()


if __name__ == "__main__":
    unittest.main()
