import Avatar from './Avatar.jsx'
import { countsAt, displayName, topicOf } from '../model.js'

// The coloured edge on each post says what kind of turn wrote it (see the legend).
export function turnKind(run, post) {
  if (post.news) return 'news'
  return run.turns[post.turn]?.mode || 'unknown'
}

function Header({ run, post, onProfile, tag }) {
  const agent = run.agents[post.author] || {}
  return (
    <div className="posthead">
      <button className="dname" title={agent.bio || ''} onClick={(e) => { e.stopPropagation(); onProfile?.(post.author) }}>
        {post.news ? post.author : displayName(post.author)}
      </button>
      {post.news ? <span className="badge news">NEWS</span> : <span className="handle">@{post.author}</span>}
      {tag}
      <span className="tick" title={`Posted during tick ${post.tick}`}>t{post.tick}</span>
    </div>
  )
}

export function MiniPost({ run, id, label, onOpen, mark }) {
  const p = run.posts[id]
  if (!p) return <div className="mini missing">{id} (not in this run)</div>
  const shown = p.repost_of ? run.posts[p.repost_of] : p
  return (
    <button className={`mini ${mark ? 'marked' : ''}`} onClick={() => onOpen?.(p)} title="Open this thread">
      {label && <span className="label">{label}</span>}
      <span className="minibody">
        <span className="minihead">
          @{p.author} · t{p.tick} · {p.id}
          {p.repost_of && ` · reposted @${shown?.author}`}
          {p.reply_to && ` · reply to @${run.posts[p.reply_to]?.author}`}
        </span>
        <span className="minitext">{shown?.text}</span>
      </span>
    </button>
  )
}

export default function Post({ run, idx, post, T, onWhy, onThread, onProfile, selected, isNew, compact, replyLine = true, tag }) {
  const kind = turnKind(run, post)
  const c = countsAt(idx, post.id, T)
  const original = post.repost_of ? idx.posts[post.repost_of] : null
  const parent = post.reply_to ? idx.posts[post.reply_to] : null
  const topic = topicOf(idx, post)

  return (
    <article className={`post kind-${kind} ${selected ? 'selected' : ''} ${isNew ? 'new' : ''} ${compact ? 'compact' : ''}`}>
      <button className="avbtn" onClick={() => onProfile?.(post.author)} aria-label={`Profile of @${post.author}`}>
        <Avatar name={post.author} news={post.news} size={compact ? 32 : 40} />
      </button>
      <div className="postmain">
        {original ? (
          <>
            <div className="reposter">↻ @{post.author} reposted · t{post.tick}</div>
            <div className="quoted" onClick={() => onThread(original)}>
              <Header run={run} post={original} onProfile={onProfile} tag={tag} />
              <p className="text">{original.text}</p>
            </div>
          </>
        ) : (
          <>
            <Header run={run} post={post} onProfile={onProfile} tag={tag} />
            {replyLine && parent && <div className="replyto">replying to @{parent.author}</div>}
            <p className="text" onClick={() => onThread(post)}>
              {post.text}
            </p>
          </>
        )}
        <div className="postfoot">
          <button className="count" onClick={() => onThread(post)} title="Replies by this tick">
            💬 {c.replies}
          </button>
          <span className="count" title="Reposts by this tick">↻ {c.reposts}</span>
          <span className="count" title="Likes by this tick">♥ {c.likes}</span>
          {topic && topic !== 'other' && <span className="topic">#{topic.replace(/\s+/g, '')}</span>}
          <button className={`why ${selected ? 'on' : ''}`} onClick={() => onWhy(post)} title="See the turn behind this post">
            why?
          </button>
        </div>
      </div>
    </article>
  )
}
