/**
 * DebateView — Vue temps réel d'un débat en cours (stream NDJSON).
 *
 * Affiche les événements du débat au fur et à mesure :
 * - Phases (opening, debate, verdict)
 * - Tours de parole avec persona
 * - Score de stabilité
 * - Verdict final
 *
 * Ref: DESIGN/architecture.md §4.3 (Protocole NDJSON)
 */
import { useState, useCallback, useEffect, useRef } from 'react'
import useNDJSONStream from '../../hooks/useNDJSONStream'

export default function DebateView({ debateId, streamUrl, onBack }) {
  const [events, setEvents] = useState([])
  const [phase, setPhase] = useState('connecting')
  const [verdict, setVerdict] = useState(null)
  const [stability, setStability] = useState(null)
  const bottomRef = useRef(null)

  /** Traitement de chaque événement NDJSON. */
  const handleEvent = useCallback((event) => {
    setEvents((prev) => [...prev, event])

    switch (event.type) {
      case 'phase':
        setPhase(event.phase)
        break
      case 'stability':
        setStability(event)
        break
      case 'verdict':
        setVerdict(event)
        setPhase('completed')
        break
      case 'debate_end':
        setPhase('completed')
        break
      case 'error':
        setPhase('error')
        break
    }
  }, [])

  const { start, stop, isStreaming, error } = useNDJSONStream(streamUrl, handleEvent)

  // Démarrer le stream à l'ouverture
  useEffect(() => {
    start()
    return () => stop()
  }, [start, stop])

  // Auto-scroll vers le bas
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <button
          onClick={onBack}
          className="text-sm text-gray-500 hover:text-gray-700 flex items-center gap-1"
        >
          ← Retour
        </button>
        <PhaseIndicator phase={phase} isStreaming={isStreaming} />
      </div>

      {/* Stabilité */}
      {stability && (
        <div className="bg-white rounded-lg border border-gray-200 p-3 flex items-center gap-3">
          <span className="text-sm font-medium text-gray-600">📊 Stabilité :</span>
          <div className="flex-1 bg-gray-200 rounded-full h-2">
            <div
              className={`h-2 rounded-full transition-all ${
                stability.score >= stability.threshold ? 'bg-green-500' : 'bg-blue-500'
              }`}
              style={{ width: `${Math.min(stability.score * 100, 100)}%` }}
            />
          </div>
          <span className="text-sm text-gray-500">
            {(stability.score * 100).toFixed(0)}%
            {stability.can_stop && ' ✓'}
          </span>
        </div>
      )}

      {/* Timeline des événements */}
      <div className="space-y-3">
        {events.map((event, i) => (
          <EventCard key={i} event={event} />
        ))}
      </div>

      {/* Verdict */}
      {verdict && <VerdictPanel verdict={verdict} />}

      {/* Erreur */}
      {error && (
        <div className="p-4 bg-red-50 text-red-700 rounded-lg">
          ⚠️ Erreur de connexion : {error}
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}

/** Indicateur de phase du débat. */
function PhaseIndicator({ phase, isStreaming }) {
  const labels = {
    connecting: { text: 'Connexion...', color: 'text-gray-500', dot: 'bg-gray-400' },
    opening: { text: 'Phase 1 — Ouverture', color: 'text-blue-600', dot: 'bg-blue-500' },
    debate: { text: 'Phase 2 — Débat', color: 'text-orange-600', dot: 'bg-orange-500' },
    verdict: { text: 'Phase 3 — Verdict', color: 'text-purple-600', dot: 'bg-purple-500' },
    completed: { text: 'Terminé ✓', color: 'text-green-600', dot: 'bg-green-500' },
    error: { text: 'Erreur', color: 'text-red-600', dot: 'bg-red-500' },
  }
  const info = labels[phase] || labels.connecting

  return (
    <div className={`flex items-center gap-2 text-sm font-medium ${info.color}`}>
      <span className={`w-2 h-2 rounded-full ${info.dot} ${isStreaming ? 'animate-pulse' : ''}`} />
      {info.text}
    </div>
  )
}

/** Carte d'un événement dans la timeline. */
function EventCard({ event }) {
  switch (event.type) {
    case 'debate_start':
      return (
        <div className="animate-fade-in p-4 bg-primary-50 rounded-lg border border-primary-200">
          <div className="font-medium text-primary-700">🏛️ Débat lancé</div>
          <div className="text-sm text-primary-600 mt-1">
            « {event.question} »
          </div>
          <div className="text-xs text-primary-500 mt-2">
            {event.participants?.length} participants
          </div>
        </div>
      )

    case 'turn_start':
      return (
        <div className="animate-fade-in flex items-center gap-2 text-sm text-gray-500 pl-4">
          <span>{event.participant?.icon || '🤖'}</span>
          <span className="font-medium">{event.participant?.persona}</span>
          <span className="text-gray-400">({event.participant?.model})</span>
          {event.round > 0 && <span className="text-gray-400">· Round {event.round}</span>}
        </div>
      )

    case 'turn_end':
      return (
        <div className="animate-fade-in pl-4 text-xs text-gray-400">
          ✓ Tour terminé {event.has_position ? '(position structurée)' : ''}
        </div>
      )

    case 'phase':
      const phaseLabels = {
        opening: '📖 Phase 1 — Positions initiales',
        debate: '⚔️ Phase 2 — Débat',
        verdict: '⚖️ Phase 3 — Verdict',
      }
      return (
        <div className="animate-fade-in py-2 text-center">
          <span className="inline-block px-4 py-1 bg-gray-100 text-gray-600 rounded-full text-sm font-medium">
            {phaseLabels[event.phase] || event.phase}
            {event.round > 0 && ` — Round ${event.round}`}
          </span>
        </div>
      )

    case 'stability':
      return null // Affiché dans la barre de stabilité

    case 'error':
      return (
        <div className="animate-fade-in p-3 bg-red-50 text-red-700 rounded-lg text-sm">
          ❌ {event.error || event.reason || 'Erreur'}
        </div>
      )

    default:
      return null
  }
}

/** Panel du verdict final. */
function VerdictPanel({ verdict }) {
  const typeLabels = {
    consensus: { label: '✅ Consensus', color: 'bg-green-50 border-green-200' },
    consensus_partiel: { label: '🟡 Consensus partiel', color: 'bg-yellow-50 border-yellow-200' },
    dissensus: { label: '🔴 Dissensus', color: 'bg-red-50 border-red-200' },
  }
  const info = typeLabels[verdict.verdict_type] || typeLabels.dissensus

  return (
    <div className={`animate-fade-in rounded-xl border-2 p-6 ${info.color}`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-bold">{info.label}</h3>
        <span className="text-sm text-gray-500">
          Confiance : {verdict.confidence}%
        </span>
      </div>

      {verdict.summary && (
        <p className="text-gray-700 mb-4">{verdict.summary}</p>
      )}

      {verdict.agreement_points?.length > 0 && (
        <div className="mb-3">
          <h4 className="text-sm font-semibold text-gray-600 mb-1">Points d'accord :</h4>
          <ul className="list-disc list-inside text-sm text-gray-600">
            {verdict.agreement_points.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </div>
      )}

      {verdict.recommendation && (
        <div className="mt-3 p-3 bg-white/50 rounded-lg">
          <h4 className="text-sm font-semibold text-gray-600 mb-1">💡 Recommandation :</h4>
          <p className="text-sm text-gray-700">{verdict.recommendation}</p>
        </div>
      )}

      {verdict.key_insights?.length > 0 && (
        <div className="mt-3">
          <h4 className="text-sm font-semibold text-gray-600 mb-1">🔍 Insights :</h4>
          <ul className="list-disc list-inside text-sm text-gray-600">
            {verdict.key_insights.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}
