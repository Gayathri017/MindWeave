import { useState } from 'react'
import { askQuestion } from '../lib/api'

export default function ChatPanel() {
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(event) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || asking) return

    setMessages((prev) => [...prev, { role: 'user', text: trimmed }])
    setQuestion('')
    setAsking(true)
    setError(null)

    try {
      const response = await askQuestion(trimmed)
      setMessages((prev) => [...prev, { role: 'answer', text: response.answer }])
    } catch (err) {
      setError(err.message)
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="middle-panel">
      <div className="header wordmark">Ask your mind</div>

      <div className="chat">
        {messages.length === 0 && (
          <p className="panel-hint dark">Ask a question about anything you've saved.</p>
        )}
        {messages.map((message, index) => (
          <div className={`bubble ${message.role === 'user' ? 'user' : 'answer'}`} key={index}>
            {message.text}
          </div>
        ))}
        {asking && <div className="bubble answer">Thinking&hellip;</div>}
      </div>

      <form className="chat-form" onSubmit={handleSubmit}>
        {error && <p className="error dark">{error}</p>}
        <input
          className="chat-input"
          placeholder="Ask a question about what you've saved&hellip;"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={asking}
        />
      </form>
    </div>
  )
}
