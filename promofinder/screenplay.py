"""Parse Kuku microdrama screenplays into timed beats.

The input pack drifts in small ways between files: most use ``Scene heading:``
but two use ``SCENE HEADING:``. Every parser rule here is therefore
case-insensitive and whitespace tolerant, and malformed blocks are skipped
rather than raising, because the tool has to survive a new show it has never
seen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TS_RE = re.compile(r"(\d{1,2}):(\d{2})\.(\d{1,2})")
RANGE_RE = re.compile(
    r"start\s*:\s*\(?\s*([\d:.]+)\s*\)?\s*\|\s*end\s*:\s*\(?\s*([\d:.]+)\s*\)?",
    re.IGNORECASE,
)
SCENE_RE = re.compile(r"^SCENE\s+(\d+)\s*$", re.IGNORECASE)
BLOCK_RE = re.compile(r"^\*\*(.+?)\*\*:?\s*$")
KEY_RE = re.compile(r"^(scene heading|scene start|scene end)\s*:\s*(.*)$", re.IGNORECASE)
PAREN_RE = re.compile(r"\(([^)]*)\)")
SCRIPT_MARK_RE = re.compile(r"-{2,}\s*SCRIPT\s+(?:START|END)\s*-{2,}", re.IGNORECASE)
DELIVERY_TAGS = {"o.s.", "v.o.", "continues", "cont'd", "pre-lap", "off screen", "voice over"}

TECH_KINDS = {
    "camera": "camera",
    "action": "action",
    "sound fx": "sound",
    "sfx": "sound",
    "sound": "sound",
    "music": "sound",
}


def parse_ts(value: str) -> float | None:
    m = TS_RE.search(value or "")
    if not m:
        return None
    minutes, seconds, centis = m.groups()
    return int(minutes) * 60 + int(seconds) + int(centis.ljust(2, "0")) / 100


def fmt_ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes:02d}:{secs:05.2f}"


def split_speaker(header: str) -> tuple[str, str]:
    """'MATRIARCH (O.S.) (Firm)' -> ('MATRIARCH', 'Firm')."""
    parts = [p.strip() for p in PAREN_RE.findall(header)]
    name = PAREN_RE.sub(" ", header)
    name = re.sub(r"\s+", " ", name).strip(" -:")
    tone = ", ".join(p for p in parts if p and p.lower() not in DELIVERY_TAGS)
    return name, tone


@dataclass
class Beat:
    kind: str  # camera | action | dialogue | sound
    text: str
    start: float
    end: float
    speaker: str = ""
    tone: str = ""
    scene: int = 0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def is_speech(self) -> bool:
        return self.kind == "dialogue"


@dataclass
class Scene:
    index: int
    heading: str
    start: float
    end: float
    beats: list[Beat] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Episode:
    number: int
    label: str
    logline: str
    continuity: str
    scenes: list[Scene]
    path: str

    @property
    def duration(self) -> float:
        return max((s.end for s in self.scenes), default=0.0)

    @property
    def beats(self) -> list[Beat]:
        return [b for s in self.scenes for b in s.beats]

    @property
    def dialogue(self) -> list[Beat]:
        return [b for b in self.beats if b.kind == "dialogue"]


def _split_header(text: str) -> tuple[dict[str, str], str]:
    marker = "--- SCRIPT START ---"
    head, _, body = text.partition(marker)
    if not body:  # no marker: treat whole file as body
        head, body = "", text
    meta: dict[str, str] = {}
    for line in head.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip()
    return meta, body


def _scene_chunks(body: str) -> list[tuple[int, str]]:
    chunks: list[tuple[int, str]] = []
    current_idx: int | None = None
    current: list[str] = []
    for line in body.splitlines():
        m = SCENE_RE.match(line.strip())
        if m:
            if current_idx is not None:
                chunks.append((current_idx, "\n".join(current)))
            current_idx, current = int(m.group(1)), []
            continue
        if current_idx is not None:
            current.append(line)
    if current_idx is not None:
        chunks.append((current_idx, "\n".join(current)))
    return chunks


def _parse_scene(idx: int, chunk: str) -> Scene | None:
    heading = ""
    start = end = None
    beats: list[Beat] = []

    lines = chunk.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        k = KEY_RE.match(line)
        if k:
            key, value = k.group(1).lower(), k.group(2).strip()
            if key == "scene heading":
                heading = value
            elif key == "scene start":
                start = parse_ts(value)
            elif key == "scene end":
                end = parse_ts(value)
            i += 1
            continue

        b = BLOCK_RE.match(line)
        if b:
            header = b.group(1).strip().rstrip(":").strip()
            rng = RANGE_RE.match(lines[i + 1].strip()) if i + 1 < len(lines) else None
            if not rng:
                i += 1
                continue
            b_start, b_end = parse_ts(rng.group(1)), parse_ts(rng.group(2))
            j = i + 2
            content: list[str] = []
            while j < len(lines):
                nxt = lines[j].strip()
                if BLOCK_RE.match(nxt) or KEY_RE.match(nxt) or SCENE_RE.match(nxt):
                    break
                if nxt:
                    content.append(nxt)
                j += 1
            text = SCRIPT_MARK_RE.sub("", " ".join(content)).strip()
            if b_start is not None and b_end is not None:
                kind_key = header.lower()
                if kind_key in TECH_KINDS:
                    beats.append(
                        Beat(TECH_KINDS[kind_key], text, b_start, b_end, scene=idx)
                    )
                else:
                    name, tone = split_speaker(header)
                    beats.append(
                        Beat(
                            "dialogue",
                            text,
                            b_start,
                            b_end,
                            speaker=name,
                            tone=tone,
                            scene=idx,
                        )
                    )
            i = j
            continue
        i += 1

    if start is None:
        start = min((b.start for b in beats), default=0.0)
    if end is None:
        end = max((b.end for b in beats), default=start)
    if not beats:
        return None
    beats.sort(key=lambda b: b.start)
    return Scene(idx, heading, start, end, beats)


def parse_episode_text(text: str, path: str = "") -> Episode | None:
    meta, body = _split_header(text)
    scenes = [s for idx, chunk in _scene_chunks(body) if (s := _parse_scene(idx, chunk))]
    if not scenes:
        return None
    label = meta.get("episode number", "")
    m = re.search(r"(\d+)", label)
    number = int(m.group(1)) if m else 0
    return Episode(
        number=number,
        label=label or f"Episode {number}",
        logline=meta.get("episode logline", ""),
        continuity=meta.get("continuity notes", ""),
        scenes=scenes,
        path=path,
    )


def load_episode(path: str | Path) -> Episode | None:
    p = Path(path)
    return parse_episode_text(p.read_text(encoding="utf-8", errors="replace"), str(p))


def load_dir(directory: str | Path) -> list[Episode]:
    episodes = [e for p in sorted(Path(directory).glob("*.txt")) if (e := load_episode(p))]
    return sorted(episodes, key=lambda e: e.number)
