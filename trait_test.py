"""Milestone 2: does a trait actually change behavior?

Same agent, same fixed feed, one trait set low vs high, several runs each.
If the two sides look the same, the trait isn't doing anything yet: fix the
wording in agent.py TRAIT_TEXT before scaling up.

    python3 trait_test.py --persona marcus_skeptic --trait judgmental
    python3 trait_test.py --persona lena_lurker --trait agreeableness --low 0.05 --high 0.95 --runs 8
    python3 trait_test.py --persona riya_hype --trait judgmental --mode post   # new posts, not reactions
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import os
import random
import re
import sys
import textwrap
from collections import Counter

from agent import TRAIT_TEXT, Agent, level
from llm import LLM
from loader import TRAITS, load_config, load_personas, load_templates, resolve, story_topics
from world import World

# A fixed feed so the only thing that changes between runs is the trait.
FIXED_FEED = [
    (
        "technews",
        "BREAKING: Startup NovaCode says its new AI agent can fully replace junior developers, and it plans to cut 40% of its own junior engineering hires this year.",
    ),
    (
        "dev_dan",
        "Honestly this is overblown. These agents can barely write a working migration.",
    ),
    (
        "ana_codes",
        "I'm a bootcamp grad and this genuinely scares me. Is it even worth applying for junior roles anymore?",
    ),
    (
        "growth_guru",
        "If your job can be replaced by an AI agent, it was never a real job. Adapt. 🚀",
    ),
]

# What a pass looks like for each trait, printed above the results.
LOOK_FOR = {
    "attention_seeking": "HIGH gets more [write] turns and uses them to reply and ask for reactions; LOW mostly likes or stays quiet.",
    "agreeableness": "HIGH picks worried/agreeing people (p3, p2) and is kind; LOW argues (p1, p4) and attacks the person.",
    "judgmental": "HIGH states conclusions with certainty; LOW hedges (maybe, might, depends) and admits doubt.",
    "curiosity": "HIGH asks real questions and engages beyond its interests; LOW asks nothing.",
    "conformity": "Needs a feed where most people agree. This mixed feed can't show it well.",
}

HEDGES = ["maybe", "might", "perhaps", "depends", "not sure", "i think", "probably", "could be", "i guess"]
WIDTH = 92


class Tee:
    """Write everything printed to both the terminal and a log file."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()


def wrap(text: str, indent: int) -> str:
    pad = " " * indent
    return textwrap.fill(text, WIDTH, initial_indent=pad, subsequent_indent=pad)


def shorten(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def repeated_phrases(texts: list, n: int = 4) -> list:
    """n-word phrases that appear in 2+ different runs: a sign of copying or collapse."""
    seen = Counter()
    for t in texts:
        words = re.findall(r"[a-z']+", t.lower())
        seen.update({" ".join(words[i : i + n]) for i in range(len(words) - n + 1)})
    return [(p, c) for p, c in seen.most_common(3) if c >= 2]


def stats(runs: list) -> dict:
    texts = [r["text"] for r in runs if r["text"]]
    k = len(texts)
    actions = Counter(r["action"] for r in runs)
    modes = Counter(r["mode"] for r in runs)
    blocked = [r["blocked"] for r in runs if r.get("blocked")]
    targets = Counter(
        f"@{r['target_author']}" if r["action"] == "follow" else f"{r['target_id']} @{r['target_author']}"
        for r in runs
        if r["target_id"]
    )
    rep = repeated_phrases(texts)
    return {
        "modes": ", ".join(f"{m} ×{c}" for m, c in sorted(modes.items())),
        "blocked (ignored the menu)": f"{len(blocked)}" + (f" ({', '.join(blocked)})" if blocked else ""),
        "actions": ", ".join(f"{a} ×{c}" for a, c in actions.most_common()),
        "targets": ", ".join(f"{t} ×{c}" for t, c in targets.most_common()) or "-",
        "asks a question": f"{sum('?' in t for t in texts)}/{k}" if k else "-",
        "hedges": f"{sum(any(h in t.lower() for h in HEDGES) for t in texts)}/{k}" if k else "-",
        "avg length": f"{sum(map(len, texts)) // k} chars" if k else "-",
        "repeated phrases": "; ".join(f'"{p}" in {c} runs' for p, c in rep) or "none",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--persona", required=True)
    ap.add_argument("--trait", required=True, choices=TRAITS)
    ap.add_argument("--low", type=float, default=0.1)
    ap.add_argument("--high", type=float, default=0.9)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument(
        "--mode",
        choices=["roll", "write", "react", "post"],
        default="roll",
        help="roll = pick write/react each run like the sim does (default); write/react/post = force one mode. "
        "post = a post turn with a spark (same sparks for LOW and HIGH)",
    )
    args = ap.parse_args(argv)

    # Save a copy of this output to logs/trait_tests/ (same text you see in the terminal).
    os.makedirs(resolve("logs/trait_tests"), exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    mock = "_mock" if args.mock else ""
    log_path = resolve(f"logs/trait_tests/{args.persona}_{args.trait}{mock}_{stamp}.txt")
    log_file = open(log_path, "w")
    sys.stdout = Tee(sys.__stdout__, log_file)

    cfg = load_config(args.config)
    llm_cfg = {"provider": "mock", "model": "mock"} if args.mock else cfg["llm"]
    llm = LLM(llm_cfg, mock_seed=cfg["random_seed"])
    templates = load_templates()
    base = next(
        (p for p in load_personas(cfg["personas_dir"]) if p["name"] == args.persona),
        None,
    )
    if base is None:
        raise SystemExit(f"no persona named {args.persona}")

    world = World([base["name"]] + [a for a, _ in FIXED_FEED])
    for author, text in FIXED_FEED:
        world.add_post(author, text, tick=0)

    print("=" * WIDTH)
    print(f"TRAIT TEST  {args.persona} · {args.trait}   (model: {llm_cfg.get('model')}, {args.runs} runs per value)")
    print("=" * WIDTH)
    print("Other traits (fixed): " + ", ".join(f"{t} {v}" for t, v in base["traits"].items() if t != args.trait))
    print("Feed shown to the agent:")
    for p in world.posts.values():
        print(f"  {p.id}  @{p.author}: {shorten(p.text, WIDTH - 14 - len(p.author))}")
    print(f"Pass looks like: {LOOK_FOR[args.trait]}")
    if args.mode == "roll":
        print("Mode: rolled per run from each version's write chance (same random sequence for LOW and HIGH)")
    else:
        print(f"Mode: forced to {args.mode} for every run")

    results = {}
    for label, value in (("LOW", args.low), ("HIGH", args.high)):
        persona = copy.deepcopy(base)
        persona["traits"][args.trait] = value
        agent = Agent(persona, templates, cfg["seed_topic"], cfg["memory_size"], topics=story_topics(cfg))
        mode_rng = random.Random(cfg["random_seed"] + 3)  # reset so LOW and HIGH get the same rolls
        post_rng = random.Random(cfg["random_seed"] + 4)  # same for sparks

        print("\n" + "-" * WIDTH)
        print(f"{label}: {args.trait} = {value}    write chance: {agent.write_prob:.0%}")
        print(wrap(f'trait text: "{TRAIT_TEXT[args.trait][level(value)]}"', 2))
        print("-" * WIDTH)

        runs = []
        for i in range(args.runs):
            if args.mode == "roll":
                mode = "write" if mode_rng.random() < agent.write_chance(False) else "react"
            else:
                mode = args.mode
            # Sparks come from the persona as given, so a trait change doesn't change the spark.
            turn = Agent(base, templates, cfg["seed_topic"], 0).roll_post_turn(world, 1, post_rng) if mode == "post" else None
            agent.seed = cfg["random_seed"] + i  # different eye-catchers each run, same for LOW and HIGH
            rec = agent.decide(world, 1, llm, cfg["feed_size"], mode, turn)
            a = dict(rec["action"], mode=mode, blocked=rec["blocked"])
            turn_label = f"post: {turn['spark']}" if turn else mode
            head = f"#{i + 1}  [{turn_label}]  {a['action'].upper()}"
            if a["action"] == "follow" and a["target_id"]:
                a["target_author"] = a["target_id"].lstrip("@")
                head += f" -> @{a['target_author']}"
            elif a["target_id"]:
                target = world.posts.get(a["target_id"])
                a["target_author"] = target.author if target else "?"
                head += f" -> {a['target_id']}" + (f" (@{target.author})" if target else " (no such post!)")
            print(head)
            if a["text"]:
                print(wrap(f'"{a["text"]}"', 5))
            if a["reason"]:
                print(wrap(f"why: {a['reason']}", 5))
            if rec["parse_error"]:
                print(f"     !! parse error: {rec['parse_error']}")
            runs.append(a)
        results[label] = (value, stats(runs))

    (lo_v, lo), (hi_v, hi) = results["LOW"], results["HIGH"]
    print("\n" + "=" * WIDTH)
    print(f"COMPARISON   LOW ({lo_v})  vs  HIGH ({hi_v})        * = differs")
    print("=" * WIDTH)
    for key in lo:
        mark = "*" if lo[key] != hi[key] else " "
        print(f"{mark} {key}")
        print(f"     LOW : {lo[key]}")
        print(f"     HIGH: {hi[key]}")
    print(
        "\nNumbers are hints, not a verdict: still read the texts. "
        "Repeated phrases across runs mean the model is copying or collapsing."
    )
    sys.stdout = sys.__stdout__
    log_file.close()
    print(f"\nSaved to {os.path.relpath(log_path)}")


if __name__ == "__main__":
    main()
