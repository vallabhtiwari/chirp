// The turn behind an action, split the way Chirp works (HOW_IT_WORKS.md §0.1):
// what code decided, what the model decided, and what code checked afterwards.
import { useEffect, useState } from 'react'
import { getJSON, promptsUrl } from '../api.js'
import { pct } from '../model.js'
import { MiniPost } from './Post.jsx'
import Avatar from './Avatar.jsx'

const NOT_RECORDED = <span className="muted">not recorded in this run</span>

function Section({ who, title, children }) {
  return (
    <section className={`isec ${who}`}>
      <h3>
        <span className="who">{who === 'code' ? 'CODE' : who === 'model' ? 'MODEL' : 'CODE'}</span> {title}
      </h3>
      {children}
    </section>
  )
}

function Row({ k, children }) {
  return (
    <div className="irow">
      <span className="k">{k}</span>
      <span className="v">{children}</span>
    </div>
  )
}

function Prompts({ runName, agent, turnKey }) {
  const [state, setState] = useState({ open: false })
  useEffect(() => setState({ open: false }), [turnKey])
  if (!state.open)
    return (
      <button
        className="ghost"
        onClick={() => {
          setState({ open: true })
          getJSON(promptsUrl(runName, agent)).then(
            (p) => setState({ open: true, p }),
            (e) => setState({ open: true, error: String(e.message || e) }),
          )
        }}
      >
        Show the exact prompts and raw answer
      </button>
    )
  if (state.error) return <p className="error">{state.error}</p>
  if (!state.p) return <p className="muted">Loading prompts…</p>
  const t = state.p.turns[turnKey] || {}
  return (
    <div className="prompts">
      <details>
        <summary>System prompt (same every turn for @{agent})</summary>
        <pre>{state.p.system_prompt}</pre>
      </details>
      <details open>
        <summary>User prompt for this turn</summary>
        <pre>{t.user_prompt ?? 'not recorded'}</pre>
      </details>
      <details open>
        <summary>Raw model answer</summary>
        <pre>{t.raw ?? 'not recorded'}</pre>
      </details>
    </div>
  )
}

function NewsInspector({ run, post, onClose }) {
  return (
    <aside className="inspector">
      <div className="ihead">
        <Avatar name={post.author} news size={36} />
        <div>
          <strong>@{post.author}</strong> · tick {post.tick}
          <div className="muted">scheduled news story</div>
        </div>
        <button className="iconbtn close" onClick={onClose} aria-label="Close">✕</button>
      </div>
      <Section who="code" title="decided everything">
        <p>
          News stories are written in <code>config.json</code> and appear at a fixed tick. No model is involved.
          They're what gives the agents something to talk about.
        </p>
        {post.topic && <Row k="topic">{post.topic}</Row>}
      </Section>
    </aside>
  )
}

export default function Inspector({ run, turnKey, runName, onClose, onOpen, onEye, onProfile }) {
  if (turnKey?.startsWith('news:')) {
    const post = run.posts[turnKey.slice(5)]
    if (post) return <NewsInspector run={run} post={post} onClose={onClose} />
  }
  const t = run.turns[turnKey]
  if (!t)
    return (
      <aside className="inspector">
        <p className="muted">No turn {turnKey} in this run.</p>
        <button className="ghost" onClick={onClose}>Close</button>
      </aside>
    )
  const a = run.agents[t.agent] || {}
  const act = t.action || {}
  const labels = t.reply_labels ? Object.entries(t.reply_labels) : null
  const eye = new Set(labels ? labels.map(([, id]) => id) : t.reply_targets || [])
  const [form, subject] = (t.spark || '').split('/')

  return (
    <aside className="inspector">
      <div className="ihead">
        <Avatar name={t.agent} size={36} />
        <div>
          <strong>@{t.agent}</strong> · tick {t.tick}
          <div className="muted">
            {t.mode ? `${t.mode} turn` : 'turn'}
            {a.bio ? ` · ${a.bio}` : ''}
          </div>
        </div>
        <button className="iconbtn close" onClick={onClose} aria-label="Close">✕</button>
      </div>
      <div className="iactions">
        {t.mode !== 'sleep' && <button className="ghost" onClick={() => onEye(turnKey)}>See their screen</button>}
        <button className="ghost" onClick={() => onProfile(t.agent)}>Profile</button>
      </div>

      <Section who="code" title="decided">
        {t.mode === 'sleep' && (
          <>
            <Row k="woke up?">no. Chance each tick: {pct(a.wake_prob)}</Row>
            <p className="muted">No model call. As far as the model knows, this tick never happened.</p>
          </>
        )}
        {t.mode === 'post' && (
          <>
            <Row k="turn type">
              post turn. Picked to post this tick (≈{pct(a.post_chance)} chance per tick, weighted by
              attention_seeking {a.traits?.attention_seeking ?? '?'})
            </Row>
            <Row k="spark">
              {t.spark ? (
                <>
                  a <b>{form?.replace('_', ' ')}</b> about <b>{subject}</b>
                </>
              ) : (
                NOT_RECORDED
              )}
            </Row>
            {t.story_id ? (
              <Row k="shown">
                the story, plus {t.glance_ids?.length || 0} reaction(s):
                <MiniPost run={run} id={t.story_id} onOpen={onOpen} />
                {(t.glance_ids || []).map((id) => (
                  <MiniPost key={id} run={run} id={id} onOpen={onOpen} />
                ))}
              </Row>
            ) : (
              <Row k="shown">nothing from the feed (told it isn't thinking about the news right now)</Row>
            )}
            <Row k="menu">none. A post turn must post; the model only chooses the words.</Row>
          </>
        )}
        {(t.mode === 'write' || t.mode === 'react' || !t.mode) && (
          <>
            <Row k="woke up?">yes. Chance each tick: {pct(a.wake_prob)}</Row>
            <Row k="turn type">
              {t.mode ? (
                <>
                  {t.mode} turn. Write chance {pct(t.p_write)}
                  {t.replied_to ? ' (includes +20%: someone replied to them since their last turn)' : ''}
                  {t.mode === 'react' ? ', so react had ' + pct(1 - (t.p_write ?? 0)) : ''}
                </>
              ) : (
                NOT_RECORDED
              )}
            </Row>
            <Row k="menu">
              {t.allowed ? t.allowed.map((x) => <span key={x} className="chip">{x}</span>) : NOT_RECORDED}
              {t.mode === 'react' && <div className="muted">React turns never offer reply.</div>}
            </Row>
            {t.mode !== 'react' && (
              <Row k="caught its eye">
                {labels ? (
                  <>
                    <div className="muted">The only posts it could reply to, picked at random (weighted):</div>
                    {labels.map(([L, id]) => (
                      <MiniPost key={L} run={run} id={id} label={L} onOpen={onOpen} mark={act.target_label === L} />
                    ))}
                  </>
                ) : t.reply_targets ? (
                  <span className="muted">{t.reply_targets.join(', ')} (by id; this run predates A/B/C letters)</span>
                ) : (
                  NOT_RECORDED
                )}
              </Row>
            )}
            {t.like_targets && <Row k="could like">{t.like_targets.length} posts it hadn't liked yet</Row>}
            {t.feed_ids && (
              <details className="feedseen">
                <summary>The feed it saw ({t.feed_ids.length} posts, ranked)</summary>
                {t.feed_ids.map((id) => (
                  <MiniPost key={id} run={run} id={id} onOpen={onOpen} mark={eye.has(id)} />
                ))}
              </details>
            )}
          </>
        )}
      </Section>

      {t.mode !== 'sleep' && (
        <Section who="model" title="decided">
          <Row k="action">
            <span className="chip strong">{act.action || 'none'}</span>
            {act.target_label && <span className="muted"> answered “{act.target_label}”</span>}
          </Row>
          {act.text && <blockquote className="said">{act.text}</blockquote>}
          {act.reason && (
            <Row k="private reason">
              <i>{act.reason}</i>
            </Row>
          )}
        </Section>
      )}

      {t.mode !== 'sleep' && (
        <Section who="check" title="checked and applied">
          {act.target_label && (
            <Row k="letter → post">
              {act.target_label} → {act.target_id}
            </Row>
          )}
          {t.fixed_target && <Row k="fixed id">{t.fixed_target}</Row>}
          {t.blocked && <Row k="blocked">{t.blocked} wasn't on the menu, so it became “none”</Row>}
          {t.parse_error && <Row k="unparsed">{t.parse_error}, so it became “none”</Row>}
          {t.llm_error && <Row k="LLM error">{t.llm_error}</Row>}
          <Row k="result">
            {t.ok === false
              ? 'rejected by the world rules'
              : t.result_post
                ? `created ${t.result_post}`
                : act.action && act.action !== 'none'
                  ? `${act.action} ${act.target_id ?? ''}`
                  : 'nothing'}
          </Row>
          <p className="muted">
            Applied at the end of tick {t.tick}, so other agents see it from tick {t.tick + 1}.
          </p>
        </Section>
      )}

      {t.mode !== 'sleep' && <Prompts runName={runName} agent={t.agent} turnKey={turnKey} />}
    </aside>
  )
}
