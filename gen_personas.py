"""Generate a population of personas for bigger runs. Free: no LLM calls.

    python3 gen_personas.py                # personas/ ends up with 30 agents
    python3 gen_personas.py --count 50 --seed 7

Each persona starts from an archetype (a role that has a reason to care about the
seed topic) and gets its traits, stance and wake_prob jittered, so two agents with
the same role still behave differently. Generated files are marked "generated": true.
Rerunning replaces only those; hand-written personas are never touched and count
toward the total.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random

from loader import TRAITS, load_config, resolve, story_topics, validate_persona

# role -> bios, interests, trait centers (attention, agreeable, judgmental, curiosity, conformity), stance, wake
ARCHETYPES = {
    "skeptic": (
        ["Senior engineer who has cleaned up after too many 'revolutionary' tools.",
         "Staff engineer at a bank. Has opinions about every framework released since 2010."],
        ["software engineering", "code quality", "tech history"],
        (0.4, 0.25, 0.85, 0.35, 0.15), -0.6, 0.55),
    "founder": (
        ["Founder of a two-person AI startup. Ships fast, pivots faster.",
         "Ex-consultant turned founder, building 'the Stripe of AI agents'."],
        ["startups", "AI tools", "fundraising"],
        (0.85, 0.55, 0.5, 0.4, 0.7), 0.65, 0.7),
    "student": (
        ["Final-year CS student applying to 80 internships and hearing back from none.",
         "First-year CS student. Still deciding if this was the right major."],
        ["learning to code", "internships", "student life"],
        (0.2, 0.8, 0.2, 0.8, 0.6), -0.1, 0.4),
    "junior": (
        ["Junior web developer, one year into a first job, nervous about the next layoff round.",
         "Self-taught developer who landed a first job last spring."],
        ["career growth", "web development", "job market"],
        (0.35, 0.65, 0.3, 0.6, 0.55), -0.35, 0.5),
    "researcher": (
        ["ML researcher who reads the benchmarks, not the press releases.",
         "PhD student working on code-generation models."],
        ["machine learning", "benchmarks", "AI evaluation"],
        (0.35, 0.5, 0.55, 0.85, 0.2), 0.1, 0.45),
    "recruiter": (
        ["Tech recruiter. Sees hiring trends months before they hit the news.",
         "Talent lead at a mid-size SaaS company."],
        ["hiring", "tech careers", "job market"],
        (0.55, 0.8, 0.3, 0.5, 0.75), 0.2, 0.5),
    "investor": (
        ["Angel investor who writes long threads about 'the future of work'.",
         "Partner at a seed fund. Every deck this year has 'agents' on slide two."],
        ["venture capital", "AI startups", "future of work"],
        (0.75, 0.4, 0.75, 0.35, 0.5), 0.7, 0.55),
    "organizer": (
        ["Organizer with a tech workers' union. Reads every layoff announcement twice.",
         "Former QA engineer, now campaigns for tech worker protections."],
        ["tech labor", "unions", "worker rights"],
        (0.6, 0.2, 0.85, 0.4, 0.1), -0.8, 0.6),
    "manager": (
        ["Engineering manager who has to decide next year's headcount.",
         "Director of engineering at a logistics company. Budget season is coming."],
        ["engineering management", "team building", "productivity"],
        (0.4, 0.6, 0.5, 0.55, 0.5), 0.0, 0.45),
    "teacher": (
        ["Coding bootcamp instructor worried about where the graduates will land.",
         "CS lecturer rewriting the intro course for the third time this year."],
        ["teaching", "bootcamps", "tech careers"],
        (0.4, 0.8, 0.4, 0.75, 0.35), -0.4, 0.45),
    "journalist": (
        ["Tech reporter chasing the story behind the press release.",
         "Writes a weekly newsletter on AI and the job market."],
        ["tech news", "AI policy", "startups"],
        (0.6, 0.45, 0.45, 0.85, 0.3), 0.0, 0.55),
    "maintainer": (
        ["Open-source maintainer drowning in AI-generated pull requests.",
         "Maintains a popular testing library in their spare time."],
        ["open source", "code review", "developer tools"],
        (0.35, 0.3, 0.8, 0.45, 0.2), -0.5, 0.45),
    "influencer": (
        ["Coding YouTuber, 200k subscribers. Thumbnails are mostly shocked faces.",
         "Posts daily 'AI tools you need to know' threads."],
        ["developer content", "AI tools", "productivity"],
        (0.95, 0.65, 0.4, 0.35, 0.85), 0.45, 0.75),
}

# How a persona writes. Each voice must state its hashtag and emoji habit: the model fills any
# habit left unsaid with its own default (hashtags and emoji everywhere), and overuses any habit
# described as "sometimes".
VOICES = [
    "All lowercase, short and casual.",
    "Terse and dry. Short sentences.",
    "Chatty, long run-on sentences, the occasional typo.",
    "Plain and matter-of-fact, like a text to a friend.",
    "Deadpan and sarcastic, mostly one-liners.",
    "Warm and upbeat, with an exclamation mark here and there.",
    "Careful and precise. Full sentences, no slang.",
    "Internet slang and abbreviations (tbh, ngl, imo), no capital letters at the start.",
    "Talks in fragments, with asides in parentheses.",
    "A bit formal and stiff.",
]
# Life outside work, so agents have something besides the tech news to post about.
HOBBIES = [
    "cooking", "football", "cricket", "hiking", "video games", "indie music", "films", "gardening",
    "chess", "travel", "running", "their cat", "their dog", "coffee", "anime", "photography",
    "fantasy novels", "board games", "basketball", "baking", "cycling", "stargazing",
    "true crime podcasts", "thrift shopping", "reality TV", "climbing",
]
HASHTAG_HABITS = {"Never uses hashtags.": 7, "At most one hashtag, and rarely.": 2}
EMOJI_HABITS = {"No emoji.": 5, "At most one emoji, and rarely.": 3, "Likes emoji.": 1}
# Some roles really do write like a personal brand.
ROLE_VOICES = {
    "influencer": "Writes like a personal brand: hooks, emoji, hashtags, asks followers to weigh in.",
}

NAMES = [
    "aarav", "mei", "tomas", "fatima", "jonas", "priya", "diego", "hana", "kwame",
    "sofia", "ivan", "amara", "lucas", "noor", "kenji", "zara", "mateo", "ines",
    "omar", "yuki", "elena", "samir", "chloe", "rohan", "nadia", "felix", "ayesha",
    "ben", "lin", "carlos", "dara", "emil", "gita", "hugo", "isla", "jae",
]


def clip(x, lo=0.0, hi=1.0):
    return round(max(lo, min(hi, x)), 2)


def with_habits(voice: str, rng) -> str:
    """Add a hashtag and an emoji habit, unless the voice already states one."""
    for word, habits in (("hashtag", HASHTAG_HABITS), ("emoji", EMOJI_HABITS)):
        if word not in voice.lower():
            voice += " " + rng.choices(list(habits), weights=list(habits.values()))[0]
    return voice


OPINIONS_PER_PERSONA = 3  # on stories other than the seed topic


def pick_opinions(topics: list, rng) -> dict:
    """A few strong-ish views on random stories, either side: something to argue about."""
    picked = rng.sample(topics, min(OPINIONS_PER_PERSONA, len(topics)))
    return {t: round(rng.choice([-1, 1]) * rng.uniform(0.3, 1.0), 2) for t in picked}


def make(name, role, rng, variant, voice, hobbies, opinions):
    bios, interests, centers, stance, wake = ARCHETYPES[role]
    return validate_persona({
        "name": f"{name}_{role}",
        "bio": bios[variant % len(bios)],
        "interests": interests,
        "hobbies": hobbies,
        "voice": voice,
        "traits": {t: clip(rng.gauss(c, 0.12)) for t, c in zip(TRAITS, centers)},
        "stance": clip(rng.gauss(stance, 0.15), -1, 1),
        "opinions": opinions,
        "wake_prob": clip(rng.gauss(wake, 0.08), 0.2, 0.85),
        "generated": True,
    })


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate personas for a bigger run.")
    ap.add_argument("--count", type=int, default=30, help="total agents, hand-written ones included")
    ap.add_argument("--out", default="personas")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)

    out = resolve(args.out)
    os.makedirs(out, exist_ok=True)
    originals = []
    for f in sorted(glob.glob(os.path.join(out, "*.json"))):
        with open(f) as fh:
            if json.load(fh).get("generated"):
                os.remove(f)  # an earlier generated persona; replaced below
            else:
                originals.append(f)
    if args.count < len(originals):
        raise SystemExit(f"--count {args.count} is less than the {len(originals)} hand-written personas")

    rng = random.Random(args.seed)
    names = rng.sample(NAMES, args.count - len(originals))
    roles = list(ARCHETYPES)
    rng.shuffle(roles)
    # Voices get their own RNG, so adding them didn't change anyone's traits.
    voice_rng = random.Random(args.seed + 100)
    hobby_rng = random.Random(args.seed + 200)  # same for hobbies
    opinion_rng = random.Random(args.seed + 300)  # and opinions
    cfg = load_config("config.json")
    other_topics = [t for t, v in story_topics(cfg).items() if v["opinion_on"] != cfg["seed_topic"]]
    personas = []
    for i, name in enumerate(names):
        role = roles[i % len(roles)]
        voice = ROLE_VOICES.get(role) or with_habits(voice_rng.choice(VOICES), voice_rng)
        p = make(name, role, rng, i // len(roles), voice, hobby_rng.sample(HOBBIES, 2),
                 pick_opinions(other_topics, opinion_rng))
        personas.append(p)
        with open(os.path.join(out, p["name"] + ".json"), "w") as f:
            f.write(json.dumps(p, indent=2) + "\n")

    print(f"{args.out}/ now has {len(originals)} hand-written + {len(personas)} generated personas\n")
    print("name".ljust(22) + "attn agree judg  cur   conf  stance wake")
    for p in personas:
        t = p["traits"]
        print(p["name"].ljust(22) + "".join(f"{t[k]:<6.2f}" for k in TRAITS)[:-1] + f" {p['stance']:+.2f}  {p['wake_prob']:.2f}")
    calls = sum(p["wake_prob"] for p in personas) + sum(
        json.load(open(f))["wake_prob"] for f in originals)
    print(f"\nExpected LLM calls per tick: about {calls:.0f}")


if __name__ == "__main__":
    main()
