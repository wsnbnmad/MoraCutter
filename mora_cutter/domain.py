from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import uuid


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
    confidence: float = 0.0
    quality_score: float = 0.0
    favorite: bool = False
    accepted: bool = False
    breath: bool = False
    gain_db: float = 0.0
    order: int = 0
    origin: str = "auto"

    @classmethod
    def create(cls, source_id: str, start: float, end: float, **kwargs: Any) -> "Segment":
        cue = float(kwargs.pop("cue", start))
        return cls(str(uuid.uuid4()), source_id, float(start), cue, float(end), **kwargs)

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
    transcripts: dict[str, str] = field(default_factory=dict)
    settings: ProjectSettings = field(default_factory=ProjectSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Project":
        return cls(
            version=int(raw.get("version", 1)),
            name=raw.get("name", "名称未設定"),
            sources=[AudioSource(**v) for v in raw.get("sources", [])],
            segments=[Segment(**v) for v in raw.get("segments", [])],
            transcripts=dict(raw.get("transcripts", {})),
            settings=ProjectSettings(**raw.get("settings", {})),
        )
