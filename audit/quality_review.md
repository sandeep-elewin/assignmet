# Quality review — human pass over the tool's top 15

Input: 50 episodes / 102.7 minutes of screenplay. Run: `python3 -m promofinder --input .. --out outputs --top 15`
(raw log in `run.log`, full transcripts in `top15_transcripts.txt`).

I read every in/out transcript below, start to finish, and judged each pick against the
brief's three conditions:

1. **Hook** — does something land in the first ~3 seconds that would stop a scroll?
2. **Cliff** — does the cut leave an unresolved question or threat?
3. **Standalone** — can someone who has never seen the show follow it with no setup?

Grades: **Post** (ship as-is) · **Post + fix** (one trim or one title card makes it work) ·
**Don't post**.

| # | Ep | In–out | Grade | Why |
|---|----|--------|-------|-----|
| 1 | 18 | 02:25.80–03:06.75 | Post | Burning home → "Someone wanted us out" → vow → "What are you going to do?" Clean escalation, real question at the cut. Hook is a line over a strong image, not a line alone. |
| 2 | 36 | 01:57.50–02:28.25 | **Post — post this first** | Accusation in the first second, four escalations (witch → cell → condemned → executed), cut on "What wedding?" Nobody needs a name to follow it. |
| 3 | 45 | 00:22.90–00:42.05 + 01:33.20–01:53.25 | Post | Reveal ("You're the Duke?") then invalidation ("You are not Alexander Ashburton's lawful wife"). The 51s jump is a causal leap, not a random montage. |
| 4 | 22 | 01:36.00–02:11.00 | Post | Sneaking into a forbidden room, a dying woman, "This isn't ordinary fever." → "Who has been treating you?" Vertical-friendly: visual, escalating, no names needed. |
| 5 | 35 | 01:51.00–02:25.25 | Post | "How did you escape?" into a survival story, cut on a terrified "Who?" Strongest cliff in the list. |
| 6 | 1 | 01:15.00–01:59.25 | Post + fix | Strong cold line, but 44s of family politics and a wounded rhetorical question at the end. Add "She was jilted at the altar" as a title card, or start 4s later at "And I am what?". |
| 7 | 27 | 00:44.50–01:20.75 | Post | "What is your husband's name?" → door bursts open → interrogation → "Who permitted you to give medicine to the Duchess?" Textbook. |
| 8 | 9 | 00:06.30–00:54.25 | Post + fix | Great first 10s (a mother begging for a dying child) and a decent "Why isn't it working?" — but 20s of measuring pulses and naming herbs sags in the middle. Trim to the diagnosis and the dose. |
| 9 | 23 | 00:32.00–01:24.25 | Post + fix | 52s is the longest pick. The diagnosis is compelling; the journal recitation is not. Cut at "Someone is poisoning her." + "Poison?" and lose ~15s. |
| 10 | 41 | 00:57.80–01:36.09 | Post | Ends on a wordless reaction after an explosion. The tool reports the camera beat as the cliff, which reads oddly in JSON, but for video this is a legitimate visual cliff. |
| 11 | 34 | 00:19.40–01:00.35 | Post + fix | The clip opens on a one-word answer ("No.") to a question the viewer never heard. Start at the judge's line ~8s later. |
| 12 | 29 | 00:27.10–01:14.55 | Post + fix | Opens mid-argument on "It is medicine!" — understandable, but the viewer has no idea what "it" is. Start at "The magistrate will call it witchcraft." |
| 13 | 38 | 00:23.20–00:47.75 | Post | Starving prisoner drags bread into frame; cut on "What if I die here?" 25s, most self-contained pick in the list. |
| 14 | 43 | 01:11.40–01:52.75 | Post + fix | Opens on a denial ("I didn't!") with no context, then becomes a strong document reveal. Start at "You took my title." |
| 15 | 15 | 00:08.50–00:31.45 | Post | "Stop! What are you doing?!" → thugs grinding herbs into the mud → "Months? You actually spend your days growing this filth?" Best hook score (0.73) and standalone score (0.95) in the run. |

**Precision.** Publishable as-is: **9/15 (60%)**. Publishable after one trim or title card:
**15/15 (100%)**. Unusable: **0**.

**Rank order.** The tool's #1 is ep18; I would post **ep36 first**. Ep18's hook is an image plus a
question, which needs the burning cottage to register before the line means anything. Ep36's hook is
spoken at 01:57.50 and lands in 1.8s, and it ends on the cleanest cliff in the show ("What wedding?").
Ep18 is still top-3. This is the human override the brief asks for: the score ranks, the editor picks.

## Failure modes this pass found (and what I changed)

**1. The reported cliffhanger was sometimes not the ending.** The scorer took the highest-scoring
line in the last 4s. On ep32 that was "A disgraced woman?" at 00:47.8, while the clip actually ran to
"…You cannot destroy me." at 00:52.4. That is a resolved, triumphant ending, and the card was
describing a cut that was never made. Fix: `window_cliff` now scores the last *spoken* beat in the
tail. Effect: ep32 and ep3 dropped out of the top 15 (correctly — both end on resolved statements),
and ep18's narrative clip (vow + "What are you going to do?") surfaced at #1 instead of its weaker
"burning house only" cut.

**2. Clips could open on the back half of a sentence.** The screenplays split lines across two blocks
(`"And when they find your corpse..."` / `"...no one will remember..."`). One ep29 pick opened on the
second half. Fix: `_sentence_start` walks back to the nearest earlier speech beat (max 10s) and moves
the in-point there. Effect: ep29's pick moved from 00:53.6 (ellipsis-led) to a clean 00:27.1 start.

**3. Stitching won for the wrong reason.** A two-segment montage is supposed to supply a better opener
*and* closer than any single stretch. A flat score margin let a montage win by jumping 35s and ending
on "Cut to black." (ep1) while a genuinely good one (ep45) lost. Fix: a montage is accepted only if
(a) it ends on a spoken line, (b) its combined hook+cliff beats the best continuous pick by ≥0.15, and
(c) it loses ≤1.0 point elsewhere. Effect: ep1's montage is gone, ep45's is ranked #3.

## Where the tool still picks badly

* **Cold opens on fragments.** #11 ("No."), #12 ("It is medicine!"), #14 ("I didn't!") are all lines
  that answer something the viewer hasn't heard. The hook scorer rewards short, high-emotion lines and
  has no notion of "this is a reply". A cheap fix would be a penalty for ≤3-word lines that begin with
  an answer word (No/Yes/I didn't); it would cost recall on punchy one-liners, so I left it as a
  human-trim case instead.
* **Procedural middle.** #8 and #9 score pacing 1.00 because pacing only measures speech ratio and cut
  rate. Ten seconds of measuring a pulse looks identical to ten seconds of interrogation. A real fix
  needs "does new information arrive", which is a model's job.
* **The emotion tags are doing a lot of work.** ep50's best hook — "Absolution is free. Discretion has
  a price." — scored 0.42 and was refused, because it has no emotion parenthetical and no threat
  keyword. Flat-delivered but excellent lines are underrated. This is the clearest argument for the
  LLM second pass being on by default in production.
* **Visual-only endings.** ep41's cliff is an image; the JSON has to print a stage direction for it.
  That is honest but ugly. A rule that marks `cliff_kind: "visual"` would let the report phrase it
  ("cuts on her expression changing") instead of quoting blocking.

## The 11 refusals — checked by hand

The gate refused 11 episodes. I read the best effort for each. Six are right: ep5 ("They destroyed
it."), ep40, ep42, ep46 and ep48 all end resolved, and ep50's best cut ends on a wordless camera beat
with a hook the lexicon scores 0.42. Three are arguably false negatives:
ep21 cuts on "Sinking to your knees will not save him" (a real menace the lexicon misses), ep39 on
"And I am bringing my wife home" (a strong button, though it resolves), and ep49's hook scored 0.40
against a 0.45 gate. The last two (ep6, ep8) fail on an establishing-shot opening — a visual hook the
text-only scorer cannot see.

So the gate is conservative: it will not ship a bad clip, and it costs the show roughly 2–4 usable
episodes. That is the right trade for a first version, and the failure list is printed on every run
instead of being hidden.
