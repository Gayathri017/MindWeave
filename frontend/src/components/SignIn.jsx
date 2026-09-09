import { useState } from 'react'
import { supabase } from '../lib/supabase'

export default function SignIn() {
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(event) {
    event.preventDefault()

    if (!email.trim()) {
      setError('Enter your email first.')
      return
    }

    setError(null)
    setSubmitting(true)
    const { error: signInError } = await supabase.auth.signInWithOtp({ email })
    setSubmitting(false)

    if (signInError) {
      setError(signInError.message)
      return
    }

    setSent(true)
  }

  return (
    <div className="centered-screen">
      <div className="signin-card">
        <h1 className="wordmark">mindweave</h1>

        {sent ? (
          <p className="confirmation">
            Check {email} for a sign-in link. You can close this tab.
          </p>
        ) : (
          <form onSubmit={handleSubmit} style={{ display: 'contents' }}>
            <p className="tagline">
              Save what you're thinking about. Watch the connections appear.
            </p>
            <input
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value)
                if (error) setError(null)
              }}
            />
            {error && <p className="error">{error}</p>}
            <button type="submit" disabled={submitting}>
              {submitting ? 'Sending…' : 'Send sign-in link'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
