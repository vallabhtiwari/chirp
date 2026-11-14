// Hash routing: the view lives in the URL after "#", so links are shareable, Back and
// refresh work, and it runs on GitHub Pages (which can't route paths to index.html).
//   #/                                         run list
//   #/run/<name>?t=12&thread=p1&turn=19/marcus  a run at tick 12, a thread open, a turn inspected
import { useCallback, useEffect, useState } from 'react'

export function parseHash(hash) {
  const raw = (hash || '').replace(/^#/, '') || '/'
  const [path, query = ''] = raw.split('?')
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent)
  return { parts, query: Object.fromEntries(new URLSearchParams(query)) }
}

export function buildHash(parts, query = {}) {
  const kept = Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== '')
  const q = new URLSearchParams(kept).toString()
  return '#/' + parts.map(encodeURIComponent).join('/') + (q ? '?' + q : '')
}

export function useRoute() {
  const [route, setRoute] = useState(() => parseHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  // replace: true for steps that shouldn't each become a Back-button stop (tick scrubbing).
  const go = useCallback((parts, query, { replace = false } = {}) => {
    const hash = buildHash(parts, query)
    if (replace) {
      window.history.replaceState(null, '', hash)
      setRoute(parseHash(hash))
    } else {
      window.location.hash = hash
    }
  }, [])
  return [route, go]
}
