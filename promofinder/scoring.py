"""Composite scoring and plain-language rationale.

The weights mirror the brief's definition of a good promo. They are constants
on purpose: a hand-tuned linear score is easy to audit, and the doc records the
single experiment behind the numbers.
"""

from __future__ import annotations

import hashlib

from .candidates import Candidate
from .screenplay import fmt_ts

W_HOOK = 0.30
W_CLIFF = 0.30
W_STANDALONE = 0.22
W_ARC = 0.12
W_PACING = 0.06


def duration_fit(clip_duration: float) -> float:
    if 28.0 <= clip_duration <= 45.0:
        return 1.0
    if clip_duration < 28.0:
        return 0.90 + 0.10 * (clip_duration - 20.0) / 8.0 if clip_duration >= 20 else 0.85
    return max(0.86, 1.0 - 0.14 * (clip_duration - 45.0) / 15.0)


def score_candidate(cand: Candidate) -> float:
    f = cand.feats
    if not f:
        return 0.0
    base = (
        W_HOOK * f.hook
        + W_CLIFF * f.cliff
        + W_STANDALONE * f.standalone
        + W_ARC * f.arc
        + W_PACING * f.pacing
    )
    score = 100.0 * base * duration_fit(cand.clip_duration)
    cand.heuristic_score = round(score, 2)
    cand.score = cand.heuristic_score
    if not cand.id:
        h = hashlib.sha1(
            f"{cand.episode.number}:{cand.start:.2f}:{cand.end:.2f}:{cand.stitched}".encode()
        ).hexdigest()[:8]
        cand.id = f"ep{cand.episode.number:02d}-{h}"
    return cand.score


LLM_WEIGHT = 0.55


def blend_verdict(cand: Candidate, verdict: dict) -> float:
    """Fold an LLM verdict into the score without throwing away the audit trail."""
    heur = cand.heuristic_score / 100.0
    llm = (verdict["hook"] + verdict["cliffhanger"] + verdict["standalone"] - 3.0) / 12.0
    blended = (1.0 - LLM_WEIGHT) * heur + LLM_WEIGHT * llm
    if verdict.get("spoiler_risk", 1) >= 4:
        blended *= 0.85
    if not verdict.get("postable", True):
        blended *= 0.80
    cand.verdict = verdict
    cand.score = round(100.0 * blended * duration_fit(cand.clip_duration), 2)
    return cand.score


def _short(text: str, limit: int = 110) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def why_it_works(cand: Candidate) -> str:
    """One line explaining the verdict, assembled from the strongest signals."""
    f = cand.feats
    if not f:
        return ""
    if cand.verdict and cand.verdict.get("reason"):
        return cand.verdict["reason"]
    bits: list[str] = []
    if f.hook >= 0.7:
        bits.append("opens cold on a high-voltage line or physical beat")
    elif f.hook >= 0.45:
        bits.append("opens on a clear dramatic question")
    else:
        bits.append("opening is the weak point")

    if f.cliff >= 0.7:
        bits.append("cuts on an unresolved threat or question")
    elif f.cliff >= 0.45:
        bits.append("ends on a raised stake")
    else:
        bits.append("ends without a real cliffhanger")

    if f.standalone >= 0.75:
        bits.append("reads clean to a first-time viewer")
    elif f.standalone >= 0.5:
        bits.append("mostly self-contained, needs one line of setup")
    else:
        bits.append("leans on names a new viewer will not know")

    if f.arc >= 0.65:
        bits.append("escalates steadily into the cut")

    return "; ".join(bits) + "."


def timeline(cand: Candidate) -> list[dict]:
    out = []
    for i, seg in enumerate(cand.segments, start=1):
        out.append(
            {
                "segment": i,
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "start_tc": fmt_ts(seg.start),
                "end_tc": fmt_ts(seg.end),
                "duration": round(seg.duration, 2),
            }
        )
    return out


def to_dict(cand: Candidate, rank: int | None = None) -> dict:
    f = cand.feats
    data = {
        "id": cand.id,
        "rank": rank,
        "episode": cand.episode.number,
        "episode_label": cand.episode.label,
        "logline": cand.episode.logline,
        "stitched": cand.stitched,
        "segments": timeline(cand),
        "clip_duration": round(cand.clip_duration, 2),
        "hook": _short(f.hook_text) if f else "",
        "cliffhanger": _short(f.cliff_text) if f else "",
        "why_it_works": why_it_works(cand),
        "score": cand.score,
        "heuristic_score": cand.heuristic_score,
        "judged_by": "llm+heuristic" if cand.verdict else "heuristic",
        "llm": cand.verdict or None,
        "subscores": {
            "hook": round(f.hook, 3) if f else 0,
            "cliffhanger": round(f.cliff, 3) if f else 0,
            "standalone": round(f.standalone, 3) if f else 0,
            "arc": round(f.arc, 3) if f else 0,
            "pacing": round(f.pacing, 3) if f else 0,
        },
        "signals": {
            "arc_notes": [r for r in (f.reasons if f else []) if "peak" in r or "escalation" in r or "flat" in r],
            "standalone_notes": f.standalone_reasons if f else [],
            "prior_knowledge_entities": f.debt_entities if f else [],
        },
    }
    return data
