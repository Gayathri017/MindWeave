import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
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

function localDateKey(isoString) {
  const date = new Date(isoString)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function formatShortDate(isoString) {
  return new Date(isoString).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

const RESURFACE_MIN_AGE_MS = 48 * 60 * 60 * 1000
const RESURFACE_DISMISS_KEY_PREFIX = 'mindweave:resurface-dismissed:'

function todayKey() {
  return new Date().toISOString().slice(0, 10)
}

// A small deterministic hash of today's date, so the resurfaced item stays
// the same all day (and across tabs/reloads) but changes tomorrow -- no
// server-side state needed for something this low-stakes.
function dayHash(dateKey) {
  let hash = 0
  for (let i = 0; i < dateKey.length; i++) {
    hash = (hash * 31 + dateKey.charCodeAt(i)) >>> 0
  }
  return hash
}

function pickResurfacedItem(items) {
  const eligible = items.filter((item) => Date.now() - new Date(item.created_at).getTime() > RESURFACE_MIN_AGE_MS)
  if (eligible.length === 0) return null
  const index = dayHash(todayKey()) % eligible.length
  return eligible[index]
}

function isResurfaceDismissedToday(itemId) {
  try {
    return localStorage.getItem(RESURFACE_DISMISS_KEY_PREFIX + todayKey()) === itemId
  } catch {
    return false
  }
}

function dismissResurfaceToday(itemId) {
  try {
    localStorage.setItem(RESURFACE_DISMISS_KEY_PREFIX + todayKey(), itemId)
  } catch {
    // Best-effort -- private browsing or a full storage quota just means
    // the card reappears next reload, which is harmless.
  }
}

function formatFieldLabel(key) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function ExtractedDataCard({ data }) {
  const keyFields = Object.entries(data.key_fields || {})
  const lineItems = data.line_items || []
  const figures = data.figures || []
  const keyPoints = data.key_points || []

  if (keyFields.length === 0 && lineItems.length === 0 && figures.length === 0 && keyPoints.length === 0) {
    return null
  }

  return (
    <div className="extracted-data">
      {data.video_url && (
        <a className="extracted-video-link" href={data.video_url} target="_blank" rel="noreferrer">
          Watch on YouTube ↗
        </a>
      )}

      {keyPoints.length > 0 && (
        <ul className="extracted-figures">
          {keyPoints.map((point, index) => (
            <li key={index}>{point}</li>
          ))}
        </ul>
      )}

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

function ItemCard({ item, onDelete }) {
  return (
    <div className="item-card" id={`item-${item.id}`}>
      <div className="item-card-header">
        <p className="title">{item.title || item.preview || item.source_url}</p>
        <button
          type="button"
          className="delete-button"
          onClick={() => onDelete(item.id)}
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
  )
}

const VIEW_MODES = ['list', 'table', 'calendar']

const TYPE_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'note', label: 'Notes' },
  { id: 'link', label: 'Links' },
  { id: 'video', label: 'Videos' },
  { id: 'audio', label: 'Audio' },
  { id: 'document', label: 'Documents' },
]

function itemTypeCategory(item) {
  if (item.source_type === 'url' && item.extracted_data?.video_url) return 'video'
  if (item.source_type === 'url') return 'link'
  if (item.source_type === 'text') return 'note'
  return item.source_type
}

function TableView({ items, onDelete }) {
  const [sortKey, setSortKey] = useState('date')
  const [sortDir, setSortDir] = useState('desc')

  function toggleSort(key) {
    if (sortKey === key) {
      setSortDir((dir) => (dir === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const sorted = [...items].sort((a, b) => {
    let result
    if (sortKey === 'title') {
      result = (a.title || a.preview || '').localeCompare(b.title || b.preview || '')
    } else if (sortKey === 'type') {
      result = a.source_type.localeCompare(b.source_type)
    } else {
      result = new Date(a.created_at) - new Date(b.created_at)
    }
    return sortDir === 'asc' ? result : -result
  })

  function sortIndicator(key) {
    if (sortKey !== key) return ''
    return sortDir === 'asc' ? ' ↑' : ' ↓'
  }

  return (
    <table className="items-table">
      <thead>
        <tr>
          <th onClick={() => toggleSort('title')}>Title{sortIndicator('title')}</th>
          <th onClick={() => toggleSort('type')}>Type{sortIndicator('type')}</th>
          <th onClick={() => toggleSort('date')}>Date{sortIndicator('date')}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {sorted.map((item) => (
          <tr key={item.id} id={`item-${item.id}`}>
            <td>{item.title || item.preview || item.source_url}</td>
            <td>
              <span className="tag">{item.source_type}</span>
            </td>
            <td>{formatShortDate(item.created_at)}</td>
            <td>
              <button
                type="button"
                className="delete-button"
                onClick={() => onDelete(item.id)}
                aria-label="Delete this item"
                title="Delete"
              >
                &times;
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function CalendarView({ items, onDelete }) {
  const [monthOffset, setMonthOffset] = useState(0)
  const [selectedDay, setSelectedDay] = useState(null)

  const itemsByDay = {}
  for (const item of items) {
    const key = localDateKey(item.created_at)
    ;(itemsByDay[key] ||= []).push(item)
  }

  const today = new Date()
  const viewedMonth = new Date(today.getFullYear(), today.getMonth() + monthOffset, 1)
  const year = viewedMonth.getFullYear()
  const month = viewedMonth.getMonth()
  const firstWeekday = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()

  const cells = []
  for (let i = 0; i < firstWeekday; i++) cells.push(null)
  for (let day = 1; day <= daysInMonth; day++) cells.push(day)

  function dayKey(day) {
    return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
  }

  const selectedItems = selectedDay ? itemsByDay[selectedDay] || [] : []

  return (
    <div className="calendar-view">
      <div className="calendar-nav">
        <button type="button" className="calendar-nav-button" onClick={() => setMonthOffset((o) => o - 1)}>
          &lsaquo;
        </button>
        <span>{viewedMonth.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}</span>
        <button type="button" className="calendar-nav-button" onClick={() => setMonthOffset((o) => o + 1)}>
          &rsaquo;
        </button>
      </div>

      <div className="calendar-grid">
        {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((label, index) => (
          <div className="calendar-weekday" key={index}>
            {label}
          </div>
        ))}
        {cells.map((day, index) => {
          if (day === null) return <div className="calendar-cell empty" key={index} />
          const key = dayKey(day)
          const hasItems = Boolean(itemsByDay[key]?.length)
          return (
            <button
              type="button"
              key={index}
              className={`calendar-cell${hasItems ? ' has-items' : ''}${selectedDay === key ? ' selected' : ''}`}
              onClick={() => setSelectedDay(selectedDay === key ? null : key)}
            >
              {day}
              {hasItems && <span className="calendar-dot" />}
            </button>
          )
        })}
      </div>

      {selectedDay && (
        <div className="calendar-day-items">
          {selectedItems.length === 0 ? (
            <p className="panel-hint">Nothing saved on this day.</p>
          ) : (
            selectedItems.map((item) => <ItemCard item={item} onDelete={onDelete} key={item.id} />)
          )}
        </div>
      )}
    </div>
  )
}

const ItemsPanel = forwardRef(function ItemsPanel({ userEmail, onSignOut, onItemsChanged, width }, ref) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [showUploadMenu, setShowUploadMenu] = useState(false)
  const [viewMode, setViewMode] = useState('list')
  const [typeFilter, setTypeFilter] = useState('all')
  const [resurfaceDismissed, setResurfaceDismissed] = useState(false)

  const audioFileInputRef = useRef(null)
  const documentFileInputRef = useRef(null)
  const menuRef = useRef(null)
  const noteInputRef = useRef(null)

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

  const resurfacedItem = useMemo(() => pickResurfacedItem(items), [items])

  const filteredItems =
    typeFilter === 'all' ? items : items.filter((item) => itemTypeCategory(item) === typeFilter)

  useEffect(() => {
    if (resurfacedItem) {
      setResurfaceDismissed(isResurfaceDismissedToday(resurfacedItem.id))
    }
  }, [resurfacedItem])

  function handleDismissResurface() {
    if (!resurfacedItem) return
    dismissResurfaceToday(resurfacedItem.id)
    setResurfaceDismissed(true)
  }

  function scrollToItemInList(itemId) {
    setViewMode('list')
    setTypeFilter('all')
    // Wait a tick so the list view (with this item's card) is in the DOM
    // before we look it up -- switching viewMode above is async.
    setTimeout(() => {
      const el = document.getElementById(`item-${itemId}`)
      if (!el) return
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('item-card-flash')
      setTimeout(() => el.classList.remove('item-card-flash'), 1200)
    }, 0)
  }

  function handleViewResurfaced() {
    if (resurfacedItem) scrollToItemInList(resurfacedItem.id)
  }

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

  useImperativeHandle(ref, () => ({
    focusNoteInput: () => noteInputRef.current?.focus(),
    startRecording: () => recorder.start(),
    openDocumentPicker: () => documentFileInputRef.current?.click(),
    scrollToItem: scrollToItemInList,
  }))

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
        <span className="header-title">
          <span className="header wordmark">mindweave</span>
          <span className="palette-hint" title="Press Ctrl+K or Cmd+K to search and jump to actions">
            <kbd>⌘K</kbd>
          </span>
        </span>
        <button type="button" className="signout-link" onClick={onSignOut} title={userEmail}>
          Sign out
        </button>
      </div>

      {resurfacedItem && !resurfaceDismissed && (
        <div className="resurface-card">
          <div className="resurface-card-header">
            <span className="resurface-card-label">From your notes</span>
            <button
              type="button"
              className="delete-button"
              onClick={handleDismissResurface}
              aria-label="Dismiss for today"
              title="Dismiss for today"
            >
              &times;
            </button>
          </div>
          <button type="button" className="resurface-card-title" onClick={handleViewResurfaced}>
            {resurfacedItem.title || resurfacedItem.preview || resurfacedItem.source_url}
          </button>
          <p className="time">{timeAgo(resurfacedItem.created_at)}</p>
        </div>
      )}

      {!loading && items.length > 0 && (
        <div className="view-tabs">
          {VIEW_MODES.map((mode) => (
            <button
              type="button"
              key={mode}
              className={`view-tab${viewMode === mode ? ' active' : ''}`}
              onClick={() => setViewMode(mode)}
            >
              {mode.charAt(0).toUpperCase() + mode.slice(1)}
            </button>
          ))}
        </div>
      )}

      {!loading && items.length > 0 && (
        <div className="type-filters">
          {TYPE_FILTERS.filter(
            (filter) => filter.id === 'all' || items.some((item) => itemTypeCategory(item) === filter.id)
          ).map((filter) => (
            <button
              type="button"
              key={filter.id}
              className={`type-filter-chip${typeFilter === filter.id ? ' active' : ''}`}
              onClick={() => setTypeFilter(filter.id)}
            >
              {filter.label}
            </button>
          ))}
        </div>
      )}

      <div className="item-list">
        {loading && <p className="panel-hint">Loading&hellip;</p>}
        {!loading && items.length === 0 && (
          <p className="panel-hint">Nothing saved yet &mdash; add your first thought below.</p>
        )}
        {!loading && items.length > 0 && filteredItems.length === 0 && (
          <p className="panel-hint">Nothing in this category yet.</p>
        )}
        {!loading && filteredItems.length > 0 && viewMode === 'list' && (
          filteredItems.map((item) => <ItemCard item={item} onDelete={handleDelete} key={item.id} />)
        )}
        {!loading && filteredItems.length > 0 && viewMode === 'table' && (
          <TableView items={filteredItems} onDelete={handleDelete} />
        )}
        {!loading && filteredItems.length > 0 && viewMode === 'calendar' && (
          <CalendarView items={filteredItems} onDelete={handleDelete} />
        )}
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
              ref={noteInputRef}
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
})

export default ItemsPanel