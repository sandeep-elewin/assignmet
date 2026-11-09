"""Write JSON, per-episode cut sheets and a self-contained HTML review console.

The HTML is deliberately dependency-free and offline: one file you can email to
an editor, drop on GitHub Pages, or open from disk. No CDN, no build step.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .candidates import Candidate
from .pipeline import RunResult
from .prompting import render_clip
from .scoring import timeline, to_dict, why_it_works
from .screenplay import fmt_ts


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def write_outputs(result: RunResult, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    per_episode_dir = out / "by_episode"
    cuts_dir = out / "cut_sheets"
    per_episode_dir.mkdir(exist_ok=True)
    cuts_dir.mkdir(exist_ok=True)
    # Candidate ids change between runs, so a rerun on a new pack must not
    # leave the previous run's sheets behind.
    for stale in cuts_dir.glob("*.txt"):
        stale.unlink()
    for stale in per_episode_dir.glob("episode-*.json"):
        stale.unlink()

    ranked_ids = {c.id: rank for rank, (_, c) in enumerate(result.ranked, start=1)}
    all_items = []
    for res in result.episodes:
        items = []
        for c in res.picks:
            d = to_dict(c, rank=ranked_ids.get(c.id))
            ok, why = _gate(c)
            d["meets_brief"] = ok
            d["gate_failures"] = why
            d["transcript"] = render_clip(c, include_logline=False)
            items.append(d)
            all_items.append(d)
            paths[f"cut_{c.id}"] = _write_cut_sheet(cuts_dir / f"{c.id}.txt", c)
        _write_json(
            per_episode_dir / f"episode-{res.episode.number:02d}.json",
            {
                "episode": res.episode.number,
                "label": res.episode.label,
                "logline": res.episode.logline,
                "continuity_notes": res.episode.continuity,
                "duration_s": round(res.episode.duration, 2),
                "candidates_considered": len(res.candidates),
                "postable": res.postable,
                "notes": res.notes,
                "picks": items,
            },
        )

    ranked = [to_dict(c, rank=r) for r, (_, c) in enumerate(result.ranked, start=1)]
    for d, (_, c) in zip(ranked, result.ranked):
        ok, why = _gate(c)
        d["meets_brief"] = ok
        d["gate_failures"] = why
        d["transcript"] = render_clip(c, include_logline=False)

    paths["promos"] = out / "promos.json"
    _write_json(
        paths["promos"],
        {
            "generator": "promo-finder",
            "judged_by": result.judge_used,
            "stats": result.stats,
            "characters": {
                "count": len(result.index.characters),
                "major": sorted(result.index.major),
            },
            "ranked_promos": ranked,
            "all_promos": all_items,
        },
    )
    paths["report"] = out / "report.html"
    paths["report"].write_text(render_html(result, all_items, ranked), encoding="utf-8")
    return paths


def _gate(c: Candidate) -> tuple[bool, list[str]]:
    from .rank import meets_brief

    return meets_brief(c)


def _cand_by_id(result: RunResult, cand_id: str) -> Candidate:
    for res in result.episodes:
        for c in res.picks:
            if c.id == cand_id:
                return c
    return next(c for _, c in result.ranked if c.id == cand_id)


def _write_cut_sheet(path: Path, c: Candidate) -> Path:
    lines = [
        f"PROMO {c.id}",
        f"Episode {c.episode.number} - {c.episode.label}",
        f"Duration: {c.clip_duration:.1f}s   Segments: {len(c.segments)}",
        f"Score: {c.score} (heuristic {c.heuristic_score})",
        "",
        "IN / OUT",
    ]
    for seg in timeline(c):
        lines.append(f"  segment {seg['segment']}: {seg['start_tc']} -> {seg['end_tc']}  ({seg['duration']}s)")
    lines += [
        "",
        f"HOOK      {fmt_ts(c.feats.hook_beat.start)}  {c.feats.hook_text}",
        f"CLIFF     {fmt_ts(c.feats.cliff_beat.start)}  {c.feats.cliff_text}",
        "",
        f"WHY       {why_it_works(c)}",
        "",
        "TRANSCRIPT",
        render_clip(c, include_logline=False),
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

CSS = """
:root{--bg:#0e0f13;--panel:#16181f;--panel2:#1c1f28;--line:#282c38;--ink:#eceef4;
--mute:#8d93a6;--hot:#ff5a5f;--good:#39d98a;--warn:#ffb020;--cool:#5aa9ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
a{color:var(--cool)}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 80px}
header h1{font-size:26px;margin:0 0 4px;letter-spacing:-.02em}
header p{margin:0;color:var(--mute);max-width:760px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:22px 0 6px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.stat b{display:block;font-size:21px;letter-spacing:-.02em;white-space:nowrap}
.stat span{color:var(--mute);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.warnbox{background:rgba(255,176,32,.08);border:1px solid rgba(255,176,32,.35);color:#ffd27a;
border-radius:10px;padding:12px 14px;margin:18px 0;font-size:14px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:26px 0 14px}
input,select{background:var(--panel);border:1px solid var(--line);color:var(--ink);
border-radius:8px;padding:9px 11px;font:inherit;min-width:150px}
#q{flex:1 1 260px}
input[type=checkbox]{min-width:0;width:15px;height:15px;padding:0;accent-color:var(--cool)}
.pill{border:1px solid var(--line);background:var(--panel);color:var(--mute);border-radius:999px;
padding:7px 13px;font-size:13px;cursor:pointer;display:inline-flex;align-items:center;gap:8px}
.pill.on{border-color:var(--cool);color:var(--cool)}
.logline{color:#a9b0c4;font-size:13px;margin:5px 0 6px;max-width:74ch}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:var(--mute);margin:34px 0 12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:14px}
.card.fail{border-color:rgba(255,176,32,.4)}
.chead{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap}
.rank{font:700 28px/1 -apple-system,sans-serif;color:var(--hot);min-width:54px}
.eplabel{font-weight:650;letter-spacing:-.01em}
.meta{color:var(--mute);font-size:13px;margin-top:2px}
.score{margin-left:auto;text-align:right}
.score b{font-size:24px;letter-spacing:-.02em}
.score span{display:block;color:var(--mute);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.segs{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 4px}
.seg{font:12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;background:#11131a;border:1px solid var(--line);
border-radius:7px;padding:7px 9px;color:#cfd5e6}
.quotes{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:14px 0}
@media(max-width:720px){.quotes{grid-template-columns:1fr}}
.quote{background:var(--panel2);border-left:3px solid var(--hot);border-radius:8px;padding:10px 12px}
.quote.c{border-left-color:var(--cool)}
.quote small{display:block;color:var(--mute);text-transform:uppercase;letter-spacing:.07em;font-size:10px;margin-bottom:5px}
.quote p{margin:0;font-size:14px}
.bars{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:14px 0 0}
.bar small{display:block;color:var(--mute);font-size:10px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px}
.track{height:5px;background:#0b0c11;border-radius:99px;overflow:hidden}
.fill{height:100%;background:linear-gradient(90deg,var(--cool),var(--good))}
.why{margin:14px 0 0;color:#cfd5e6;font-size:14px}
details{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
summary{cursor:pointer;color:var(--mute);font-size:13px}
pre{white-space:pre-wrap;font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;color:#b9c0d4;
background:#0b0c11;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;max-height:340px}
.tag{font-size:11px;text-transform:uppercase;letter-spacing:.06em;border-radius:999px;padding:3px 9px;
border:1px solid var(--line);color:var(--mute)}
.tag.ok{color:var(--good);border-color:rgba(57,217,138,.45)}
.tag.warn{color:var(--warn);border-color:rgba(255,176,32,.45)}
.tag.stitch{color:var(--cool);border-color:rgba(90,169,255,.45)}
.llm{margin-top:10px;font-size:13px;color:#cfd5e6;border-left:2px solid var(--good);padding-left:10px}
footer{margin-top:44px;color:var(--mute);font-size:12px;border-top:1px solid var(--line);padding-top:16px}
"""

JS = """
const cards=[...document.querySelectorAll('.card')];
const q=document.getElementById('q'),ep=document.getElementById('ep'),only=document.getElementById('only');
function apply(){
  const term=(q.value||'').toLowerCase();
  cards.forEach(c=>{
    const hay=c.dataset.text.toLowerCase();
    let ok=!term||hay.includes(term);
    if(ok&&ep.value) ok=c.dataset.ep===ep.value;
    if(ok&&only.checked) ok=c.dataset.postable==='1';
    c.style.display=ok?'':'none';
  });
}
q.addEventListener('input',apply);ep.addEventListener('change',apply);only.addEventListener('change',apply);
document.querySelectorAll('.pill[data-toggle]').forEach(p=>p.addEventListener('click',()=>{
  const open=p.dataset.toggle==='open';
  document.querySelectorAll('.card details').forEach(d=>d.open=open);
}));
"""


def _bar(label: str, value: float) -> str:
    return (
        f'<div class="bar"><small>{label}</small><div class="track">'
        f'<div class="fill" style="width:{max(0, min(100, value * 100)):.0f}%"></div></div></div>'
    )


def _card(d: dict, total: int) -> str:
    e = html.escape
    segs = "".join(
        f'<span class="seg">SEG {s["segment"]} &nbsp;{s["start_tc"]} &rarr; {s["end_tc"]}'
        f' &nbsp;({s["duration"]}s)</span>'
        for s in d["segments"]
    )
    tags = []
    tags.append('<span class="tag ok">meets brief</span>' if d.get("meets_brief") else
                '<span class="tag warn">below brief</span>')
    if d["stitched"]:
        tags.append('<span class="tag stitch">stitched</span>')
    if d.get("llm"):
        tags.append(f'<span class="tag ok">llm: {e(d["llm"]["model"])}</span>')

    gate = ""
    if d.get("gate_failures"):
        gate = ('<p class="why" style="color:#ffd27a">Fails: '
                + e("; ".join(d["gate_failures"])) + "</p>")

    llm_block = ""
    if d.get("llm"):
        llm_block = (
            f'<div class="llm"><b>Model verdict</b> hook {d["llm"]["hook"]}/5 &middot; '
            f'cliff {d["llm"]["cliffhanger"]}/5 &middot; standalone {d["llm"]["standalone"]}/5'
            f' &middot; spoiler risk {d["llm"]["spoiler_risk"]}/5<br>{e(d["llm"]["reason"])}'
            f'<br><i>Fix:</i> {e(d["llm"]["fix"])}</div>'
        )

    hay = " ".join([str(d["episode"]), d["hook"], d["cliffhanger"], d["why_it_works"], d["transcript"]]).lower()
    rank = d.get("rank")
    rank_html = f"{rank:02d}" if rank else "&mdash;"
    return f"""
    <article class="card{' fail' if not d.get('meets_brief') else ''}"
      data-ep="{d['episode']}" data-postable="{1 if d.get('meets_brief') else 0}"
      data-text="{e(hay)}">
      <div class="chead">
        <div class="rank">{rank_html}</div>
        <div>
          <div class="eplabel">Episode {d['episode']}</div>
          <div class="logline">{e(d['logline'])}</div>
          <div class="meta">{d['clip_duration']:.1f}s &middot; {len(d['segments'])} segment(s) &middot; {d['judged_by']}</div>
          <div class="meta">{' '.join(tags)}</div>
        </div>
        <div class="score"><b>{d['score']:.0f}</b><span>score</span></div>
      </div>
      <div class="segs">{segs}</div>
      <div class="quotes">
        <div class="quote"><small>Hook</small><p>{e(d['hook'])}</p></div>
        <div class="quote c"><small>Cliffhanger</small><p>{e(d['cliffhanger'])}</p></div>
      </div>
      <div class="why">{e(d['why_it_works'])}</div>
      {gate}{llm_block}
      <div class="bars">
        {_bar('hook', d['subscores']['hook'])}
        {_bar('cliff', d['subscores']['cliffhanger'])}
        {_bar('standalone', d['subscores']['standalone'])}
        {_bar('arc', d['subscores']['arc'])}
        {_bar('pacing', d['subscores']['pacing'])}
      </div>
      <details><summary>Transcript &amp; signals</summary>
        <pre>{e(d['transcript'])}</pre>
        <p class="meta">Prior-knowledge entities: {e(', '.join(d['signals']['prior_knowledge_entities']) or 'none')}</p>
        <p class="meta">Standalone notes: {e('; '.join(d['signals']['standalone_notes']) or 'none')}</p>
      </details>
    </article>"""


def render_html(result: RunResult, all_items: list[dict], ranked: list[dict]) -> str:
    s = result.stats
    e = html.escape
    ep_options = "".join(
        f'<option value="{d["episode"]}">Episode {d["episode"]}</option>'
        for d in sorted(ranked, key=lambda x: x["episode"])
    )
    judge_banner = ""
    if result.judge_used == "heuristic":
        judge_banner = (
            '<div class="warnbox"><b>Scored by heuristics only.</b> No model key was configured for this run, '
            'so every score comes from the deterministic lexicons. Set <code>PROMO_LLM_PROVIDER</code> and an '
            'API key to add the model pass; results are blended 55/45 model/heuristic.</div>'
        )
    failed = s["failed_episodes"]

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Promo Finder &mdash; I Married a Broken Soldier</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header>
  <h1>Promo Finder</h1>
  <p>Candidate promos cut from 50 screenplay episodes. Every in/out point below is snapped to a
  real beat boundary in the source script &mdash; the hook lands inside the first 3 seconds and the
  clip stops on an unresolved moment. Scores are reproducible: same pack in, same list out.</p>
</header>

<div class="stats">
  <div class="stat"><b>{s['episodes']}</b><span>episodes</span></div>
  <div class="stat"><b>{s['candidates_generated']}</b><span>windows considered</span></div>
  <div class="stat"><b>{s['episodes_with_postable_promo']}/{s['episodes']}</b><span>episodes with a postable cut</span></div>
  <div class="stat"><b>{s['duration_s']['median']:.0f}s</b><span>median clip length</span></div>
  <div class="stat"><b>{s['score_summary']['top']:.0f}</b><span>top score</span></div>
</div>

{judge_banner}

<div class="toolbar">
  <input id="q" placeholder="Search hook, cliff, transcript&hellip;">
  <select id="ep"><option value="">All episodes</option>{ep_options}</select>
  <label class="pill"><input id="only" type="checkbox"> only postable</label>
  <button class="pill" data-toggle="open">expand all</button>
  <button class="pill" data-toggle="close">collapse all</button>
</div>

<h2>Ranked &mdash; post these first</h2>
{''.join(_card(d, len(ranked)) for d in ranked)}

<h2>Every episode, best cut</h2>
{''.join(_card(d, len(all_items)) for d in all_items if d.get('rank') is None)}

<footer>
  <p><b>{len(failed)} episodes had no clip that met all three brief conditions</b>
  (hook under 0.45, cliffhanger under 0.45, or standalone under 0.50):
  {e(', '.join('ep ' + str(f['episode']) for f in failed) or 'none')}.
  Their best-effort cut is shown and labelled, not hidden.</p>
  <p>Generated by promo-finder &middot; judged_by={e(result.judge_used)}.
  Cut sheets for every promo are in <code>cut_sheets/</code>; full JSON in <code>promos.json</code>.</p>
</footer>
</div><script>{JS}</script></body></html>"""


def write_json_only(result: RunResult, path: str | Path) -> Path:
    p = Path(path)
    _write_json(p, {"stats": result.stats, "ranked": [to_dict(c) for _, c in result.ranked]})
    return p
