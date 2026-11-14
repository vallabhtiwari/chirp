import { useEffect, useMemo, useState } from 'react'
import { getJSON, runUrl } from '../api.js'
import { displayName, indexRun, latestAt, threadsAt } from '../model.js'
import Avatar from './Avatar.jsx'
import EyeView from './EyeView.jsx'
import Inspector from './Inspector.jsx'
import Logo from './Logo.jsx'
import Overview from './Overview.jsx'
import Post from './Post.jsx'
import Profile from './Profile.jsx'
import Thread from './Thread.jsx'
import TickBar from './TickBar.jsx'

const PLAY_MS = 900

// URL query → what the middle column shows. The first one present wins:
//   eye=<tick/agent>   what that agent saw at that turn
//   agent=<name>       a profile
//   thread=<post id>   a whole thread
//   view=overview|latest, else the threads feed
// turn=<tick/agent> opens the inspector beside any of them; t=<tick> sets the time.
export default function RunView({ name, query, go }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [playing, setPlaying] = useState(false)
  useEffect(() => {
    getJSON(runUrl(name)).then(setData, setError)
  }, [name])
  const idx = useMemo(() => (data ? indexRun(data) : null), [data])

  const max = idx?.maxTick ?? 0
  const T = Math.max(0, Math.min(max, query.t !== undefined ? Number(query.t) || 0 : max))
  const set = (changes, opts) => go(['run', name], { ...query, ...changes }, opts)
  const setTick = (t) => set({ t: Math.max(0, Math.min(max, t)) }, { replace: true })
  const page = (changes) => set({ eye: undefined, agent: undefined, thread: undefined, focus: undefined, ...changes })

  useEffect(() => {
    if (!playing) return
    if (T >= max) return setPlaying(false)
    const id = setTimeout(() => setTick(T + 1), PLAY_MS)
    return () => clearTimeout(id)
  })

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.closest('input, textarea, select')) return
      if (e.key === 'ArrowLeft') setTick(T - 1)
      if (e.key === 'ArrowRight') setTick(T + 1)
      if (e.key === 'Escape' && query.turn) set({ turn: undefined })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  useEffect(() => {
    window.scrollTo(0, 0)
  }, [query.eye, query.agent, query.thread, query.view])

  if (error)
    return (
      <div className="page narrow">
        <p className="error">Couldn't load {name}: {String(error.message || error)}</p>
        <a href="#/">All runs</a>
      </div>
    )
  if (!data) return <div className="page narrow"><p className="muted">Loading {name}…</p></div>

  const r = data.run
  const topic = query.topic || ''
  const view = ['latest', 'overview'].includes(query.view) ? query.view : 'threads'
  const turnKey = query.turn
  const why = (p) => set({ turn: p.news ? `news:${p.id}` : p.turn })
  const openThread = (p) =>
    page({ thread: p.repost_of && !p.text ? idx.posts[p.repost_of]?.root : p.root || p.id, focus: p.id })
  const openProfile = (agent) => page({ agent })
  const openEye = (key) => page({ eye: key })
  const openTurn = (key) => set({ turn: key })
  const isSelected = (p) => (p.news ? turnKey === `news:${p.id}` : p.turn && p.turn === turnKey)

  const visible = Object.values(idx.posts).filter((p) => p.tick <= T)
  const stats = {
    posts: visible.length,
    likes: data.events.filter((e) => e.kind === 'like' && e.tick <= T).length,
    newHere: visible.filter((p) => p.tick === T).length,
  }
  const topics = [...new Set(r.topics), 'other'] // two NovaCode stories share one topic
  const people = Object.values(data.agents)
    .filter((a) => !a.is_news)
    .sort((a, b) => a.name.localeCompare(b.name))

  const postProps = { run: data, idx, T, onWhy: why, onThread: openThread, onProfile: openProfile }
  const back = () => page({})
  let feed
  if (query.eye) {
    feed = <EyeView run={data} idx={idx} turnKey={query.eye} onBack={back} onTurn={openTurn} postProps={postProps} />
  } else if (query.agent) {
    feed = (
      <Profile run={data} idx={idx} name={query.agent} T={T} onBack={back} onTurn={openTurn}
        onEye={openEye} postProps={postProps} />
    )
  } else if (query.thread) {
    feed = (
      <Thread {...postProps} root={query.thread} focus={query.focus} turnKey={turnKey} onBack={back} />
    )
  } else if (view === 'overview') {
    feed = <Overview run={data} idx={idx} T={T} onTick={setTick} onAgent={openProfile} />
  } else if (view === 'latest') {
    const posts = latestAt(idx, T, { topic })
    feed = posts.length ? (
      posts.map((p) => <Post key={p.id} {...postProps} post={p} selected={isSelected(p)} isNew={p.tick === T} />)
    ) : (
      <p className="empty muted">Nothing yet at tick {T}.</p>
    )
  } else {
    const threads = threadsAt(idx, T, { topic })
    feed = threads.length ? (
      threads.map((th) => (
        <div key={th.root} className="threadcard">
          <Post {...postProps} post={idx.posts[th.root]} selected={isSelected(idx.posts[th.root])}
            isNew={idx.posts[th.root].tick === T} />
          {th.total > th.replies.length && (
            <button className="more" onClick={() => openThread(idx.posts[th.root])}>
              Show all {th.total} replies
            </button>
          )}
          {th.replies.map((id) => (
            <div key={id} className="inline-reply">
              <Post {...postProps} post={idx.posts[id]} selected={isSelected(idx.posts[id])}
                isNew={idx.posts[id].tick === T} compact />
            </div>
          ))}
        </div>
      ))
    ) : (
      <p className="empty muted">Nothing yet at tick {T}.</p>
    )
  }
  const onFeed = !query.eye && !query.agent && !query.thread

  return (
    <div className={`app ${turnKey ? 'with-inspector' : ''}`}>
      <nav className="side">
        <a className="brand" href="#/">
          <Logo /> <span>Chirp</span>
        </a>
        <div className="runinfo">
          <div className="runname">{r.name}</div>
          <div className="muted">
            {r.provider === 'mock' ? 'mock model' : r.model} · seed {r.seed ?? '?'} · {r.agents} agents
          </div>
          <div className="muted">
            {r.counts.post} posts · {r.counts.reply} replies · {r.counts.like} likes
            {r.cost_usd != null && ` · $${r.cost_usd.toFixed(2)}`}
          </div>
          {!r.complete && <div className="tag warn">incomplete run</div>}
        </div>

        <div className="group">
          <div className="glabel">Show</div>
          <div className="seg">
            <button className={onFeed && view === 'threads' ? 'on' : ''} onClick={() => page({ view: undefined })}>Threads</button>
            <button className={onFeed && view === 'latest' ? 'on' : ''} onClick={() => page({ view: 'latest' })}>Latest</button>
            <button className={onFeed && view === 'overview' ? 'on' : ''} onClick={() => page({ view: 'overview' })}>Overview</button>
          </div>
        </div>

        {r.topics.length > 0 && view !== 'overview' && (
          <div className="group">
            <div className="glabel">Topic</div>
            <div className="chips">
              <button className={`chip ${!topic ? 'on' : ''}`} onClick={() => page({ topic: undefined })}>all</button>
              {topics.map((t) => (
                <button key={t} className={`chip ${topic === t ? 'on' : ''}`} onClick={() => page({ topic: t })}>
                  {t}
                </button>
              ))}
            </div>
          </div>
        )}

        <details className="group agents">
          <summary className="glabel">Agents ({people.length})</summary>
          {people.map((a) => (
            <button key={a.name} className={`agentrow ${query.agent === a.name ? 'on' : ''}`} onClick={() => openProfile(a.name)}>
              <Avatar name={a.name} size={24} />
              <span>{displayName(a.name)}</span>
              <span className="muted">@{a.name}</span>
            </button>
          ))}
        </details>

        <div className="group legend">
          <div className="glabel">Edge colour = who wrote it</div>
          <div><i className="sw sw-news" /> news story (config, no model)</div>
          <div><i className="sw sw-post" /> post turn (code said: post)</div>
          <div><i className="sw sw-write" /> write turn (could reply)</div>
          <div><i className="sw sw-react" /> react turn (no reply offered)</div>
          <p className="muted small">
            Click <b>why?</b> on any post to see what code decided and what the model decided. Click a name for
            their profile.
          </p>
        </div>
      </nav>

      <main className="feed">
        <TickBar T={T} max={max} playing={playing} stats={stats} onTick={setTick}
          onPlay={() => {
            if (!playing && T >= max) setTick(0)
            setPlaying(!playing)
          }} />
        {feed}
      </main>

      {turnKey && (
        <div className="inspector-wrap">
          <Inspector run={data} runName={name} turnKey={turnKey} onClose={() => set({ turn: undefined })}
            onOpen={openThread} onEye={openEye} onProfile={openProfile} />
        </div>
      )}
    </div>
  )
}
