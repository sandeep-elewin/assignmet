"""Feature extraction: hook, cliffhanger, arc, pacing, standalone.

Hook and cliffhanger are scored at beat level because a promo's quality is
decided by its first 3 seconds and its last 3 seconds, not by its average.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import lexicon
from .entities import SeriesIndex, standalone_report
from .screenplay import Beat, Episode

HOOK_WINDOW = 3.0          # brief: hook must land inside the first 3 seconds
CLIFF_WINDOW = 4.0         # a short trailing sound/reaction tag may follow the last line

TAIL_REACTION_RE = re.compile(r"close[- ]up|extreme close|gasp|recoil|flinches|stares|silence", re.I)
OPEN_CUE_RE = re.compile(
    r"\b(turns? to see|reveals?|unveils?|pulls off|tears off|"
    r"slaps?|strikes?|shoves?|kneels?|collapses?|gasping)\b",
    re.I,
)


def beat_hook(beat: Beat, prev: Beat | None = None) -> float:
    """How likely this beat is to stop a scrolling viewer, 0-1."""
    if beat.is_speech:
        score = lexicon.dialogue_salience(beat.text, beat.tone)
        if prev and prev.is_speech and re.search(
            r"\b(why|what|who|how|where|when|do you|did you)\b", prev.text, re.I
        ):
            score += 0.06
        return min(1.0, score)

    score = lexicon.action_salience(beat.text)
    if OPEN_CUE_RE.search(beat.text):
        score += 0.08
    return min(1.0, score)


def beat_cliff(beat: Beat, nxt: Beat | None, episode: Episode) -> float:
    """How strongly this beat works as an unresolved last moment, 0-1."""
    structural = 0.0
    if beat.end >= episode.duration - 1.0:
        # Microdrama episodes are written to end on a hook, so a final beat earns credit.
        structural += 0.18
    if nxt is not None:
        if TAIL_REACTION_RE.search(nxt.text):
            structural += 0.10
        if re.search(r"silence|cut to black|fade to black", nxt.text, re.I):
            structural += 0.12

    if not beat.is_speech:
        strong = lexicon.action_salience(beat.text)
        return min(1.0, 0.85 * strong + structural)

    body = lexicon.strip_quotes(beat.text)
    low = body.lower()
    tl = lexicon.tone_intensity(beat.tone)

    strong = 0.0
    if body.endswith("?"):
        strong = max(strong, 0.55)
    if any(body.endswith(e) for e in lexicon.UNRESOLVED_ENDINGS):
        strong = max(strong, 0.58)
    if lexicon.count_phrases(body, lexicon.THREAT_PHRASES):
        strong = max(strong, 0.60)
    if lexicon.count_phrases(body, lexicon.REVEAL_PHRASES):
        strong = max(strong, 0.50)

    secondary = 0.0
    if any(w in lexicon.MENACE_WORDS for w in lexicon.words(body)):
        secondary = max(secondary, 0.26)
    if low.startswith(lexicon.IMPERATIVE_STARTS):
        secondary = max(secondary, 0.22)
    if len(lexicon.words(body)) <= 8:
        secondary = max(secondary, 0.12)
    if body.count("!"):
        secondary = max(secondary, 0.10)

    score = 0.78 * strong + 0.40 * secondary + 0.18 * tl + structural
    return min(1.0, score)


@dataclass
class WindowFeatures:
    hook: float
    cliff: float
    standalone: float
    arc: float
    pacing: float
    hook_text: str
    cliff_text: str
    hook_beat: Beat | None = None
    cliff_beat: Beat | None = None
    reasons: list[str] = field(default_factory=list)
    standalone_reasons: list[str] = field(default_factory=list)
    debt_entities: list[str] = field(default_factory=list)


def _pacing_score(beats: list[Beat], start: float, end: float) -> float:
    dur = max(0.1, end - start)
    speech = sum(b.duration for b in beats if b.is_speech)
    ratio = speech / dur
    if 0.35 <= ratio <= 0.80:
        ratio_score = 1.0
    elif ratio < 0.35:
        ratio_score = max(0.0, ratio / 0.35)
    else:
        ratio_score = max(0.0, 1.0 - (ratio - 0.80) / 0.2)
    cuts = len(beats) / (dur / 10.0)
    if 2.5 <= cuts <= 7.5:
        cut_score = 1.0
    elif cuts < 2.5:
        cut_score = cuts / 2.5
    else:
        cut_score = max(0.2, 1.0 - (cuts - 7.5) / 12.0)
    return 0.6 * ratio_score + 0.4 * cut_score


def _arc_score(beats: list[Beat], start: float, dur: float) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if not beats:
        return 0.0, reasons

    def intensity(b: Beat) -> float:
        if b.is_speech:
            return lexicon.dialogue_salience(b.text, b.tone)
        return lexicon.action_salience(b.text)

    vals = [(b.start - start, intensity(b)) for b in beats]
    opening = max((v for t, v in vals if t < 4.0), default=vals[0][1])
    peak_t, peak = max(vals, key=lambda p: p[1])
    peak_pos = peak_t / max(dur, 0.1)

    if peak_pos >= 0.6:
        shape = 1.0
        reasons.append("emotional peak lands in the back half")
    elif peak_pos >= 0.35:
        shape = 0.7
    else:
        shape = 0.35
        reasons.append("peak arrives early, tail sags")

    lift = peak - opening
    if lift >= 0.35:
        reasons.append("clear escalation from opening to peak")
    elif lift <= 0.0:
        reasons.append("flat emotional line")

    reversal = sum(
        1 for b in beats if b.is_speech and re.search(r"\b(but|never|instead|suddenly|yet)\b", b.text, re.I)
    )
    score = 0.55 * shape + 0.30 * max(0.0, min(1.0, (lift + 0.2) / 0.7)) + 0.15 * min(1.0, reversal / 2)
    return min(1.0, score), reasons


def window_hook(beats: list[Beat], start: float, prev_outside: Beat | None) -> tuple[float, Beat]:
    opening = [b for b in beats if b.start - start <= HOOK_WINDOW]
    if not opening:
        opening = beats[:1]
    beat = max(opening, key=lambda b: beat_hook(b, prev_outside))
    return beat_hook(beat, prev_outside), beat


def window_cliff(
    beats: list[Beat], clip_end: float, nxt_outside: Beat | None, episode: Episode
) -> tuple[float, Beat]:
    """Score the beat the clip actually ends on.

    The reported cliffhanger has to be the last thing the viewer hears. Picking
    the highest-scoring line in the tail instead would describe a cut that was
    never made, and would hide a clip that resolves its own tension before the
    out point.
    """
    window = [b for b in beats if b.end >= clip_end - CLIFF_WINDOW]
    if not window:
        window = beats[-1:]
    # A "cut to black" or a music sting is a transition, not the cliffhanger
    # itself; when a line carries the tail, that line is the ending.
    speech = [b for b in window if b.is_speech]
    beat = max(speech or window, key=lambda b: b.end)
    i = beats.index(beat)
    nxt = beats[i + 1] if i + 1 < len(beats) else nxt_outside
    return beat_cliff(beat, nxt, episode), beat


def compute_features(
    beats: list[Beat],
    start: float,
    end: float,
    episode: Episode,
    index: SeriesIndex,
    prev_outside: Beat | None = None,
    next_outside: Beat | None = None,
    clip_duration: float | None = None,
) -> WindowFeatures:
    reasons: list[str] = []
    hook, hook_beat = window_hook(beats, start, prev_outside)
    cliff, cliff_beat = window_cliff(beats, end, next_outside, episode)

    sa = standalone_report(beats, episode, index)
    dur = clip_duration if clip_duration is not None else max(0.1, end - start)
    arc, arc_reasons = _arc_score(beats, start, max(0.1, end - start))
    pacing = _pacing_score(beats, start, start + max(0.1, dur))
    reasons.extend(arc_reasons)

    if hook_beat.is_speech:
        reasons.insert(0, f"hook is a line: \u201c{hook_beat.text}\u201d")
    else:
        reasons.insert(0, f"hook is a visual beat: {hook_beat.text[:90]}")

    return WindowFeatures(
        hook=hook,
        cliff=cliff,
        standalone=sa.score,
        arc=arc,
        pacing=pacing,
        hook_text=hook_beat.text,
        cliff_text=cliff_beat.text,
        hook_beat=hook_beat,
        cliff_beat=cliff_beat,
        reasons=reasons,
        standalone_reasons=sa.reasons,
        debt_entities=sa.debt_entities,
    )
