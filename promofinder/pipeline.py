"""End-to-end run: pack in, ranked promos out."""

from __future__ import annotations

import statistics as st
from dataclasses import dataclass, field
from pathlib import Path

from .candidates import Candidate, generate_single, generate_stitched, tighten_tail
from .entities import SeriesIndex, build_series_index
from .llm import JudgeConfig, LLMJudge
from .rank import EpisodeResult, meets_brief, rank_globally, select_per_episode
from .scoring import blend_verdict, score_candidate
from .screenplay import Episode, load_dir, load_episode

STITCH_BOOKEND_GAIN = 0.15   # combined hook+cliff a stitched cut must add over the best continuous one
STITCH_SCORE_FLOOR = -1.0    # ...while giving up no more than this on arc, pacing and standalone


def stitch_is_worth_preferring(extra: Candidate, best: Candidate) -> bool:
    """A montage exists to supply a better opening *and* ending than any single
    stretch has. It earns its place only if it actually buys both, if it lands
    the final beat on a spoken line, and if the extra jump does not cost it much
    on arc, pacing or standalone.
    """
    if extra.feats is None or best.feats is None or extra.feats.cliff_beat is None:
        return False
    if not extra.feats.cliff_beat.is_speech:
        return False
    gain = (extra.feats.hook + extra.feats.cliff) - (
        best.feats.hook + best.feats.cliff
    )
    return gain >= STITCH_BOOKEND_GAIN and extra.score >= best.score + STITCH_SCORE_FLOOR


def _load(input_dir: str | Path) -> list[Episode]:
    p = Path(input_dir)
    if p.is_file():
        ep = load_episode(p)
        return [ep] if ep else []
    return load_dir(p)


@dataclass
class RunResult:
    episodes: list[EpisodeResult]
    ranked: list[tuple[int, Candidate]]
    index: SeriesIndex
    stats: dict = field(default_factory=dict)
    judge_used: str = "heuristic"
    judge_error: str = ""


def find_promos(
    input_dir: str | Path,
    *,
    use_llm: bool = False,
    stitch: bool = True,
    keep_per_episode: int = 2,
    top: int = 20,
    judge_top_per_episode: int = 2,
    judge_limit: int = 0,
    cache_path: str | Path = "outputs/llm_cache.json",
) -> RunResult:
    episodes = _load(input_dir)
    if not episodes:
        raise SystemExit(f"no *.txt screenplays found in {input_dir}")
    index = build_series_index(episodes)

    judge: LLMJudge | None = None
    cfg = JudgeConfig.from_env()
    if use_llm and cfg.enabled:
        judge = LLMJudge(cfg, cache_path=cache_path)

    results: list[EpisodeResult] = []
    judged = 0
    for ep in episodes:
        cands = generate_single(ep, index)
        for c in cands:
            score_candidate(c)

        # Editorial tightening: prefer the cut that stops on the line rather
        # than running through the scene's soft outro.
        tightened: list[Candidate] = []
        for c in cands:
            t = tighten_tail(c, index)
            if t is not None:
                score_candidate(t)
                if t.score >= c.score:
                    tightened.append(t)
        cands.extend(tightened)

        best = max(cands, key=lambda c: c.score) if cands else None
        if stitch and best is not None:
            extra = generate_stitched(ep, index)
            if extra is not None:
                score_candidate(extra)
                if stitch_is_worth_preferring(extra, best):
                    cands.append(extra)

        if judge is not None:
            shortlist = sorted(cands, key=lambda c: -c.score)[:judge_top_per_episode]
            for c in shortlist:
                if judge_limit and judged >= judge_limit:
                    break
                verdict = judge.judge(c)
                if verdict is not None:
                    blend_verdict(c, verdict.to_dict())
                    judged += 1

        results.append(select_per_episode(ep, cands, keep=keep_per_episode))

    ranked = rank_globally(results, limit=top)
    stats = _stats(episodes, results, ranked, judged)
    if judge is not None:
        stats["llm_failures"] = judge.failures
    return RunResult(
        episodes=results,
        ranked=ranked,
        index=index,
        stats=stats,
        judge_used="llm+heuristic" if judged else "heuristic",
        judge_error=(judge.last_error if judge is not None else ""),
    )


def _stats(episodes: list[Episode], results: list[EpisodeResult], ranked, judged: int) -> dict:
    all_c = [c for r in results for c in r.candidates]
    top_scores = [c.score for _, c in ranked]
    picks = [c for r in results for c in r.picks]
    durations = [c.clip_duration for c in picks] or [0]
    failed = [
        {"episode": r.episode.number, "notes": r.notes}
        for r in results
        if not r.postable
    ]
    return {
        "episodes": len(episodes),
        "screenplay_minutes": round(sum(e.duration for e in episodes) / 60.0, 1),
        "candidates_generated": len(all_c),
        "candidates_per_episode": round(len(all_c) / max(1, len(episodes)), 1),
        "episodes_with_postable_promo": sum(1 for r in results if r.postable),
        "episodes_without_postable_promo": len(failed),
        "failed_episodes": failed,
        "promos_ranked": len(ranked),
        "stitched_promos": sum(1 for c in picks if c.stitched),
        "duration_s": {
            "min": round(min(durations), 1),
            "median": round(st.median(durations), 1),
            "max": round(max(durations), 1),
        },
        "score_summary": {
            "top": round(max(top_scores), 1) if top_scores else 0,
            "median_of_top": round(st.median(top_scores), 1) if top_scores else 0,
            "bottom_of_top": round(min(top_scores), 1) if top_scores else 0,
        },
        "llm_calls": judged,
    }
