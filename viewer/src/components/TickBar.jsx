export default function TickBar({ T, max, playing, onTick, onPlay, stats }) {
  return (
    <div className="tickbar">
      <div className="tickrow">
        <button className="iconbtn" onClick={() => onTick(T - 1)} disabled={T <= 0} aria-label="Previous tick">
          ◀
        </button>
        <input
          type="range"
          min={0}
          max={max}
          value={T}
          onChange={(e) => onTick(Number(e.target.value))}
          aria-label="Tick"
        />
        <button className="iconbtn" onClick={() => onTick(T + 1)} disabled={T >= max} aria-label="Next tick">
          ▶
        </button>
        <button className="play" onClick={onPlay}>
          {playing ? '❚❚ Pause' : T >= max ? '↺ Replay' : '▶ Play'}
        </button>
      </div>
      <div className="tickinfo">
        <strong>
          Tick {T} <span className="muted">/ {max}</span>
        </strong>
        <span className="muted">
          {stats.posts} posts · {stats.likes} likes so far · {stats.newHere} new this tick
        </span>
      </div>
    </div>
  )
}
