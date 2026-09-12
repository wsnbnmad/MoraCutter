from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import uuid


def _timestamp() -> str:
    """Return a local, sortable timestamp for project data."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class AudioSource:
    id: str
    path: str
    duration: float
    sample_rate: int
    display_name: str

    @classmethod
    def create(cls, path: str, duration: float, sample_rate: int) -> "AudioSource":
        p = Path(path)
        return cls(str(uuid.uuid4()), str(p.resolve()), duration, sample_rate, p.stem)


@dataclass
class Segment:
    id: str
    source_id: str
    start: float
    cue: float
    end: float
    label: str = ""
    unit: str = "mora"
    pitch: str = "--"
    # Kept in project data for the commented-out auto-recognition code.
    confidence: float = 0.0
    quality_score: float = 0.0
    breath: bool = False
    sigh: bool = False
    # Restore the pronunciation after temporarily marking this as breath/sigh.
    label_before_voice_type: str = ""
    gain_db: float = 0.0
    order: int = 0
    origin: str = "auto"
    created_at: str = field(default_factory=_timestamp)
    updated_at: str = field(default_factory=_timestamp)

    @classmethod
    def create(cls, source_id: str, start: float, end: float, **kwargs: Any) -> "Segment":
        cue = float(kwargs.pop("cue", start))
        created_at = kwargs.pop("created_at", _timestamp())
        kwargs.setdefault("updated_at", created_at)
        return cls(str(uuid.uuid4()), source_id, float(start), cue, float(end), created_at=created_at, **kwargs)

    def clamp(self, duration: float) -> None:
        self.start = max(0.0, min(self.start, duration))
        self.end = max(self.start + 0.001, min(self.end, duration))
        self.cue = max(self.start, min(self.cue, self.end - 0.001))


@dataclass
class ProjectSettings:
    autosave_minutes: int = 5
    recovery_folder: str = ""
    sample_rate: int = 48000
    bit_depth: int = 24
    normalize: bool = True
    use_gpu: bool = True
    detection_model: str = "内蔵ベースライン（音量＋仮名）"
    unit: str = "mora"


@dataclass
class Project:
    version: int = 1
    name: str = "名称未設定"
    sources: list[AudioSource] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    # Shared across every source: this is a collection target list, not a
    # per-file transcript.  Keep transcripts for compatibility with older
    # projects and the currently disabled recognition workflow.
    collection_list: str = ""
    transcripts: dict[str, str] = field(default_factory=dict)
    settings: ProjectSettings = field(default_factory=ProjectSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Project":
        transcripts = dict(raw.get("transcripts", {}))
        collection_list = str(raw.get("collection_list", ""))
        # Upgrade previous projects without discarding a list entered in the
        # former per-source field.
        if not collection_list:
            collection_list = next((value for value in transcripts.values() if value.strip()), "")
        return cls(
            version=int(raw.get("version", 1)),
            name=raw.get("name", "名称未設定"),
            sources=[AudioSource(**v) for v in raw.get("sources", [])],
            # Older projects may contain auto-recognition confidence/rank
            # fields and favourite/accepted flags.  Ignore those safely.
            segments=[Segment(**{
                key: value for key, value in v.items()
                if key in Segment.__dataclass_fields__
            }) for v in raw.get("segments", [])],
            collection_list=collection_list,
            transcripts=transcripts,
            settings=ProjectSettings(**raw.get("settings", {})),
        )
