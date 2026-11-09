"""Turn a candidate into compact text for a reviewer (human or model)."""

from __future__ import annotations

from .candidates import Candidate
from .screenplay import fmt_ts

MAX_CHARS = 6000


def render_clip(cand: Candidate, include_logline: bool = True) -> str:
    """Readable transcript of just the clip, with in/out points on every line."""
    lines: list[str] = []
    if include_logline:
        lines.append(f"SERIES LOGLINE: {cand.episode.logline}")
        lines.append("")
    lines.append(f"CLIP: episode {cand.episode.number}, {len(cand.segments)} segment(s), "
                 f"{cand.clip_duration:.0f}s")
    for i, seg in enumerate(cand.segments, start=1):
        if len(cand.segments) > 1:
            lines.append(f"-- segment {i}: {fmt_ts(seg.start)} to {fmt_ts(seg.end)} --")
        for b in seg.beats:
            t = f"[{fmt_ts(b.start)}-{fmt_ts(b.end)}]"
            if b.is_speech:
                tone = f" ({b.tone})" if b.tone else ""
                lines.append(f"{t} {b.speaker}{tone}: {b.text}")
            else:
                lines.append(f"{t} {b.kind.upper()}: {b.text}")
    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[... truncated ...]"
    return text
