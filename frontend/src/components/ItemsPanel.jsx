import { useEffect, useRef, useState } from 'react'
import { deleteItem, listItems, saveItem, uploadAudio, uploadDocument } from '../lib/api'
import { useAudioRecorder } from '../hooks/useAudioRecorder'

const URL_PATTERN = /^https?:\/\//i

function timeAgo(isoString) {
  const then = new Date(isoString)
  const seconds = Math.floor((Date.now() - then.getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`
  return then.toLocaleDateString()
}

function formatDuration(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

function PlusIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
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

function DocumentIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="9" y1="13" x2="15" y2="13" />
      <line x1="9" y1="17" x2="13" y2="17" />
    </svg>
  )
}

function formatFieldLabel(key) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function ExtractedDataCard({ data }) {
  const keyFields = Object.entries(data.key_fields || {})
  const lineItems = data.line_items || []
  const figures = data.figures || []

  if (keyFields.length === 0 && lineItems.length === 0 && figures.length === 0) {
    return null
  }

  return (
    <div className="extracted-data">
      {keyFields.length > 0 && (
        <dl className="extracted-fields">
          {keyFields.map(([key, value]) => (
            <div className="extracted-field" key={key}>
              <dt>{formatFieldLabel(key)}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {lineItems.length > 0 && (
        <table className="extracted-line-items">
          <tbody>
            {lineItems.map((item, index) => (
              <tr key={index}>
                <td>{item.description}</td>
                <td>{item.quantity}</td>
                <td>{item.amount || item.unit_price}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {figures.length > 0 && (
        <ul className="extracted-figures">
          {figures.map((figure, index) => (
            <li key={index}>
              <strong>{figure.label}</strong>: {figure.description}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function ItemsPanel({ userEmail, onSignOut, onItemsChanged, width }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [showUploadMenu, setShowUploadMenu] = useState(false)

  const audioFileInputRef = useRef(null)
  const documentFileInputRef = useRef(null)
  const menuRef = useRef(null)

  async function loadItems() {
    try {
      const data = await listItems()
      setItems(data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    async function load() {
      await loadItems()
    }
    load()
  }, [])

  useEffect(() => {
    function handleOutsideClick(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setShowUploadMenu(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [])

  async function handleSubmit(event) {
    event.preventDefault()
    const trimmed = content.trim()
    if (!trimmed || saving) return

    setSaving(true)
    setError(null)
    try {
      const sourceType = URL_PATTERN.test(trimmed) ? 'url' : 'text'
      await saveItem({ sourceType, content: trimmed })
      setContent('')
      await loadItems()
      onItemsChanged?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(itemId) {
    const confirmed = window.confirm(
      'Delete this saved item? Any concepts that only came from it will be removed from your graph too.'
    )
    if (!confirmed) return

    try {
      await deleteItem(itemId)
      await loadItems()
      onItemsChanged?.()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleAudioReady(blobOrFile) {
    setSaving(true)
    setError(null)
    try {
      await uploadAudio(blobOrFile, blobOrFile.name || 'recording.webm')
      await loadItems()
      onItemsChanged?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const recorder = useAudioRecorder({
    onComplete: handleAudioReady,
    onError: (message) => setError(message),
  })

  function handleAudioFileSelected(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file) handleAudioReady(file)
  }

  async function handleDocumentFilesSelected(event) {
    const files = Array.from(event.target.files || [])
    event.target.value = ''
    if (files.length === 0) return

    setSaving(true)
    setError(null)
    const failures = []
    for (const file of files) {
      try {
        await uploadDocument(file)
      } catch (err) {
        failures.push(`${file.name}: ${err.message}`)
      }
    }
    await loadItems()
    onItemsChanged?.()
    setSaving(false)
    if (failures.length > 0) {
      setError(failures.join(' — '))
    }
  }

  return (
    <div className="left-panel" style={{ width }}>
      <div className="panel-header">
        <span className="header wordmark">mindweave</span>
        <button type="button" className="signout-link" onClick={onSignOut} title={userEmail}>
          Sign out
        </button>
      </div>

      <div className="item-list">
        {loading && <p className="panel-hint">Loading&hellip;</p>}
        {!loading && items.length === 0 && (
          <p className="panel-hint">Nothing saved yet &mdash; add your first thought below.</p>
        )}
        {items.map((item) => (
          <div className="item-card" key={item.id}>
            <div className="item-card-header">
              <p className="title">{item.title || item.preview || item.source_url}</p>
              <button
                type="button"
                className="delete-button"
                onClick={() => handleDelete(item.id)}
                aria-label="Delete this item"
                title="Delete"
              >
                &times;
              </button>
            </div>
            <p className="time">{timeAgo(item.created_at)}</p>
            {item.extracted_data && <ExtractedDataCard data={item.extracted_data} />}
            {item.concepts.map((concept, index) => (
              <span className={`tag${index === 0 ? ' orange' : ''}`} key={concept}>
                {concept}
              </span>
            ))}
          </div>
        ))}
      </div>

      <form className="save-form" onSubmit={handleSubmit}>
        {error && <p className="error">{error}</p>}

        {recorder.isRecording ? (
          <div className="recording-bar">
            <span className="recording-dot" />
            <span className="recording-time">Recording&hellip; {formatDuration(recorder.seconds)}</span>
            <button type="button" className="stop-button" onClick={recorder.stop}>
              Stop
            </button>
          </div>
        ) : (
          <div className="save-row">
            <div className="upload-menu-wrapper" ref={menuRef}>
              <button
                type="button"
                className="icon-button"
                onClick={() => setShowUploadMenu((open) => !open)}
                disabled={saving}
                aria-label="More options"
                title="More options"
              >
                <PlusIcon />
              </button>
              {showUploadMenu && (
                <div className="upload-menu">
                  <button
                    type="button"
                    onClick={() => {
                      setShowUploadMenu(false)
                      audioFileInputRef.current?.click()
                    }}
                  >
                    Upload an audio file
                  </button>
                </div>
              )}
            </div>

            <input
              className="save-input"
              placeholder="Paste a link, or save a thought&hellip;"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              disabled={saving}
            />

            <button
              type="button"
              className="icon-button"
              onClick={() => documentFileInputRef.current?.click()}
              disabled={saving}
              aria-label="Upload a document or receipt"
              title="Upload a document or receipt"
            >
              <DocumentIcon />
            </button>

            <button
              type="button"
              className="icon-button"
              onClick={recorder.start}
              disabled={saving}
              aria-label="Record a voice note"
              title="Record a voice note"
            >
              <MicIcon />
            </button>
          </div>
        )}

        <input
          type="file"
          accept="audio/*"
          ref={audioFileInputRef}
          onChange={handleAudioFileSelected}
          style={{ display: 'none' }}
        />
        <input
          type="file"
          accept="application/pdf,image/*"
          multiple
          ref={documentFileInputRef}
          onChange={handleDocumentFilesSelected}
          style={{ display: 'none' }}
        />
      </form>
    </div>
  )
}