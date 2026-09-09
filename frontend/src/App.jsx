import { useAuth } from './hooks/useAuth'
import SignIn from './components/SignIn'

export default function App() {
  const { session, loading } = useAuth()

  if (loading) {
    return <div className="centered-screen wordmark">mindweave</div>
  }

  if (!session) {
    return <SignIn />
  }

  return (
    <div className="centered-screen">
      <p>Signed in as {session.user.email}. The three panels come next.</p>
    </div>
  )
}
