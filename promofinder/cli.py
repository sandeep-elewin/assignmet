"""Command line entry point.

    python3 -m promofinder --input ../ --out outputs

Exits non-zero only on real failure: "some episodes have no good promo" is a
valid, reported result, not an error.
"""

from __future__ import annotations

import argparse
import sys
import time

from .pipeline import find_promos
from .render import write_outputs
from .scoring import to_dict
from .screenplay import fmt_ts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="promofinder",
        description="Find ranked 20-60s promo clips in microdrama screenplays.",
    )
    ap.add_argument("--input", default=".", help="directory of .txt screenplays, or a single file")
    ap.add_argument("--out", default="outputs", help="output directory")
    ap.add_argument("--top", type=int, default=20, help="how many ranked promos to return")
    ap.add_argument("--keep", type=int, default=2, help="picks to keep per episode")
    ap.add_argument("--no-stitch", action="store_true", help="disable multi-segment promos")
    ap.add_argument("--llm", action="store_true", help="enable the model second pass (needs a key)")
    ap.add_argument("--judge-top", type=int, default=2, help="candidates per episode sent to the model")
    ap.add_argument("--judge-limit", type=int, default=0, help="hard cap on model calls, 0 = no cap")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    started = time.time()
    result = find_promos(
        args.input,
        use_llm=args.llm,
        stitch=not args.no_stitch,
        keep_per_episode=args.keep,
        top=args.top,
        judge_top_per_episode=args.judge_top,
        judge_limit=args.judge_limit,
        cache_path=f"{args.out}/llm_cache.json",
    )
    paths = write_outputs(result, args.out)
    elapsed = time.time() - started

    if args.llm and result.judge_used == "heuristic":
        if result.judge_error:
            print(
                f"note: model calls failed ({result.judge_error[:300]}); "
                "ran the heuristic pass only",
                file=sys.stderr,
            )
        else:
            print(
                "note: --llm was requested but no provider key is configured "
                "(set PROMO_LLM_API_KEY or OPENAI_API_KEY); ran the heuristic pass only",
                file=sys.stderr,
            )
    elif args.llm and result.stats.get("llm_failures"):
        print(
            f"note: {result.stats['llm_failures']} model calls failed "
            f"({result.judge_error[:160]}); those clips kept their heuristic score",
            file=sys.stderr,
        )

    if not args.quiet:
        s = result.stats
        print(f"parsed {s['episodes']} episodes ({s['screenplay_minutes']} min of screen time)")
        print(f"generated {s['candidates_generated']} candidate windows "
              f"({s['candidates_per_episode']}/episode), judged_by={result.judge_used}")
        print(f"postable episodes: {s['episodes_with_postable_promo']}/{s['episodes']}")
        if s["failed_episodes"]:
            print("no postable promo: " + ", ".join(f"ep{f['episode']}" for f in s["failed_episodes"]))
        print(f"median clip length: {s['duration_s']['median']}s")
        print()
        print(f"{'#':>3} {'ep':>4} {'in':>9} {'out':>9} {'len':>5} {'score':>6}  hook / cliff")
        for rank, (_, c) in enumerate(result.ranked, start=1):
            d = to_dict(c, rank=rank)
            segs = " + ".join(f"{x['start_tc']}-{x['end_tc']}" for x in d["segments"])
            print(f"{rank:>3} {d['episode']:>4} {segs:>19} {d['clip_duration']:>4.0f}s {d['score']:>6.1f}  "
                  f"{d['hook'][:44]!r} -> {d['cliffhanger'][:44]!r}")
        print()
        print(f"wrote {paths['report']}  ({elapsed:.1f}s)")
        print(f"wrote {paths['promos']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
