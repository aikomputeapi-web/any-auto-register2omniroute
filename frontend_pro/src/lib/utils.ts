export const API = '/api'
export const API_BASE = '/api'
export const AUTH_PORTAL = 'https://auth.' + (window.location.hostname.replace(/^www\./, ''))

export function getToken(): string {
  return localStorage.getItem('auth_token') || ''
}

export function setToken(token: string): void {
  localStorage.setItem('auth_token', token)
}

export function clearToken(): void {
  localStorage.removeItem('auth_token')
}

export function redirectToAuthPortal(): void {
  const rd = encodeURIComponent(window.location.origin + window.location.pathname)
  window.location.href = `${AUTH_PORTAL}/?rd=${rd}`
}

export async function apiFetch(path: string, opts?: RequestInit) {
  const token = getToken()
  const baseHeaders: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) baseHeaders['Authorization'] = `Bearer ${token}`
  const res = await fetch(API + path, {
    ...opts,
    headers: { ...baseHeaders, ...(opts?.headers as Record<string, string> || {}) },
  })
  if (res.status === 401) {
    clearToken()
    redirectToAuthPortal()
    throw new Error('Not authenticated, redirecting to login')
  }
  if (!res.ok) {
    const text = await res.text()
    try {
      const json = JSON.parse(text)
      throw new Error(json.detail || text)
    } catch (e) {
      if (e instanceof SyntaxError) throw new Error(text)
      throw e
    }
  }
  return res.json()
}
