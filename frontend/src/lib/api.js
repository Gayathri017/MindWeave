import { supabase } from './supabase'

const API_URL = import.meta.env.VITE_API_URL

if (!API_URL) {
  throw new Error('Missing VITE_API_URL -- check your .env file.')
}

async function authorizedFetch(path, options = {}) {
  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (!session) {
    throw new Error('Not signed in.')
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${session.access_token}`,
      ...options.headers,
    },
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}).`)
  }

  if (response.status === 204) {
    return null
  }

  return response.json()
}

async function authorizedUpload(path, formData) {
  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (!session) {
    throw new Error('Not signed in.')
  }

  const response = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      // Deliberately no Content-Type here -- the browser sets it itself
      // for FormData, including the multipart boundary string, which we
      // can't reproduce by hand.
    },
    body: formData,
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}).`)
  }

  return response.json()
}

function withFolderQuery(path, folderId) {
  return folderId ? `${path}?folder_id=${folderId}` : path
}

export function listItems(folderId = null) {
  return authorizedFetch(withFolderQuery('/api/items', folderId))
}

export function saveItem({ sourceType, content, folderId = null }) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  return authorizedFetch('/api/items', {
    method: 'POST',
    body: JSON.stringify({ source_type: sourceType, content, folder_id: folderId, timezone }),
  })
}

export function askQuestion(question, folderId = null) {
  return authorizedFetch('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ question, folder_id: folderId }),
  })
}

export function getChatHistory(folderId = null) {
  return authorizedFetch(withFolderQuery('/api/chat/messages', folderId))
}

export function askAboutImage(file, question, folderId = null) {
  const formData = new FormData()
  formData.append('file', file, file.name)
  formData.append('question', question)
  if (folderId) formData.append('folder_id', folderId)
  return authorizedUpload('/api/chat/image', formData)
}

export function getGraph() {
  return authorizedFetch('/api/graph')
}

export function deleteItem(id) {
  return authorizedFetch(`/api/items/${id}`, { method: 'DELETE' })
}

export function moveItemToFolder(itemId, folderId) {
  return authorizedFetch(`/api/items/${itemId}/folder`, {
    method: 'PATCH',
    body: JSON.stringify({ folder_id: folderId }),
  })
}

export function listFolders() {
  return authorizedFetch('/api/folders')
}

export function createFolder(name) {
  return authorizedFetch('/api/folders', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export function deleteFolder(id) {
  return authorizedFetch(`/api/folders/${id}`, { method: 'DELETE' })
}

export function renameFolder(id, name) {
  return authorizedFetch(`/api/folders/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  })
}

export function uploadAudio(audioBlob, filename = 'recording.webm', folderId = null) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const formData = new FormData()
  formData.append('file', audioBlob, filename)
  formData.append('timezone', timezone)
  if (folderId) formData.append('folder_id', folderId)
  return authorizedUpload('/api/items/audio', formData)
}

export function transcribeAudio(audioBlob, filename = 'question.webm') {
  const formData = new FormData()
  formData.append('file', audioBlob, filename)
  return authorizedUpload('/api/transcribe', formData)
}

export function explainItem(itemId) {
  return authorizedFetch(`/api/items/${itemId}/explain`, { method: 'POST' })
}

export function uploadDocument(file, folderId = null) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const formData = new FormData()
  formData.append('file', file, file.name)
  formData.append('timezone', timezone)
  if (folderId) formData.append('folder_id', folderId)
  return authorizedUpload('/api/items/document', formData)
}
