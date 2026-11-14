"""Offline stand-in for an LLM, for testing the pipeline without API calls.

It picks actions with probabilities driven by the persona's traits and fills
text from canned phrases. It is a plumbing test, not a simulation result.
"""
from __future__ import annotations

import json
import random

PRO = [
    "This is the future. Juniors who learn to drive AI agents will be fine, the rest won't.",
    "NovaCode is just saying out loud what every startup is already thinking.",
    "Adapt or get left behind. AI agents shipping code is not a fad.",
]
ANTI = [
    "Replace all your juniors and in 5 years you have zero seniors. Brilliant plan.",
    "Show me the AI agent debugging a prod outage at 3am. I'll wait.",
    "Every hype cycle has its NovaCode. This one will age badly.",
]
NEUTRAL = [
    "Not sure what to make of this NovaCode thing. Anyone actually used it?",
    "Curious how much of this is real vs a press release.",
    "Kind of worried, kind of curious. What does this mean for people starting out?",
]
AGREE = ["Totally agree with this.", "Love this take, well said!", "So true, thanks for posting this."]
CURIOUS = ["Wait, how would that actually work?", "Interesting, what makes you say that?", "Do you have a source? Genuinely curious."]
DISAGREE = ["No. This is just wrong.", "Did you think about this for more than 5 seconds?", "Hard disagree. Where's the evidence?"]


class MockModel:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def respond(self, system: str, user: str, hint: dict | None) -> str:
        hint = hint or {}
        if hint.get("kind") == "judge":
            s = hint.get("stance", 0.0) + self.rng.uniform(-0.2, 0.2)
            return f"{max(-1.0, min(1.0, s)):.2f}"
        if hint.get("kind") == "target":  # mostly agree, sometimes pick another post or none
            r = self.rng.random()
            return hint["target"] if r < 0.85 else ("none" if r < 0.9 else self.rng.choice(hint["feed"]))
        if hint.get("kind") == "post":
            s = hint["persona"]["stance"]
            text = self.rng.choice(PRO if s > 0.3 else ANTI if s < -0.3 else NEUTRAL)
            return json.dumps({"text": text, "reason": f"mock post, spark {hint.get('spark')}"})
        return self._action(hint["persona"], hint.get("feed", []), hint.get("allowed"), hint.get("targets"),
                            hint.get("reply_labels"))

    def _action(self, persona: dict, feed: list, allowed=None, targets=None, reply_labels=None) -> str:
        t = persona["traits"]
        has_feed = 1.0 if feed else 0.0
        weights = {
            "post": 0.15 + 0.9 * t["attention_seeking"],
            "reply": has_feed * (0.1 + 0.5 * t["judgmental"] + 0.4 * t["curiosity"]),
            "like": has_feed * (0.1 + 0.9 * t["agreeableness"]),
            "repost": has_feed * (0.05 + 0.4 * t["attention_seeking"] * t["conformity"]),
            "follow": has_feed * (0.05 + 0.3 * t["curiosity"]),
            "none": 0.9 - 0.5 * t["attention_seeking"],
        }
        if allowed:
            weights = {k: w for k, w in weights.items() if k in allowed}
        kind = self.rng.choices(list(weights), weights=list(weights.values()))[0]
        target, text = None, None
        if kind == "reply" and reply_labels:
            target = self.rng.choice(list(reply_labels))  # answers with a letter, like the real prompt asks
        elif targets and targets.get(kind):
            target = self.rng.choice(targets[kind])
        elif kind in ("reply", "like", "repost"):
            target = self.rng.choice(feed).id
        elif kind == "follow":
            target = self.rng.choice(feed).author
        if kind == "post":
            s = persona["stance"]
            text = self.rng.choice(PRO if s > 0.3 else ANTI if s < -0.3 else NEUTRAL)
        elif kind == "reply":
            r = self.rng.random()
            text = self.rng.choice(AGREE if r < t["agreeableness"] else CURIOUS if r < t["agreeableness"] + t["curiosity"] else DISAGREE)

        out = json.dumps({"action": kind, "target_id": target, "text": text, "reason": f"mock picked {kind}"})
        # Real models often wrap JSON or add chatter; make sure the parser copes.
        r = self.rng.random()
        if r < 0.05:
            out = "```json\n" + out + "\n```"
        elif r < 0.07:
            out = "Sure! Here's my action: " + out
        return out
