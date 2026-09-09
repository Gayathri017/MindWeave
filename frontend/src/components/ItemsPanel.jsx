import { useEffect, useState } from 'react'
import { deleteItem, listItems, saveItem } from '../lib/api'

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

export default function ItemsPanel({ userEmail, onSignOut, onItemsChanged, width }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)

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
        <input
          className="save-input"
          placeholder="Paste a link, or save a thought&hellip;"
          value={content}
          onChange={(event) => setContent(event.target.value)}
          disabled={saving}
        />
      </form>
    </div>
  )
}