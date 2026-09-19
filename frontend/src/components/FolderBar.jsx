import { useState } from 'react'
import { createFolder, deleteFolder } from '../lib/api'

function PlusIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}

export default function FolderBar({ folders, activeFolderId, onSelectFolder, onFoldersChanged }) {
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState(null)

  async function handleCreate(event) {
    event.preventDefault()
    const trimmed = newName.trim()
    if (!trimmed) {
      setCreating(false)
      return
    }
    try {
      const folder = await createFolder(trimmed)
      setNewName('')
      setCreating(false)
      setError(null)
      await onFoldersChanged()
      onSelectFolder(folder.id)
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleDelete(event, folder) {
    event.stopPropagation()
    const confirmed = window.confirm(
      `Delete "${folder.name}"? This permanently deletes everything filed in it (${folder.item_count} item${folder.item_count === 1 ? '' : 's'}), not just the folder.`
    )
    if (!confirmed) return

    try {
      await deleteFolder(folder.id)
      if (activeFolderId === folder.id) onSelectFolder(null)
      await onFoldersChanged()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="folder-bar">
      {error && <p className="error folder-bar-error">{error}</p>}
      <div className="folder-bar-row">
        <button
          type="button"
          className={`folder-pill${activeFolderId === null ? ' active' : ''}`}
          onClick={() => onSelectFolder(null)}
        >
          Home
        </button>

        {folders.map((folder) => (
          <button
            type="button"
            key={folder.id}
            className={`folder-pill${activeFolderId === folder.id ? ' active' : ''}`}
            onClick={() => onSelectFolder(folder.id)}
          >
            {folder.name}
            <span className="folder-pill-count">{folder.item_count}</span>
            <span
              className="folder-pill-delete"
              onClick={(event) => handleDelete(event, folder)}
              role="button"
              aria-label={`Delete folder ${folder.name}`}
              title="Delete folder"
            >
              &times;
            </span>
          </button>
        ))}

        {creating ? (
          <form className="folder-create-form" onSubmit={handleCreate}>
            <input
              autoFocus
              className="folder-create-input"
              placeholder="Folder name&hellip;"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              onBlur={() => !newName.trim() && setCreating(false)}
            />
          </form>
        ) : (
          <button type="button" className="folder-pill new-folder" onClick={() => setCreating(true)}>
            <PlusIcon /> New folder
          </button>
        )}
      </div>
    </div>
  )
}
