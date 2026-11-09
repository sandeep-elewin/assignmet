# promo-finder

Finds 20–60 second promo clips in a folder of timestamped microdrama screenplays.
Rules do the recall and the boundaries; an optional LLM judge does the taste check.
Stdlib only — no install, no build step, no API key required for the default run.

```
python3 -m promofinder --input ".." --out outputs --top 15
open outputs/report.html
```

Python 3.11+ (tested on 3.15). Run it from this folder (`promo-finder/`); `--input` points at a
directory of `episode-*.txt` files or a single file.

## What you get

| File | What it is |
|---|---|
| `outputs/promos.json` | Every ranked promo: episode, each segment's in/out + timecode, hook, cliffhanger, why it works, sub-scores, segment transcript, gate reasons. |
| `outputs/report.html` | Self-contained review page (no CDN, works offline). Ranked cards, transcript per clip, filters by episode / length / stitched. |
| `outputs/by_episode/*.json` | Per-episode candidates, including the best effort when nothing passed the gate. |
| `outputs/cut_sheets/*.txt` | A plain-text editor's sheet per pick: exact in/out and every line between. |
| `outputs/llm_cache.json` | Model verdicts, keyed by provider+model+clip. Only created with `--llm`. |
| `audit/top15_transcripts.txt` | The raw sheet a human reviews (regenerate with `python3 audit/make_audit.py`). |
| `audit/quality_review.md` | My hand review of every top-15 pick, with grades and the failure modes it exposed. |
| `audit/run.log` | Unedited stdout of the canonical run. |

## How it works

1. **Parse** every `CAMERA` / `ACTION` / `SOUND` / dialogue block into beats with absolute
   timestamps (`promofinder/screenplay.py`). Tolerates uppercase keys and `**CAMERA:**`.
2. **Generate** candidate windows from 12 anchors per episode × up to 3 out-points each, plus the
   episode's own ending. Every in/out is snapped to a beat boundary; a spoken line is never cut
   mid-sentence, and a clip never opens on the back half of a split line
   (`promofinder/candidates.py`).
3. **Score** each window on hook (first 3s), cliffhanger (the last spoken line), standalone-ness
   (series-wide character debt), arc and pacing (`promofinder/features.py`, `scoring.py`).
4. **Tighten** the tail when a scene deflates after its best line (`tighten_tail`).
5. **Stitch** one opener to one closer when no single stretch has both — only if it ends on a spoken
   line and keeps its arc (`promofinder/pipeline.py`).
6. **Gate** hard on the brief's three conditions. Episodes that fail are reported as
   "no postable promo", not forced (`promofinder/rank.py`).
7. **Rank** globally, one pick per episode first, then a second pass for deferred picks, rejecting
   overlaps >0.40.

Optional **LLM judge** (`--llm`) re-scores the top 2 clips per episode on hook, cliffhanger,
standalone, spoiler risk and postability, and the result is blended 55/45 with the heuristic score.
The model never touches timestamps.

## Swapping the model

`promofinder/llm.py` speaks either OpenAI-compatible JSON chat or Anthropic messages, over plain
`urllib`. Provider, base URL, key and model are all environment variables — nothing to edit.

```bash
# OpenAI (default model: gpt-4o-mini)
export OPENAI_API_KEY=sk-...
python3 -m promofinder --input .. --out outputs --llm

# Anthropic (default model: claude-sonnet-4-20250514)
export PROMO_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-...
python3 -m promofinder --input .. --out outputs --llm

# Groq / OpenRouter / vLLM / Ollama / LM Studio — any OpenAI-compatible endpoint
export PROMO_LLM_BASE_URL=http://localhost:11434/v1 \
       PROMO_LLM_API_KEY=ollama PROMO_LLM_MODEL=llama3.1:8b
python3 -m promofinder --input .. --out outputs --llm
```

Precedence: `PROMO_LLM_API_KEY` → `OPENAI_API_KEY` → `ANTHROPIC_API_KEY` → `GROQ_API_KEY`.
`PROMO_LLM_PROVIDER` is `openai` or `anthropic`; a bare `PROMO_LLM_BASE_URL` implies `openai`.
Without a key, `--llm` prints a warning and runs the heuristic pass — it never fails silently.

**Cost.** A 50-episode pack yields ~100 judged clips. Each prompt is the clip transcript (~900
tokens) plus ~250 tokens of instructions, and the reply is capped at 400 tokens (usually ~100):

| Model | Input | Output | Per 50 episodes | Per 500 episodes |
|---|---|---|---|---|
| gpt-4o-mini | ~115k tok | ~12k tok | **≈ $0.02** | ≈ $0.20 |
| claude-3.5-haiku | ~115k tok | ~12k tok | **≈ $0.14** | ≈ $1.40 |
| claude-sonnet-4 | ~115k tok | ~12k tok | **≈ $0.50** | ≈ $5.00 |

(At list prices, no prompt caching; verify current prices before quoting them.) Verdicts are cached
by content hash, so re-runs are free. A whole season costs less than one editor-minute, which is the
point of only sending the shortlist to the model.

## Tuning

| Knob | Where | Default |
|---|---|---|
| Clip length | `candidates.py` `MIN_DUR` / `MAX_DUR` | 20s / 60s |
| Hook / cliff / standalone gates | `rank.py` `GATE_*` | 0.45 / 0.45 / 0.50 |
| Score weights | `scoring.py` `W_*` | .30/.30/.22/.12/.06 |
| Stitch acceptance | `pipeline.py` `STITCH_BOOKEND_GAIN` / `STITCH_SCORE_FLOOR` | +0.15 / −1.0 |
| Picks kept per episode | `--keep` | 2 |
| Model calls | `--judge-top`, `--judge-limit` | 2, unlimited |

`--no-stitch` disables multi-segment promos. `--quiet` prints only the file paths.

## Tests

```bash
python3 -m unittest discover -s tests
```

35 tests: parser coverage on all 50 files, boundary invariants (20–60s, cuts on beat boundaries,
hook inside 3s, cliff at the tail), known failure cases now fixed (quote-wrapped questions,
"cut to black" tags, mid-sentence openings), ranking gates and determinism, and the LLM HTTP path via
a local stub server (round-trip, cache, unreachable endpoint, prose-wrapped JSON, score clamping).

## Sharing it

The tool itself is the prototype; `outputs/report.html` is the demo you can open with no server.
To turn this folder into the public link the brief asks for:

```bash
cd promo-finder
git init && git add . && git commit -m "promo finder: rules + optional LLM judge"
gh repo create promo-finder --public --source=. --push
```

GitHub Pages also works for the report alone (Settings → Pages → deploy from `main`, root). Nothing in
the report loads from a CDN, so it renders unchanged from a static host.

## Known limits

Text only — no audio or video, so a promo that works purely on a shot (ep41's wordless ending) is
scored as a stage direction. The hook scorer leans on the show's own emotion parentheticals, so a
flat-delivered great line is underrated. The gate is deliberately conservative: on this pack it
refuses 11 of 50 episodes, and I judge 3 of those refusals to be false negatives (see
`audit/quality_review.md`).
