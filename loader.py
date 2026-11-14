"""Loading config, personas and prompt templates from disk, with validation."""
from __future__ import annotations

import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

TRAITS = ["attention_seeking", "agreeableness", "judgmental", "curiosity", "conformity"]


def resolve(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(HERE, path)


def load_dotenv(path: str = ".env"):
    """Copy KEY=VALUE lines from .env into os.environ. Variables already set in
    the shell win, so `export X=...` still overrides the file."""
    full = resolve(path)
    if not os.path.exists(full):
        return
    with open(full) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)


def load_json(path: str):
    with open(resolve(path)) as f:
        return json.load(f)


def load_config(path: str) -> dict:
    return load_json(path)


def story_topics(cfg: dict) -> dict:
    """topic -> {"opinion_on", "keywords", "sides"} for every topic among the scheduled stories.
    The seed topic's statement is cfg["seed_topic"]; persona["stance"] is the view on it."""
    topics = {}
    for sp in cfg.get("scheduled_posts", []):
        t = sp.get("topic")
        if t and t not in topics:
            topics[t] = {"opinion_on": sp.get("opinion_on") or cfg["seed_topic"], "keywords": sp.get("keywords", []),
                         "sides": sp.get("opinion_sides")}
    return topics


def check_opinions(personas: list, topics: dict):
    for p in personas:
        unknown = set(p.get("opinions", {})) - set(topics)
        if unknown:
            raise ValueError(f"persona {p['name']}: opinions on unknown topics {sorted(unknown)}; known: {sorted(topics)}")


def _check_range(name: str, key: str, value, lo: float, hi: float):
    if not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise ValueError(f"persona {name}: {key} must be a number in [{lo}, {hi}], got {value!r}")


def validate_persona(p: dict) -> dict:
    name = p.get("name", "?")
    for key in ("name", "bio", "interests", "traits", "stance", "wake_prob"):
        if key not in p:
            raise ValueError(f"persona {name}: missing '{key}'")
    for trait in TRAITS:
        if trait not in p["traits"]:
            raise ValueError(f"persona {name}: missing trait '{trait}'")
        _check_range(name, f"traits.{trait}", p["traits"][trait], 0, 1)
    unknown = set(p["traits"]) - set(TRAITS)
    if unknown:
        raise ValueError(f"persona {name}: unknown traits {sorted(unknown)}")
    _check_range(name, "stance", p["stance"], -1, 1)
    _check_range(name, "wake_prob", p["wake_prob"], 0, 1)
    if "hobbies" in p and not (isinstance(p["hobbies"], list) and all(isinstance(h, str) for h in p["hobbies"])):
        raise ValueError(f"persona {name}: hobbies must be a list of strings")
    for topic, value in (p.get("opinions") or {}).items():
        _check_range(name, f"opinions.{topic}", value, -1, 1)
    if "voice" in p and not isinstance(p["voice"], str):
        raise ValueError(f"persona {name}: voice must be a string")
    if p.get("write_prob") is not None:  # optional override; otherwise derived from attention_seeking
        _check_range(name, "write_prob", p["write_prob"], 0, 1)
    return p


def load_personas(directory: str) -> list:
    files = sorted(glob.glob(os.path.join(resolve(directory), "*.json")))
    if not files:
        raise ValueError(f"no persona files found in {directory}")
    personas = [validate_persona(load_json(f)) for f in files]
    names = [p["name"] for p in personas]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate persona names: {names}")
    return personas


def load_templates() -> dict:
    out = {}
    for key in ("system", "tick", "post"):
        with open(resolve(f"prompts/{key}.txt")) as f:
            out[key] = f.read()
    return out
