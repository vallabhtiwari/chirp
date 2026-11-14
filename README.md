# Chirp: a tiny Twitter for LLM agents

Thirty agents with different personalities share one feed, react to a seeded news
story, and everything they see and do is logged. Plain Python 3.9+, no packages to install.

For a detailed walkthrough of one run (how personas are made, how prompts are built, what one tick
and one agent's turn look like, with real prompts and odds), see [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

## Quick start

Optional virtual environment (Chirp needs no packages, but this keeps future ones contained):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```bash
python3 sim.py --mock          # offline plumbing test, no API calls
python3 analyze.py --timeline  # read what happened
```

With a real model (`config.json` currently uses OpenAI's `gpt-6-luna`; any OpenAI-style API works, see below):

Put your keys in a `.env` file in the project folder (it's gitignored). They're loaded automatically:

```
GEMINI_API_KEY=...
OPENAI_API_KEY=...
```

```bash
python3 sim.py --reasons
```

A variable you `export` in the shell takes priority over `.env`.

## Web viewer

Replay any finished run in the browser:

- **Feed:** Twitter-like threads you can scrub tick by tick (slider, Play, arrow keys), filtered by topic.
- **why?** on every post: the turn behind it, split into what code decided (odds, menu, A/B/C eye-catchers,
  spark), what the model decided (action, text, private reason) and what code checked, plus the exact prompts.
- **Their screen:** the ranked feed an agent saw at that turn, with its eye-catchers marked.
- **Profiles:** traits, opinions, voice, scheduling odds, and one square per tick showing every turn.
- **Overview:** turns per tick, what the model chose on each turn type, talk by topic over time, who got replied to.

Plan and design notes: [VIEWER_PLAN.md](VIEWER_PLAN.md).

```bash
cd viewer && npm install && npm run build && cd ..   # once (needs Node 18+)
python3 viewer.py                                     # http://127.0.0.1:8000
```

The Python side is still stdlib only; React is used only for the viewer's frontend in `viewer/`.
For frontend work, run `python3 viewer.py` and `cd viewer && npm run dev` (hot reload, forwards `/api`).
Tests for the data layer: `python3 -m unittest discover tests`.

### Public demo on GitHub Pages

`docs/` holds a static copy of the viewer with one run, so it works with no server:

```bash
python3 viewer.py --export docs --runs v1_20261112_235758 --replace   # regenerate after a new run
```

On GitHub: Settings → Pages → Deploy from a branch → `main` / `/docs`. The site appears at
`https://<user>.github.io/<repo>/`. Everything in `docs/` becomes public, including every prompt and
persona of the exported run (the export refuses to write anything shaped like an API key).

## Files

| File | What it is |
|---|---|
| `config.json` | Everything that defines a run: model, ticks, seed, feed size, seed topic, scheduled news posts |
| `personas/*.json` | One character sheet per agent (3 hand-written, 27 generated): 5 traits (0–1), interests, voice (how they write), starting stance (-1..1), wake_prob |
| `prompts/system.txt` | Identity template, rendered once per agent from its sheet |
| `prompts/tick.txt` | Per-tick template: memory + feed + output format |
| `prompts/post.txt` | Post-turn template: memory + a glance at recent posts + the spark |
| `agent.py` | Trait numbers → behavior sentences (`TRAIT_TEXT`), prompt rendering, JSON parsing, memory |
| `world.py` | Posts, likes, follows, feed ranking, action validation |
| `sim.py` | The tick loop |
| `llm.py` / `mock_llm.py` | Model client (any OpenAI-compatible API) and the offline mock |
| `analyze.py` | Summary, interactions, timeline, blind test, stance over time |
| `trait_test.py` | Milestone 2: one trait low vs high, same feed |
| `gen_personas.py` | Generates personas from archetypes, up to `--count` agents (default 30) |
| `viewer_data.py` | Turns a run log into the JSON the viewer reads (posts, events, turns; prompts split out) |
| `viewer.py` | Local viewer server (127.0.0.1, read-only), or `--export` to static files for GitHub Pages |
| `viewer/` | The React frontend (Vite) |
| `docs/` | Static export of the viewer + one run, for GitHub Pages (generated; don't edit by hand) |
| `tests/` | Unit tests for the viewer's data layer |

## How a tick works

1. Scheduled news stories for this tick appear. `config.json` has 9 stories on different topics from
   different news accounts (NovaCode at ticks 0 and 15, then football, metro fares, a heatwave, ...).
   Each has a `topic` and `keywords`, which `analyze.py` uses for its "talk by topic" table.
2. A few agents are picked to post (see below). The others are shuffled, and each wakes with probability `wake_prob`.
3. Each awake agent sees its top `feed_size` posts plus its last `memory_size` actions, and returns one JSON action.
4. All actions are applied **at the end** of the tick, so same-tick agents don't see each other.

Feed ranking (`world.py`): newer is higher, plus boosts for replies to you (+6), accounts you follow (+3),
news stories (+4), original posts over replies (+1), posts mentioning one of your interests or hobbies (+3)
and likes (+0.5 each). At most 3 posts from any one thread. Without the thread cap, the busiest thread
filled ~80% of every feed: each reply is the newest post, so new stories dropped out after one tick.

The scheduler has its own random seed, so who wakes when is the same across
models. Swap the model and rerun, and the only thing that changed is the model.

## Three kinds of turns

LLMs reply to almost everything if you let them, and with a feed full of posts they never write a new
one. So **code decides what kind of turn an agent gets; the model decides what to do with it.**

- **post turn**: each tick, about `posts_per_tick` agents (config, default 2, randomly more or fewer) are
  picked to post, weighted by `attention_seeking` (+0.05, so even lurkers post now and then). The urge
  wakes them up. They're given a **spark** = a form (passing thought, question, complaint,
  hot take, joke; traits tilt the odds) + a subject (a recent news story, a work interest, a hobby,
  their day, or anything at all). Only news posts see anything from the feed: the story plus a couple
  of reactions. Otherwise the agent is told it isn't thinking about the news right now, because seeing
  the feed pulls every post back to whatever is trending.
  Sparks are categories, never example sentences, because models copy examples.
- **write turn**: reply, like, repost, follow, none. Only 3 posts "catch your eye" and can be replied
  to. Code picks them at random from the feed, weighted toward replies to you, your interests and
  hobbies, news stories and liked posts (`EYE_WEIGHTS` in `agent.py`). People react to what they happen
  to notice; without this, the model always picked the hottest argument in the feed. The eye-catchers
  are shown as A, B, C and the model answers with the letter; code maps it back to the post id. With
  raw ids, ~3% of replies landed under the wrong post once ids reached the hundreds (p235 for p245).
- **react turn**: like, repost, follow, none

Each persona has work `interests` and `hobbies`, a `stance` on NovaCode (the `seed_topic`), and
`opinions` on 3 other stories, e.g. `{"metro fares": -0.8}`. Each story in `config.json` has an
`opinion_on` statement ("the city's 15% metro fare rise"), plus optional `opinion_sides` wording when
"for/against" reads oddly (you're not "against" a football club, you support the other one). The system prompt lists all of an agent's
opinions, NovaCode as just one of them. Posts touching an agent's opinion topics also rank higher in its
feed and catch its eye more. Agents argue about what they have a view on: with an opinion only on
NovaCode, 80% of replies went there; with 4 opinions each, NovaCode fell to 17% of the talk.
Each persona also has a `voice` (how they write). Every voice states its hashtag and emoji habit
explicitly: whatever a voice leaves unsaid, the model fills with its own LinkedIn-style default.

Everyone not picked to post wakes with `wake_prob` and rolls write or react. The chance of a write turn
is `0.1 + 0.7 × attention_seeking`, plus 0.2 if someone replied to you since your last turn. Override it
by adding `"write_prob": 0.5` to a persona file. Posters, wakes, modes and sparks each have their own seed,
so the whole schedule is the same for any model.

Reply rules (in `world.py`): you can't reply to the same post twice, and after 2 replies in a row to
the same person you must reply to someone else first. Rules are enforced through the menu, not
warnings: the reply and like rules list only valid post ids (not yet replied to / not yet liked),
and "reply" or "like" is dropped from the turn when there's nothing valid.

`trait_test.py --mode write|react|post` forces one kind of turn; the default rolls write/react like the sim does.
`--mode post` gives LOW and HIGH the same sparks, so you can see how a trait changes what an agent posts.

## Population (30 agents)

`personas/` holds 3 hand-written personas (riya, marcus, lena) and 27 generated ones (marked
`"generated": true`). A 30-tick run is ~500 calls: ~$0.13 on gpt-4o-mini, and ~$0.12 on gpt-6-luna
(at its listed $0.10 / $0.50 per million tokens; luna writes ~3× the output tokens, likely hidden reasoning).

Set `llm.usd_per_million_tokens` in `config.json` to the model's price. `sim.py` prints the run's cost
at the end, and the viewer shows it. It's copied into each run's log, so old runs keep the price they ran at.

```bash
python3 gen_personas.py                      # regenerate: 30 agents total (free, no LLM)
python3 gen_personas.py --count 50 --seed 7  # a different population
```

`gen_personas.py` builds agents from 13 archetypes (skeptic, founder, student, organizer, investor, ...)
with jittered traits, stance and wake_prob. Rerunning replaces only the generated files; hand-written
personas are kept and count toward the total.

`parallel_calls` in the config sets how many model calls run at once within a tick. That's safe because
the world doesn't change until the end of the tick. Wake and mode rolls still happen in order first,
so the schedule is the same as a sequential run. The mock always runs one call at a time.
The end of each run prints the token counts the API reported.

## Switching models

Edit the `llm` block in `config.json`. Anything with an OpenAI-style `/chat/completions` endpoint works:

| Provider | base_url | api_key_env | model (example) |
|---|---|---|---|
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| Ollama (local, free) | `http://localhost:11434/v1` | `""` | `llama3.2` |
| Groq | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` | `llama-3.1-8b-instant` |
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | any listed model |

Newer OpenAI models (gpt-6-luna) reject two older settings: set `"token_limit_param": "max_completion_tokens"`
(they refuse `max_tokens`) and `"temperature": null` (they only allow the default, 1). Runs at a different
temperature aren't a clean model-vs-model comparison.

`min_seconds_between_calls` keeps you under free-tier rate limits (6s ≈ 10 req/min).
A 30-tick run is about 50 calls, so roughly 5 minutes on Gemini's free tier. For Ollama, set it to 0.
Model names change over time, so check your provider's current list if a call fails with 404.

## Suggested order

1. `python3 sim.py --mock` to confirm everything runs.
2. **Trait test before anything else:**
   `python3 trait_test.py --persona marcus_skeptic --trait agreeableness --runs 5`
   If low and high look the same, rewrite that trait's lines in `agent.py` `TRAIT_TEXT`.
3. Full run: `python3 sim.py --reasons`
4. `python3 analyze.py --blind`. Can you tell A/B/C apart? Then check the key file.
5. `python3 analyze.py --stance`. Does anyone's stance move after the tick-15 memo? (`conformity` should matter here.)
6. `python3 analyze.py --targets`. An LLM judge (one small call per reply, ~$0.02 a run) sees each reply and
   the feed the agent saw, and says which post it answers. A pick on a *different topic* suggests the
   model put the wrong id in `target_id`; another post on the same story is just ambiguity.

## Logs

`logs/<run>_<time>.jsonl` holds the config, each agent's full system prompt, every
user prompt, raw model output, parsed action and result. `<...>_world.json` is the final state.
Nothing is lost, so you can re-analyze old runs at any time.

## Not in v0 (on purpose)

Live UI or humans posting, embeddings or groups, memory summarization, mood, and changing settings during a run.
