import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { askQuestion, transcribeAudio } from '../lib/api'
import { useAudioRecorder } from '../hooks/useAudioRecorder'

function formatDuration(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

function MicIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  )
}

export default function ChatPanel() {
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [error, setError] = useState(null)

  async function ask(trimmed) {
    setMessages((prev) => [...prev, { role: 'user', text: trimmed }])
    setQuestion('')
    setAsking(true)
    setError(null)

    try {
      const response = await askQuestion(trimmed)
      setMessages((prev) => [...prev, { role: 'answer', text: response.answer, image: response.image }])
    } catch (err) {
      setError(err.message)
    } finally {
      setAsking(false)
    }
  }

  async function handleSubmit(event) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || asking) return
    await ask(trimmed)
  }

  async function handleVoiceQuestion(audioBlob) {
    setTranscribing(true)
    setError(null)
    try {
      const { text } = await transcribeAudio(audioBlob)
      const trimmed = text.trim()
      if (trimmed) await ask(trimmed)
    } catch (err) {
      setError(err.message)
    } finally {
      setTranscribing(false)
    }
  }

  const recorder = useAudioRecorder({
    onComplete: handleVoiceQuestion,
    onError: (message) => setError(message),
  })

  const busy = asking || transcribing || recorder.isRecording

  return (
    <div className="middle-panel">
      <div className="header wordmark">Ask your mind</div>

      <div className="chat">
        {messages.length === 0 && (
          <p className="panel-hint dark">Ask a question about anything you've saved.</p>
        )}
        {messages.map((message, index) => (
          <div className={`bubble ${message.role === 'user' ? 'user' : 'answer'}`} key={index}>
            {message.role === 'answer' ? (
              <ReactMarkdown>{message.text}</ReactMarkdown>
            ) : (
              message.text
            )}
            {message.image && <img className="chat-generated-image" src={message.image} alt="" />}
          </div>
        ))}
        {transcribing && <div className="bubble answer">Listening&hellip;</div>}
        {asking && <div className="bubble answer">Thinking&hellip;</div>}
      </div>

      <form className="chat-form" onSubmit={handleSubmit}>
        {error && <p className="error dark">{error}</p>}

        {recorder.isRecording ? (
          <div className="chat-recording-bar">
            <span className="recording-dot" />
            <span className="recording-time">Recording&hellip; {formatDuration(recorder.seconds)}</span>
            <button type="button" className="stop-button" onClick={recorder.stop}>
              Stop
            </button>
          </div>
        ) : (
          <div className="chat-row">
            <input
              className="chat-input"
              placeholder="Ask a question about what you've saved&hellip;"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              disabled={busy}
            />
            <button
              type="button"
              className="chat-mic-button"
              onClick={recorder.start}
              disabled={busy}
              aria-label="Ask by voice"
              title="Ask by voice"
            >
              <MicIcon />
            </button>
          </div>
        )}
      </form>
    </div>
  )
}