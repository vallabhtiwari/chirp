# Chirp web viewer: plan for discussion

Status: **steps 1–7 built (2026-11-12).** Steps 5–7 summary at the end of this section.
Earlier status: **steps 1–4 built (2026-11-12).** Decisions made: React + Vite frontend; GitHub Pages demo
(step 7); finished runs first, live view later; Twitter-like but its own look; steps 1–4 first.

What was built, and where it differs from the draft below:
- `viewer_data.py` + `tests/test_viewer_data.py` (9 tests; every kept run is rebuilt and matched
  against its `_world.json`: posts, texts, likes, follows).
- `viewer.py`: server + `--export` (export written but not yet used; that's step 7).
- `viewer/`: run list, timeline (Threads / Latest), tick slider with play and arrow keys, topic
  filter, thread view, inspector with lazy-loaded prompts. Light + dark, works at phone width.
- Instead of a turn-type *filter*, every post has a coloured edge for the turn type that wrote it
  (news / post / write / react), with a legend. Filtering by turn type hid the context of threads.
- Routing is `#/run/<name>?t=12&thread=p1&turn=19/marcus_skeptic` (query parameters rather than
  path segments, so tick, thread and inspected turn combine freely).
- The run JSON is ~600 KB, not "a few hundred": 504 turns each carry their feed and menu ids.
  Fine locally; gzipped (as GitHub Pages serves it) it is 93 KB.

Steps 5–7:
- Profiles (`?agent=`): stats, scheduling odds, a clickable square per tick (post/write/react/asleep),
  traits, opinions on a −1…+1 scale, voice, interests/hobbies, who they reply to and who replies to them.
  Names and avatars anywhere open profiles; the sidebar lists all agents.
- Agent's-eye view (`?eye=<tick/agent>`): the ranked feed at the start of that turn (counts as of the
  tick before), eye-catchers badged A/B/C, the chosen post outlined. Post turns show the story + glance.
- Overview (`?view=overview`): totals, turns per tick (stacked bars), what the model chose on write and
  react turns, talk by topic over time (heatmap), most replied to / most active, code interventions.
  Hand-drawn SVG, hover tooltips, "show as table" under each chart. Turn-type colours were run through
  the palette validator (CVD and contrast) in light and dark.
- GitHub Pages: `viewer.py --export docs --runs <run> [--replace]` writes a static site into `docs/`
  (checked for key-shaped strings first; `--replace` only overwrites a folder marked as an export).
  Tested served from a sub-path (`/chirp/`) as Pages does. Publishing needs a GitHub repo (not done).
- Run cost now comes from `llm.usd_per_million_tokens` in the run's own config (gpt-6-luna: $0.10 / $0.50,
  from secondary sources), falling back to a built-in table for older logs.

---

## 1. What the viewer is for

Today a run can only be read through `analyze.py` text output and a 2.8 MB `.jsonl` file. The viewer
should make a run readable the way a social network is readable, and then let you look *under the hood*
of any post.

Three questions it should answer, in order of importance:

1. **What happened?** Scroll the feed like a Twitter timeline, open threads, scrub through ticks.
2. **Why did it happen?** Click any post or action to see the turn behind it: which turn type code
   rolled, the menu, the A/B/C eye-catchers, the spark, the exact prompt, the raw model answer, the
   private reason. This is what makes Chirp different from a fake Twitter clone, and it shows the
   "code decides, model speaks" split from HOW_IT_WORKS.md §0.1 visually.
3. **Who is everyone?** Agent profiles: traits, opinions, voice, their posts, and every turn they had,
   including the ticks they slept.

Not in scope: humans posting, editing runs, starting runs from the browser (see §8).

---

## 2. What data we already have (checked against `logs/v1_20261028_101422.jsonl`)

The log already holds everything the viewer needs. No change to `sim.py` is required.

| Record type | Count | What it gives the viewer |
|---|---|---|
| `config` | 1 | Run settings, model, seed, scheduled stories (no API key, only the env var *name*) |
| `agent` | 30 | Full persona + rendered system prompt |
| `scheduled_post` | 9 | News stories with `topic` |
| `decision` | 504 | Per turn: mode, allowed actions, `reply_labels` (A/B/C → post id), `feed_ids` (what the agent saw), spark, user prompt, raw output, parsed action + reason, `p_write`, parse/block/fix notes |
| `applied` | 504 | Result: ok?, new `post_id`, target, target author |
| `sleep` | 396 | Who slept at which tick |
| `end` | 1 | LLM calls, token usage |

`_world.json` has the final posts/likes/follows but **no tick on likes or follows**, so replaying "the
world at tick 12" needs the `.jsonl` (the `applied` records). The `.jsonl` is the single source of truth.

Two facts that shape the design:

- `sim.py` flushes every line as it goes, so a **live view of a running sim is possible later** by
  re-reading the growing file. No sim change needed for that either.
- Older logs (v1_20261022…) lack newer fields (`reply_labels`, `spark`, `topic`). The data builder must
  treat every field as optional so all kept runs open.

---

## 3. Architecture

```
logs/<run>.jsonl ──> viewer_data.py ──> run JSON ──> viewer/ (HTML + JS + CSS in the browser)
                     build_run()        (one shape)        renders feed, threads, profiles, inspector
                          ▲
            viewer.py ────┘  local:  python3 viewer.py   → http://127.0.0.1:8000 (stdlib http.server)
                             static: python3 viewer.py --export site/  → same files, no server needed
```

**Backend: Python stdlib only, like the rest of Chirp.** No Flask, no npm, no build step.

- `viewer_data.py`: pure functions, no I/O beyond reading the log. `build_run(path) -> dict` turns the
  `.jsonl` into the shape in §4. Testable on its own and reusable by `analyze.py` later.
- `viewer.py`: a small `http.server` that serves `viewer/` plus three JSON endpoints, bound to
  `127.0.0.1` only. Results are cached by file modification time.
- `--export DIR` writes the exact same JSON to files at the same paths. The frontend can't tell the
  difference, so the same viewer works on **GitHub Pages** with a sample run: a link on your resume
  that anyone can click without installing anything.

**Frontend (decide):**

| Option | Pros | Cons |
|---|---|---|
| **A. Vanilla JS modules (recommended)** | Zero dependencies, matches the stdlib-only story, nothing to install, easy to read in a portfolio | A bit more code for rendering and state |
| B. Preact + htm from a CDN | Component code, still no build step | A dependency and a CDN; needs internet |
| C. React + Vite | Most "industry standard" on a resume | npm, node_modules, build step: a second toolchain for a small app |

**Routing:** hash URLs, so every view is a shareable link and it works on static hosting:
`#/run/v1_20261028_101422`, `…/tick/12`, `…/post/p141`, `…/agent/marcus_skeptic`, `…/turn/19/marcus_skeptic`.

**Endpoints (same paths in export mode):**

| Path | Size (est.) | Contents |
|---|---|---|
| `api/runs.json` | tiny | List of runs: name, date, model, agents, ticks, posts, cost |
| `api/run/<name>.json` | a few hundred KB | Everything except prompts: agents, posts, events, turns (without prompt text) |
| `api/run/<name>/prompts/<agent>.json` | ~70 KB each | That agent's system prompt and user prompts, loaded only when you open the inspector |

Splitting out the prompts keeps the first load several times smaller: prompts and raw answers are ~75% of the log
(2.1 MB of 2.8 MB in the latest run).

---

## 4. Data shape (`build_run` output)

```jsonc
{
  "run":    {"name", "started", "ended", "model", "seed", "ticks", "agents": 30,
             "calls", "tokens": {"in", "out"}, "cost_usd_est"},
  "agents": {"marcus_skeptic": {"bio", "traits", "interests", "hobbies", "voice", "opinions",
                                "stance", "wake_prob", "write_prob", "generated", "is_news": false}},
  "posts":  {"p141": {"id", "tick", "author", "text", "reply_to", "repost_of", "root", "topic",
                      "turn": "19/marcus_skeptic"}},          // which turn produced it
  "events": [{"tick", "agent", "kind": "like|repost|follow|post|reply", "target", "post"}],
  "turns":  {"19/marcus_skeptic": {"tick", "agent", "mode": "post|write|react|sleep",
             "p_write", "replied_to", "allowed", "eye": {"A": "p141", "B": …}, "like_targets",
             "feed_ids", "spark", "story_id", "action", "target_label", "reason",
             "parse_error", "blocked", "fixed_target", "ok", "result_post"}}
}
```

From this one shape, the frontend computes everything else, e.g. "likes on p141 as of tick 12" =
events with `kind: like, target: p141, tick ≤ 12`.

---

## 5. Views

### 5.1 Run picker
A list of runs from `logs/`, newest first: date, model, posts, replies, cost. Opens the timeline.

### 5.2 Timeline (the main screen)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Chirp · v1_20261028_101422 · gpt-4o-mini · seed 42        [Runs] [Agents]   │
├──────────────────────────────────────────────────────────────────────────────┤
│ tick ◀ ━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━ ▶   12 / 30   [▶ play]               │
│ topics: [all] novacode football metro heatwave …   turns: [post][write][react]│
├───────────────────────────────────────────┬──────────────────────────────────┤
│ 📰 @citynews · t6 · metro fares            │  INSPECTOR (opens on click)      │
│ City raises metro fares 15% …              │  turn 19 · marcus_skeptic        │
│ ♥ 7  ↻ 1  💬 9                             │  CODE: woke (60%) → write (38%)  │
│                                            │  eye-catchers: A p141 B p150 …   │
│   ↳ @marcus_skeptic · t19                  │  MODEL: reply → "B"              │
│     Fifteen percent for the same delays.   │  code mapped B → p141            │
│     ♥ 3   [why?]                           │  reason: "…"                     │
│                                            │  [show prompt] [show raw]        │
└───────────────────────────────────────────┴──────────────────────────────────┘
```

- Feed = all posts up to the selected tick, newest first, grouped into threads.
- The tick slider replays the run: likes and replies count up as you move it. Play animates it.
- Filters by topic and by turn type.
- Every post has a "why?" that opens the **inspector** for the turn that made it.

### 5.3 Inspector (the turn behind an action)
Laid out in the two colours of §0.1, so the split is visible:
- **Code decided:** posting / woke / slept (with the odds), write or react (`p_write`), the menu
  (allowed actions), eye-catchers A/B/C, the spark for post turns, the story shown.
- **Model decided:** action, letter, text, private reason.
- **Code checked:** letter → id, fixed target, blocked rule, parse errors.
- Collapsible: full system prompt, full user prompt, raw output (loaded on demand).

### 5.4 Agent's-eye view
"What did marcus see at tick 19?" Renders his feed (`feed_ids`) in that order, with his 3 eye-catchers
highlighted. It shows *why* he answered B: the other posts weren't on his menu.

### 5.5 Agent profile
Persona card (traits as bars, opinions as −1…+1 scales, voice, hobbies), their posts and replies, who
they reply to most, and a strip of 30 ticks: slept / react / write / post, colour-coded.

### 5.6 Run overview
Posts per tick, talk by topic over time (the same numbers as `analyze.py`), most-replied agents,
token usage and cost.

### Later (not in the first build)
Live view of a running sim, side-by-side comparison of two runs, interaction graph.

---

## 6. Things to get right

- **Model text is untrusted.** Posts and reasons are LLM output; insert them with `textContent`, never
  `innerHTML`, so a model writing `<script>` can't run code in the page.
- **No secrets.** Only `logs/` is read. The log holds the env var *name*, never a key; the builder never
  touches `.env`. The export is checked for `sk-`-like strings before writing.
- **Local only.** The server binds to `127.0.0.1`, read-only, GET only, and serves only files under
  `viewer/` plus the built JSON, so a path like `../.env` can't leak.
- **Old logs open.** Missing fields show as "not recorded in this run".
- **Speed.** 30 agents and 300 posts is tiny; plain DOM rendering is fine. If runs grow 10×, render only
  the visible part of the feed.

---

## 7. Build order (each step usable on its own)

| # | Step | Done when |
|---|---|---|
| 1 | `viewer_data.py` + tests on a mock run and the latest real run | `build_run` reproduces `analyze.py` totals exactly (posts, replies, likes per agent) |
| 2 | `viewer.py` server + run picker + timeline with threads | You can scroll a run in the browser |
| 3 | Tick slider + play + filters | Scrubbing to tick 12 shows the world as it was at tick 12 |
| 4 | Inspector + lazy prompts | Every post's "why?" works, including old logs |
| 5 | Agent profiles + agent's-eye view | |
| 6 | Run overview | |
| 7 | `--export` + GitHub Pages with one sample run | A public link works with no server |

Steps 1–4 are the core; I'd stop there and look at it together before 5–7.
Cost: $0. Everything uses existing logs and mock runs; no API calls.

---

## 8. Questions for you

1. **Frontend:** vanilla JS (recommended), Preact without a build, or React + Vite?
2. **Public demo:** do you want a GitHub Pages version with a sample run? It costs nothing extra if we
   design for it now (the static export), and it's the strongest resume link.
3. **Live view:** replay of finished runs first, live viewing later (recommended)? Or is watching a run
   as it happens important to you now?
4. **Look:** a Twitter-like feed (familiar, good for screenshots) or a research-dashboard look
   (denser, more numbers)? My suggestion: Twitter-like feed with the inspector as the "research" side panel.
5. **First-build scope:** is steps 1–4 the right first milestone, or is another view (profiles,
   overview) more important to you?
