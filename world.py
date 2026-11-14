"""The shared world: users, posts, likes and follows.

Agents never change the world directly. The simulation collects every agent's
chosen action during a tick and applies them all at the end of the tick, so
agents acting in the same tick can't see each other's moves.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field

MAX_LEN = 280
MAX_REPLIES_IN_A_ROW = 2  # to the same person, before you must reply to someone else

# Feed ranking. Without these, the busiest thread fills every feed: each reply is the newest
# post, so it outranks everything else, and new stories drop out after one tick.
MAX_PER_THREAD = 3  # posts from one thread (same root) in one feed
NEWS_BOOST = 4  # news stories stay near the top for a few ticks
ORIGINAL_BOOST = 1  # a new post ranks a bit above a reply from the same tick
INTEREST_BOOST = 3  # the post mentions one of the viewer's interests or hobbies


@dataclass
class Post:
    id: str
    tick: int
    author: str
    text: str
    reply_to: str | None = None
    repost_of: str | None = None
    likes: list = field(default_factory=list)


class World:
    def __init__(self, usernames):
        self.users = set()
        self.follows = {}
        self.posts = {}  # id -> Post, in creation order
        self.news = []  # ids of scheduled news stories, oldest first
        self._next_id = 1
        for name in usernames:
            self.add_user(name)

    def add_user(self, name: str):
        self.users.add(name)
        self.follows.setdefault(name, set())

    def add_post(self, author, text, tick, reply_to=None, repost_of=None) -> Post:
        post = Post(f"p{self._next_id}", tick, author, text[:MAX_LEN], reply_to, repost_of)
        self._next_id += 1
        self.posts[post.id] = post
        return post

    def reply_block(self, agent: str, post: "Post") -> str | None:
        """Why `agent` may not reply to `post`, or None if it may. Stops reply ping-pong."""
        if any(p.author == agent and p.reply_to == post.id for p in self.posts.values()):
            return f"you already replied to {post.id}"
        recent = [p for p in self.posts.values() if p.author == agent and p.reply_to][-MAX_REPLIES_IN_A_ROW:]
        if len(recent) == MAX_REPLIES_IN_A_ROW and all(self.posts[p.reply_to].author == post.author for p in recent):
            return f"your last {MAX_REPLIES_IN_A_ROW} replies were all to @{post.author}"
        return None

    def replied_to_since(self, agent: str, tick: int) -> bool:
        """Did anyone reply to one of agent's posts at or after `tick`?"""
        own = {p.id for p in self.posts.values() if p.author == agent}
        return any(p.reply_to in own and p.tick >= tick and p.author != agent for p in self.posts.values())

    def followers_of(self, name: str) -> list:
        return sorted(u for u, f in self.follows.items() if name in f)

    # ---- reading -------------------------------------------------------

    def feed_for(self, viewer: str, k: int, interests=()) -> list:
        """Top-k posts by others, ranked by recency plus boosts for replies to the viewer,
        accounts the viewer follows, likes, news, original posts and the viewer's interests.
        At most MAX_PER_THREAD posts per thread. Returned oldest first."""
        own = {p.id for p in self.posts.values() if p.author == viewer}
        following = self.follows.get(viewer, set())
        news = set(self.news)

        def score(p: Post) -> float:
            s = float(p.tick)
            if p.reply_to in own:
                s += 6
            if p.author in following:
                s += 3
            if p.id in news:
                s += NEWS_BOOST
            elif not p.reply_to:
                s += ORIGINAL_BOOST
            if self.mentions(p, interests):
                s += INTEREST_BOOST
            return s + 0.5 * len(p.likes)

        candidates = sorted((p for p in self.posts.values() if p.author != viewer), key=score, reverse=True)
        top, per_thread = [], Counter()
        for p in candidates:
            root = self.root(p).id
            if per_thread[root] < MAX_PER_THREAD:
                per_thread[root] += 1
                top.append(p)
                if len(top) == k:
                    break
        return sorted(top, key=lambda p: int(p.id[1:]))

    def format_post(self, p: Post, viewer: str) -> str:
        meta = [f"tick {p.tick}"]
        if p.likes:
            meta.append(f"{len(p.likes)} like{'s' if len(p.likes) != 1 else ''}")
        if p.reply_to:
            parent = self.posts.get(p.reply_to)
            whose = "YOUR post" if parent and parent.author == viewer else f"@{parent.author}'s post"
            meta.append(f"replying to {whose} {p.reply_to}")
        if viewer in p.likes:
            meta.append("you liked this")
        if p.author in self.follows.get(viewer, set()):
            meta.append("you follow them")
        if p.author != viewer and self.reply_block(viewer, p):
            meta.append("can't reply: " + self.reply_block(viewer, p))
        if p.repost_of:
            orig = self.posts[p.repost_of]
            body = f'reposted {orig.id} by @{orig.author}: "{orig.text}"'
        else:
            body = f'"{p.text}"'
        return f"[{p.id}] @{p.author} ({', '.join(meta)}): {body}"

    def mentions(self, post: Post, interests) -> bool:
        """Does the post (or the post it reposts) mention any of these interests?"""
        text = (self.posts[post.repost_of].text if post.repost_of else post.text).lower()
        return any(i.lower() in text for i in interests)

    def root(self, post: Post) -> Post:
        while post.reply_to:
            post = self.posts[post.reply_to]
        return post

    def pick_story(self, tick: int, rng):
        """A recent news story, newer ones more likely. None if there's no story yet."""
        stories = [self.posts[i] for i in self.news if tick - self.posts[i].tick <= 10]
        if not stories:
            return None
        return rng.choices(stories, weights=[1 / (1 + tick - p.tick) for p in stories])[0]

    def reactions(self, story: Post, viewer: str, k: int, rng) -> list:
        """Up to k random replies by others somewhere in the story's thread, oldest first."""
        thread = [p for p in self.posts.values()
                  if p.reply_to and p.author != viewer and self.root(p).id == story.id]
        return sorted(rng.sample(thread, min(k, len(thread))), key=lambda p: int(p.id[1:]))

    def glance(self, viewer: str, tick: int, k: int, rng) -> list:
        """Up to k random posts by others from the last 3 ticks (no reposts), oldest first.
        What a post turn sees: enough to know what's going on, not a list to reply to."""
        pool = [p for p in self.posts.values() if p.author != viewer and not p.repost_of]
        recent = [p for p in pool if p.tick >= tick - 3] or pool[-k:]
        picked = rng.sample(recent, min(k, len(recent)))
        return sorted(picked, key=lambda p: int(p.id[1:]))

    def format_glance(self, posts: list) -> str:
        """No ids or thread info, so the agent writes a post rather than aiming at one."""
        if not posts:
            return "(nothing yet)"
        return "\n".join(f'- @{p.author}: "{p.text}"' for p in posts)

    def format_eye_catcher(self, p: Post, viewer: str) -> str:
        """A post as offered for a reply: no id (it gets a letter), but who it answers."""
        context = ""
        if p.reply_to:
            parent = self.posts[p.reply_to]
            context = " (replying to you)" if parent.author == viewer else f" (replying to @{parent.author})"
        body = f'reposted @{self.posts[p.repost_of].author}: "{self.posts[p.repost_of].text}"' if p.repost_of else f'"{p.text}"'
        return f"@{p.author}{context}: {body}"

    def format_feed(self, posts: list, viewer: str) -> str:
        if not posts:
            return "(your feed is empty)"
        return "\n".join(self.format_post(p, viewer) for p in posts)

    # ---- writing -------------------------------------------------------

    def apply(self, agent: str, action: dict, tick: int) -> dict:
        """Apply one action. Returns {"ok": bool, "error"?, "post_id"?, "target_id"?, "target_author"?}."""
        kind = action["action"]
        target = action.get("target_id")
        text = (action.get("text") or "").strip()

        if kind == "none":
            return {"ok": True}

        if kind == "post":
            if not text:
                return {"ok": False, "error": "post needs text"}
            return {"ok": True, "post_id": self.add_post(agent, text, tick).id}

        if kind == "follow":
            name = str(target or "").strip().lstrip("@")
            if name not in self.users:
                return {"ok": False, "error": f"unknown user {name!r}"}
            if name == agent:
                return {"ok": False, "error": "cannot follow yourself"}
            if name in self.follows[agent]:
                return {"ok": False, "error": f"already follows {name}"}
            self.follows[agent].add(name)
            return {"ok": True, "target_author": name}

        # reply / like / repost all target an existing post
        pid = str(target or "").strip().strip("[]")
        if pid.isdigit():
            pid = f"p{pid}"
        parent = self.posts.get(pid)
        if parent is None:
            return {"ok": False, "error": f"no post {target!r}"}
        result = {"target_id": pid, "target_author": parent.author}

        if kind == "reply":
            if not text:
                return {"ok": False, "error": "reply needs text", **result}
            block = self.reply_block(agent, parent)
            if block:
                return {"ok": False, "error": block, **result}
            return {"ok": True, "post_id": self.add_post(agent, text, tick, reply_to=pid).id, **result}

        if kind == "like":
            if parent.author == agent:
                return {"ok": False, "error": "cannot like own post", **result}
            if agent in parent.likes:
                return {"ok": False, "error": "already liked", **result}
            parent.likes.append(agent)
            return {"ok": True, **result}

        if kind == "repost":
            orig = self.posts[parent.repost_of] if parent.repost_of else parent
            post = self.add_post(agent, "", tick, repost_of=orig.id)
            return {"ok": True, "post_id": post.id, "target_id": orig.id, "target_author": orig.author}

        return {"ok": False, "error": f"unknown action {kind!r}"}

    def to_dict(self) -> dict:
        return {
            "users": sorted(self.users),
            "follows": {u: sorted(f) for u, f in self.follows.items()},
            "posts": [asdict(p) for p in self.posts.values()],
        }
