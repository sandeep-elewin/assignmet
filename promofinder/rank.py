"""Selection and ranking.

Two levels, because the editor's job has two levels: pick the best moments per
episode, then decide what to post first this week. The second needs diversity --
a feed of eight clips from episode 36 is worse than eight good clips from eight
episodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .candidates import Candidate
from .screenplay import Episode

# A promo that fails these does not satisfy the brief, whatever its total score.
GATE_HOOK = 0.45
GATE_CLIFF = 0.45
GATE_STANDALONE = 0.50


def meets_brief(cand: Candidate) -> tuple[bool, list[str]]:
    f = cand.feats
    if not f:
        return False, ["no features"]
    reasons = []
    if f.hook < GATE_HOOK:
        reasons.append(f"hook too weak ({f.hook:.2f} < {GATE_HOOK})")
    if f.cliff < GATE_CLIFF:
        reasons.append(f"no real cliffhanger ({f.cliff:.2f} < {GATE_CLIFF})")
    if f.standalone < GATE_STANDALONE:
        reasons.append(f"needs too much prior context ({f.standalone:.2f} < {GATE_STANDALONE})")
    return not reasons, reasons


def _overlap(a: Candidate, b: Candidate) -> float:
    """Share of the shorter clip that the two candidates both contain."""
    def span(c: Candidate) -> list[tuple[float, float]]:
        return [(s.start, s.end) for s in c.segments]

    def total(c: Candidate) -> float:
        return max(0.01, c.clip_duration)

    inter = 0.0
    for s1, e1 in span(a):
        for s2, e2 in span(b):
            inter += max(0.0, min(e1, e2) - max(s1, s2))
    return inter / min(total(a), total(b))


@dataclass
class EpisodeResult:
    episode: Episode
    candidates: list[Candidate]
    picks: list[Candidate] = field(default_factory=list)
    postable: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "episode": self.episode.number,
            "label": self.episode.label,
            "logline": self.episode.logline,
            "duration_s": round(self.episode.duration, 2),
            "candidate_count": len(self.candidates),
            "postable": self.postable,
            "notes": self.notes,
            "picks": len(self.picks),
        }


def select_per_episode(episode: Episode, cands: list[Candidate], keep: int = 2) -> EpisodeResult:
    ranked = sorted(cands, key=lambda c: -c.score)
    picks: list[Candidate] = []
    for c in ranked:
        if len(picks) >= keep:
            break
        if any(_overlap(c, p) > 0.40 for p in picks):
            continue
        ok, why = meets_brief(c)
        if ok:
            picks.append(c)
    notes: list[str] = []
    postable = bool(picks)
    if not picks:
        best = ranked[0] if ranked else None
        if best:
            ok, why = meets_brief(best)
            notes.append("no clip met the brief; best effort returned")
            notes.extend(why)
            picks = [best]
    return EpisodeResult(episode=episode, candidates=ranked, picks=picks, postable=postable, notes=notes)


def rank_globally(
    results: list[EpisodeResult], limit: int = 20, per_episode_in_top: int = 1
) -> list[tuple[int, Candidate]]:
    """Order the postable clips, keeping the top of the list diverse."""
    pool = [(r.episode.number, c) for r in results if r.postable for c in r.picks]
    pool.sort(key=lambda p: -p[1].score)

    ordered: list[tuple[int, Candidate]] = []
    counts: dict[int, int] = {}
    deferred: list[tuple[int, Candidate]] = []
    for ep, c in pool:
        if counts.get(ep, 0) >= per_episode_in_top:
            deferred.append((ep, c))
            continue
        if ordered and any(_overlap(c, o[1]) > 0.3 and ep == o[0] for o in ordered):
            continue
        ordered.append((ep, c))
        counts[ep] = counts.get(ep, 0) + 1
        if len(ordered) >= limit:
            break
    if len(ordered) < limit:
        ordered.extend(deferred[: limit - len(ordered)])
    return ordered[:limit]
