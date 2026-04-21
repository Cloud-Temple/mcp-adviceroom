#!/bin/bash
# Test débat E2E avec Claude Opus 4-6 comme participant
# Objectif : Valider que ANTHROPIC_MAX_TOKENS=64000 résout les réponses vides

BASE_URL="http://localhost:8000/api/v1"

echo "=== Création du débat avec Claude Opus + GPT-5.2 ==="
echo "Question: Quels sont les 3 risques majeurs de l'IA générative en entreprise ?"
echo ""

# Créer le débat
RESPONSE=$(curl -s -X POST "${BASE_URL}/debates" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Quels sont les 3 risques majeurs de l IA generative en entreprise et comment les mitiger ?",
    "participants": [
      {"provider": "anthropic", "model": "claude-opus-46"},
      {"provider": "openai", "model": "gpt-52"}
    ],
    "config": {"max_rounds": 3}
  }')

DEBATE_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('debate_id','ERREUR'))" 2>/dev/null)

if [ "$DEBATE_ID" = "ERREUR" ] || [ -z "$DEBATE_ID" ]; then
  echo "❌ Erreur création débat:"
  echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
  exit 1
fi

echo "✅ Débat créé: $DEBATE_ID"
echo ""
echo "=== Streaming NDJSON (événements temps réel) ==="
echo ""

# Streamer les événements avec timeout 10 minutes
curl -s -N --max-time 600 "${BASE_URL}/debates/${DEBATE_ID}/stream" | while IFS= read -r line; do
  if [ -z "$line" ]; then
    continue
  fi
  
  EVENT_TYPE=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('event','?'))" 2>/dev/null)
  
  case "$EVENT_TYPE" in
    "debate_start")
      echo "🎯 DÉBAT DÉMARRÉ"
      ;;
    "phase")
      PHASE=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('phase','?'))" 2>/dev/null)
      echo ""
      echo "📌 PHASE: $PHASE"
      echo "---"
      ;;
    "turn_start")
      MODEL=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('model','?'))" 2>/dev/null)
      ROUND=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('round',0))" 2>/dev/null)
      echo ""
      echo "🤖 Tour: $MODEL (round $ROUND)"
      ;;
    "turn_end")
      MODEL=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('model','?'))" 2>/dev/null)
      TOKENS=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tokens',0))" 2>/dev/null)
      ERROR=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" 2>/dev/null)
      CONTENT_LEN=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('content','')))" 2>/dev/null)
      
      if [ -n "$ERROR" ] && [ "$ERROR" != "" ] && [ "$ERROR" != "None" ]; then
        echo "   ❌ ERREUR: $ERROR"
      else
        echo "   ✅ $MODEL: ${CONTENT_LEN} chars, ${TOKENS} tokens"
      fi
      ;;
    "tool_call")
      TOOL=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name','?'))" 2>/dev/null)
      echo "   🔧 Tool call: $TOOL"
      ;;
    "stability")
      SCORE=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('score',0))" 2>/dev/null)
      STABLE=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('is_stable',False))" 2>/dev/null)
      echo "   📊 Stabilité: ${SCORE} (stable: ${STABLE})"
      ;;
    "verdict")
      TYPE=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('verdict_type','?'))" 2>/dev/null)
      CONF=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('confidence',0))" 2>/dev/null)
      echo ""
      echo "⚖️  VERDICT: $TYPE (confiance: ${CONF}%)"
      ;;
    "debate_end")
      TOTAL_TOKENS=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_tokens',0))" 2>/dev/null)
      ROUNDS=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('rounds',0))" 2>/dev/null)
      echo ""
      echo "🏁 DÉBAT TERMINÉ: $ROUNDS rounds, $TOTAL_TOKENS tokens"
      ;;
    *)
      # Ignorer les chunks et autres événements verbose
      ;;
  esac
done

echo ""
echo "=== Vérification status final ==="
curl -s "${BASE_URL}/debates/${DEBATE_ID}/status" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'Phase: {d.get(\"phase\", \"?\")}')
print(f'Rounds: {d.get(\"current_round\", \"?\")}')
participants = d.get('participants', {})
for name, info in participants.items():
    turns_ok = info.get('turns_ok', 0)
    turns_err = info.get('turns_error', 0)
    print(f'  {name}: {turns_ok} OK, {turns_err} erreurs')
verdict = d.get('verdict', {})
if verdict:
    print(f'Verdict: {verdict.get(\"type\", \"?\")} ({verdict.get(\"confidence\", 0)}%)')
" 2>/dev/null
