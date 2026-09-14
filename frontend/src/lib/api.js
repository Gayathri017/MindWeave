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

export function listItems() {
  return authorizedFetch('/api/items')
}

export function saveItem({ sourceType, content }) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  return authorizedFetch('/api/items', {
    method: 'POST',
    body: JSON.stringify({ source_type: sourceType, content, timezone }),
  })
}

export function askQuestion(question) {
  return authorizedFetch('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ question }),
  })
}

export function getGraph() {
  return authorizedFetch('/api/graph')
}

export function deleteItem(id) {
  return authorizedFetch(`/api/items/${id}`, { method: 'DELETE' })
}

export function uploadAudio(audioBlob, filename = 'recording.webm') {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const formData = new FormData()
  formData.append('file', audioBlob, filename)
  formData.append('timezone', timezone)
  return authorizedUpload('/api/items/audio', formData)
}

export function transcribeAudio(audioBlob, filename = 'question.webm') {
  const formData = new FormData()
  formData.append('file', audioBlob, filename)
  return authorizedUpload('/api/transcribe', formData)
}

export function uploadDocument(file) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const formData = new FormData()
  formData.append('file', file, file.name)
  formData.append('timezone', timezone)
  return authorizedUpload('/api/items/document', formData)
}