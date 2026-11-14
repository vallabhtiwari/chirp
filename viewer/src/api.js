// Relative paths: served by viewer.py locally and as plain files on GitHub Pages.
const cache = new Map()

export function getJSON(path) {
  if (!cache.has(path)) {
    const p = fetch(path).then((r) => {
      if (!r.ok) throw new Error(`${path}: ${r.status}`)
      return r.json()
    })
    p.catch(() => cache.delete(path)) // let a failed fetch be retried
    cache.set(path, p)
  }
  return cache.get(path)
}

export const runsUrl = () => 'api/runs.json'
export const runUrl = (name) => `api/run/${encodeURIComponent(name)}.json`
export const promptsUrl = (name, agent) =>
  `api/run/${encodeURIComponent(name)}/prompts/${encodeURIComponent(agent)}.json`
