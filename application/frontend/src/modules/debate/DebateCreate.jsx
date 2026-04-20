/**
 * DebateCreate — Formulaire de création d'un débat.
 *
 * L'utilisateur :
 * 1. Tape sa question
 * 2. Sélectionne les LLMs participants (2-5)
 * 3. Lance le débat → redirigé vers la vue temps réel
 */
import { useState, useEffect } from 'react'
import useHttpClient from '../../hooks/useHttpClient'

/** Modèles pré-définis pour le MVP (avant chargement dynamique). */
const DEFAULT_MODELS = [
  { provider: 'llmaas', model: 'gpt-oss-120b', label: '🛡️ GPT-OSS 120B (SNC)' },
  { provider: 'llmaas', model: 'qwen35-27b', label: '🛡️ Qwen 3.5 27B (SNC)' },
  { provider: 'llmaas', model: 'gemma4-31b', label: '🛡️ Gemma 4 31B (SNC)' },
  { provider: 'openai', model: 'gpt-52', label: '🟢 GPT-5.2 (OpenAI)' },
  { provider: 'anthropic', model: 'claude-opus-46', label: '🟠 Claude Opus 4.6 (Anthropic)' },
  { provider: 'google', model: 'gemini-31-pro', label: '🔵 Gemini 3.1 Pro (Google)' },
]

export default function DebateCreate({ onCreated }) {
  const { post, loading, error } = useHttpClient()
  const [question, setQuestion] = useState('')
  const [selected, setSelected] = useState([DEFAULT_MODELS[0].model, DEFAULT_MODELS[4].model])

  /** Toggle un modèle dans la sélection. */
  const toggleModel = (modelId) => {
    setSelected((prev) => {
      if (prev.includes(modelId)) {
        return prev.filter((m) => m !== modelId)
      }
      if (prev.length >= 5) return prev // Max 5
      return [...prev, modelId]
    })
  }

  /** Soumet le formulaire → crée le débat via l'API. */
  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!question.trim() || selected.length < 2) return

    try {
      const participants = selected.map((modelId) => {
        const m = DEFAULT_MODELS.find((d) => d.model === modelId)
        return { provider: m?.provider || 'llmaas', model: modelId }
      })

      const data = await post('/debates', { question, participants })

      onCreated({
        id: data.debate_id,
        streamUrl: data.stream_url,
      })
    } catch (err) {
      // Erreur affichée via useHttpClient
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-700 mb-4">
        🏛️ Nouveau débat
      </h2>

      {/* Question */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-600 mb-1">
          Votre question
        </label>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ex: Faut-il migrer notre infrastructure vers Kubernetes ?"
          rows={3}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 resize-none"
        />
      </div>

      {/* Sélection des LLMs */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-600 mb-2">
          Participants ({selected.length}/5)
        </label>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {DEFAULT_MODELS.map((m) => (
            <button
              key={m.model}
              type="button"
              onClick={() => toggleModel(m.model)}
              className={`px-3 py-2 text-sm rounded-lg border transition-all text-left ${
                selected.includes(m.model)
                  ? 'border-primary-500 bg-primary-50 text-primary-700 font-medium'
                  : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {/* Erreur */}
      {error && (
        <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
          ⚠️ {error}
        </div>
      )}

      {/* Bouton submit */}
      <button
        type="submit"
        disabled={loading || !question.trim() || selected.length < 2}
        className="w-full py-3 bg-primary-600 text-white rounded-lg font-medium hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? '⏳ Création...' : `🚀 Lancer le débat (${selected.length} LLMs)`}
      </button>
    </form>
  )
}
