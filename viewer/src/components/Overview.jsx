// Run overview: what happened across the whole run. Charts are hand-drawn SVG (no chart
// library), each with a hover tooltip and a table view.
import { useState } from 'react'
import { overview } from '../model.js'

const SERIES = [
  { key: 'post', label: 'post turns', color: 'var(--k-post)' },
  { key: 'write', label: 'write turns', color: 'var(--k-write)' },
  { key: 'react', label: 'react turns', color: 'var(--k-react)' },
]

function Tip({ tip }) {
  if (!tip) return null
  return (
    <div className="tip" style={{ left: tip.x, top: tip.y }}>
      {tip.lines.map((l, i) => <div key={i} className={i === 0 ? 'tiphead' : ''}>{l}</div>)}
    </div>
  )
}

function useTip() {
  const [tip, setTip] = useState(null)
  const show = (e, lines) => {
    const box = e.currentTarget.closest('.chart').getBoundingClientRect()
    setTip({ x: e.clientX - box.left + 12, y: e.clientY - box.top - 8, lines })
  }
  return [tip, show, () => setTip(null)]
}

function TurnsPerTick({ rows, T, onTick }) {
  const [tip, show, hide] = useTip()
  const W = 600, H = 170, padL = 28, padB = 20, padT = 8
  const n = rows.length
  const max = Math.max(1, ...rows.map((r) => r.post + r.write + r.react))
  const step = (W - padL) / n
  const bw = Math.max(3, step - 2) // 2px surface gap between bars
  const y = (v) => ((H - padB - padT) * v) / max
  const ticks = [0, Math.round(max / 2), max]
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Turns per tick, by turn type">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={padL} x2={W} y1={H - padB - y(v)} y2={H - padB - y(v)} className="grid" />
            <text x={padL - 6} y={H - padB - y(v) + 4} className="axis" textAnchor="end">{v}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          let base = H - padB
          const x = padL + i * step + 1
          return (
            <g key={r.tick} onMouseMove={(e) => show(e, [`tick ${r.tick}`, ...SERIES.map((s) => `${s.label}: ${r[s.key]}`), `asleep: ${r.sleep}`])}
              onMouseLeave={hide} onClick={() => onTick(r.tick)} className={`barcol ${r.tick === T ? 'now' : ''}`}>
              <rect x={x - 1} y={padT} width={step} height={H - padB - padT} className="hit" />
              {SERIES.map((s, si) => {
                const h = y(r[s.key])
                if (!h) return null
                base -= h
                const top = si === SERIES.length - 1 || !SERIES.slice(si + 1).some((t) => r[t.key])
                return <rect key={s.key} x={x} y={base} width={bw} height={Math.max(0, h - 2)} rx={top ? 2 : 0} fill={s.color} />
              })}
            </g>
          )
        })}
        {rows.filter((r) => r.tick % 5 === 0).map((r) => (
          <text key={r.tick} x={padL + r.tick * step + step / 2} y={H - 4} className="axis" textAnchor="middle">t{r.tick}</text>
        ))}
      </svg>
      <Tip tip={tip} />
    </div>
  )
}

function Bars({ entries, color }) {
  const [tip, show, hide] = useTip()
  const total = entries.reduce((a, [, v]) => a + v, 0) || 1
  const max = Math.max(1, ...entries.map(([, v]) => v))
  return (
    <div className="chart hbars">
      {entries.map(([k, v]) => (
        <div key={k} className="hbar" onMouseMove={(e) => show(e, [k, `${v} turns (${Math.round((100 * v) / total)}%)`])} onMouseLeave={hide}>
          <span className="hlabel">{k}</span>
          <span className="htrack"><span style={{ width: `${(100 * v) / max}%`, background: color }} /></span>
          <span className="hval">{v} <span className="muted">· {Math.round((100 * v) / total)}%</span></span>
        </div>
      ))}
      <Tip tip={tip} />
    </div>
  )
}

function TopicHeat({ rows, T, onTick }) {
  const [tip, show, hide] = useTip()
  const max = Math.max(1, ...rows.flatMap((r) => r.cells))
  const steps = [0, 0.18, 0.35, 0.55, 0.78, 1] // sequential: one hue, light to dark
  const level = (v) => (v === 0 ? 0 : 1 + Math.min(4, Math.floor((4 * v) / max)))
  const n = rows[0]?.cells.length || 0
  return (
    <div className="chart heat">
      <div className="heatgrid" style={{ gridTemplateColumns: `112px repeat(${n}, minmax(6px, 1fr)) 44px` }}>
        {rows.map((r) => (
          <div key={r.topic} className="heatrow" style={{ display: 'contents' }}>
            <span className="hlabel">{r.topic}</span>
            {r.cells.map((v, t) => (
              <span key={t} className={`hc ${t === T ? 'now' : ''}`}
                style={{ background: v ? `color-mix(in srgb, var(--brand) ${steps[level(v)] * 100}%, var(--panel-2))` : 'var(--panel-2)' }}
                onMouseMove={(e) => show(e, [`${r.topic} · tick ${t}`, `${v} actions (posts, replies, reposts, likes)`])}
                onMouseLeave={hide} onClick={() => onTick(t)} />
            ))}
            <span className="hval">{r.total}</span>
          </div>
        ))}
      </div>
      <div className="heatlegend muted">
        fewer {steps.slice(1).map((s, i) => <i key={i} style={{ background: `color-mix(in srgb, var(--brand) ${s * 100}%, var(--panel-2))` }} />)} more
        <span> · click a cell to jump to that tick</span>
      </div>
      <Tip tip={tip} />
    </div>
  )
}

function Table({ head, rows }) {
  return (
    <details className="tableview">
      <summary>Show as table</summary>
      <table>
        <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
      </table>
    </details>
  )
}

export default function Overview({ run, idx, T, onTick, onAgent }) {
  const o = overview(run, idx)
  const r = run.run
  const order = (obj) => ['reply', 'like', 'repost', 'follow', 'none'].filter((k) => obj[k]).map((k) => [k, obj[k]])
  const writeTotal = Object.values(o.choices.write).reduce((a, b) => a + b, 0)
  const sleeps = o.perTick.reduce((a, x) => a + x.sleep, 0)
  const awake = o.perTick.reduce((a, x) => a + x.post + x.write + x.react, 0)
  return (
    <div className="overview">
      <div className="threadbar"><span className="muted">Whole run · the highlighted column is tick {T}</span></div>

      <div className="tiles">
        <div><b>{r.counts.post}</b><span>posts</span></div>
        <div><b>{r.counts.reply}</b><span>replies</span></div>
        <div><b>{r.counts.like}</b><span>likes</span></div>
        <div><b>{r.counts.repost}</b><span>reposts</span></div>
        <div><b>{r.counts.follow}</b><span>follows</span></div>
        <div><b>{r.calls ?? '?'}</b><span>model calls</span></div>
        <div><b>{r.tokens ? `${Math.round(r.tokens.input_tokens / 1000)}k / ${Math.round(r.tokens.output_tokens / 1000)}k` : '?'}</b><span>tokens in / out</span></div>
        <div><b>{r.cost_usd != null ? `$${r.cost_usd.toFixed(3)}` : '?'}</b><span>est. cost</span></div>
      </div>

      <section className="ocard">
        <h3>Turns per tick</h3>
        <p className="muted small">Code decides the kind of every turn. {awake} turns in all; agents were asleep {sleeps} times (not drawn).</p>
        <div className="legendrow">{SERIES.map((s) => <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>)}</div>
        <TurnsPerTick rows={o.perTick.slice(1)} T={T} onTick={onTick} />
        <Table head={['tick', 'post', 'write', 'react', 'asleep']} rows={o.perTick.slice(1).map((x) => [x.tick, x.post, x.write, x.react, x.sleep])} />
      </section>

      <section className="ocard two">
        <div>
          <h3>What the model chose on write turns</h3>
          <p className="muted small">Reply was on the menu; {writeTotal} turns.</p>
          <Bars entries={order(o.choices.write)} color="var(--k-write)" />
        </div>
        <div>
          <h3>…and on react turns</h3>
          <p className="muted small">No reply on the menu.</p>
          <Bars entries={order(o.choices.react)} color="var(--k-react)" />
        </div>
      </section>

      {o.topicRows.length > 1 && (
        <section className="ocard">
          <h3>Talk by topic over time</h3>
          <p className="muted small">Posts, replies, reposts and likes, each counted under the topic of the post it belongs to.</p>
          <TopicHeat rows={o.topicRows} T={T} onTick={onTick} />
          <Table head={['topic', 'total', ...o.topicRows[0].cells.map((_, t) => `t${t}`)]} rows={o.topicRows.map((x) => [x.topic, x.total, ...x.cells])} />
        </section>
      )}

      <section className="ocard two">
        <div>
          <h3>Most replied to</h3>
          {o.repliedTo.map(([n, c]) => <button key={n} className="kv link" onClick={() => onAgent(n)}><span>@{n}</span><b>{c}</b></button>)}
        </div>
        <div>
          <h3>Most posts and replies</h3>
          {o.mostActive.map(([n, c]) => <button key={n} className="kv link" onClick={() => onAgent(n)}><span>@{n}</span><b>{c}</b></button>)}
        </div>
      </section>

      <section className="ocard">
        <h3>When code had to step in</h3>
        <div className="tiles small">
          <div><b>{o.quality.fixed}</b><span>post ids fixed (e.g. "26" → p26)</span></div>
          <div><b>{o.quality.blocked}</b><span>picked something not on the menu</span></div>
          <div><b>{o.quality.unparsed}</b><span>answers that weren't valid JSON</span></div>
          <div><b>{o.quality.rejected}</b><span>rejected by world rules</span></div>
          <div><b>{o.quality.llm_error}</b><span>failed model calls</span></div>
        </div>
      </section>
    </div>
  )
}
