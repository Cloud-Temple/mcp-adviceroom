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
        const text = await response.text()
        if (!text.trim()) {
          throw new Error(response.status === 403
            ? 'Requête bloquée par le WAF (403) — le contenu est peut-être trop riche'
            : `Réponse vide du serveur (HTTP ${response.status})`)
        }
        let data
        try { data = JSON.parse(text) } catch { data = {} }
        throw new Error(data.detail || `HTTP ${response.status}`)
      }

      const text = await response.text()
      if (!text.trim()) return {}
      return JSON.parse(text)
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
