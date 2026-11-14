"""Turn a run log (logs/<run>.jsonl) into the JSON the web viewer reads.

The log is the single source of truth: _world.json has no ticks on likes or follows, so
replaying "the world at tick 12" needs the log's `applied` records.

    build_run(path)   -> (run, prompts)   run = everything but prompt text; prompts = per agent
    list_runs(dir)    -> [summary, ...]   newest first

Every field after `type` is optional, because older logs recorded less (v0 logs have no
modes, no menus, no sparks). Missing fields come out as None and the viewer says so.
"""

from __future__ import annotations

import glob
import json
import os
import random
from collections import Counter

from analyze import post_topics
from world import MAX_LEN

# USD per million tokens (input, output), for logs from before config.json had
# llm.usd_per_million_tokens. Newer runs carry their own price in the logged config.
PRICES = {"gpt-4o-mini": (0.15, 0.60)}


def run_cost(llm_cfg: dict, usage):
    """Estimated USD for a run, or None when the price or the token counts are unknown."""
    if not usage:
        return None
    own = llm_cfg.get("usd_per_million_tokens")
    price = (own["input"], own["output"]) if own else PRICES.get(llm_cfg.get("model"))
    if not price:
        return None
    return round(usage.get("input_tokens", 0) / 1e6 * price[0] + usage.get("output_tokens", 0) / 1e6 * price[1], 4)

TURN_FIELDS = [
    "mode", "p_write", "replied_to", "allowed", "reply_targets", "reply_labels", "like_targets",
    "feed_ids", "glance_ids", "spark", "story_id", "parse_error", "blocked", "fixed_target",
    "llm_error",
]


def load(path: str) -> list:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def run_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def poster_chances(personas: dict, mean: float, trials: int = 20000, seed: int = 0) -> dict:
    """P(an agent is picked to post in a given tick), estimated by replaying sim.pick_posters.

    Same rule as sim.py: a Poisson(mean) number of posters, drawn without replacement with
    weight 0.05 + attention_seeking. Estimated rather than exact; fine to two digits.
    """
    from sim import poisson  # local import: sim imports a lot we don't otherwise need

    names = list(personas)
    if not names or not mean:
        return {n: 0.0 for n in names}
    weights = {n: 0.05 + personas[n]["traits"]["attention_seeking"] for n in names}
    rng, hits = random.Random(seed), Counter()
    for _ in range(trials):
        pool = names[:]
        for _ in range(min(poisson(rng, mean), len(pool))):
            n = rng.choices(pool, weights=[weights[x] for x in pool])[0]
            pool.remove(n)
            hits[n] += 1
    return {n: round(hits[n] / trials, 3) for n in names}


def build_run(path: str):
    records = load(path)
    if not records or records[0].get("type") != "config":
        raise ValueError(f"{path}: not a Chirp run log (first line isn't the config)")
    cfg = records[0]["config"]
    has_topics = any(sp.get("topic") for sp in cfg.get("scheduled_posts", []))
    topic_of = post_topics(records)[0] if has_topics else {}  # logs before topics existed: none

    personas = {r["name"]: r["persona"] for r in records if r["type"] == "agent"}
    prompts = {n: {"system_prompt": r["system_prompt"], "turns": {}}
               for r in records if r["type"] == "agent" for n in [r["name"]]}
    chances = poster_chances(personas, cfg.get("posts_per_tick", 0))

    agents = {}
    for name, p in personas.items():
        traits = p.get("traits", {})
        write_prob = p.get("write_prob")
        if write_prob is None and "attention_seeking" in traits:
            write_prob = round(0.1 + 0.7 * traits["attention_seeking"], 3)
        agents[name] = {
            "name": name, "bio": p.get("bio"), "traits": traits, "interests": p.get("interests"),
            "hobbies": p.get("hobbies"), "voice": p.get("voice"), "stance": p.get("stance"),
            "opinions": p.get("opinions"), "wake_prob": p.get("wake_prob"), "write_prob": write_prob,
            "post_chance": chances.get(name), "generated": bool(p.get("generated")), "is_news": False,
        }

    posts, events, turns = {}, [], {}
    ended, calls, usage = None, None, None
    for r in records:
        t = r["type"]
        if t == "scheduled_post":
            author = r["author"]
            agents.setdefault(author, {"name": author, "is_news": True})
            posts[r["post_id"]] = {
                "id": r["post_id"], "tick": r["tick"], "author": author, "text": r["text"],
                "reply_to": None, "repost_of": None, "turn": None, "news": True,
            }
        elif t == "sleep":
            key = f'{r["tick"]}/{r["agent"]}'
            turns[key] = {"tick": r["tick"], "agent": r["agent"], "mode": "sleep"}
        elif t == "decision":
            key = f'{r["tick"]}/{r["agent"]}'
            action = r.get("action") or {}
            turn = {"tick": r["tick"], "agent": r["agent"]}
            turn.update({f: r.get(f) for f in TURN_FIELDS})
            turn["action"] = {k: action.get(k) for k in ("action", "target_id", "target_label", "text", "reason")}
            turns[key] = turn
            if r["agent"] in prompts:
                prompts[r["agent"]]["turns"][key] = {"user_prompt": r.get("user_prompt"), "raw": r.get("raw")}
        elif t == "applied":
            key = f'{r["tick"]}/{r["agent"]}'
            turn = turns.get(key)
            if turn is not None:
                turn["ok"] = r.get("ok")
                turn["result_post"] = r.get("post_id")
                turn["target_author"] = r.get("target_author")
            if not r.get("ok"):
                continue
            kind = (r.get("action") or {}).get("action")
            target = r.get("target_id") or (r.get("action") or {}).get("target_id")
            if kind in ("post", "reply", "repost") and r.get("post_id"):
                posts[r["post_id"]] = {
                    "id": r["post_id"], "tick": r["tick"], "author": r["agent"],
                    # The world strips and caps text (world.py apply/add_post); show what was posted.
                    "text": None if kind == "repost" else (r["action"].get("text") or "").strip()[:MAX_LEN],
                    "reply_to": target if kind == "reply" else None,
                    "repost_of": target if kind == "repost" else None,
                    "turn": key, "news": False,
                }
            if kind in ("post", "reply", "repost", "like", "follow"):
                events.append({"tick": r["tick"], "agent": r["agent"], "kind": kind,
                               "target": target if kind != "post" else None, "post": r.get("post_id")})
        elif t == "end":
            ended, calls, usage = r.get("ended"), r.get("llm_calls"), r.get("usage")

    for p in posts.values():
        p["root"] = thread_root(posts, p["id"])
        p["topic"] = topic_of.get(p["id"])

    model = cfg.get("llm", {}).get("model")
    cost = run_cost(cfg.get("llm", {}), usage)
    kinds = Counter(e["kind"] for e in events)
    run = {
        "run": {
            "name": run_name(path), "started": records[0].get("started"), "ended": ended,
            "complete": ended is not None,
            "model": model, "provider": cfg.get("llm", {}).get("provider"),
            "seed": cfg.get("random_seed"), "ticks": cfg.get("ticks"), "feed_size": cfg.get("feed_size"),
            "seed_topic": cfg.get("seed_topic"),
            "posts_per_tick": cfg.get("posts_per_tick"), "agents": len(personas),
            "calls": calls, "tokens": usage, "cost_usd": cost,
            "topics": [sp["topic"] for sp in cfg.get("scheduled_posts", []) if sp.get("topic")],
            "counts": {k: kinds.get(k, 0) for k in ("post", "reply", "repost", "like", "follow")},
        },
        "agents": agents,
        "posts": posts,
        "events": events,
        "turns": turns,
    }
    return run, prompts


def thread_root(posts: dict, pid: str) -> str:
    seen = set()
    while posts.get(pid, {}).get("reply_to") and pid not in seen:
        seen.add(pid)
        pid = posts[pid]["reply_to"]
    return pid


def list_runs(log_dir: str) -> list:
    """One summary per run log, newest first. Reads only the first and last lines of each file."""
    out = []
    for path in glob.glob(os.path.join(log_dir, "*.jsonl")):
        try:
            with open(path) as f:
                first = json.loads(f.readline())
                last = first
                for line in f:
                    if line.strip():
                        last = line
                last = json.loads(last) if isinstance(last, str) else last
        except (OSError, ValueError):
            continue
        if first.get("type") != "config":
            continue
        cfg = first["config"]
        usage = last.get("usage") if last.get("type") == "end" else None
        model = cfg.get("llm", {}).get("model")
        cost = run_cost(cfg.get("llm", {}), usage)
        out.append({
            "name": run_name(path), "started": first.get("started"),
            "complete": last.get("type") == "end", "model": model,
            "provider": cfg.get("llm", {}).get("provider"), "ticks": cfg.get("ticks"),
            "seed": cfg.get("random_seed"), "cost_usd": cost,
            "calls": last.get("llm_calls") if last.get("type") == "end" else None,
        })
    return sorted(out, key=lambda r: r["started"] or "", reverse=True)
