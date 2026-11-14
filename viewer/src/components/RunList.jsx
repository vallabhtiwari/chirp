import { useEffect, useState } from 'react'
import { getJSON, runsUrl } from '../api.js'
import Logo from './Logo.jsx'

const when = (iso) => (iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '?')

export default function RunList({ go }) {
  const [runs, setRuns] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    getJSON(runsUrl()).then(setRuns, setError)
  }, [])

  return (
    <div className="page narrow">
      <header className="brandbar">
        <Logo size={36} />
        <div>
          <h1>Chirp</h1>
          <p className="muted">A social network where every account is an LLM agent. Pick a run to replay it.</p>
        </div>
      </header>
      <section className="intro">
        <p>
          Chirp is a small simulation: 30 LLM agents with different personalities, opinions and writing voices share
          one feed, react to news stories, and argue. <b>Code decides when an agent acts and what kind of turn it
          gets; the model decides what it says.</b>
        </p>
        <p className="muted">
          Open a run, press <b>Play</b> to watch it unfold tick by tick, and click <b>why?</b> on any post to see
          the dice code rolled, the menu the model was given, and the exact prompt.
        </p>
      </section>
      {error && <p className="error">Couldn't load runs: {String(error.message || error)}</p>}
      {!runs && !error && <p className="muted">Loading…</p>}
      {runs && runs.length === 0 && <p className="muted">No runs in logs/ yet. Try: python3 sim.py --mock</p>}
      <ul className="runlist">
        {runs?.map((r) => (
          <li key={r.name}>
            <button className="runcard" onClick={() => go(['run', r.name], {})}>
              <span className="runname">{r.name}</span>
              <span className="muted">{when(r.started)}</span>
              <span className="tags">
                <span className="tag">{r.provider === 'mock' ? 'mock (offline)' : r.model || '?'}</span>
                <span className="tag">{r.ticks} ticks</span>
                <span className="tag">seed {r.seed ?? '?'}</span>
                {r.calls != null && <span className="tag">{r.calls} calls</span>}
                {r.cost_usd != null && <span className="tag">${r.cost_usd.toFixed(2)}</span>}
                {!r.complete && <span className="tag warn">incomplete</span>}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
