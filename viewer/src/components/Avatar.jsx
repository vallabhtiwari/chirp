// Generated avatars: agents are round with a colour from their name; news desks are square.
function hue(name) {
  let h = 0
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360
  return h
}

export default function Avatar({ name, news, size = 40 }) {
  const initials = name.split('_').map((w) => w[0]).join('').slice(0, 2).toUpperCase()
  const style = {
    width: size,
    height: size,
    fontSize: size * 0.38,
    background: news ? 'var(--news)' : `hsl(${hue(name)} 55% 45%)`,
    borderRadius: news ? 8 : '50%',
  }
  return (
    <div className="avatar" style={style} aria-hidden="true">
      {initials}
    </div>
  )
}
