// "What did the agent see?" The feed as the model got it at the start of a turn: ranked,
// with the eye-catchers it could reply to marked A/B/C. Counts are as of the end of the
// previous tick, because nothing from the current tick is visible until it ends.
import Post from './Post.jsx'
import { displayName } from '../model.js'

export default function EyeView({ run, idx, turnKey, onBack, onTurn, postProps }) {
  const t = run.turns[turnKey]
  if (!t) return <p className="empty muted">No turn {turnKey} in this run.</p>
  const seen = t.tick - 1
  const labelOf = Object.fromEntries(Object.entries(t.reply_labels || {}).map(([L, id]) => [id, L]))
  const picked = t.action?.target_id
  const props = { ...postProps, T: seen }

  let body
  if (t.mode === 'sleep') {
    body = <p className="empty muted">Asleep this tick: no feed, no model call.</p>
  } else if (t.mode === 'post') {
    body = (
      <>
        <p className="eyenote">
          Post turns don't see the feed. {t.story_id
            ? 'This one was about a news story, so it saw the story and a couple of reactions:'
            : 'It was told it isn\'t thinking about the news right now, and saw nothing.'}
        </p>
        {t.story_id && idx.posts[t.story_id] && <Post {...props} post={idx.posts[t.story_id]} />}
        {(t.glance_ids || []).map((id) => idx.posts[id] && <Post key={id} {...props} post={idx.posts[id]} />)}
      </>
    )
  } else if (!t.feed_ids) {
    body = <p className="empty muted">This run didn't record the feed.</p>
  } else {
    body = (
      <>
        <p className="eyenote">
          {t.feed_ids.length} posts, in the order the feed ranked them.
          {t.reply_labels ? ' Only the lettered ones caught its eye, and those were the only ones it could reply to.' : ''}
          {picked && run.posts[picked] ? ` It chose ${t.action.action} → ${picked}.` : ` It chose ${t.action?.action || 'none'}.`}
        </p>
        {t.feed_ids.map((id, i) => {
          const p = idx.posts[id]
          if (!p) return null
          return (
            <div key={id} className={`ranked ${labelOf[id] ? 'eye' : ''} ${picked === id ? 'chosen' : ''}`}>
              <span className="rank">{i + 1}</span>
              <Post {...props} post={p}
                tag={labelOf[id] && <span className="eyelabel" title="Caught its eye: it could reply to this">{labelOf[id]}</span>} />
            </div>
          )
        })}
      </>
    )
  }

  return (
    <div className="eyeview">
      <div className="threadbar">
        <button className="ghost" onClick={onBack}>← Back</button>
        <span className="muted">
          What @{t.agent} saw at the start of tick {t.tick}
        </span>
        <button className="ghost right" onClick={() => onTurn(turnKey)}>why?</button>
      </div>
      <div className="eyehead">
        <b>{displayName(t.agent)}'s screen</b> · {t.mode ? `${t.mode} turn` : 'turn'} · counts as of tick {seen}
      </div>
      {body}
    </div>
  )
}
