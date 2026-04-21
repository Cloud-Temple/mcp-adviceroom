/**
 * DebateView — Vue temps réel enrichie d'un débat (stream NDJSON).
 *
 * Affiche :
 * - Contenu complet de chaque intervention (prose, thinking)
 * - Positions structurées (thèse, confiance, arguments)
 * - Challenges entre participants
 * - Tool calls avec résultats
 * - Dashboard technique (tokens, durées, stabilité)
 * - Évolution des positions par round
 * - Verdict final
 *
 * Ref: DESIGN/architecture.md §4.3 (Protocole NDJSON)
 */
import { useState, useCallback, useEffect, useRef } from 'react'
import useNDJSONStream from '../../hooks/useNDJSONStream'

// Couleurs par provider
const PROVIDER_COLORS = {
  llmaas:    { bg: 'bg-cyan-50',    border: 'border-cyan-300',    text: 'text-cyan-700',    badge: 'bg-cyan-100 text-cyan-800' },
  openai:    { bg: 'bg-green-50',   border: 'border-green-300',   text: 'text-green-700',   badge: 'bg-green-100 text-green-800' },
  anthropic: { bg: 'bg-yellow-50',  border: 'border-yellow-300',  text: 'text-yellow-700',  badge: 'bg-yellow-100 text-yellow-800' },
  google:    { bg: 'bg-blue-50',    border: 'border-blue-300',    text: 'text-blue-700',    badge: 'bg-blue-100 text-blue-800' },
}
const DEFAULT_COLORS = { bg: 'bg-gray-50', border: 'border-gray-300', text: 'text-gray-700', badge: 'bg-gray-100 text-gray-800' }

export default function DebateView({ debateId, streamUrl, onBack }) {
  const [events, setEvents] = useState([])
  const [phase, setPhase] = useState('connecting')
  const [verdict, setVerdict] = useState(null)
  const [stability, setStability] = useState(null)
  const [participants, setParticipants] = useState({})
  const [debateInfo, setDebateInfo] = useState(null)
  const [stats, setStats] = useState({ tokens: 0, turns: 0, rounds: 0, duration: 0 })
  const [positions, setPositions] = useState({}) // {pid: [{round, thesis, confidence}]}
  const [showDashboard, setShowDashboard] = useState(true)
  const bottomRef = useRef(null)

  /** Traitement de chaque événement NDJSON. */
  const handleEvent = useCallback((event) => {
    setEvents((prev) => [...prev, event])

    switch (event.type) {
      case 'debate_start':
        setDebateInfo(event)
        // Indexer les participants
        const pMap = {}
        for (const p of event.participants || []) {
          pMap[p.id || p.model] = p
        }
        setParticipants(pMap)
        break

      case 'phase':
        setPhase(event.phase)
        if (event.round > 0) {
          setStats(s => ({ ...s, rounds: Math.max(s.rounds, event.round) }))
        }
        break

      case 'turn_end':
        // Mettre à jour les stats
        setStats(s => ({
          ...s,
          tokens: s.tokens + (event.tokens_used || 0),
          turns: s.turns + 1,
          duration: s.duration + (event.duration_ms || 0),
        }))
        // Tracker les positions
        if (event.position) {
          const pid = event.participant_id
          setPositions(prev => ({
            ...prev,
            [pid]: [...(prev[pid] || []), {
              round: event.round ?? 0,
              thesis: event.position.thesis,
              confidence: event.position.confidence,
            }]
          }))
        }
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
        if (event.total_tokens) setStats(s => ({ ...s, tokens: event.total_tokens }))
        break

      case 'error':
        setPhase('error')
        break
    }
  }, [])

  const { start, stop, isStreaming, error } = useNDJSONStream(streamUrl, handleEvent)

  useEffect(() => { start(); return () => stop() }, [start, stop])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [events])

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <button onClick={onBack} className="text-sm text-gray-500 hover:text-gray-700 flex items-center gap-1">
          ← Retour
        </button>
        <div className="flex items-center gap-3">
          <PhaseIndicator phase={phase} isStreaming={isStreaming} />
          <button
            onClick={() => setShowDashboard(d => !d)}
            className="text-xs px-2 py-1 rounded bg-gray-100 hover:bg-gray-200 text-gray-600"
          >
            {showDashboard ? '📊 Masquer stats' : '📊 Stats'}
          </button>
          {phase === 'completed' && debateId && (
            <a
              href={`/api/v1/debates/${debateId}/export?format=markdown`}
              target="_blank"
              rel="noopener"
              className="text-xs px-2 py-1 rounded bg-primary-100 hover:bg-primary-200 text-primary-700"
            >
              📥 Export MD
            </a>
          )}
        </div>
      </div>

      {/* Question */}
      {debateInfo && (
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-lg font-semibold text-gray-800">🏛️ {debateInfo.question}</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {(debateInfo.participants || []).map((p, i) => {
              const colors = PROVIDER_COLORS[p.provider] || DEFAULT_COLORS
              return (
                <span key={i} className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${colors.badge}`}>
                  {p.icon} {p.display_name} <span className="opacity-60">— {p.persona}</span>
                </span>
              )
            })}
          </div>
        </div>
      )}

      {/* Dashboard technique (toggle) */}
      {showDashboard && (
        <TechDashboard stats={stats} stability={stability} positions={positions} participants={participants} phase={phase} />
      )}

      {/* Stabilité */}
      {stability && (
        <div className="bg-white rounded-lg border border-gray-200 p-3 flex items-center gap-3">
          <span className="text-sm font-medium text-gray-600">📊 Stabilité :</span>
          <div className="flex-1 bg-gray-200 rounded-full h-2.5">
            <div
              className={`h-2.5 rounded-full transition-all duration-500 ${stability.score >= 0.85 ? 'bg-green-500' : stability.score >= 0.5 ? 'bg-yellow-500' : 'bg-red-400'}`}
              style={{ width: `${Math.min(stability.score * 100, 100)}%` }}
            />
          </div>
          <span className="text-sm font-medium text-gray-600 w-16 text-right">
            {(stability.score * 100).toFixed(0)}%{stability.can_stop && ' ✓'}
          </span>
        </div>
      )}

      {/* Timeline des événements */}
      <div className="space-y-3">
        {events.map((event, i) => (
          <EventCard key={i} event={event} participants={participants} />
        ))}
      </div>

      {/* Verdict */}
      {verdict && <VerdictPanel verdict={verdict} />}

      {/* Erreur */}
      {error && (
        <div className="p-4 bg-red-50 text-red-700 rounded-lg">⚠️ Erreur de connexion : {error}</div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}


// ============================================================
// Dashboard technique
// ============================================================

function TechDashboard({ stats, stability, positions, participants, phase }) {
  const hasPositions = Object.keys(positions).length > 0

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-4">
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">📊 Dashboard Technique</h3>

      {/* Stats en grille */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="Rounds" value={stats.rounds} icon="🔄" />
        <StatCard label="Tours" value={stats.turns} icon="🎤" />
        <StatCard label="Tokens" value={stats.tokens.toLocaleString()} icon="🔤" />
        <StatCard label="Durée" value={`${(stats.duration / 1000).toFixed(0)}s`} icon="⏱" />
        <StatCard label="Stabilité" value={stability ? `${(stability.score * 100).toFixed(0)}%` : '—'} icon="📊"
          color={stability?.can_stop ? 'text-green-600' : stability?.score >= 0.5 ? 'text-yellow-600' : 'text-gray-400'} />
      </div>

      {/* Évolution des positions */}
      {hasPositions && (
        <div>
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">📈 Évolution des positions</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-1 pr-3 text-gray-500 font-medium">Participant</th>
                  <th className="text-left py-1 pr-3 text-gray-500 font-medium">Thèse</th>
                  {/* Colonnes dynamiques par round */}
                  {(() => {
                    const allRounds = new Set()
                    Object.values(positions).forEach(ps => ps.forEach(p => allRounds.add(p.round)))
                    return [...allRounds].sort((a, b) => a - b).map(r => (
                      <th key={r} className="text-center py-1 px-2 text-gray-500 font-medium">
                        {r === 0 ? 'Ouv.' : `R${r}`}
                      </th>
                    ))
                  })()}
                </tr>
              </thead>
              <tbody>
                {Object.entries(positions).map(([pid, pos]) => {
                  const p = participants[pid] || {}
                  const colors = PROVIDER_COLORS[p.provider] || DEFAULT_COLORS
                  const lastThesis = pos[pos.length - 1]?.thesis || '?'
                  const allRounds = new Set()
                  Object.values(positions).forEach(ps => ps.forEach(p => allRounds.add(p.round)))
                  const rounds = [...allRounds].sort((a, b) => a - b)
                  const confByRound = {}
                  pos.forEach(p => { confByRound[p.round] = p.confidence })

                  return (
                    <tr key={pid} className="border-b border-gray-100">
                      <td className={`py-1.5 pr-3 font-medium ${colors.text}`}>
                        {p.icon} {p.display_name || pid}
                      </td>
                      <td className="py-1.5 pr-3 text-gray-600 max-w-xs truncate text-xs">
                        {lastThesis.length > 50 ? lastThesis.slice(0, 50) + '…' : lastThesis}
                      </td>
                      {rounds.map(r => {
                        const conf = confByRound[r]
                        const prevIdx = rounds.indexOf(r) - 1
                        const prevConf = prevIdx >= 0 ? confByRound[rounds[prevIdx]] : null
                        let arrow = ''
                        let color = 'text-gray-700'
                        if (prevConf != null && conf != null) {
                          if (conf > prevConf) { arrow = ' ↑'; color = 'text-green-600' }
                          else if (conf < prevConf) { arrow = ' ↓'; color = 'text-red-500' }
                        }
                        return (
                          <td key={r} className={`text-center py-1.5 px-2 font-medium ${color}`}>
                            {conf != null ? `${conf}%${arrow}` : '—'}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, icon, color = 'text-gray-800' }) {
  return (
    <div className="bg-gray-50 rounded-lg p-2.5 text-center">
      <div className="text-xs text-gray-500">{icon} {label}</div>
      <div className={`text-lg font-bold ${color}`}>{value}</div>
    </div>
  )
}


// ============================================================
// Phase Indicator
// ============================================================

function PhaseIndicator({ phase, isStreaming }) {
  const labels = {
    connecting: { text: 'Connexion...', color: 'text-gray-500', dot: 'bg-gray-400' },
    opening:    { text: '📖 Ouverture', color: 'text-blue-600', dot: 'bg-blue-500' },
    debate:     { text: '💬 Débat', color: 'text-orange-600', dot: 'bg-orange-500' },
    verdict:    { text: '⚖️ Verdict', color: 'text-purple-600', dot: 'bg-purple-500' },
    completed:  { text: '✅ Terminé', color: 'text-green-600', dot: 'bg-green-500' },
    error:      { text: '❌ Erreur', color: 'text-red-600', dot: 'bg-red-500' },
  }
  const info = labels[phase] || labels.connecting
  return (
    <div className={`flex items-center gap-2 text-sm font-medium ${info.color}`}>
      <span className={`w-2 h-2 rounded-full ${info.dot} ${isStreaming ? 'animate-pulse' : ''}`} />
      {info.text}
    </div>
  )
}


// ============================================================
// Event Card — Rendu de chaque événement NDJSON
// ============================================================

function EventCard({ event, participants }) {
  switch (event.type) {
    case 'debate_start':
      return null  // Affiché dans le header

    case 'turn_start': {
      const p = event.participant || {}
      const pid = p.id || p.model || '?'
      const info = participants[pid] || p
      const colors = PROVIDER_COLORS[info.provider] || DEFAULT_COLORS
      return (
        <div className="animate-fade-in flex items-center gap-2 text-sm text-gray-400 pl-2">
          <span className="animate-pulse">⏳</span>
          <span>{info.icon || '🤖'}</span>
          <span className={`font-medium ${colors.text}`}>{info.display_name || pid}</span>
          <span className="text-gray-300">réfléchit...</span>
          {event.round > 0 && <span className="text-gray-300">· Round {event.round}</span>}
        </div>
      )
    }

    case 'turn_end':
      return <TurnCard event={event} participants={participants} />

    case 'phase': {
      const phaseLabels = {
        opening: '📖 Phase 1 — Positions initiales',
        debate:  `💬 Phase 2 — Débat${event.round > 0 ? ` — Round ${event.round}` : ''}`,
        verdict: '⚖️ Phase 3 — Verdict',
      }
      return (
        <div className="animate-fade-in py-2 text-center">
          <span className="inline-block px-4 py-1.5 bg-gray-100 text-gray-600 rounded-full text-sm font-semibold">
            {phaseLabels[event.phase] || event.phase}
          </span>
        </div>
      )
    }

    case 'stability':
      return null  // Affiché dans la barre

    case 'error':
      return (
        <div className="animate-fade-in p-3 bg-red-50 text-red-700 rounded-lg text-sm border border-red-200">
          ❌ {event.error || event.reason || 'Erreur'}
        </div>
      )

    case 'user_question':
      return (
        <div className="animate-fade-in p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
          <div className="font-medium text-yellow-800">❓ Question pour vous</div>
          <div className="text-sm text-yellow-700 mt-1">{event.question}</div>
        </div>
      )

    default:
      return null
  }
}


// ============================================================
// Turn Card — Affichage enrichi d'un tour de parole
// ============================================================

function TurnCard({ event, participants }) {
  const [expanded, setExpanded] = useState(true)
  const pid = event.participant_id || '?'
  const pInfo = event.participant || {}
  const info = participants[pid] || pInfo
  const colors = PROVIDER_COLORS[info.provider || pInfo.provider] || DEFAULT_COLORS

  const content = event.content || ''
  const position = event.position
  const toolCalls = event.tool_calls || []
  const toolResults = event.tool_results || []
  const tokens = event.tokens_used || 0
  const duration = event.duration_ms || 0
  const error = event.error
  const name = info.display_name || pInfo.display_name || pid
  const icon = info.icon || pInfo.icon || '🤖'
  const persona = info.persona || pInfo.persona || ''
  const provider = info.provider || pInfo.provider || ''

  const durStr = duration < 1000 ? `${duration}ms` : `${(duration / 1000).toFixed(1)}s`
  const hasContent = content || error || position

  return (
    <div className={`animate-fade-in rounded-xl border-2 ${colors.border} ${colors.bg} overflow-hidden`}>
      {/* Header du tour */}
      <div
        className="flex items-center justify-between px-4 py-2.5 cursor-pointer hover:opacity-80"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-2">
          <span className="text-lg">{icon}</span>
          <span className={`font-semibold ${colors.text}`}>{name}</span>
          {persona && <span className="text-xs text-gray-500">— {persona}</span>}
          <span className={`text-xs px-1.5 py-0.5 rounded ${colors.badge}`}>{provider}</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          {toolCalls.length > 0 && <span>🔧 {toolCalls.length}</span>}
          <span>🔤 {tokens.toLocaleString()}</span>
          <span>⏱ {durStr}</span>
          <span className="text-gray-400">{expanded ? '▼' : '▶'}</span>
        </div>
      </div>

      {/* Contenu (collapsible) */}
      {expanded && hasContent && (
        <div className="px-4 pb-4 space-y-3 border-t border-gray-200/50">
          {/* Erreur */}
          {error && (
            <div className="mt-3 p-3 bg-red-100 text-red-700 rounded-lg text-sm">
              ❌ <strong>Erreur :</strong> {error}
            </div>
          )}

          {/* Contenu textuel (prose) */}
          {content && (
            <div className="mt-3 text-sm text-gray-700 leading-relaxed whitespace-pre-wrap max-h-96 overflow-y-auto">
              {content}
            </div>
          )}

          {/* Tool calls */}
          {toolCalls.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs font-semibold text-gray-500 uppercase">🔧 Outils utilisés</div>
              {toolCalls.map((tc, i) => (
                <div key={i} className="text-xs bg-white/70 rounded p-2 border border-gray-200">
                  <span className="font-mono text-cyan-700">{tc.name}</span>
                  <span className="text-gray-400">({JSON.stringify(tc.arguments || {}).slice(0, 80)})</span>
                  {i < toolResults.length && toolResults[i]?.result?.status === 'success' && (
                    <span className="ml-2 text-green-600">✅</span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Position structurée */}
          {position && (
            <div className="bg-white/60 rounded-lg p-3 border border-gray-200/50 space-y-2">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-xs font-semibold text-gray-500 uppercase">💭 Position</div>
                  <div className="text-sm font-medium text-gray-800 mt-0.5">"{position.thesis}"</div>
                </div>
                <div className={`text-2xl font-bold ${
                  position.confidence >= 80 ? 'text-green-600' :
                  position.confidence >= 60 ? 'text-yellow-600' : 'text-red-500'
                }`}>
                  {position.confidence}%
                </div>
              </div>

              {/* Arguments */}
              {position.arguments?.length > 0 && (
                <div>
                  <div className="text-xs text-gray-500 font-medium">📌 Arguments :</div>
                  <ul className="mt-1 space-y-0.5">
                    {position.arguments.slice(0, 5).map((arg, i) => (
                      <li key={i} className="text-xs text-gray-600 flex items-start gap-1">
                        <span className="text-gray-400 mt-0.5">•</span>
                        <span>{typeof arg === 'string' ? arg : JSON.stringify(arg)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Challenge */}
              {position.challenged && (
                <div className="mt-2 p-2 bg-red-50 rounded border border-red-200">
                  <div className="text-xs font-semibold text-red-600">
                    ⚔️ Challenge → {participants[position.challenged]?.display_name || position.challenged}
                  </div>
                  {position.challenge_reason && (
                    <div className="text-xs text-red-600 mt-0.5">{position.challenge_reason.slice(0, 300)}</div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}


// ============================================================
// Verdict Panel
// ============================================================

function VerdictPanel({ verdict }) {
  const typeLabels = {
    consensus:         { label: '✅ Consensus', bg: 'bg-green-50', border: 'border-green-300' },
    consensus_partiel: { label: '⚠️ Consensus partiel', bg: 'bg-yellow-50', border: 'border-yellow-300' },
    dissensus:         { label: '❌ Dissensus', bg: 'bg-red-50', border: 'border-red-300' },
  }
  const info = typeLabels[verdict.verdict_type] || typeLabels.dissensus

  return (
    <div className={`animate-fade-in rounded-xl border-2 p-6 ${info.bg} ${info.border}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xl font-bold">{info.label}</h3>
        <span className="text-lg font-semibold text-gray-600">
          Confiance : {verdict.confidence}%
        </span>
      </div>

      {verdict.summary && (
        <div className="mb-4">
          <h4 className="text-sm font-semibold text-gray-600 mb-1">📝 Synthèse</h4>
          <p className="text-gray-700 text-sm whitespace-pre-wrap">{verdict.summary}</p>
        </div>
      )}

      {verdict.agreement_points?.length > 0 && (
        <div className="mb-3">
          <h4 className="text-sm font-semibold text-green-700 mb-1">✅ Points d'accord</h4>
          <ul className="list-disc list-inside text-sm text-gray-600 space-y-0.5">
            {verdict.agreement_points.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </div>
      )}

      {verdict.divergence_points?.length > 0 && (
        <div className="mb-3">
          <h4 className="text-sm font-semibold text-red-700 mb-1">❌ Points de divergence</h4>
          <ul className="list-disc list-inside text-sm text-gray-600 space-y-0.5">
            {verdict.divergence_points.map((p, i) => (
              <li key={i}>{typeof p === 'object' ? p.topic || JSON.stringify(p) : p}</li>
            ))}
          </ul>
        </div>
      )}

      {verdict.recommendation && (
        <div className="mt-4 p-3 bg-white/50 rounded-lg">
          <h4 className="text-sm font-semibold text-gray-600 mb-1">💡 Recommandation</h4>
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{verdict.recommendation}</p>
        </div>
      )}

      {verdict.key_insights?.length > 0 && (
        <div className="mt-3">
          <h4 className="text-sm font-semibold text-gray-600 mb-1">🔍 Insights clés</h4>
          <ul className="list-disc list-inside text-sm text-gray-600 space-y-0.5">
            {verdict.key_insights.map((p, i) => <li key={i}>{typeof p === 'string' ? p : JSON.stringify(p)}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}
