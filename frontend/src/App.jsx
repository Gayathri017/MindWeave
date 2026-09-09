import { useEffect, useState } from 'react'
import { useAuth } from './hooks/useAuth'
import { supabase } from './lib/supabase'
import SignIn from './components/SignIn'
import ItemsPanel from './components/ItemsPanel'
import ChatPanel from './components/ChatPanel'
import GraphPanel from './components/GraphPanel'

const MIN_PANEL_WIDTH = 220
const MAX_LEFT_WIDTH = 480
const MAX_RIGHT_WIDTH = 560
const HANDLE_WIDTH = 6
const MIN_MIDDLE_WIDTH = 280
const MOBILE_QUERY = '(max-width: 768px)'

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max)
}

export default function App() {
  const { session, loading } = useAuth()
  const [refreshKey, setRefreshKey] = useState(0)
  const [leftWidth, setLeftWidth] = useState(300)
  const [rightWidth, setRightWidth] = useState(380)
  const [isMobile, setIsMobile] = useState(() => window.matchMedia(MOBILE_QUERY).matches)

  // Below the breakpoint, panels stack and scroll instead of sitting
  // side-by-side -- dragging to resize doesn't make sense there, so we
  // track screen size here and skip both the width props and the drag
  // handles entirely on mobile, letting CSS take over the layout.
  useEffect(() => {
    const mediaQuery = window.matchMedia(MOBILE_QUERY)
    function handleChange(event) {
      setIsMobile(event.matches)
    }
    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [])

  // Each drag creates its own mousemove/mouseup closures, capturing the
  // starting position and width at that moment -- this avoids the classic
  // stale-closure bug where a listener added once keeps referencing
  // outdated state on every subsequent render.
  function startDrag(side) {
    return function onMouseDown(event) {
      const startX = event.clientX
      const startLeft = leftWidth
      const startRight = rightWidth

      function onMouseMove(moveEvent) {
        const delta = moveEvent.clientX - startX
        const available = window.innerWidth - 2 * HANDLE_WIDTH - MIN_MIDDLE_WIDTH

        if (side === 'left') {
          const maxLeft = Math.max(MIN_PANEL_WIDTH, Math.min(MAX_LEFT_WIDTH, available - startRight))
          setLeftWidth(clamp(startLeft + delta, MIN_PANEL_WIDTH, maxLeft))
        } else {
          const maxRight = Math.max(MIN_PANEL_WIDTH, Math.min(MAX_RIGHT_WIDTH, available - startLeft))
          setRightWidth(clamp(startRight - delta, MIN_PANEL_WIDTH, maxRight))
        }
      }

      function onMouseUp() {
        window.removeEventListener('mousemove', onMouseMove)
        window.removeEventListener('mouseup', onMouseUp)
      }

      window.addEventListener('mousemove', onMouseMove)
      window.addEventListener('mouseup', onMouseUp)
    }
  }

  if (loading) {
    return <div className="centered-screen wordmark">mindweave</div>
  }

  if (!session) {
    return <SignIn />
  }

  return (
    <div className="app-shell">
      <ItemsPanel
        userEmail={session.user.email}
        onSignOut={() => supabase.auth.signOut()}
        onItemSaved={() => setRefreshKey((key) => key + 1)}
        width={isMobile ? undefined : leftWidth}
      />
      {!isMobile && <div className="resize-handle" onMouseDown={startDrag('left')} />}
      <ChatPanel />
      {!isMobile && <div className="resize-handle" onMouseDown={startDrag('right')} />}
      <GraphPanel refreshKey={refreshKey} width={isMobile ? undefined : rightWidth} />
    </div>
  )
}