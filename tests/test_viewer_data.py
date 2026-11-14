"""Tests for viewer_data.py.   python3 -m unittest discover tests

1. A tiny hand-written log covers threads, reposts, likes, follows, sleeps and failed actions.
2. Every real run in logs/ is rebuilt and checked against its _world.json (skipped if none).
"""

import glob
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from viewer_data import build_run, list_runs, run_cost, thread_root  # noqa: E402

PERSONA = {"traits": {"attention_seeking": 0.5}, "wake_prob": 0.5}


def write_log(dirname, name, records):
    path = os.path.join(dirname, name + ".jsonl")
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


def turn(tick, agent, action, **extra):
    return {"type": "decision", "tick": tick, "agent": agent, "action": action,
            "user_prompt": f"prompt {tick} {agent}", "raw": "{}", **extra}


def applied(tick, agent, action, ok=True, **extra):
    return {"type": "applied", "tick": tick, "agent": agent, "action": action, "ok": ok, **extra}


SAMPLE = [
    {"type": "config", "started": "2026-01-01T00:00:00",
     "config": {"ticks": 3, "random_seed": 1, "posts_per_tick": 1,
                "llm": {"provider": "openai_compatible", "model": "gpt-4o-mini"},
                "scheduled_posts": [{"tick": 0, "author": "news", "text": "Big story",
                                     "topic": "story", "keywords": ["story"]}]}},
    {"type": "agent", "name": "a", "persona": {**PERSONA, "generated": True}, "system_prompt": "You are a"},
    {"type": "agent", "name": "b", "persona": PERSONA, "system_prompt": "You are b"},
    {"type": "scheduled_post", "tick": 0, "author": "news", "post_id": "p1", "text": "Big story", "topic": "story"},
    # tick 1: a replies to the story (with surrounding spaces the world strips), b sleeps
    {"type": "sleep", "tick": 1, "agent": "b"},
    turn(1, "a", {"action": "reply", "target_id": "p1", "target_label": "A", "text": "  hi  ", "reason": "r"},
         mode="write", reply_labels={"A": "p1"}, feed_ids=["p1"], p_write=0.45),
    applied(1, "a", {"action": "reply", "target_id": "p1", "text": "  hi  "},
            post_id="p2", target_id="p1", target_author="news"),
    # tick 2: b replies to a's reply, likes fail, a reposts and follows
    turn(2, "b", {"action": "reply", "target_id": "p2", "text": "x" * 300, "reason": "r"}, mode="write"),
    applied(2, "b", {"action": "reply", "target_id": "p2", "text": "x" * 300},
            post_id="p3", target_id="p2", target_author="a"),
    turn(2, "a", {"action": "repost", "target_id": "p3", "reason": "r"}, mode="react"),
    applied(2, "a", {"action": "repost", "target_id": "p3"}, post_id="p4", target_id="p3", target_author="b"),
    # tick 3: a likes p3, b's like fails, a follows b
    turn(3, "a", {"action": "like", "target_id": "p3", "reason": "r"}, mode="react"),
    applied(3, "a", {"action": "like", "target_id": "p3"}, target_id="p3", target_author="b"),
    turn(3, "b", {"action": "like", "target_id": "p3", "reason": "r"}, mode="react"),
    applied(3, "b", {"action": "like", "target_id": "p3"}, ok=False),
    {"type": "end", "ended": "2026-01-01T00:01:00", "llm_calls": 5,
     "usage": {"input_tokens": 1_000_000, "output_tokens": 100_000}},
]


class SampleLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = write_log(cls.tmp.name, "v9_20260101_000000", SAMPLE)
        cls.built, cls.prompts = build_run(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_posts_and_threads(self):
        posts = self.built["posts"]
        self.assertEqual(sorted(posts), ["p1", "p2", "p3", "p4"])
        self.assertTrue(posts["p1"]["news"])
        self.assertEqual(posts["p2"]["text"], "hi")                  # stripped like world.py
        self.assertEqual(len(posts["p3"]["text"]), 280)              # capped like world.py
        self.assertEqual(posts["p3"]["root"], "p1")
        self.assertEqual(posts["p4"]["repost_of"], "p3")
        self.assertIsNone(posts["p4"]["text"])
        self.assertEqual(posts["p2"]["turn"], "1/a")
        self.assertEqual(posts["p2"]["topic"], "story")              # reply inherits its target's topic

    def test_events_skip_failed_actions(self):
        kinds = [(e["tick"], e["agent"], e["kind"]) for e in self.built["events"]]
        self.assertIn((3, "a", "like"), kinds)
        self.assertNotIn((3, "b", "like"), kinds)
        self.assertEqual(self.built["run"]["counts"], {"post": 0, "reply": 2, "repost": 1, "like": 1, "follow": 0})

    def test_turns(self):
        t = self.built["turns"]
        self.assertEqual(t["1/b"]["mode"], "sleep")
        self.assertEqual(t["1/a"]["reply_labels"], {"A": "p1"})
        self.assertEqual(t["1/a"]["action"]["target_label"], "A")
        self.assertEqual(t["1/a"]["result_post"], "p2")
        self.assertFalse(t["3/b"]["ok"])
        self.assertIsNone(t["2/b"]["spark"])                       # missing fields come out as None

    def test_prompts_are_split_out(self):
        self.assertNotIn("user_prompt", json.dumps(self.built))
        self.assertEqual(self.prompts["a"]["system_prompt"], "You are a")
        self.assertEqual(self.prompts["a"]["turns"]["1/a"]["user_prompt"], "prompt 1 a")

    def test_agents(self):
        a = self.built["agents"]
        self.assertTrue(a["news"]["is_news"])
        self.assertTrue(a["a"]["generated"])
        self.assertAlmostEqual(a["a"]["write_prob"], 0.45)
        self.assertGreater(a["a"]["post_chance"], 0)

    def test_run_summary(self):
        r = self.built["run"]
        self.assertTrue(r["complete"])
        self.assertEqual(r["cost_usd"], 0.21)                      # 1M in * 0.15 + 0.1M out * 0.60
        listed = list_runs(self.tmp.name)
        self.assertEqual([x["name"] for x in listed], ["v9_20260101_000000"])
        self.assertEqual(listed[0]["cost_usd"], 0.21)

    def test_incomplete_and_old_logs(self):
        old = [SAMPLE[0] | {"config": {"ticks": 1, "llm": {}}}, SAMPLE[1],
               turn(1, "a", {"action": "none"}), applied(1, "a", {"action": "none"})]
        with tempfile.TemporaryDirectory() as d:
            run, _ = build_run(write_log(d, "v0_old", old))
        self.assertFalse(run["run"]["complete"])
        self.assertIsNone(run["turns"]["1/a"]["mode"])

    def test_price_from_config_wins(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
        own = {"model": "gpt-6-luna", "usd_per_million_tokens": {"input": 0.10, "output": 0.50}}
        self.assertEqual(run_cost(own, usage), 0.6)
        self.assertEqual(run_cost({"model": "gpt-4o-mini"}, usage), 0.75)   # old logs: built-in table
        self.assertIsNone(run_cost({"model": "unknown"}, usage))
        self.assertIsNone(run_cost(own, None))

    def test_thread_root_survives_cycles(self):
        self.assertEqual(thread_root({"x": {"reply_to": "y"}, "y": {"reply_to": "x"}}, "x"), "x")


class RealRuns(unittest.TestCase):
    """Every kept run, rebuilt from its log, must match the world state sim.py saved."""

    def test_matches_world_files(self):
        pairs = [(f, f[:-6] + "_world.json") for f in sorted(glob.glob(os.path.join(ROOT, "logs", "*.jsonl")))]
        pairs = [(f, w) for f, w in pairs if os.path.exists(w)]
        if not pairs:
            self.skipTest("no runs in logs/")
        for log, world_path in pairs:
            with self.subTest(run=os.path.basename(log)):
                run, _ = build_run(log)
                with open(world_path) as f:
                    world = json.load(f)
                posts = run["posts"]
                self.assertEqual(sorted(posts), sorted(p["id"] for p in world["posts"]))
                likes = {}
                for e in run["events"]:
                    if e["kind"] == "like":
                        likes.setdefault(e["target"], set()).add(e["agent"])
                follows = {}
                for e in run["events"]:
                    if e["kind"] == "follow":
                        follows.setdefault(e["agent"], set()).add(e["target"])
                for p in world["posts"]:
                    mine = posts[p["id"]]
                    for k in ("author", "tick", "reply_to", "repost_of"):
                        self.assertEqual(mine[k], p[k], (p["id"], k))
                    if not p["repost_of"]:
                        self.assertEqual(mine["text"], p["text"], p["id"])
                    self.assertEqual(likes.get(p["id"], set()), set(p["likes"]), p["id"])
                for who, whom in world["follows"].items():
                    self.assertEqual(follows.get(who, set()), set(whom), who)


if __name__ == "__main__":
    unittest.main()
