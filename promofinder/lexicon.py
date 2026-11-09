"""Small hand-built lexicons.

These exist so the cheap pass has real signal without paying for a model. Two
things make them work on this show:

* every spoken line is labelled with an emotion in its parenthetical, e.g.
  ``JULIANA (Devastated)`` -- effectively free annotation, and the strongest
  single hook feature;
* the CAMERA / ACTION tracks use a narrow staging vocabulary, so a tiered word
  list separates real events (a slap) from blocking (she sets down the cup).
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Emotion intensity from dialogue parentheticals / tone tags
# ---------------------------------------------------------------------------

TONE_INTENSITY: dict[str, float] = {
    # breaking / grief
    "devastated": 1.0, "heartbroken": 1.0, "shattered": 1.0, "crushed": 1.0,
    "destroyed": 1.0, "broken": 0.95, "choking on tears": 1.0, "sobbing": 1.0,
    "weeping": 0.9, "crying": 0.9, "tearful": 0.8, "anguished": 1.0,
    "grieving": 0.9, "despairing": 0.95, "hopeless": 0.8,
    # rage / aggression
    "furious": 1.0, "enraged": 1.0, "outraged": 1.0, "seething": 0.95,
    "fuming": 0.9, "accusing": 0.85, "threatening": 0.95, "venomous": 0.95,
    "savage": 0.9, "fierce": 0.8, "snapping": 0.8, "shouting": 0.85,
    "screaming": 1.0, "crying out": 0.9, "hysterical": 1.0,
    # fear / shock
    "horrified": 1.0, "terrified": 1.0, "panicked": 1.0, "panicking": 1.0,
    "gasping": 0.9, "shaken": 0.8, "stunned": 0.9, "shocked": 1.0,
    "aghast": 0.9, "trembling": 0.8, "tremulous": 0.7, "breathless": 0.7,
    "unbelieving": 0.85, "disbelieving": 0.85, "dumbfounded": 0.8,
    # pleading / vulnerability
    "pleading": 0.85, "begging": 0.9, "desperate": 0.95, "urgent": 0.7,
    "frantic": 0.8, "frantically": 0.8, "imploring": 0.85, "vulnerable": 0.7,
    # villain power / contempt
    "gloating": 0.9, "smug": 0.85, "mocking": 0.9, "sneering": 0.9,
    "cruel": 0.95, "vicious": 0.95, "malicious": 0.95, "triumphant": 0.9,
    "unapologetic": 0.85, "dismissive": 0.8, "contemptuous": 0.9,
    "disdainful": 0.85, "haughty": 0.8, "condescending": 0.8,
    "cold": 0.7, "callous": 0.85, "blunt": 0.7, "unforgiving": 0.85,
    "sadistic": 1.0, "gleeful": 0.8, "posh": 0.4,
    # resolve / defiance
    "resolute": 0.7, "unyielding": 0.75, "steely": 0.75, "defiant": 0.8,
    "piercing": 0.8, "sharp": 0.6, "commanding": 0.7, "stern": 0.6,
    "determined": 0.65, "firm": 0.5,
    # low intensity
    "calm": 0.25, "gentle": 0.3, "quiet": 0.3, "measured": 0.2,
    "soft": 0.3, "warm": 0.25, "matter-of-fact": 0.3, "neutral": 0.1,
    "nervous": 0.5, "uneasy": 0.5, "wary": 0.5, "confused": 0.55,
    "puzzled": 0.45, "curious": 0.4, "amused": 0.4, "wry": 0.4,
    "formal": 0.2, "practical": 0.2, "soothing": 0.25, "reassuring": 0.3,
}

# ---------------------------------------------------------------------------
# Staging vocabulary, tiered by how much it earns a viewer's attention
# ---------------------------------------------------------------------------

HARD_VIOLENCE = {
    "slap", "slaps", "slapped", "strike", "strikes", "struck", "shove",
    "shoves", "shoved", "punch", "punches", "punched", "choke", "chokes",
    "choked", "strangle", "strangles", "stab", "stabs", "stabbed", "smash",
    "smashes", "smashed", "shatter", "shatters", "shattered", "slam", "slams",
    "slammed", "rip", "rips", "ripped", "drag", "drags", "dragged", "hurl",
    "hurls", "hurled", "wrench", "wrenches", "grapple", "grapples",
    "wrestle", "wrestles", "kick", "kicks", "kicked", "spit", "spits", "spat",
    "blood", "bloodied", "bleeding", "bleeds", "wound", "wounded", "bruise",
    "bruised", "gun", "knife", "blade", "sword", "dagger", "poison", "poisoned",
    "kill", "kills", "killed", "murder", "murdered", "burn", "burns", "burned",
    "bury", "hangs", "hanged", "whip", "whipped", "lash", "lashes", "collapses",
    "collapsed", "crumples", "flings", "flung",
}

SOFT_CONTACT = {
    "grab", "grabs", "grabbed", "pull", "pulls", "pulled", "push", "pushes",
    "pushed", "lift", "lifts", "lifted", "grip", "grips", "gripped", "seize",
    "seizes", "seized", "clutch", "clutches", "clutched", "toss", "tosses",
    "tossed", "shake", "shakes", "shoved aside", "kneel", "kneels", "kneeled",
    "steps", "turns", "walks", "runs", "enters", "leaves", "approaches",
    "hands", "gives", "takes", "sets", "places", "opens", "closes",
}

REVEAL_VERBS = {
    "reveals", "revealed", "reveal", "unveils", "unveiled", "unmasks",
    "exposes", "exposed", "pulls off", "tears off", "rips off", "removes",
    "removing", "withdraws", "produces", "displays", "shows", "showing",
    "uncovers", "discovers", "found", "points at", "points to",
}

SHOCK_CUES = {
    "freezes", "frozen", "stops dead", "turns to see", "spins around",
    "gasps", "recoils", "flinches", "staggers", "stumbles", "falls",
    "drops to", "falls to", "interrupts", "bursts in", "barges in",
    "appears", "arrives", "silence", "stunned",
}

# ---------------------------------------------------------------------------
# Dialogue cues
# ---------------------------------------------------------------------------

REVEAL_PHRASES = (
    "i never", "it was you", "it's you", "you lied", "you betrayed", "the truth",
    "the secret", "you're not", "you are not", "i'm pregnant", "i am pregnant",
    "he's alive", "she's alive", "is dead", "was never", "turns out",
    "i know what you did", "i know who", "your real", "the real", "illegitimate",
    "not your", "not my", "you're the", "you are the", "i will never",
    "i am leaving", "i'm leaving", "i'm done", "i divorce", "divorce you",
    "give me the", "sign this", "the will", "the deed", "the child",
    "the baby", "pregnant", "bastard", "mistress", "your wife", "your husband",
)

THREAT_PHRASES = (
    "or else", "you'll regret", "you will regret", "i'll destroy", "i will destroy",
    "you will pay", "you'll pay", "you owe me", "mark my words", "i'll ruin",
    "i will ruin", "never show your face", "i'll kill", "i will kill",
    "you're dead", "you are dead", "you'll be sorry", "you will be sorry",
    "mine to", "i own you", "you belong to me", "don't you dare", "how dare",
    "i'll have you", "you will hang", "you'll hang", "still hang", "treason",
    "i'll see you", "i will see you", "never see", "i warn you", "last warning",
    "i'll make you", "i will make you", "you'll never", "you will never",
    "no one will", "nobody will", "i'll tell", "i will tell", "i'll expose",
    "i will expose",
)

IMPERATIVE_STARTS = (
    "stop", "wait", "don't", "do not", "look at me", "tell me", "leave",
    "go", "get out", "kneel", "beg", "apologize", "answer me", "listen",
    "shut up", "let me", "give me", "take it", "say that again", "come back",
    "don't touch", "get away", "get up", "sit down", "stand up", "open it",
    "tell the truth", "look at", "hold on", "let go",
)

# Single menacing tokens that are too common to be phrases but still land.
MENACE_WORDS = {
    "hang", "hanged", "treason", "regret", "ruin", "ruined", "destroy",
    "destroyed", "kill", "killed", "dead", "death", "die", "curse", "cursed",
    "damn", "damned", "burn", "burned", "buried", "exile", "exiled",
    "disgrace", "disgraced", "shame", "shamed", "bastard", "witch", "devil",
    "sin", "sinner", "hell", "murder", "murderer", "betray", "betrayed",
    "traitor", "poison", "thief", "liar", "whore", "slave", "beggar",
}

UNRESOLVED_ENDINGS = ("?", "\u2026", "—", "--")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z']+")
_QUOTE_CHARS = "\"'\u201c\u201d\u2018\u2019\u00ab\u00bb"


def strip_quotes(text: str) -> str:
    """Remove wrapping quotes/whitespace.

    The packs wrap every spoken line in quotes, so ``"Why?"`` ends with a quote
    character, not a question mark. Any terminal-punctuation test must run on
    the stripped text or every question-ending cliffhanger is missed.
    """
    return text.strip().strip(_QUOTE_CHARS).strip()


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def tone_intensity(tone: str) -> float:
    """Max intensity over comma-separated tone labels, 0.0 when unknown."""
    if not tone:
        return 0.0
    best = 0.0
    for part in re.split(r"[,/&]| and ", tone.lower()):
        part = part.strip()
        if not part:
            continue
        if part in TONE_INTENSITY:
            best = max(best, TONE_INTENSITY[part])
            continue
        for key, value in TONE_INTENSITY.items():
            if key in part:
                best = max(best, value * 0.9)
    return best


def count_phrases(text: str, phrases: tuple[str, ...]) -> int:
    low = " " + re.sub(r"[^\w' ]+", " ", text.lower()) + " "
    low = re.sub(r"\s+", " ", low)
    return sum(1 for p in phrases if p in low)


def _has_word(text: str, vocab: set[str]) -> bool:
    low = text.lower()
    return any(re.search(rf"\b{re.escape(w)}\b", low) for w in vocab)


def action_salience(text: str) -> float:
    """0-1 salience for a camera or action beat, tiered by event type."""
    score = 0.0
    if _has_word(text, HARD_VIOLENCE):
        score = 0.60
    elif _has_word(text, SOFT_CONTACT):
        score = 0.16
    if _has_word(text, REVEAL_VERBS):
        score = max(score, 0.34)
    if _has_word(text, SHOCK_CUES):
        score = max(score, 0.30)
    if count_phrases(text, REVEAL_PHRASES):
        score = max(score, 0.34)
    low = text.lower()
    if "extreme close" in low:
        score += 0.10
    elif "close-up" in low or "close up" in low:
        score += 0.07
    if re.search(r"cut to black|fade to black", low):
        score = max(score, 0.70)
    return min(1.0, score)


def dialogue_salience(text: str, tone: str = "") -> float:
    """0-1 salience for a spoken line, combining tone, shape and content."""
    body = strip_quotes(text)
    low = body.lower()
    tl = tone_intensity(tone)

    strongest = 0.0
    secondary = 0.0
    if count_phrases(body, REVEAL_PHRASES):
        strongest = 0.45
    if count_phrases(body, THREAT_PHRASES):
        strongest = max(strongest, 0.42)
    if any(w in MENACE_WORDS for w in words(body)):
        secondary = max(secondary, 0.26)
    if low.startswith(IMPERATIVE_STARTS):
        secondary = max(secondary, 0.24)
    if body.endswith("?"):
        secondary = max(secondary, 0.22)

    # Signals are combined sub-additively: one strong cue should dominate, and
    # tone alone must never manufacture a hook out of a calm line.
    score = 0.50 * tl + 0.75 * strongest + 0.35 * secondary

    if body.count("!") >= 2:
        score += 0.10
    elif body.count("!"):
        score += 0.06
    n = len(words(body))
    if 2 <= n <= 9:
        score += 0.07
    elif n > 32:
        score -= 0.08
    return max(0.0, min(1.0, score))
