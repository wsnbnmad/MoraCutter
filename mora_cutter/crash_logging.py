from __future__ import annotations

from datetime import datetime
from pathlib import Path
import platform
import traceback

from . import __version__
from .runtime import LOG_DIR, ensure_user_directories


MAX_LOG_FILES = 10
MAX_LOG_BYTES = 20 * 1024 * 1024


def prune_logs(log_dir: Path = LOG_DIR) -> None:
    files = sorted(log_dir.glob("crash-*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    total = 0
    for index, path in enumerate(files):
        size = path.stat().st_size
        if index >= MAX_LOG_FILES or total + size > MAX_LOG_BYTES:
            try:
                path.unlink()
            except OSError:
                pass
        else:
            total += size


def write_crash_log(exc_type: type[BaseException], exc: BaseException, tb: object) -> Path:
    ensure_user_directories()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = LOG_DIR / f"crash-{stamp}.log"
    header = (
        f"MoraCutter {__version__}\n"
        f"Time: {datetime.now().astimezone().isoformat(timespec='seconds')}\n"
        f"OS: {platform.platform()}\n"
        f"Python: {platform.python_version()}\n\n"
    )
    path.write_text(header + "".join(traceback.format_exception(exc_type, exc, tb)), encoding="utf-8")
    prune_logs()
    return path
