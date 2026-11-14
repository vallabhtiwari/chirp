import { useRoute } from './route.js'
import RunList from './components/RunList.jsx'
import RunView from './components/RunView.jsx'

export default function App() {
  const [route, go] = useRoute()
  const [first, name] = route.parts
  if (first === 'run' && name) return <RunView key={name} name={name} query={route.query} go={go} />
  return <RunList go={go} />
}
