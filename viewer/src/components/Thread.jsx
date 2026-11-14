import Post from './Post.jsx'

// A whole thread as a tree, up to tick T. Deep replies stop indenting after a few levels.
export default function Thread({ run, idx, root, T, focus, turnKey, onWhy, onProfile, onBack }) {
  const rootPost = idx.posts[root]
  if (!rootPost) return <p className="muted">No post {root} in this run.</p>
  if (rootPost.tick > T)
    return (
      <div className="empty">
        <p>This thread starts at tick {rootPost.tick}; you're at tick {T}.</p>
        <button className="ghost" onClick={onBack}>Back to the feed</button>
      </div>
    )
  const render = (id, depth) => {
    const p = idx.posts[id]
    if (!p || p.tick > T) return null
    const kids = (idx.children[id] || []).filter((c) => idx.posts[c].tick <= T)
    return (
      <div key={id} className={`node ${depth ? 'child' : ''}`} style={{ marginLeft: Math.min(depth, 4) * 18 }}>
        <Post
          run={run}
          idx={idx}
          post={p}
          T={T}
          onWhy={onWhy}
          onProfile={onProfile}
          onThread={() => {}}
          selected={p.turn === turnKey || (p.news && turnKey === `news:${p.id}`)}
          isNew={p.id === focus}
          compact={depth > 0}
          replyLine={false}
        />
        {kids.map((c) => render(c, depth + 1))}
      </div>
    )
  }
  const count = idx.thread[root].filter((id) => idx.posts[id].tick <= T).length
  return (
    <div className="threadview">
      <div className="threadbar">
        <button className="ghost" onClick={onBack}>← Feed</button>
        <span className="muted">
          Thread {root} · {count} post{count === 1 ? '' : 's'} by tick {T}
        </span>
      </div>
      {render(root, 0)}
    </div>
  )
}
