"""Tests for the promo finder. Stdlib only: ``python3 -m unittest discover -s tests``."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from promofinder.candidates import generate_single, generate_stitched
from promofinder.entities import build_series_index
from promofinder.features import beat_cliff, beat_hook, window_cliff
from promofinder.lexicon import strip_quotes
from promofinder.llm import JudgeConfig, LLMJudge, parse_verdict
from promofinder.pipeline import find_promos, stitch_is_worth_preferring
from promofinder.rank import meets_brief
from promofinder.render import write_outputs
from promofinder.scoring import score_candidate
from promofinder.screenplay import (
    Beat,
    Episode,
    Scene,
    load_dir,
    parse_episode_text,
    parse_ts,
)

PACK = Path(__file__).resolve().parents[2]


class TestParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.episodes = load_dir(PACK)

    def test_reads_every_episode(self):
        self.assertEqual(len(self.episodes), 50)
        self.assertEqual([e.number for e in self.episodes], list(range(1, 51)))

    def test_no_episode_is_empty(self):
        for e in self.episodes:
            self.assertGreater(len(e.beats), 20, f"episode {e.number}")
            self.assertGreater(e.duration, 60, f"episode {e.number}")
            self.assertTrue(e.logline, f"episode {e.number} has no logline")

    def test_uppercase_key_variant_parses(self):
        # episode 6 uses SCENE HEADING: / SCENE START: / SCENE END:
        ep6 = next(e for e in self.episodes if e.number == 6)
        self.assertGreater(len(ep6.scenes), 1)
        self.assertTrue(ep6.scenes[0].heading)

    def test_all_four_tracks_are_classified(self):
        kinds = {b.kind for e in self.episodes for b in e.beats}
        self.assertEqual(kinds, {"camera", "action", "dialogue", "sound"})

    def test_timestamps_are_sane(self):
        for e in self.episodes:
            self.assertLessEqual(e.duration, 60 * 10)
            prev = -1.0
            for b in e.beats:
                self.assertGreaterEqual(b.start, 0)
                self.assertGreaterEqual(b.end, b.start, f"ep{e.number} @ {b.start}")
                self.assertGreaterEqual(b.start, prev - 0.01, f"ep{e.number} not sorted")
                prev = b.start

    def test_speaker_titles_are_stripped_from_tone(self):
        for e in self.episodes:
            for b in e.dialogue:
                self.assertNotIn("(", b.speaker, f"{b.speaker}")
                self.assertNotIn(")", b.speaker, f"{b.speaker}")

    def test_script_markers_do_not_leak_into_text(self):
        for e in self.episodes:
            for b in e.beats:
                self.assertNotIn("SCRIPT END", b.text)
                self.assertNotIn("SCRIPT START", b.text)

    def test_parse_ts(self):
        self.assertAlmostEqual(parse_ts("01:23.45"), 83.45)
        self.assertAlmostEqual(parse_ts("00:00.00"), 0.0)
        self.assertIsNone(parse_ts("nope"))


class TestClipBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.episodes = load_dir(PACK)
        cls.index = build_series_index(cls.episodes)
        cls.cands = []
        for e in cls.episodes:
            cs = generate_single(e, cls.index)
            for c in cs:
                score_candidate(c)
            cls.cands.extend(cs)
            s = generate_stitched(e, cls.index)
            if s:
                score_candidate(s)
                cls.cands.append(s)

    def test_cut_points_land_on_beat_boundaries(self):
        """A cut must never start mid-line or mid-shot."""
        for c in self.cands:
            starts = {round(b.start, 2) for b in c.episode.beats}
            for seg in c.segments:
                self.assertIn(round(seg.start, 2), starts, f"{c.id} seg start floats")

    def test_durations_within_brief(self):
        for c in self.cands:
            self.assertGreaterEqual(c.clip_duration, 20.0 - 0.01, c.id)
            self.assertLessEqual(c.clip_duration, 60.0 + 1.01, c.id)

    def test_segment_end_does_not_swallow_the_next_line(self):
        for c in self.cands:
            for seg in c.segments:
                inside = [b for b in c.episode.beats if b.start < seg.end - 0.01]
                if not inside:
                    continue
                last = max(inside, key=lambda b: b.end)
                after = [b for b in c.episode.beats if b.start >= last.start and b.start > seg.start]
                nxt = next((b for b in after if b.start > last.end - 0.01), None)
                if nxt is not None:
                    self.assertLessEqual(seg.end, nxt.start + 0.01, f"{c.id} overlaps next beat")

    def test_hook_is_inside_first_three_seconds(self):
        for c in self.cands:
            off = c.feats.hook_beat.start - c.start
            self.assertLessEqual(off, 3.0 + 0.01, c.id)

    def test_cliff_is_at_the_tail(self):
        for c in self.cands:
            last_end = c.segments[-1].end
            self.assertGreaterEqual(c.feats.cliff_beat.end, last_end - 4.0 - 0.01, c.id)


class TestCliffDetection(unittest.TestCase):
    def _ep(self, duration=120.0):
        return Episode(1, "Episode 1", "", "", [Scene(1, "INT. ROOM - DAY", 0, duration)], "")

    def test_question_ending_beats_statement(self):
        q = Beat("dialogue", '"Why did you do it?"', 70.0, 72.0, "A", "Desperate")
        s = Beat("dialogue", '"I will fetch the water."', 70.0, 72.0, "A", "Calm")
        ep = self._ep()
        self.assertGreater(beat_cliff(q, None, ep), beat_cliff(s, None, ep) + 0.25)

    def test_quoted_lines_are_unwrapped_before_shape_tests(self):
        self.assertEqual(strip_quotes('"Why?"'), "Why?")
        self.assertTrue(strip_quotes('"Wait\u2026"').endswith("\u2026"))

    def test_threat_scores_high(self):
        t = Beat("dialogue", '"Careful men still hang when the crime is treason."', 118.0, 119.5, "P", "Cold")
        self.assertGreater(beat_cliff(t, None, self._ep()), 0.55)

    def test_episode_final_line_gets_structural_credit(self):
        ep = self._ep(100.0)
        a = Beat("dialogue", '"I see."', 98.5, 99.5, "A", "")
        b = Beat("dialogue", '"I see."', 60.0, 61.0, "A", "")
        self.assertGreater(beat_cliff(a, None, ep), beat_cliff(b, None, ep))

    def test_cut_to_black_is_a_cliffhanger(self):
        ep = self._ep()
        a = Beat("camera", "Cut to black.", 118.0, 120.0)
        b = Beat("camera", "She sets down the cup.", 118.0, 120.0)
        self.assertGreater(beat_cliff(a, None, ep), beat_cliff(b, None, ep))

    def test_window_cliff_looks_past_a_trailing_sound_tag(self):
        ep = self._ep()
        line = Beat("dialogue", '"What wedding?"', 95.0, 97.0, "A", "Shocked")
        sting = Beat("sound", "A low ominous drone swells.", 97.0, 99.0)
        _, chosen = window_cliff([line, sting], sting.end, None, ep)
        self.assertIs(chosen, line)


class TestHookDetection(unittest.TestCase):
    def test_shocking_line_beats_narration(self):
        loud = Beat("dialogue", '"I buried you."', 10.0, 12.0, "J", "Horrified")
        flat = Beat("camera", "Wide shot of the empty corridor.", 10.0, 12.0)
        self.assertGreater(beat_hook(loud), beat_hook(flat) + 0.2)

    def test_camera_blocking_does_not_max_the_scale(self):
        flat = Beat("camera", "Medium shot of the room as she walks in.", 0.0, 3.0)
        self.assertLess(beat_hook(flat), 0.5)

    def test_violence_beats_close_up_alone(self):
        slap = Beat("action", "She slaps him hard across the face.", 0.0, 3.0)
        close = Beat("camera", "Close-up on his face.", 0.0, 3.0)
        self.assertGreater(beat_hook(slap), beat_hook(close) + 0.15)


class TestRanking(unittest.TestCase):
    def test_gate_rejects_missing_cliffhanger(self):
        class F:
            hook = 0.9
            cliff = 0.1
            standalone = 0.9

        class C:
            feats = F()

        ok, why = meets_brief(C())
        self.assertFalse(ok)
        self.assertTrue(any("cliffhanger" in w for w in why))

    def test_diversity_caps_episodes_in_top_list(self):
        result = find_promos(PACK, top=10)
        eps = [c.episode.number for _, c in result.ranked]
        self.assertEqual(len(eps), len(set(eps)), "top 10 repeats an episode")
        for rank, (_, c) in enumerate(result.ranked, start=1):
            ok, _ = meets_brief(c)
            self.assertTrue(ok, f"rank {rank} does not meet the brief")


class TestStitchRule(unittest.TestCase):
    """Stitching must buy both bookends, not just a bigger number."""

    @staticmethod
    def _cand(hook, cliff, score, speech=True):
        class F:
            pass

        class B:
            is_speech = speech

        f = F()
        f.hook, f.cliff, f.cliff_beat = hook, cliff, B()

        class C:
            pass

        c = C()
        c.feats, c.score = f, score
        return c

    def test_montage_needs_a_better_opening_and_ending(self):
        best = self._cand(0.9, 0.6, 70.0)
        same = self._cand(0.9, 0.65, 72.0)
        self.assertFalse(stitch_is_worth_preferring(same, best))

    def test_montage_must_stop_on_a_spoken_line(self):
        best = self._cand(0.4, 0.4, 60.0)
        better = self._cand(0.9, 0.7, 61.0, speech=False)
        self.assertFalse(stitch_is_worth_preferring(better, best))

    def test_montage_cannot_tank_the_rest_of_the_score(self):
        best = self._cand(0.4, 0.4, 70.0)
        jump = self._cand(0.9, 0.7, 60.0)
        self.assertFalse(stitch_is_worth_preferring(jump, best))

    def test_a_real_improvement_is_accepted(self):
        best = self._cand(0.4, 0.4, 70.0)
        montage = self._cand(0.9, 0.7, 70.5)
        self.assertTrue(stitch_is_worth_preferring(montage, best))


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        a = find_promos(PACK, top=10)
        b = find_promos(PACK, top=10)
        self.assertEqual([c.id for _, c in a.ranked], [c.id for _, c in b.ranked])
        self.assertEqual([c.score for _, c in a.ranked], [c.score for _, c in b.ranked])


class TestRerunClearsStaleOutputs(unittest.TestCase):
    def test_sheets_from_a_previous_run_are_removed(self):
        src = sorted(PACK.glob("*.txt"))[0]
        with tempfile.TemporaryDirectory() as pack, tempfile.TemporaryDirectory() as out:
            shutil.copy(src, Path(pack) / src.name)
            result = find_promos(pack, top=5)
            write_outputs(result, out)
            first_run = sorted((Path(out) / "cut_sheets").glob("*.txt"))
            self.assertTrue(first_run)

            stale = Path(out) / "cut_sheets" / "ep99-deadbeef.txt"
            stale.write_text("from an older pack")
            write_outputs(result, out)
            self.assertFalse(stale.exists())
            self.assertEqual(sorted((Path(out) / "cut_sheets").glob("*.txt")), first_run)


# ---------------------------------------------------------------------------


class _Stub(BaseHTTPRequestHandler):
    reply = {
        "hook": 5, "cliffhanger": 4, "standalone": 3,
        "spoiler_risk": 2, "postable": True,
        "reason": "The question lands before a hard cut.",
        "fix": "Trim two seconds of setup.",
    }
    hits = 0

    def do_POST(self):  # noqa: N802
        _Stub.hits += 1
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        assert body["messages"], "empty request"
        payload = json.dumps({
            "choices": [{"message": {"content": json.dumps(self.reply)}}]
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class TestLLMPlumbing(unittest.TestCase):
    """Proves the HTTP call, JSON parse, cache and fallback work.

    This is a plumbing test against a local stub, not evidence that any real
    model judges promos well.
    """

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Stub)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.episodes = load_dir(PACK)
        cls.cand = generate_single(cls.episodes[0], build_series_index(cls.episodes))[0]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _judge(self, tmp):
        cfg = JudgeConfig(provider="openai", model="stub-1", api_key="test",
                          base_url=f"http://127.0.0.1:{self.port}/v1", timeout=5)
        return LLMJudge(cfg, cache_path=Path(tmp) / "cache.json")

    def test_verdict_round_trips(self):
        _Stub.hits = 0
        with tempfile.TemporaryDirectory() as tmp:
            v = self._judge(tmp).judge(self.cand)
            self.assertIsNotNone(v)
            self.assertEqual(v.hook, 5.0)
            self.assertTrue(v.postable)
            self.assertEqual(_Stub.hits, 1)

    def test_second_call_is_served_from_cache(self):
        _Stub.hits = 0
        with tempfile.TemporaryDirectory() as tmp:
            j = self._judge(tmp)
            j.judge(self.cand)
            v2 = j.judge(self.cand)
            self.assertTrue(v2.cached)
            self.assertEqual(_Stub.hits, 1)

    def test_unreachable_endpoint_returns_none(self):
        cfg = JudgeConfig(provider="openai", model="x", api_key="k",
                          base_url="http://127.0.0.1:1/v1", timeout=2)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(LLMJudge(cfg, cache_path=Path(tmp) / "c.json").judge(self.cand))

    def test_no_key_means_no_call(self):
        cfg = JudgeConfig(provider="openai", model="x", api_key="", base_url="http://127.0.0.1:1/v1")
        self.assertFalse(cfg.enabled)

    def test_parse_tolerates_prose_around_json(self):
        v = parse_verdict('Sure! {"hook":4,"cliffhanger":5,"standalone":2,'
                          '"spoiler_risk":1,"postable":true,"reason":"r","fix":"f"} done')
        self.assertEqual(v["hook"], 4.0)
        self.assertEqual(v["standalone"], 2.0)

    def test_parse_clamps_out_of_range(self):
        self.assertEqual(parse_verdict('{"hook":99,"cliffhanger":-4}')["hook"], 5.0)
        self.assertEqual(parse_verdict('{"hook":99,"cliffhanger":-4}')["cliffhanger"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
