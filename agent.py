"""An agent = a fixed character sheet + a short rolling memory.

The prompt is never hand-written per agent: one template, rendered from the
sheet. Trait numbers become behavioral sentences, because small models follow
"you push back on claims" far better than "judgmental: 0.9".
"""

from __future__ import annotations

import json
import random
from string import Template

VALID_ACTIONS = {"post", "reply", "like", "repost", "follow", "none"}
NONE_ACTION = {"action": "none", "target_id": None, "text": None, "reason": ""}

# Code decides WHEN an agent writes; the model decides WHAT it does with the turn.
# Each wake rolls a mode: "write" allows replies, "react" doesn't. New posts never come from
# these turns: they come from separate "post" turns (see SPARKS), because a model that sees a
# feed full of posts replies to them instead of posting.
MODE_ACTIONS = {
    "write": ["reply", "like", "repost", "follow", "none"],
    "react": ["like", "repost", "follow", "none"],
}
MODE_TEXT = {
    "write": "You have time to write this turn. These posts caught your eye:\n{eye}\nYou can reply to one of them, or just react if none is worth replying to.",
    "write_no_reply": "You have time to write this turn, but there's nothing you can reply to right now. You can react to posts or do nothing.",
    "react": "You're only scrolling this turn, not writing. You can react to posts or do nothing. You cannot reply.",
}
ACTION_RULES = {
    "reply": '- reply: "target_id" is the letter of the post that caught your eye that you are answering ({targets}). "text" required.',
    "like": '- like: "target_id" must be one of these posts: {targets}. "text" null.',
    "repost": '- repost: "target_id" is a post id from your feed, "text" null.',
    "follow": '- follow: "target_id" is a username from your feed, without the @. "text" null.',
    "none": '- none: do nothing this tick. "target_id" and "text" null.',
}
REPLY_BOOST = 0.2  # extra write chance when someone replied to you since your last turn

# On a write turn only a few posts "catch your eye", and only those can be replied to. People
# don't weigh a whole feed before replying; they react to what they happen to notice. Code picks
# them (random, weighted below), so the model can't always pick the hottest argument.
EYE_CATCH = 3
# Eye-catchers are offered as A, B, C, not post ids: with hundreds of posts, the model mixed up
# nearby ids (p235 for p245) and ~3% of replies landed under the wrong post.
LABELS = "ABCDEFGH"
EYE_WEIGHTS = {"base": 1.0, "replies_to_you": 3.0, "interest": 2.0, "news": 1.0, "per_like": 0.2}

# A post turn starts from a spark = a form (how) + a subject (about what), picked by code so
# posts vary. "news" posts react to one of the recent stories (any topic); the rest are about the
# agent's own life, which models drift away from unless told. Categories only, never example
# sentences, because models copy examples word for word.
FORMS = {
    "thought": "a passing thought",
    "question": "a question you want people to answer",
    "complaint": "a small complaint",
    "hot_take": "a strong opinion",
    "joke": "something meant to be funny",
}
SUBJECTS = {
    "news": "that story",
    "work": "{interest}",
    "hobby": "{hobby}",
    "day": "something that happened in your day",
    "anything": "whatever happens to be on your mind right now, big or small",
}
SUBJECT_WEIGHTS = {"news": 1.5, "work": 1.5, "hobby": 1.5, "day": 1.0, "anything": 1.0}


def form_weights(traits: dict) -> dict:
    """Every form is possible for everyone; traits tilt the odds."""
    return {
        "thought": 1.0,
        "question": 0.3 + 1.5 * traits["curiosity"],
        "complaint": 0.3 + 1.2 * (1 - traits["agreeableness"]),
        "hot_take": 0.3 + 1.5 * traits["judgmental"],
        "joke": 0.3 + 0.8 * traits["attention_seeking"],
    }


DEFAULT_VOICE = "Casual and plain, like most people on Chirp."


def base_write_prob(persona: dict) -> float:
    """persona["write_prob"] if set, else derived from attention_seeking (0 -> 0.1, 1 -> 0.8)."""
    if persona.get("write_prob") is not None:
        return persona["write_prob"]
    return 0.1 + 0.7 * persona["traits"]["attention_seeking"]

# trait -> (low, mid, high) descriptions. Each one describes something you can see in posts.
TRAIT_TEXT = {
    "attention_seeking": (
        "You rarely post your own takes. You prefer reacting to others with likes or short replies, or staying quiet.",
        "You enjoy some attention but don't chase it. You post your own takes now and then.",
        "You crave reactions. You post bold, punchy takes, hype things up, and often end posts by inviting replies or reposts. You love being the one who started the conversation.",
    ),
    "agreeableness": (
        # low
        "You are combative toward people, not just ideas. You reply mostly to people you disagree with, "
        "to argue. You attack the other person's credibility and experience directly, not just their argument. "
        'You never open with agreement, never say "I see your point", "fair" or "great question", '
        "and you never thank or encourage anyone.",
        # mid
        "You are civil. You disagree directly when you think someone is wrong, but you argue with the idea, "
        "never insult the person.",
        # high
        "You are kind to people, even when you disagree with their idea. You reply mostly to people who sound "
        "worried, unsure, or who agree with you, to support them. When you disagree, you first acknowledge "
        "something the person got right, in your own words, then disagree gently. "
        "You never insult or mock anyone, and you would rather like a post than argue under it.",
    ),
    "judgmental": (
        "You avoid verdicts. You hedge and admit when you're unsure.",
        "You have opinions but acknowledge nuance.",
        'You state your conclusions with full certainty. No "maybe", no hedging. You compare companies and ideas bluntly.',
    ),
    "curiosity": (
        "You never ask questions. You only engage with posts directly about your own interests.",
        "You sometimes ask a question, mostly about your own interests.",
        "When you reply, you usually ask the person a genuine question about their experience or reasoning. "
        "You often reply to posts outside your usual interests, not just ones you disagree with.",
    ),
    "conformity": (
        "You hold your position no matter how many people disagree. How popular an opinion is means nothing to you.",
        "Popular opinion nudges you a little, but you mostly keep your own view.",
        "You are easily swayed. When several people seem to agree on something, you shift toward their view and join in.",
    ),
}


def level(value: float) -> int:
    return 0 if value < 0.34 else 1 if value < 0.67 else 2


def stance_text(s: float) -> str:
    if s <= -0.6:
        return "strongly against it"
    if s <= -0.2:
        return "somewhat against it"
    if s < 0.2:
        return "undecided and unsure about it"
    if s < 0.6:
        return "somewhat in favor of it"
    return "strongly in favor of it"


def opinion_text(value: float, sides=None) -> str:
    """"you are strongly in favor of it", or the story's own wording for each side when
    for/against reads oddly (you're not "against" a football club, you support the other one)."""
    if not sides or abs(value) < 0.2:
        return f"you are {stance_text(value)}"
    side = sides["for"] if value > 0 else sides["against"]
    return f"{side} ({'strongly' if abs(value) >= 0.6 else 'mildly'})"


def opinion_lines(persona: dict, seed_topic: str, topics: dict) -> str:
    """The seed topic's stance first, then the persona's other opinions."""
    lines = [f"- {seed_topic}: you are {stance_text(persona['stance'])}."]
    for t, v in (persona.get("opinions") or {}).items():
        lines.append(f"- {topics[t]['opinion_on']}: {opinion_text(v, topics[t].get('sides'))}.")
    return "\n".join(lines)


def render_system(persona: dict, template: str, seed_topic: str, topics=None) -> str:
    personality = "\n".join(
        f"- {TRAIT_TEXT[t][level(v)]}" for t, v in persona["traits"].items()
    )
    return Template(template).substitute(
        name=persona["name"],
        bio=persona["bio"],
        interests=", ".join(persona["interests"]),
        hobbies=", ".join(persona.get("hobbies") or ["nothing in particular"]),
        personality=personality,
        seed_topic=seed_topic,
        stance_text=stance_text(persona["stance"]),
        opinions=opinion_lines(persona, seed_topic, topics or {}),
        voice=persona.get("voice") or DEFAULT_VOICE,
    )


def first_json(raw: str):
    """(first JSON object in raw, error_or_None). Models sometimes wrap it in text or ```."""
    start = raw.find("{")
    if start == -1:
        return None, "no JSON object in response"
    try:
        data, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError as e:
        return None, f"bad JSON: {e}"
    if not isinstance(data, dict):
        return None, "JSON is not an object"
    return data, None


def parse_action(raw: str):
    """Returns (action_dict, error_or_None). Anything unusable becomes "none"."""
    data, error = first_json(raw)
    if error:
        return dict(NONE_ACTION), error
    kind = str(data.get("action", "")).strip().lower()
    if kind not in VALID_ACTIONS:
        return dict(NONE_ACTION), f"unknown action {kind!r}"
    target = data.get("target_id")
    text = data.get("text")
    return {
        "action": kind,
        "target_id": str(target) if target not in (None, "", "null") else None,
        "text": str(text) if text not in (None, "", "null") else None,
        "reason": str(data.get("reason") or ""),
    }, None


def parse_post(raw: str):
    """Returns (action_dict, error_or_None) for a post turn. No usable text becomes "none"."""
    data, error = first_json(raw)
    text = str(data.get("text") or "").strip() if data else ""
    if not error and text in ("", "null"):
        error = "no text in post"
    if error:
        return dict(NONE_ACTION), error
    return {"action": "post", "target_id": None, "text": text, "reason": str(data.get("reason") or "")}, None


def reply_labels(post_ids: list) -> dict:
    """{"A": "p45", "B": "p57", ...} for the posts that caught an agent's eye."""
    return dict(zip(LABELS, post_ids))


def normalize_post_target(target, feed: list, allowed_ids=None):
    """Clean up common model slips in a post id: "10" or "[p10]" -> "p10", and a username
    -> that user's newest post (from allowed_ids if given). Returns the id, unchanged if unsure."""
    t = str(target).strip().strip("[]").strip()
    if t.isdigit():
        return f"p{t}"
    name = t.lstrip("@")
    by_user = [p.id for p in feed if p.author == name and (allowed_ids is None or p.id in allowed_ids)]
    return by_user[-1] if by_user else t


class Agent:
    def __init__(
        self, persona: dict, templates: dict, seed_topic: str, memory_size: int, seed: int = 0,
        topics=None,
    ):
        self.persona = persona
        self.name = persona["name"]
        self.wake_prob = persona["wake_prob"]
        self.system_prompt = render_system(persona, templates["system"], seed_topic, topics)
        self.tick_template = Template(templates["tick"])
        self.post_template = Template(templates["post"])
        self.memory_size = memory_size
        self.memory = []
        self.write_prob = base_write_prob(persona)
        self.last_turn = 0  # tick of this agent's last decision
        self.seed = seed  # for per-turn rolls made inside decide(), which may run in parallel
        # What makes a post interesting to this agent: its interests, hobbies, and the keywords
        # of the stories it has opinions on.
        opinion_words = [k for t in (persona.get("opinions") or {}) for k in (topics or {}).get(t, {}).get("keywords", [])]
        self.likes_and_hobbies = persona["interests"] + persona.get("hobbies", []) + opinion_words

    def write_chance(self, replied_to: bool) -> float:
        """This turn's chance of a write mode. Capped at 0.95 unless write_prob itself is higher."""
        p = self.write_prob + (REPLY_BOOST if replied_to else 0.0)
        return min(p, max(self.write_prob, 0.95))

    def eye_catchers(self, world, posts: list, rng) -> list:
        """Pick up to EYE_CATCH of `posts`, weighted by EYE_WEIGHTS, in feed order."""
        own = {p.id for p in world.posts.values() if p.author == self.name}
        w = EYE_WEIGHTS

        def weight(p):
            x = w["base"] + w["per_like"] * len(p.likes)
            if p.reply_to in own:
                x += w["replies_to_you"]
            if world.mentions(p, self.likes_and_hobbies):
                x += w["interest"]
            if p.id in world.news:
                x += w["news"]
            return x

        pool, picked = list(posts), []
        while pool and len(picked) < EYE_CATCH:
            p = rng.choices(pool, weights=[weight(q) for q in pool])[0]
            pool.remove(p)
            picked.append(p)
        return [p.id for p in posts if p in picked]

    def menu(self, world, feed: list, mode: str, rng=None):
        """(allowed actions, {action: valid target ids}) for this turn.

        Rules are enforced through the menu, not through warnings: the prompt only offers
        posts this agent may reply to / hasn't liked yet, and drops "reply" or "like"
        entirely when there's nothing valid to aim it at. With an rng, replies are limited
        to the few valid posts that catch the agent's eye.
        """
        can_reply = [p for p in feed if not world.reply_block(self.name, p)]
        targets = {
            "reply": self.eye_catchers(world, can_reply, rng) if rng else [p.id for p in can_reply],
            "like": [p.id for p in feed if self.name not in p.likes],
        }
        allowed = [a for a in MODE_ACTIONS[mode] if a not in targets or targets[a]]
        return allowed, targets

    def roll_post_turn(self, world, tick: int, rng) -> dict:
        """Pick this post turn's spark and the few posts the agent glances at. Uses the
        caller's rng, so the same seed gives the same sparks for any model."""
        forms = form_weights(self.persona["traits"])
        form = rng.choices(list(forms), weights=list(forms.values()))[0]
        subjects = dict(SUBJECT_WEIGHTS)
        if not self.persona.get("hobbies"):
            subjects.pop("hobby")
        subject = rng.choices(list(subjects), weights=list(subjects.values()))[0]
        story = world.pick_story(tick, rng) if subject == "news" else None
        if subject == "news" and story is None:
            subject = "anything"  # no story yet
        about = SUBJECTS[subject].format(
            interest=rng.choice(self.persona["interests"]),
            hobby=rng.choice(self.persona.get("hobbies") or ["-"]),
        )
        return {
            "spark": f"{form}/{subject}",
            "spark_text": f"{FORMS[form]} about {about}",
            # Only news posts see anything from the feed: one story plus a couple of reactions.
            # Seeing the feed is what pulls every post back to whatever is trending.
            "story": story,
            "glance": world.reactions(story, self.name, 2, rng) if story else [],
        }

    def memory_text(self) -> str:
        return "\n".join(f"- {m}" for m in self.memory) or "- (nothing yet, you just joined)"

    def build_user_prompt(self, world, feed: list, tick: int, mode: str, allowed=None, targets=None) -> str:
        if allowed is None:
            allowed, targets = self.menu(world, feed, mode)
        memory = self.memory_text()
        labels = reply_labels(targets["reply"])

        def rule(a):
            if a == "reply":
                return ACTION_RULES[a].format(targets=" or ".join(", ".join(labels).rsplit(", ", 1)))
            return ACTION_RULES[a].format(targets=", ".join(targets[a])) if a in targets else ACTION_RULES[a]

        if mode == "write" and "reply" in allowed:
            eye = "\n".join(f"{l}) {world.format_eye_catcher(world.posts[i], self.name)}" for l, i in labels.items())
            mode_text = MODE_TEXT["write"].format(eye=eye)
        else:
            mode_text = MODE_TEXT["write_no_reply" if mode == "write" else mode]
        return self.tick_template.substitute(
            tick=tick,
            memory=memory,
            feed=world.format_feed(feed, self.name),
            mode_text=mode_text,
            actions=" | ".join(allowed),
            rules="\n".join(rule(a) for a in allowed),
        )

    def compose(self, world, tick: int, llm, post_turn: dict) -> dict:
        """A post turn: write one new post from the spark, without the full feed in view."""
        self.last_turn = tick
        story = post_turn["story"]
        if story:
            scene = "You open Chirp. This story is going around:\n" + world.format_glance([story])
            if post_turn["glance"]:
                scene += "\nSome reactions:\n" + world.format_glance(post_turn["glance"])
        else:
            scene = "You open Chirp, but you're not thinking about the news right now. Something from your own life is on your mind."
        user = self.post_template.substitute(
            tick=tick,
            memory=self.memory_text(),
            scene=scene,
            spark=post_turn["spark_text"],
        )
        raw = llm.complete(self.system_prompt, user,
                           hint={"kind": "post", "persona": self.persona, "spark": post_turn["spark"]})
        action, error = parse_post(raw)
        return {
            "tick": tick,
            "agent": self.name,
            "mode": "post",
            "spark": post_turn["spark"],
            "story_id": story.id if story else None,
            "glance_ids": [p.id for p in post_turn["glance"]],
            "user_prompt": user,
            "raw": raw,
            "action": action,
            "parse_error": error,
            "blocked": None,
            "fixed_target": None,
        }

    def decide(self, world, tick: int, llm, feed_size: int, mode: str = "write", post_turn=None) -> dict:
        if mode == "post":
            return self.compose(world, tick, llm, post_turn)
        self.last_turn = tick
        feed = world.feed_for(self.name, feed_size, self.likes_and_hobbies)
        # Seeded per agent and tick, so it's the same whatever order parallel calls run in.
        eye_rng = random.Random(f"{self.seed}:{self.name}:{tick}")
        allowed, targets = self.menu(world, feed, mode, eye_rng)
        user = self.build_user_prompt(world, feed, tick, mode, allowed, targets)
        raw = llm.complete(
            self.system_prompt,
            user,
            hint={"kind": "action", "persona": self.persona, "feed": feed,
                  "allowed": allowed, "targets": targets, "reply_labels": reply_labels(targets["reply"])},
        )
        action, error = parse_action(raw)
        fixed_target = None
        labels = reply_labels(targets["reply"])
        letter = str(action["target_id"] or "").strip().strip("()[].").upper()
        if action["action"] == "reply" and letter in labels:
            action["target_label"] = letter
            action["target_id"] = labels[letter]
        elif action["action"] in ("reply", "like", "repost") and action["target_id"]:
            clean = normalize_post_target(action["target_id"], feed, targets.get(action["action"]))
            if clean != action["target_id"]:
                fixed_target = f"{action['target_id']} -> {clean}"
                action["target_id"] = clean
        blocked = None
        if action["action"] not in allowed:
            # The model ignored the menu (e.g. replied while only scrolling). Count it, then do nothing.
            blocked = action["action"]
        elif action["action"] in targets and action["target_id"] not in targets[action["action"]]:
            blocked = f"{action['action']} {action['target_id']} (not offered)"
        if blocked:
            action = dict(NONE_ACTION, reason=f"[blocked: {blocked}] {action['reason']}")
        return {
            "tick": tick,
            "agent": self.name,
            "mode": mode,
            "allowed": allowed,
            "reply_targets": targets["reply"],
            "reply_labels": labels,
            "like_targets": targets["like"],
            "feed_ids": [p.id for p in feed],
            "user_prompt": user,
            "raw": raw,
            "action": action,
            "parse_error": error,
            "blocked": blocked,
            "fixed_target": fixed_target,
        }

    def remember(self, tick: int, action: dict, result: dict):
        kind = action["action"]
        who = f"@{result['target_author']}'s " if result.get("target_author") else ""
        if not result.get("ok"):
            note = f"you tried to {kind} but it failed ({result.get('error')})"
        elif kind == "post":
            note = f'you posted {result["post_id"]}: "{action["text"]}"'
        elif kind == "reply":
            note = f'you replied to {who}post {result["target_id"]} with {result["post_id"]}: "{action["text"]}"'
        elif kind in ("like", "repost"):
            verb = "liked" if kind == "like" else "reposted"
            note = f"you {verb} {who}post {result['target_id']}"
        elif kind == "follow":
            note = f"you followed @{result['target_author']}"
        else:
            note = "you scrolled and did nothing"
        self.memory.append(f"tick {tick}: {note}")
        self.memory = self.memory[-self.memory_size :]
