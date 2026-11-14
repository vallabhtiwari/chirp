"""Run one simulation.

    python3 sim.py                 # uses config.json and the real model
    python3 sim.py --mock          # offline, no API calls (plumbing test)
    python3 sim.py --ticks 5       # shorter run

Per tick: scheduled posts appear, a few agents are picked to post (weighted by
attention_seeking), the rest act in shuffled order (each wakes with probability
wake_prob), then all actions are applied at once. Everything goes to
logs/<run>_<timestamp>.jsonl so any run can be replayed and analyzed later.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor

import analyze
from agent import NONE_ACTION, Agent
from llm import LLM, LLMError, QuotaExhausted
from loader import check_opinions, load_config, load_personas, load_templates, resolve, story_topics
from world import World

MAX_CONSECUTIVE_LLM_ERRORS = 5


def post_weight(agent) -> float:
    """How likely an agent is to get the urge to post: mostly attention_seeking, never zero."""
    return 0.05 + agent.persona["traits"]["attention_seeking"]


def poisson(rng, mean: float) -> int:
    """Random count with the given average (Knuth's method; fine for small means)."""
    limit, k, p = math.exp(-mean), 0, rng.random()
    while p > limit:
        k += 1
        p *= rng.random()
    return k


def pick_posters(agents, mean: float, rng) -> list:
    """This tick's posters: about `mean` of them, drawn without replacement by post_weight."""
    pool, picked = list(agents), []
    for _ in range(min(poisson(rng, mean), len(pool))):
        a = rng.choices(pool, weights=[post_weight(x) for x in pool])[0]
        pool.remove(a)
        picked.append(a)
    return picked


def describe(tick, agent, action, result, reason_too=False, mode=None) -> str:
    kind = action["action"]
    head = f"[t{tick:02d}] @{agent}" + (f" [{mode}]" if mode else "")
    if not result.get("ok"):
        return f"{head} !! {kind} failed: {result.get('error')}"
    if kind == "post":
        line = f'{head} posted {result["post_id"]}: "{action["text"]}"'
    elif kind == "reply":
        line = f'{head} replied to {result["target_id"]} (@{result["target_author"]}) -> {result["post_id"]}: "{action["text"]}"'
    elif kind in ("like", "repost"):
        verb = "liked" if kind == "like" else "reposted"
        line = f"{head} {verb} {result['target_id']} (@{result['target_author']})"
    elif kind == "follow":
        line = f"{head} followed @{result['target_author']}"
    else:
        line = f"{head} did nothing"
    if reason_too and action.get("reason"):
        line += f"   # {action['reason']}"
    return line


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the agent social network simulation.")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--mock", action="store_true", help="use the offline mock model")
    ap.add_argument("--ticks", type=int, help="override number of ticks")
    ap.add_argument("--reasons", action="store_true", help="print each agent's private reason")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.mock:
        cfg["llm"] = {"provider": "mock", "model": "mock"}
    if args.ticks is not None:
        cfg["ticks"] = args.ticks

    personas = load_personas(cfg["personas_dir"])
    templates = load_templates()
    topics = story_topics(cfg)
    check_opinions(personas, topics)
    agents = [Agent(p, templates, cfg["seed_topic"], cfg["memory_size"], cfg["random_seed"], topics) for p in personas]

    scheduled = {}
    for sp in cfg.get("scheduled_posts", []):
        scheduled.setdefault(sp["tick"], []).append(sp)
    world = World([a.name for a in agents] + sorted({sp["author"] for sp in cfg.get("scheduled_posts", [])}))

    try:
        llm = LLM(cfg["llm"], mock_seed=cfg["random_seed"] + 1)
    except LLMError as e:
        sys.exit(f"LLM setup failed: {e}")

    # The scheduler has its own RNG so who-wakes-when is identical across models.
    rng = random.Random(cfg["random_seed"])
    # Write/react modes get their own RNG, so adding them didn't change who wakes when.
    mode_rng = random.Random(cfg["random_seed"] + 3)
    # Post turns too, so who-posts-when and their sparks are also identical across models.
    post_rng = random.Random(cfg["random_seed"] + 4)
    posts_per_tick = cfg.get("posts_per_tick", 2)

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(resolve("logs"), exist_ok=True)
    log_path = resolve(f"logs/{cfg['run_name']}_{stamp}.jsonl")
    log_file = open(log_path, "w")

    def log(record):
        log_file.write(json.dumps(record) + "\n")
        log_file.flush()

    log({"type": "config", "config": cfg, "started": dt.datetime.now().isoformat()})
    for a in agents:
        log({"type": "agent", "name": a.name, "persona": a.persona, "system_prompt": a.system_prompt})

    # The mock shares one RNG, so it runs one call at a time to stay reproducible.
    workers = 1 if cfg["llm"]["provider"] == "mock" else cfg.get("parallel_calls", 1)
    pool = ThreadPoolExecutor(max_workers=max(1, workers))

    print(f"Running {len(agents)} agents for {cfg['ticks']} ticks with model {cfg['llm'].get('model')} ({cfg['llm']['provider']}, {workers} parallel calls)")
    for a in agents:
        source = "set in persona" if a.persona.get("write_prob") is not None else "from attention_seeking"
        print(f"  @{a.name}: wakes {a.wake_prob:.0%} of ticks, writes on {a.write_prob:.0%} of wakes ({source})")
    total = sum(post_weight(a) for a in agents)
    eager = sorted(agents, key=post_weight, reverse=True)
    print(f"  Post turns: about {posts_per_tick} per tick. Most eager: "
          + ", ".join(f"@{a.name} {post_weight(a) / total:.0%}" for a in eager[:3])
          + f"; least: @{eager[-1].name} {post_weight(eager[-1]) / total:.0%} of picks")
    print(f"Log: {os.path.relpath(log_path)}\n")

    consecutive_errors = 0
    try:
        for tick in range(cfg["ticks"] + 1):
            for sp in scheduled.get(tick, []):
                post = world.add_post(sp["author"], sp["text"], tick)
                world.news.append(post.id)
                log({"type": "scheduled_post", "tick": tick, "author": sp["author"], "post_id": post.id,
                     "text": post.text, "topic": sp.get("topic")})
                print(f'[t{tick:02d}] @{sp["author"]} posted {post.id}: "{post.text}"')
            if tick == 0:
                continue  # tick 0 is only for seeding the world

            order = agents[:]
            rng.shuffle(order)
            # A picked poster gets a post turn instead of its normal turn, awake or not:
            # the urge to post is what got it to open the app.
            posters = pick_posters(agents, posts_per_tick, post_rng)
            awake = []
            for agent in order:
                woke = rng.random() < agent.wake_prob
                if woke:
                    replied = world.replied_to_since(agent.name, agent.last_turn)
                    p_write = agent.write_chance(replied)
                    # Rolled even for posters, so mode_rng stays in step with who woke.
                    mode = "write" if mode_rng.random() < p_write else "react"
                if agent in posters:
                    turn = agent.roll_post_turn(world, tick, post_rng)
                    awake.append((agent, "post", turn, None, None))
                elif woke:
                    awake.append((agent, mode, None, p_write, replied))
                else:
                    log({"type": "sleep", "tick": tick, "agent": agent.name})

            # The world doesn't change until the end of the tick, so all awake agents can call
            # the model at once. Results come back in `order`, so logs stay in the same order.
            def decide(item):
                agent, mode, turn = item[0], item[1], item[2]
                try:
                    return agent.decide(world, tick, llm, cfg["feed_size"], mode, turn), None
                except LLMError as e:
                    return None, e

            decisions = []
            for (agent, mode, turn, p_write, replied), (rec, err) in zip(awake, pool.map(decide, awake)):
                if err is None:
                    consecutive_errors = 0
                elif isinstance(err, QuotaExhausted):
                    raise SystemExit(f"\nStopping at tick {tick}: {err}\nThe partial run is still logged and can be analyzed.")
                else:
                    consecutive_errors += 1
                    rec = {"tick": tick, "agent": agent.name, "mode": mode, "action": dict(NONE_ACTION), "llm_error": str(err)}
                    print(f"[t{tick:02d}] @{agent.name} !! LLM error: {err}")
                    if consecutive_errors >= MAX_CONSECUTIVE_LLM_ERRORS:
                        raise SystemExit(f"Stopping: {consecutive_errors} LLM errors in a row.")
                if mode == "post":
                    rec["spark"] = turn["spark"]
                else:
                    rec["p_write"] = round(p_write, 2)
                    rec["replied_to"] = replied
                if rec.get("fixed_target"):
                    print(f"[t{tick:02d}] @{agent.name} [{mode}] (note: target fixed {rec['fixed_target']})")
                if rec.get("blocked"):
                    print(f"[t{tick:02d}] @{agent.name} [{mode}] !! blocked: {rec['blocked']} wasn't on this turn's menu, treated as none")
                if rec.get("parse_error"):
                    print(f"[t{tick:02d}] @{agent.name} !! could not parse response ({rec['parse_error']}), treated as none")
                log({"type": "decision", **rec})
                label = f"post: {turn['spark']}" if mode == "post" else mode
                decisions.append((agent, rec["action"], mode, label))

            # Apply everything at the end of the tick, in the same shuffled order.
            for agent, action, mode, label in decisions:
                result = world.apply(agent.name, action, tick)
                agent.remember(tick, action, result)
                log({"type": "applied", "tick": tick, "agent": agent.name, "mode": mode, "action": action, **result})
                print(describe(tick, agent.name, action, result, args.reasons, label))
    finally:
        pool.shutdown(cancel_futures=True)
        log({"type": "end", "ended": dt.datetime.now().isoformat(), "llm_calls": llm.calls, "usage": llm.usage})
        log_file.close()
        world_path = log_path.replace(".jsonl", "_world.json")
        with open(world_path, "w") as f:
            json.dump(world.to_dict(), f, indent=2)

    tokens = f", {llm.usage['input_tokens']:,} input + {llm.usage['output_tokens']:,} output tokens" if llm.usage["input_tokens"] else ""
    price = cfg["llm"].get("usd_per_million_tokens")
    if tokens and price:
        cost = (llm.usage["input_tokens"] * price["input"] + llm.usage["output_tokens"] * price["output"]) / 1e6
        tokens += f" (about ${cost:.3f} at the config's price)"
    print(f"\nDone. {llm.calls} LLM calls{tokens}. Final world: {os.path.relpath(world_path)}\n")
    print(analyze.summary(analyze.load(log_path)))


if __name__ == "__main__":
    main()
