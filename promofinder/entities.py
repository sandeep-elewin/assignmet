"""Series-level character index.

Used for the standalone-ness feature. The question a promo must answer is
"does this make sense to someone who has never seen the show", and the cheapest
honest proxy is: how much does the clip lean on characters the viewer has never
met, and does it open mid-thought?

Alias handling is deliberately string-only (``LADY JULIANA`` -> ``JULIANA``).
Titles that replace a name entirely, e.g. ``THE FORMER GROOM`` for Gerald,
cannot be resolved without world knowledge and are a documented gap.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .screenplay import Beat, Episode

_TITLE_PREFIXES = ("LADY", "LORD", "SIR", "DAME", "PRINCE", "PRINCESS", "DUKE", "DUCHESS",
                   "KING", "QUEEN", "MR", "MRS", "MISS", "DR", "THE")

PRONOUN_OPENERS = (
    "him", "her", "them", "they", "he", "she", "it", "this", "that", "these",
    "those", "his", "hers", "their", "who", "none of", "all of", "both of",
)

CONTINUATION_OPENERS = (
    "and ", "but ", "so ", "then ", "because ", "instead ", "still ", "yet ",
    "also ", "now ", "as i said", "like i said", "as we agreed", "after what",
    "before you", "like we", "i told you", "you heard", "as you know",
)

MIDTHOUGHT_PHRASES = (
    "as i said", "like i said", "as we agreed", "after what happened",
    "you know what he", "you know what she", "the plan", "as promised",
    "like before", "again?", "still?", "you heard me",
)


def _tokens(name: str) -> list[str]:
    return re.findall(r"[A-Z0-9']+", name.upper())


def _core(name: str) -> str:
    toks = [t for t in _tokens(name) if t not in _TITLE_PREFIXES]
    return " ".join(toks) if toks else name.strip().upper()


@dataclass
class Character:
    key: str
    aliases: set[str] = field(default_factory=set)
    lines: int = 0
    first_episode: int = 10**9
    first_time: float = 0.0


@dataclass
class SeriesIndex:
    characters: dict[str, Character]
    speaker_to_key: dict[str, str]
    major: set[str]

    def key_for(self, speaker: str) -> str | None:
        return self.speaker_to_key.get(speaker.strip().upper())


def build_series_index(episodes: list[Episode]) -> SeriesIndex:
    counts: Counter[str] = Counter()
    for ep in episodes:
        for b in ep.dialogue:
            counts[b.speaker.strip().upper()] += 1

    # Alias merge: "LADY JULIANA" -> "JULIANA" when the core name is itself a speaker.
    speaker_to_key: dict[str, str] = {}
    cores = {_core(name): name for name, _ in counts.most_common()}
    for name in counts:
        core = _core(name)
        speaker_to_key[name] = core if core in cores else name

    characters: dict[str, Character] = {}
    for name, n in counts.items():
        key = speaker_to_key[name]
        ch = characters.setdefault(key, Character(key=key))
        ch.aliases.add(name)
        if key == name:
            ch.aliases.add(key)
        ch.lines += n

    # Order of first appearance, used to tell "returning" from "introduced here".
    for ep in episodes:
        for b in ep.beats:
            if not b.is_speech:
                continue
            key = speaker_to_key.get(b.speaker.strip().upper())
            if not key:
                continue
            ch = characters[key]
            if ep.number < ch.first_episode or (
                ep.number == ch.first_episode and b.start < ch.first_time
            ):
                ch.first_episode, ch.first_time = ep.number, b.start

    ranked = [c.key for c in sorted(characters.values(), key=lambda c: -c.lines)]
    major = set(ranked[:6])
    return SeriesIndex(characters=characters, speaker_to_key=speaker_to_key, major=major)


@dataclass
class StandaloneReport:
    score: float
    debt_entities: list[str]
    introduced_entities: list[str]
    reasons: list[str]


def _entity_mentions(text: str, index: SeriesIndex) -> set[str]:
    upper = text.upper()
    found: set[str] = set()
    for key, ch in index.characters.items():
        for alias in ch.aliases:
            core_tokens = [t for t in _tokens(alias) if len(t) > 2 and t not in _TITLE_PREFIXES]
            if not core_tokens:
                continue
            if all(re.search(rf"\b{re.escape(t)}\b", upper) for t in core_tokens):
                found.add(key)
                break
    return found


def standalone_report(
    beats: list[Beat], episode: Episode, index: SeriesIndex
) -> StandaloneReport:
    reasons: list[str] = []
    penalty = 0.0

    first_speech = next((b for b in beats if b.is_speech and b.text), None)
    opening_text = (first_speech.text if first_speech else beats[0].text).strip()
    low = opening_text.lower()

    # 1. Does it open mid-thought?
    if any(low.startswith(p) for p in CONTINUATION_OPENERS):
        penalty += 0.22
        reasons.append("opens mid-thought (conjunction/back-reference)")
    first_words = low.split()[:3]
    if first_words and first_words[0] in PRONOUN_OPENERS:
        has_named = bool(_entity_mentions(opening_text, index))
        if not has_named:
            penalty += 0.18
            reasons.append(f"opens on a bare pronoun ('{first_words[0]}')")

    joined = " ".join(b.text for b in beats).lower()
    hits = [p for p in MIDTHOUGHT_PHRASES if p in joined]
    if hits:
        penalty += min(0.18, 0.09 * len(hits))
        reasons.append(f"context-dependent phrasing: {', '.join(hits[:2])}")

    # 2. Entity debt: names the viewer must already know.
    mentioned: set[str] = set()
    for b in beats:
        if b.is_speech:
            key = index.key_for(b.speaker)
            if key:
                mentioned.add(key)
        mentioned |= _entity_mentions(b.text, index)

    introduced: list[str] = []
    debt: list[str] = []
    weight = 0.0
    total = 0.0
    for key in mentioned:
        ch = index.characters.get(key)
        if not ch:
            continue
        introduced_here = ch.first_episode == episode.number and ch.first_time >= beats[0].start - 0.01
        known_before = (ch.first_episode, ch.first_time) < (episode.number, beats[0].start)
        if introduced_here:
            introduced.append(key)
            continue
        if not known_before:
            continue
        per = 0.05 if key in index.major else 0.13
        weight += per
        total += per
        debt.append(key)

    if total:
        penalty += min(0.40, weight)
        if debt:
            reasons.append(
                "relies on prior knowledge of " + ", ".join(sorted(debt)[:4])
            )

    # 3. Reaction-only opening is only a problem when the cause is outside the clip.
    opener = beats[0]
    if opener.kind in ("action", "camera") and re.search(
        r"gasp|tears|trembl|shakes|flinches|recoils|stares|frozen|shock", opener.text, re.I
    ):
        has_speech_soon = any(b.is_speech for b in beats if b.start - beats[0].start < 6)
        if not has_speech_soon:
            penalty += 0.12
            reasons.append("opens on a reaction whose cause is offscreen")

    score = max(0.0, min(1.0, 1.0 - penalty))
    return StandaloneReport(score=score, debt_entities=debt, introduced_entities=introduced, reasons=reasons)
