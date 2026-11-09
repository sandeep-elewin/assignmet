"""Dump the top N picks with their full in/out transcripts.

This is the sheet the human review reads: every line the viewer will hear, in
order, with the segment breaks marked, so a verdict can be argued from the text
rather than from a score.

    python3 audit/make_audit.py --top 15
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from promofinder.pipeline import find_promos  # noqa: E402
from promofinder.scoring import why_it_works  # noqa: E402
from promofinder.screenplay import fmt_ts  # noqa: E402


def _line(beat) -> str:
    stamp = f"[{fmt_ts(beat.start)}-{fmt_ts(beat.end)}]"
    if beat.is_speech:
        tone = f" ({beat.tone})" if beat.tone else ""
        return f"{stamp} {beat.speaker}{tone}: {beat.text}"
    return f"{stamp} {beat.kind.upper()}: {beat.text}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(ROOT.parent))
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--out", default=str(ROOT / "audit" / "top15_transcripts.txt"))
    args = ap.parse_args()

    result = find_promos(args.input, top=args.top)
    s = result.stats
    lines: list[str] = [
        "PROMO FINDER -- RAW TOP-N SHEET (unedited tool output)",
        "=" * 100,
        f"input: {args.input}",
        f"episodes: {s['episodes']}   screen time: {s['screenplay_minutes']} min",
        f"candidates generated: {s['candidates_generated']} "
        f"({s['candidates_per_episode']}/episode)",
        f"postable episodes: {s['episodes_with_postable_promo']}/{s['episodes']}",
        "no postable promo: " + ", ".join(
            f"ep{f['episode']} ({'; '.join(f['notes'][1:]) or 'best effort only'})"
            for f in s["failed_episodes"]
        ),
        "judged_by: " + result.judge_used,
        "",
    ]

    for rank, (_, c) in enumerate(result.ranked, start=1):
        f = c.feats
        segs = " + ".join(f"{fmt_ts(x.start)}-{fmt_ts(x.end)}" for x in c.segments)
        lines.append("=" * 100)
        lines.append(
            f"#{rank} ep{c.episode.number} {segs} ({c.clip_duration:.0f}s) "
            f"score={c.score:.2f} "
            f"H={f.hook:.2f} C={f.cliff:.2f} S={f.standalone:.2f} "
            f"A={f.arc:.2f} P={f.pacing:.2f}"
        )
        lines.append(f"WHY: {why_it_works(c)}")
        lines.append("STANDALONE NOTES: " + ("; ".join(f.standalone_reasons) or "none"))
        lines.append("SERIES LOGLINE: " + c.episode.logline)
        lines.append(
            f"CLIP: episode {c.episode.number}, {len(c.segments)} segment(s), "
            f"{c.clip_duration:.0f}s, stitched={c.stitched}"
        )
        for i, seg in enumerate(c.segments, start=1):
            if len(c.segments) > 1:
                lines.append(f"--- segment {i}: {fmt_ts(seg.start)}-{fmt_ts(seg.end)} ---")
            for b in seg.beats:
                lines.append(_line(b))
        lines.append("")

    out = Path(args.out)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} ({len(result.ranked)} promos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
