from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "MoraCutter"
INSTALL_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """Writable per-user storage; never place runtime data beside the EXE."""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / APP_NAME


USER_DATA_DIR = user_data_dir()
CONFIG_DIR = USER_DATA_DIR / "config"
RECOVERY_DIR = USER_DATA_DIR / "recovery"
LOG_DIR = USER_DATA_DIR / "logs"
CACHE_DIR = USER_DATA_DIR / "cache"
TOOLS_DIR = USER_DATA_DIR / "tools"


def ensure_user_directories() -> None:
    for directory in (CONFIG_DIR, RECOVERY_DIR, LOG_DIR, CACHE_DIR, TOOLS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
