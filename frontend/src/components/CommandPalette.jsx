import { useEffect, useMemo, useRef, useState } from 'react'
import { listItems } from '../lib/api'

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}

function fuzzyIncludes(haystack, needle) {
  return haystack.toLowerCase().includes(needle.toLowerCase())
}

export default function CommandPalette({ itemsPanelRef, chatPanelRef }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [items, setItems] = useState([])
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef(null)

  useEffect(() => {
    function handleKeyDown(event) {
      const isPaletteShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k'
      if (isPaletteShortcut) {
        event.preventDefault()
        setOpen((wasOpen) => !wasOpen)
        return
      }
      if (event.key === 'Escape' && open) {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open])

  useEffect(() => {
    if (!open) return
    setQuery('')
    setSelectedIndex(0)
    inputRef.current?.focus()
    listItems()
      .then(setItems)
      .catch(() => setItems([]))
  }, [open])

  const actions = useMemo(
    () => [
      {
        id: 'new-note',
        label: 'New note',
        hint: 'Focus the note input',
        run: () => itemsPanelRef.current?.focusNoteInput(),
      },
      {
        id: 'record-voice',
        label: 'Record a voice note',
        hint: 'Start recording',
        run: () => itemsPanelRef.current?.startRecording(),
      },
      {
        id: 'upload-document',
        label: 'Upload a document or receipt',
        hint: 'PDF or image',
        run: () => itemsPanelRef.current?.openDocumentPicker(),
      },
      {
        id: 'ask-question',
        label: 'Ask a question',
        hint: 'Focus the chat input',
        run: () => chatPanelRef.current?.focusQuestionInput(),
      },
    ],
    [itemsPanelRef, chatPanelRef]
  )

  const filteredActions = query ? actions.filter((action) => fuzzyIncludes(action.label, query)) : actions

  const filteredItems = query
    ? items
        .filter((item) => fuzzyIncludes(item.title || item.preview || item.source_url || '', query))
        .slice(0, 8)
    : []

  const results = [
    ...filteredActions.map((action) => ({ type: 'action', ...action })),
    ...filteredItems.map((item) => ({ type: 'item', ...item })),
  ]

  function close() {
    setOpen(false)
  }

  function runResult(result) {
    if (!result) return
    if (result.type === 'action') {
      result.run()
    } else {
      itemsPanelRef.current?.scrollToItem(result.id)
    }
    close()
  }

  function handleKeyDown(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setSelectedIndex((index) => Math.min(index + 1, results.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setSelectedIndex((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      runResult(results[selectedIndex])
    }
  }

  if (!open) return null

  return (
    <div className="command-palette-overlay" onMouseDown={close}>
      <div className="command-palette" onMouseDown={(event) => event.stopPropagation()}>
        <div className="command-palette-input-row">
          <SearchIcon />
          <input
            ref={inputRef}
            className="command-palette-input"
            placeholder="Search saved items, or type a command&hellip;"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setSelectedIndex(0)
            }}
            onKeyDown={handleKeyDown}
          />
          <kbd className="command-palette-kbd">Esc</kbd>
        </div>

        <div className="command-palette-results">
          {filteredActions.length > 0 && (
            <div className="command-palette-group">
              <p className="command-palette-group-label">Actions</p>
              {filteredActions.map((action, index) => (
                <button
                  type="button"
                  key={action.id}
                  className={`command-palette-result${index === selectedIndex ? ' selected' : ''}`}
                  onMouseEnter={() => setSelectedIndex(index)}
                  onClick={() => runResult(results[index])}
                >
                  <span>{action.label}</span>
                  <span className="command-palette-hint">{action.hint}</span>
                </button>
              ))}
            </div>
          )}

          {filteredItems.length > 0 && (
            <div className="command-palette-group">
              <p className="command-palette-group-label">Saved items</p>
              {filteredItems.map((item, itemIndex) => {
                const resultIndex = filteredActions.length + itemIndex
                return (
                  <button
                    type="button"
                    key={item.id}
                    className={`command-palette-result${resultIndex === selectedIndex ? ' selected' : ''}`}
                    onMouseEnter={() => setSelectedIndex(resultIndex)}
                    onClick={() => runResult(results[resultIndex])}
                  >
                    <span>{item.title || item.preview || item.source_url}</span>
                  </button>
                )
              })}
            </div>
          )}

          {query && results.length === 0 && <p className="command-palette-empty">No matches.</p>}
        </div>
      </div>
    </div>
  )
}
