from __future__ import annotations

import json
from pathlib import Path

from .domain import PROJECT_FORMAT_VERSION, Project


CURRENT_PROJECT_VERSION = PROJECT_FORMAT_VERSION
PROJECT_EXTENSIONS = (".moracutter", ".mcp.json", ".json")


def save_project(project: Project, path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(project.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def load_project(path: str) -> Project:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("MoraCutterプロジェクトのJSONオブジェクトではありません。")
    version = int(raw.get("version", 1))
    if version > CURRENT_PROJECT_VERSION:
        raise ValueError(f"このプロジェクトは新しい形式（version {version}）です。MoraCutterを更新してください。")
    return Project.from_dict(raw)
