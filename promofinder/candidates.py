"""Candidate promo windows.

Generation is deliberately recall-heavy and rule-based: cheap heuristics propose
many plausible in/out pairs, and a later scoring stage throws most of them away.
Every boundary is snapped to a real beat boundary so a cut never lands in the
middle of a spoken line.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import lexicon
from .entities import SeriesIndex
from .features import WindowFeatures, beat_cliff, beat_hook, compute_features
from .screenplay import Beat, Episode

MIN_DUR = 20.0
MAX_DUR = 60.0
TAIL_PAD = 0.25        # let the last line breathe instead of clipping the audio
HOOK_WINDOW = 3.0
ANCHORS_PER_EPISODE = 12
ENDS_PER_ANCHOR = 3
MIN_GAP = 2.5          # anchors closer than this are redundant


@dataclass
class Segment:
    start: float
    end: float
    beats: list[Beat]

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Candidate:
    episode: Episode
    segments: list[Segment]
    feats: WindowFeatures | None = None
    score: float = 0.0
    heuristic_score: float = 0.0
    verdict: dict | None = None
    stitched: bool = False
    id: str = ""

    @property
    def start(self) -> float:
        return self.segments[0].start

    @property
    def end(self) -> float:
        return self.segments[-1].end

    @property
    def clip_duration(self) -> float:
        return sum(s.duration for s in self.segments)

    @property
    def beats(self) -> list[Beat]:
        return [b for s in self.segments for b in s.beats]


def _tail_end(beat: Beat, episode: Episode) -> float:
    return min(episode.duration, beat.end + TAIL_PAD)


def _beats_between(beats: list[Beat], start: float, end: float) -> list[Beat]:
    """Beats that begin inside the window, with any overrun clipped to the cut."""
    out: list[Beat] = []
    for b in beats:
        if b.start < start - 1e-6 or b.start >= end - 1e-6:
            continue
        if b.end > end + 1e-6:
            b = replace(b, end=round(end, 2))
        out.append(b)
    return out


def _iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0


def _anchors(episode: Episode, beats: list[Beat]) -> list[Beat]:
    """Beat starts that could plausibly open a promo."""
    scored: list[tuple[float, Beat]] = []
    for i, b in enumerate(beats):
        prev = beats[i - 1] if i else None
        h = beat_hook(b, prev)
        if b.start > episode.duration - MIN_DUR:
            continue
        scored.append((h, b))

    picked: list[Beat] = []
    for _, b in sorted(scored, key=lambda p: -p[0]):
        if len(picked) >= ANCHORS_PER_EPISODE:
            break
        if all(abs(b.start - p.start) >= MIN_GAP for p in picked):
            picked.append(b)

    # Scene starts are natural entry points even when nothing else is loud.
    for scene in episode.scenes:
        first = next((b for b in scene.beats if b.start >= scene.start - 0.01), None)
        if first and first.start <= episode.duration - MIN_DUR:
            if all(abs(first.start - p.start) >= MIN_GAP for p in picked):
                picked.append(first)

    # Coarse grid guarantees recall when the lexicons miss a quiet-but-good moment.
    t = 0.0
    while t <= episode.duration - MIN_DUR:
        if all(abs(t - p.start) >= 10.0 for p in picked):
            nearest = min(beats, key=lambda b: abs(b.start - t))
            picked.append(nearest)
        t += 10.0
    return picked


def _end_options(episode: Episode, beats: list[Beat], start: float) -> list[tuple[float, Beat]]:
    ends: list[tuple[float, Beat]] = []
    for i, b in enumerate(beats):
        e = _tail_end(b, episode)
        dur = e - start
        if dur < MIN_DUR or dur > MAX_DUR:
            continue
        nxt = beats[i + 1] if i + 1 < len(beats) else None
        ends.append((beat_cliff(b, nxt, episode), b))
    ends.sort(key=lambda p: -p[0])
    out: list[tuple[float, Beat]] = []
    for _, b in ends:
        e = _tail_end(b, episode)
        if all(abs(e - _tail_end(o, episode)) >= 1.5 for _, o in out):
            out.append((_, b))
        if len(out) >= ENDS_PER_ANCHOR:
            break
    return out


def _continues(beat: Beat) -> bool:
    body = lexicon.strip_quotes(beat.text).lstrip()
    return body.startswith(("...", "\u2026")) or body[:1].islower()


def _sentence_start(beats: list[Beat], start: float) -> float:
    """Pull the in-point back when the clip would open mid-sentence.

    The screenplays split a line across two blocks with an ellipsis, e.g.
    ``"And when they find your corpse..."`` / ``"...no one will remember..."``.
    Opening on the back half reads as a broken file to a first-time viewer.
    """
    for i, b in enumerate(beats):
        if not b.is_speech or b.start < start - 1e-6 or b.start > start + HOOK_WINDOW:
            continue
        if not _continues(b):
            continue
        j = i
        while j > 0:
            k = next((x for x in range(j - 1, -1, -1) if beats[x].is_speech), None)
            # A long jump would cross a scene change and lose the context anyway.
            if k is None or beats[j].start - beats[k].start > 10.0:
                break
            j = k
            if not _continues(beats[j]):
                break
        return min(start, beats[j].start) if j != i else start
    return start


def _make_segment(
    episode: Episode, beats: list[Beat], start: float, end: float, cap_extension: bool = True
) -> Segment | None:
    """Build a segment, extending the out point so a spoken line is never cut mid-sentence."""
    start = _sentence_start(beats, start)
    for b in beats:
        if b.is_speech and b.start < end - 1e-6 and b.end > end:
            end = b.end + TAIL_PAD
    end = min(end, episode.duration)
    if cap_extension and end - start > MAX_DUR:
        return None
    chosen = _beats_between(beats, start, end)
    if len(chosen) < 2:
        return None
    return Segment(start, round(end, 2), chosen)


def generate_single(episode: Episode, index: SeriesIndex) -> list[Candidate]:
    beats = episode.beats
    if not beats or episode.duration < MIN_DUR:
        return []
    cands: list[Candidate] = []
    seen: list[tuple[float, float]] = []

    for anchor in _anchors(episode, beats):
        start = anchor.start
        for _, end_beat in _end_options(episode, beats, start):
            end = _tail_end(end_beat, episode)
            if any(_iou((start, end), s) >= 0.55 for s in seen):
                continue
            seg = _make_segment(episode, beats, start, end)
            if seg is None:
                continue
            seen.append((seg.start, seg.end))
            cand = Candidate(episode=episode, segments=[seg])
            cand.feats = _feature(episode, cand, index, beats)
            cands.append(cand)

    # The episode's own ending is written as a cliffhanger by the show's staff.
    if episode.duration >= MIN_DUR:
        floor = max(0.0, episode.duration - 35.0)
        first = next((b for b in beats if b.start >= floor), None)
        start = first.start if first else floor
        end = episode.duration
        if MIN_DUR <= end - start <= MAX_DUR and not any(
            _iou((start, end), s) >= 0.55 for s in seen
        ):
            seg = _make_segment(episode, beats, start, end)
            if seg is not None:
                cand = Candidate(episode=episode, segments=[seg])
                cand.feats = _feature(episode, cand, index, beats)
                cands.append(cand)
    return cands


def _feature(episode: Episode, cand: Candidate, index: SeriesIndex, beats: list[Beat]) -> WindowFeatures:
    start, end = cand.start, cand.end
    prev_outside = next((b for b in reversed(beats) if b.end <= start + 0.01), None)
    next_outside = next((b for b in beats if b.start >= end - 0.01 and b not in cand.beats), None)
    return compute_features(
        cand.beats, start, end, episode, index,
        prev_outside=prev_outside,
        next_outside=next_outside,
        clip_duration=cand.clip_duration,
    )


def generate_stitched(episode: Episode, index: SeriesIndex) -> Candidate | None:
    """Join a strong opener to a strong closer when no single stretch has both.

    Returns an unscored candidate; the caller scores it and decides whether it
    is worth preferring over a simple continuous cut.
    """
    beats = episode.beats
    if len(beats) < 6:
        return None

    hooks = sorted(
        ((beat_hook(b, beats[i - 1] if i else None), i, b) for i, b in enumerate(beats)),
        key=lambda p: -p[0],
    )
    hook_i = next(
        (i for _, i, b in hooks if b.start + 8 <= episode.duration - 8), None
    )
    if hook_i is None:
        return None
    hook_beat = beats[hook_i]

    cliffs = sorted(
        (
            (beat_cliff(b, beats[i + 1] if i + 1 < len(beats) else None, episode), i, b)
            for i, b in enumerate(beats)
        ),
        key=lambda p: -p[0],
    )
    cliff_i = next((i for _, i, b in cliffs if b.start >= hook_beat.start + 12), None)
    if cliff_i is None:
        return None
    cliff_beat = beats[cliff_i]

    seg_a_end = None
    best_gap = None
    for b in beats[hook_i:]:
        gap = b.end + TAIL_PAD - hook_beat.start
        if 8.0 <= gap <= 16.0:
            dist = abs(gap - 11.0)
            if best_gap is None or dist < best_gap:
                best_gap, seg_a_end = dist, b.end + TAIL_PAD
    if seg_a_end is None:
        seg_a_end = hook_beat.start + 10.0
    seg_a_end = min(seg_a_end, cliff_beat.start)

    target = max(seg_a_end, cliff_beat.start - 10.0)
    earlier = [b.start for b in beats if b.start <= target + 1e-6]
    seg_b_start = max(earlier) if earlier else target
    if seg_b_start < seg_a_end:
        later = [b.start for b in beats if b.start >= seg_a_end - 1e-6]
        seg_b_start = later[0] if later else seg_a_end
    seg_b_end = _tail_end(cliff_beat, episode)

    if seg_b_end - seg_a_end < 4.0:
        return None

    a_seg = _make_segment(episode, beats, hook_beat.start, seg_a_end)
    b_seg = _make_segment(episode, beats, seg_b_start, seg_b_end)
    if a_seg is None or b_seg is None:
        return None

    cand = Candidate(episode=episode, segments=[a_seg, b_seg], stitched=True)
    if not (MIN_DUR <= cand.clip_duration <= MAX_DUR):
        return None
    cand.feats = _feature(episode, cand, index, beats)
    return cand


def tighten_tail(cand: Candidate, index: SeriesIndex) -> Candidate | None:
    """Pull the out-point back to the last real cliffhanger.

    A scene often keeps going after its best line -- a tender look, an embrace --
    which defuses the very tension the promo is selling. If every beat after the
    last strong line is soft, the clip should end on the line.
    """
    from . import lexicon

    seg = cand.segments[-1]
    if len(seg.beats) < 3:
        return None

    # The final beat is usually the show's own "cut to black" / sting tag; it
    # does not count as material that might justify a longer tail.
    tag_start = seg.beats[-1].start if not seg.beats[-1].is_speech else seg.end

    best: tuple[float, Beat] | None = None
    for b in seg.beats:
        if not b.is_speech or b.end >= tag_start - 1.0:
            continue
        if beat_cliff(b, None, cand.episode) < 0.28:
            continue
        after = [x for x in seg.beats if x.start >= b.end - 0.01 and x.start < tag_start]
        deflated = not any(
            (lexicon.dialogue_salience(x.text, x.tone) if x.is_speech else lexicon.action_salience(x.text)) >= 0.45
            for x in after
        )
        if not deflated:
            continue
        if best is None or beat_cliff(b, None, cand.episode) > best[0]:
            best = (beat_cliff(b, None, cand.episode), b)

    if best is None:
        return None
    _, line = best
    new_end = round(line.end + TAIL_PAD, 2)
    if new_end > seg.end - 1.0 or new_end - seg.start < MIN_DUR:
        return None

    head = _make_segment(cand.episode, cand.episode.beats, seg.start, new_end)
    if head is None:
        return None

    trimmed = Candidate(
        episode=cand.episode,
        segments=cand.segments[:-1] + [head],
        stitched=cand.stitched,
    )
    trimmed.feats = _feature(cand.episode, trimmed, index, cand.episode.beats)
    return trimmed


def generate_for_episode(episode: Episode, index: SeriesIndex) -> list[Candidate]:
    return generate_single(episode, index)
