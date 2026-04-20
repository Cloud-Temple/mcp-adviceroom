/**
 * useNDJSONStream — Hook pour consommer un stream NDJSON en temps réel.
 *
 * Connecte à un endpoint GET qui retourne du NDJSON (une ligne JSON par événement).
 * Chaque événement est dispatché au callback `onEvent`.
 *
 * Ref: DESIGN/architecture.md §4.3
 */
import { useState, useCallback, useRef } from 'react'

/**
 * @param {string} url - URL du stream NDJSON
 * @param {function} onEvent - Callback appelé pour chaque événement parsé
 * @returns {{ start, stop, isStreaming, error }}
 */
export default function useNDJSONStream(url, onEvent) {
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState(null)
  const abortRef = useRef(null)

  const start = useCallback(async () => {
    // Annuler un stream précédent si actif
    if (abortRef.current) {
      abortRef.current.abort()
    }

    const controller = new AbortController()
    abortRef.current = controller
    setIsStreaming(true)
    setError(null)

    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: { 'Accept': 'application/x-ndjson' },
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Traiter chaque ligne complète (NDJSON = une ligne JSON par événement)
        const lines = buffer.split('\n')
        buffer = lines.pop() // Garder la dernière ligne (potentiellement incomplète)

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) continue

          try {
            const event = JSON.parse(trimmed)
            onEvent(event)
          } catch (e) {
            console.warn('NDJSON parse error:', trimmed, e)
          }
        }
      }

      // Traiter le buffer restant
      if (buffer.trim()) {
        try {
          onEvent(JSON.parse(buffer.trim()))
        } catch (e) {
          // Ignorer
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message)
        console.error('NDJSON stream error:', err)
      }
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }, [url, onEvent])

  const stop = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    setIsStreaming(false)
  }, [])

  return { start, stop, isStreaming, error }
}
