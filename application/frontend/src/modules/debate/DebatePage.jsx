/**
 * DebatePage — Page principale : formulaire de création + historique des débats.
 */
import { useState, useEffect } from 'react'
import useHttpClient from '../../hooks/useHttpClient'
import DebateCreate from './DebateCreate'

export default function DebatePage({ onDebateCreated }) {
  const { get, loading } = useHttpClient()
  const [debates, setDebates] = useState([])

  // Charger la liste des débats existants
  useEffect(() => {
    get('/debates')
      .then((data) => setDebates(data.debates || []))
      .catch(() => {}) // Silencieux si le backend n'est pas démarré
  }, [get])

  return (
    <div className="space-y-8">
      {/* Formulaire de création */}
      <DebateCreate onCreated={onDebateCreated} />

      {/* Historique des débats */}
      {debates.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold text-gray-700 mb-3">
            📋 Débats récents
          </h2>
          <div className="space-y-2">
            {debates.map((d) => (
              <button
                key={d.id}
                onClick={() =>
                  onDebateCreated({
                    id: d.id,
                    streamUrl: `/api/v1/debates/${d.id}/stream`,
                  })
                }
                className="w-full text-left p-4 bg-white rounded-lg border border-gray-200 hover:border-primary-500 hover:shadow-sm transition-all"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-800 truncate">
                    {d.question}
                  </span>
                  <StatusBadge status={d.status} />
                </div>
                <div className="text-sm text-gray-500 mt-1">
                  {d.participants} participants · {d.rounds} rounds
                </div>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

/** Badge de statut du débat. */
function StatusBadge({ status }) {
  const colors = {
    created: 'bg-gray-100 text-gray-600',
    running: 'bg-blue-100 text-blue-700',
    completed: 'bg-green-100 text-green-700',
    error: 'bg-red-100 text-red-700',
    paused: 'bg-yellow-100 text-yellow-700',
  }
  return (
    <span
      className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || colors.created}`}
    >
      {status}
    </span>
  )
}
