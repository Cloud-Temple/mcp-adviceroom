/**
 * App — Composant racine avec routing simple (sans react-router).
 *
 * Pages :
 * - / (défaut) → DebatePage (création + historique)
 * - /debate/:id → DebateView (temps réel)
 */
import { useState } from 'react'
import DebatePage from './modules/debate/DebatePage'
import DebateView from './modules/debate/DebateView'

export default function App() {
  // Routing simple basé sur l'état (pas besoin de react-router pour le MVP)
  const [currentDebate, setCurrentDebate] = useState(null)

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <button
            onClick={() => setCurrentDebate(null)}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity"
          >
            <span className="text-2xl">🏛️</span>
            <h1 className="text-xl font-bold text-gray-800">AdviceRoom</h1>
          </button>
          <span className="text-sm text-gray-400">v0.1.3 — Débats Multi-LLM</span>
        </div>
      </header>

      {/* Contenu principal */}
      <main className="max-w-6xl mx-auto px-4 py-6">
        {currentDebate ? (
          <DebateView
            debateId={currentDebate.id}
            streamUrl={currentDebate.streamUrl}
            onBack={() => setCurrentDebate(null)}
          />
        ) : (
          <DebatePage
            onDebateCreated={(debate) => setCurrentDebate(debate)}
          />
        )}
      </main>
    </div>
  )
}
