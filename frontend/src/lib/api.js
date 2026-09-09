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

  return response.json()
}

export function listItems() {
  return authorizedFetch('/api/items')
}

export function saveItem({ sourceType, content }) {
  return authorizedFetch('/api/items', {
    method: 'POST',
    body: JSON.stringify({ source_type: sourceType, content }),
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
