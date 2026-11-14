// Everything the views need, derived from the one run JSON (see viewer_data.py).
// "At tick T" = only what had happened by the end of tick T.

const num = (id) => parseInt(String(id).slice(1), 10) || 0
export const byId = (a, b) => a.tick - b.tick || num(a.id) - num(b.id)

export function indexRun(data) {
  const posts = data.posts
  const children = {}
  const reposts = {}
  const likes = {}
  const thread = {} // root id -> [post ids in the thread, root included]
  for (const p of Object.values(posts).sort(byId)) {
    if (p.reply_to) (children[p.reply_to] ||= []).push(p.id)
    if (p.repost_of) (reposts[p.repost_of] ||= []).push(p.id)
    ;(thread[p.root || p.id] ||= []).push(p.id)
  }
  for (const e of data.events) if (e.kind === 'like') (likes[e.target] ||= []).push(e)
  const ticks = Object.values(posts).map((p) => p.tick)
  const maxTick = data.run.ticks ?? Math.max(0, ...ticks)
  return { posts, children, reposts, likes, thread, maxTick }
}

export function countsAt(idx, id, T) {
  const upTo = (list, tickOf) => (list || []).filter((x) => tickOf(x) <= T).length
  return {
    replies: upTo(idx.children[id], (c) => idx.posts[c].tick),
    reposts: upTo(idx.reposts[id], (c) => idx.posts[c].tick),
    likes: upTo(idx.likes[id], (e) => e.tick),
  }
}

export function topicOf(idx, p) {
  return p.topic || (p.repost_of && idx.posts[p.repost_of]?.topic) || null
}

// Threads visible at tick T, most recently active first, each with its latest replies.
export function threadsAt(idx, T, { topic, previewReplies = 2 } = {}) {
  const out = []
  for (const [root, ids] of Object.entries(idx.thread)) {
    const rootPost = idx.posts[root]
    if (!rootPost || rootPost.tick > T) continue
    if (topic && topicOf(idx, rootPost) !== topic) continue
    const replies = ids.filter((id) => id !== root && idx.posts[id].tick <= T)
    const last = replies.length ? idx.posts[replies[replies.length - 1]].tick : rootPost.tick
    out.push({ root, replies: replies.slice(-previewReplies), total: replies.length, last })
  }
  return out.sort((a, b) => b.last - a.last || num(b.root) - num(a.root))
}

export function latestAt(idx, T, { topic } = {}) {
  return Object.values(idx.posts)
    .filter((p) => p.tick <= T && (!topic || topicOf(idx, p) === topic))
    .sort(byId)
    .reverse()
}

export function displayName(name) {
  const first = String(name).split('_')[0]
  return first.charAt(0).toUpperCase() + first.slice(1)
}

export const pct = (x) => (x === null || x === undefined ? '?' : `${Math.round(x * 100)}%`)

// ---------- agent profile ----------
export function agentStats(data, idx, name, T) {
  const mine = Object.values(idx.posts).filter((p) => p.author === name && p.tick <= T)
  const repliesTo = {}
  const repliedBy = {}
  for (const p of Object.values(idx.posts)) {
    if (!p.reply_to || p.tick > T) continue
    const parent = idx.posts[p.reply_to]
    if (!parent) continue
    if (p.author === name) repliesTo[parent.author] = (repliesTo[parent.author] || 0) + 1
    if (parent.author === name && p.author !== name) repliedBy[p.author] = (repliedBy[p.author] || 0) + 1
  }
  let likesGiven = 0
  let likesGot = 0
  for (const e of data.events) {
    if (e.kind !== 'like' || e.tick > T) continue
    if (e.agent === name) likesGiven++
    if (idx.posts[e.target]?.author === name) likesGot++
  }
  const top = (o) => Object.entries(o).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 5)
  return {
    posts: mine.filter((p) => !p.reply_to && !p.repost_of).length,
    replies: mine.filter((p) => p.reply_to).length,
    reposts: mine.filter((p) => p.repost_of).length,
    likesGiven,
    likesGot,
    repliesGot: Object.values(repliedBy).reduce((a, b) => a + b, 0),
    repliesTo: top(repliesTo),
    repliedBy: top(repliedBy),
    timeline: mine.sort(byId).reverse(),
  }
}

export function turnsOf(data, name, max) {
  const out = []
  for (let t = 1; t <= max; t++) out.push(data.turns[`${t}/${name}`] || { tick: t, agent: name, mode: null })
  return out
}

// ---------- run overview ----------
export function overview(data, idx) {
  const max = idx.maxTick
  const perTick = Array.from({ length: max + 1 }, (_, t) => ({ tick: t, post: 0, write: 0, react: 0, sleep: 0 }))
  const choices = { write: {}, react: {} }
  const quality = { blocked: 0, unparsed: 0, fixed: 0, llm_error: 0, rejected: 0 }
  for (const t of Object.values(data.turns)) {
    if (perTick[t.tick] && t.mode in perTick[t.tick]) perTick[t.tick][t.mode]++
    if (t.mode === 'write' || t.mode === 'react') {
      const a = t.action?.action || 'none'
      choices[t.mode][a] = (choices[t.mode][a] || 0) + 1
    }
    if (t.blocked) quality.blocked++
    if (t.parse_error) quality.unparsed++
    if (t.fixed_target) quality.fixed++
    if (t.llm_error) quality.llm_error++
    if (t.ok === false) quality.rejected++
  }

  // Talk by topic over time: posts, replies, reposts and likes, each counted under the
  // topic of the post (or of the post it's aimed at). Same rule as analyze.py.
  const topics = [...new Set([...data.run.topics, 'other'])]
  const grid = Object.fromEntries(topics.map((t) => [t, Array(max + 1).fill(0)]))
  const add = (topic, tick) => {
    if (topic && grid[topic] && tick <= max) grid[topic][tick]++
  }
  for (const p of Object.values(idx.posts)) if (!p.news) add(topicOf(idx, p), p.tick)
  for (const e of data.events) if (e.kind === 'like') add(topicOf(idx, idx.posts[e.target] || {}), e.tick)
  const rows = topics
    .map((t) => ({ topic: t, cells: grid[t], total: grid[t].reduce((a, b) => a + b, 0) }))
    .filter((r) => r.total > 0)
    .sort((a, b) => b.total - a.total)

  const got = {}
  const active = {}
  for (const p of Object.values(idx.posts)) {
    if (p.news) continue
    active[p.author] = (active[p.author] || 0) + 1
    const parent = p.reply_to && idx.posts[p.reply_to]
    if (parent) got[parent.author] = (got[parent.author] || 0) + 1
  }
  const top = (o) => Object.entries(o).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 8)
  return { perTick, choices, quality, topicRows: rows, repliedTo: top(got), mostActive: top(active) }
}
