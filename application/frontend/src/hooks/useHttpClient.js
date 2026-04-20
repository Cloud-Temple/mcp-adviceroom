/**
 * useHttpClient — Hook pour les appels API REST (non-streaming).
 *
 * Fournit des méthodes get/post avec gestion d'erreur et loading state.
 */
import { useState, useCallback } from 'react'

const API_BASE = '/api/v1'

export default function useHttpClient() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const request = useCallback(async (method, path, body = null) => {
    setLoading(true)
    setError(null)

    try {
      const options = {
        method,
        headers: { 'Content-Type': 'application/json' },
      }
      if (body) {
        options.body = JSON.stringify(body)
      }

      const response = await fetch(`${API_BASE}${path}`, options)

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${response.status}`)
      }

      return await response.json()
    } catch (err) {
      setError(err.message)
      throw err
    } finally {
      setLoading(false)
    }
  }, [])

  const get = useCallback((path) => request('GET', path), [request])
  const post = useCallback((path, body) => request('POST', path, body), [request])

  return { get, post, loading, error }
}
