"""Read a run log and answer: did the personas behave differently?

python3 analyze.py                      # latest run: summary + interactions
python3 analyze.py logs/v0_....jsonl    # a specific run
python3 analyze.py --timeline           # every post, in order
python3 analyze.py --blind              # posts with names hidden: can you tell who's who?
python3 analyze.py --stance             # LLM-judged stance per agent, early/mid/late
python3 analyze.py --targets            # LLM judge: did replies go to the post they answer?
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
from collections import Counter, defaultdict

from loader import resolve

KINDS = ["post", "reply", "like", "repost", "follow", "none"]


def load(path: str) -> list:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def latest_log() -> str:
    logs = sorted(p for p in glob.glob(resolve("logs/*.jsonl")))
    if not logs:
        raise SystemExit("No logs yet. Run: python3 sim.py --mock")
    return max(logs, key=os.path.getmtime)


def agent_names(records) -> list:
    return [r["name"] for r in records if r["type"] == "agent"]


def summary(records) -> str:
    names = agent_names(records)
    woke = Counter(r["agent"] for r in records if r["type"] == "decision")
    slept = Counter(r["agent"] for r in records if r["type"] == "sleep")
    parse_err = Counter(
        r["agent"] for r in records if r["type"] == "decision" and r.get("parse_error")
    )
    llm_err = Counter(
        r["agent"] for r in records if r["type"] == "decision" and r.get("llm_error")
    )
    blocked = Counter(
        r["agent"] for r in records if r["type"] == "decision" and r.get("blocked")
    )
    modes = defaultdict(Counter)  # older logs have no modes; they show as "-"
    for r in records:
        if r["type"] == "decision" and r.get("mode"):
            modes[r["agent"]][r["mode"]] += 1
    done = defaultdict(Counter)
    failed = Counter()
    for r in records:
        if r["type"] != "applied":
            continue
        if r["ok"]:
            done[r["agent"]][r["action"]["action"]] += 1
        else:
            failed[r["agent"]] += 1
    for (
        n,
        c,
    ) in (
        llm_err.items()
    ):  # failed LLM calls are logged as "none"; don't count them as choices
        done[n]["none"] -= c
    for n, c in blocked.items():  # blocked choices are also logged as "none"
        done[n]["none"] -= c

    w = max(len(n) for n in names) + 2
    lines = ["Actions per agent", "-" * 80]
    lines.append(
        "agent".ljust(w)
        + "woke  "
        + "post/write/react  "
        + "".join(k.ljust(8) for k in KINDS)
        + "failed  blocked  unparsed  llm_err"
    )
    for n in names:
        row = n.ljust(w) + f"{woke[n]:>2}/{woke[n] + slept[n]:<3}"
        wr = f"{modes[n]['post']}/{modes[n]['write']}/{modes[n]['react']}" if modes[n] else "-"
        row += wr.ljust(18)
        row += "".join(str(done[n][k]).ljust(8) for k in KINDS)
        row += str(failed[n]).ljust(8) + str(blocked[n]).ljust(9) + str(parse_err[n]).ljust(10) + str(llm_err[n])
        lines.append(row)
    if sum(llm_err.values()):
        lines.append(
            f"Warning: {sum(llm_err.values())} turns lost to LLM errors; those agents did nothing through no choice of their own."
        )
    sparks = Counter(r.get("spark") for r in records if r["type"] == "decision" and r.get("mode") == "post")
    if sparks:
        lines.append("Post turns by spark: " + ", ".join(f"{k} {v}" for k, v in sparks.most_common()))
    lines.append(
        "post/write/react = turns of each kind (post turns write a new post; write turns may reply; react turns can't)"
    )
    lines.append(
        "failed = action broke a rule (e.g. reply blocked); blocked = model picked something not on its menu (wrong mode or a target not offered)"
    )
    lines += ["", interactions(records)]
    talk = topic_talk(records)
    if talk:
        lines += ["", talk]
    return "\n".join(lines)


def interactions(records, top=20) -> str:
    pairs = defaultdict(Counter)
    received = defaultdict(Counter)
    for r in records:
        if r["type"] == "applied" and r["ok"] and r.get("target_author"):
            pairs[(r["agent"], r["target_author"])][r["action"]["action"]] += 1
            received[r["target_author"]][r["action"]["action"]] += 1
    if not pairs:
        return "Interactions: none"
    ranked = sorted(pairs.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    shown = ranked if len(ranked) <= top else ranked[:top]
    title = "Interactions (who -> whom)" if shown is ranked else f"Top {top} of {len(ranked)} pairs (who -> whom)"
    lines = [title, "-" * 80]
    for (src, dst), c in shown:
        lines.append(
            f"{src} -> {dst}: " + ", ".join(f"{v} {k}" for k, v in c.most_common())
        )
    lines += ["", "Most interacted with (replies, likes, reposts, follows received)", "-" * 80]
    for name, c in sorted(received.items(), key=lambda kv: -sum(kv[1].values()))[:10]:
        lines.append(
            f"{name}: {sum(c.values())} = " + ", ".join(f"{v} {k}" for k, v in c.most_common())
        )
    return "\n".join(lines)


def post_topics(records):
    """(post id -> topic, topic -> Counter of actions). A post written from a news spark belongs
    to that story; other posts are matched by the stories' keywords, else "other". Replies,
    reposts and likes take the topic of the post they're aimed at, so a thread shares one topic."""
    stories = [sp for sp in records[0]["config"].get("scheduled_posts", []) if sp.get("topic")]

    def match(text):
        text = text.lower()
        hits = {sp["topic"]: sum(k in text for k in sp.get("keywords", [])) for sp in stories}
        best = max(hits, key=hits.get)
        return best if hits[best] else "other"

    topic_of, story_of = {}, {}
    talk = defaultdict(Counter)
    for r in records:
        if r["type"] == "scheduled_post":
            topic_of[r["post_id"]] = r.get("topic") or "other"
        elif r["type"] == "decision" and r.get("story_id"):
            story_of[(r["tick"], r["agent"])] = r["story_id"]
        elif r["type"] == "applied" and r["ok"]:
            kind = r["action"]["action"]
            if kind == "post":
                sid = story_of.get((r["tick"], r["agent"]))
                t = topic_of.get(sid) if sid else match(r["action"]["text"])
            elif kind in ("reply", "repost", "like"):
                t = topic_of.get(r["target_id"], "other")
            else:
                continue
            if r.get("post_id"):
                topic_of[r["post_id"]] = t
            talk[t][kind] += 1
    return topic_of, talk


def topic_talk(records) -> str:
    """What the agents talked about, per topic (see post_topics)."""
    stories = [sp for sp in records[0]["config"].get("scheduled_posts", []) if sp.get("topic")]
    if not stories:
        return ""
    _, talk = post_topics(records)
    order = [sp["topic"] for sp in stories]
    names = list(dict.fromkeys(order)) + ["other"]
    total = sum(sum(c[k] for k in ("post", "reply")) for c in talk.values()) or 1
    lines = ["Talk by topic (story posts by tick order; 'other' = not about any story)", "-" * 80,
             "topic".ljust(20) + "posts   replies likes   share of posts+replies"]
    for n in names:
        c = talk[n]
        written = c["post"] + c["reply"]
        lines.append(n.ljust(20) + str(c["post"]).ljust(8) + str(c["reply"]).ljust(8) + str(c["like"]).ljust(8)
                     + f"{100 * written // total}%")
    return "\n".join(lines)


def posts(records, agents_only=False) -> list:
    """Every post/reply/repost in order, as dicts."""
    names = set(agent_names(records))
    out = []
    for r in records:
        if r["type"] == "scheduled_post" and not agents_only:
            out.append(
                {
                    "id": r["post_id"],
                    "tick": r["tick"],
                    "author": r["author"],
                    "text": r["text"],
                    "kind": "post",
                }
            )
        elif (
            r["type"] == "applied"
            and r["ok"]
            and r.get("post_id")
            and r["agent"] in names
        ):
            out.append(
                {
                    "id": r["post_id"],
                    "tick": r["tick"],
                    "author": r["agent"],
                    "kind": r["action"]["action"],
                    "text": r["action"].get("text") or "",
                    "target_id": r.get("target_id"),
                }
            )
    return out


def timeline(records) -> str:
    lines = []
    for p in posts(records):
        if p["kind"] == "repost":
            lines.append(
                f"[t{p['tick']:02d}] {p['id']} @{p['author']} reposted {p['target_id']}"
            )
        else:
            prefix = f"(reply to {p['target_id']}) " if p["kind"] == "reply" else ""
            lines.append(
                f"[t{p['tick']:02d}] {p['id']} @{p['author']}: {prefix}{p['text']}"
            )
    return "\n".join(lines)


def blind(records, log_path) -> str:
    names = agent_names(records)
    letters = [f"#{i + 1}" for i in range(len(names))]
    shuffled = names[:]
    random.shuffle(shuffled)
    key = dict(zip(shuffled, letters))
    key_path = log_path.replace(".jsonl", "_blind_key.json")
    with open(key_path, "w") as f:
        json.dump({v: k for k, v in key.items()}, f, indent=2)
    lines = [f"Who is who? Personas: {', '.join(names)}", ""]
    for p in posts(records, agents_only=True):
        if p["kind"] != "repost":
            lines.append(f"{key[p['author']]}: {p['text']}")
    lines += ["", f"Answer key: {os.path.relpath(key_path)}"]
    return "\n".join(lines)


JUDGE_SYSTEM = "You are a careful annotator of social media posts. You answer with a single number only."
JUDGE_USER = """Topic: {topic}

Posts by one user:
{posts}

On a scale from -1 (strongly against) to +1 (strongly in favor), what is this user's stance on the topic? 0 means neutral or unclear. Answer with only the number."""


def stance(records, use_mock=False) -> str:
    from llm import LLM

    cfg = records[0]["config"]
    llm_cfg = {"provider": "mock", "model": "mock"} if use_mock else cfg["llm"]
    llm = LLM(llm_cfg, mock_seed=cfg["random_seed"] + 2)
    personas = {r["name"]: r["persona"] for r in records if r["type"] == "agent"}
    ticks = cfg["ticks"]
    windows = [
        ("early", 1, ticks // 3),
        ("mid", ticks // 3 + 1, 2 * ticks // 3),
        ("late", 2 * ticks // 3 + 1, ticks),
    ]

    by_agent = defaultdict(list)
    for p in posts(records, agents_only=True):
        if p["kind"] in ("post", "reply"):
            by_agent[p["author"]].append(p)

    w = max(len(n) for n in personas) + 2
    lines = [
        f"Stance on: {cfg['seed_topic']}  (persona start value in brackets)",
        "-" * 80,
    ]
    lines.append(
        "agent".ljust(w)
        + "start   "
        + "".join(f"{w[0]} (t{w[1]}-{w[2]})".ljust(16) for w in windows)
    )
    for name, persona in personas.items():
        row = name.ljust(w) + f"[{persona['stance']:+.1f}]  "
        for _, lo, hi in windows:
            texts = [p["text"] for p in by_agent[name] if lo <= p["tick"] <= hi]
            if not texts:
                row += "-".ljust(16)
                continue
            prompt = JUDGE_USER.format(
                topic=cfg["seed_topic"], posts="\n".join(f"- {t}" for t in texts)
            )
            raw = llm.complete(
                JUDGE_SYSTEM,
                prompt,
                hint={"kind": "judge", "stance": persona["stance"]},
            )
            m = re.search(r"-?\d+(?:\.\d+)?", raw)
            score = f"{max(-1.0, min(1.0, float(m.group()))):+.2f}" if m else "?"
            row += f"{score} ({len(texts)} posts)".ljust(16)
        lines.append(row)
    if use_mock or cfg["llm"]["provider"] == "mock":
        lines.append("(mock judge: these numbers are fake)")
    return "\n".join(lines)


TARGET_SYSTEM = "You match social media replies to the post they answer. You answer with a post id or the word none."
TARGET_USER = """These posts were in a user's feed:
{feed}

The user then wrote this reply:
"{reply}"

Which post is this reply answering? Answer with only the post id (like p12), or "none" if it fits none of them."""


def reply_targets(records, log_path, use_mock=False, show=12) -> str:
    """Did each reply go to the post it was meant for? An LLM judge sees the feed the agent saw
    and the reply text, and says which post it answers. A different pick suggests the model
    put the wrong id in target_id. A judge, not ground truth: read the listed cases."""
    from concurrent.futures import ThreadPoolExecutor
    from llm import LLM

    cfg = records[0]["config"]
    llm_cfg = {"provider": "mock", "model": "mock"} if use_mock else cfg["llm"]
    llm = LLM(llm_cfg, mock_seed=cfg["random_seed"] + 5)
    with open(log_path.replace(".jsonl", "_world.json")) as f:
        text = {p["id"]: (p["author"], p["text"]) for p in json.load(f)["posts"]}
    replies = [
        r for r in records
        if r["type"] == "decision" and r["action"]["action"] == "reply" and not r.get("blocked") and r.get("feed_ids")
    ]

    def judge(r):
        feed = "\n".join(f'[{i}] @{text[i][0]}: "{text[i][1]}"' for i in r["feed_ids"] if text[i][1])
        raw = llm.complete(TARGET_SYSTEM, TARGET_USER.format(feed=feed, reply=r["action"]["text"]),
                           hint={"kind": "target", "target": r["action"]["target_id"], "feed": r["feed_ids"]})
        m = re.search(r"p\d+|none", raw.lower())
        return m.group() if m else "?"

    workers = 1 if llm_cfg["provider"] == "mock" else cfg.get("parallel_calls", 1)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        picks = list(pool.map(judge, replies))

    # A different post on the same story is usually ambiguity (five posts argue the same point),
    # not an error. A different topic is the real slip: the reply landed under the wrong post.
    topic_of, _ = post_topics(records)
    same, ambiguous, unclear, wrong, none = [], [], [], [], []
    for r, p in zip(replies, picks):
        t = r["action"]["target_id"]
        if p == t:
            same.append(r)
        elif p not in text:
            none.append(r)
        elif topic_of.get(p, "other") == topic_of.get(t, "other") != "other":
            ambiguous.append((r, p))
        elif topic_of.get(p, "other") == topic_of.get(t, "other") == "other":
            unclear.append((r, p))
        else:
            wrong.append((r, p))
    n = len(replies) or 1
    pct = lambda xs: f"{len(xs)} ({100 * len(xs) // n}%)"
    lines = [
        "Reply targets, checked by an LLM judge", "-" * 80,
        f"{len(replies)} replies.",
        f"  judge picks the same post:                     {pct(same)}",
        f"  another post on the same story (ambiguous):    {pct(ambiguous)}",
        f"  another off-story post (can't tell by topic):  {pct(unclear)}",
        f"  a post on a DIFFERENT topic (likely wrong id): {pct(wrong)}",
        f"  fits no post in the feed:                      {pct(none)}",
    ]
    other = wrong + unclear
    if other:
        lines += ["", f"Likely wrong target (first {min(show, len(other))} of {len(other)}; read them, the judge can be wrong):"]
        short = lambda s: s if len(s) <= 90 else s[:89] + "…"
        for r, p in other[:show]:
            t = r["action"]["target_id"]
            lines += [
                f"[t{r['tick']:02d}] @{r['agent']}: \"{short(r['action']['text'])}\"",
                f"    sent to {t} @{text[t][0]}: \"{short(text[t][1])}\"",
                f"    judge: {p} @{text[p][0]}: \"{short(text[p][1])}\"" if p in text else f"    judge: {p}",
            ]
    if use_mock or cfg["llm"]["provider"] == "mock":
        lines.append("(mock judge: these numbers are fake)")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Analyze a simulation log.")
    ap.add_argument("log", nargs="?", help="path to a .jsonl log (default: latest)")
    ap.add_argument("--timeline", action="store_true")
    ap.add_argument("--blind", action="store_true")
    ap.add_argument(
        "--stance",
        action="store_true",
        help="score stance with the run's LLM (costs a few calls)",
    )
    ap.add_argument(
        "--targets",
        action="store_true",
        help="check reply targets with the run's LLM (one small call per reply)",
    )
    ap.add_argument(
        "--mock", action="store_true", help="use the mock judge for --stance/--targets"
    )
    args = ap.parse_args(argv)

    path = args.log or latest_log()
    records = load(path)
    print(f"Run: {os.path.relpath(path)}\n")
    if args.blind:
        print(blind(records, path))
        return
    print(summary(records))
    if args.timeline:
        print("\nTimeline\n" + "-" * 80 + "\n" + timeline(records))
    if args.stance:
        print("\n" + stance(records, args.mock))
    if args.targets:
        print("\n" + reply_targets(records, path, args.mock))


if __name__ == "__main__":
    main()
