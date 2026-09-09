from __future__ import annotations

import json
from pathlib import Path

from .domain import Project


def save_project(project: Project, path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(project.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def load_project(path: str) -> Project:
    return Project.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

