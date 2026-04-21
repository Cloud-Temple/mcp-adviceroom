#!/usr/bin/env python3
"""Analyse détaillée du dernier débat AdviceRoom via admin API."""
import json
import subprocess
import sys

DEBATE_ID = "b4059e04-6a42-4f4a-bfec-0c5778601b86"
BASE_URL = "http://localhost:8000"
TOKEN = "adviceroom-dev-key-change-in-production-2026"


def fetch(path):
    """Récupère une URL et retourne le dict JSON."""
    result = subprocess.run(
        ["curl", "-s", f"{BASE_URL}{path}", "-H", f"Authorization: Bearer {TOKEN}"],
        capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def main():
    # Charger le débat complet via admin API
    data = fetch(f"/admin/api/debates/{DEBATE_ID}")
    debate = data.get("debate", data)

    print("=" * 70)
    print("ANALYSE DU DÉBAT")
    print("=" * 70)
    print(f"ID:       {debate.get('id', '?')}")
    print(f"Question: {debate.get('question', '?')}")
    print(f"Statut:   {debate.get('status', '?')} | Phase: {debate.get('phase', '?')}")
    print(f"Créé:     {debate.get('created_at', '?')}")
    print(f"Terminé:  {debate.get('completed_at', '?')}")
    print(f"Tokens:   {debate.get('total_tokens', 0):,}")
    print()

    # Participants
    participants = debate.get("participants", [])
    print("=" * 70)
    print(f"PARTICIPANTS ({len(participants)})")
    print("=" * 70)
    for p in participants:
        name = p.get("display_name", p.get("model_id", "?"))
        provider = p.get("provider", "?")
        persona = p.get("persona_name", "?")
        if persona == "?":
            pers = p.get("persona", {})
            if isinstance(pers, dict):
                persona = pers.get("name", "?")
        icon = p.get("persona_icon", "")
        if not icon:
            pers = p.get("persona", {})
            if isinstance(pers, dict):
                icon = pers.get("icon", "")
        print(f"  {icon} {name:20s} ({provider:10s}) — Persona: {persona}")
    print()

    # Opening
    opening = debate.get("opening", {})
    if opening and opening.get("turns"):
        print("=" * 70)
        print("PHASE OPENING")
        print("=" * 70)
        for t in opening.get("turns", []):
            _print_turn(t, "  ")
        print()

    # Rounds
    rounds = debate.get("rounds", [])
    print("=" * 70)
    print(f"ROUNDS DE DÉBAT ({len(rounds)})")
    print("=" * 70)
    for r in rounds:
        rnum = r.get("round_number", "?")
        turns = r.get("turns", [])
        stab = r.get("stability")
        print(f"\n--- Round {rnum} ({len(turns)} tours) ---")
        if stab and isinstance(stab, dict):
            score = stab.get("score", 0)
            can_stop = stab.get("can_stop", False)
            if isinstance(score, (int, float)):
                print(f"    Stabilité: score={score:.2f}, can_stop={can_stop}")
            else:
                print(f"    Stabilité: score={score}, can_stop={can_stop}")
        for t in turns:
            _print_turn(t, "    ")
    print()

    # Verdict
    v = debate.get("verdict", {})
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    if v:
        print(f"Type:           {v.get('type', '?')}")
        print(f"Confiance:      {v.get('confidence', '?')}")
        print(f"Synthétiseur:   {v.get('synthesizer_model', '⚠️  NON SPÉCIFIÉ')}")
        print(f"Tokens verdict: {v.get('tokens_used', 0):,}")
        print(f"Durée verdict:  {v.get('duration_ms', 0):,}ms")
        print()
        print(f"Résumé: {v.get('summary', '?')[:300]}")
        print()

        for label, key in [
            ("Points d'accord", "agreement_points"),
            ("Divergences", "divergence_points"),
            ("Insights", "key_insights"),
        ]:
            items = v.get(key, [])
            if items:
                print(f"{label} ({len(items)}):")
                for item in items:
                    print(f"  • {str(item)[:150]}")
                print()

        reco = v.get("recommendation", "")
        if reco:
            print(f"Recommandation: {reco[:300]}")
            print()
    else:
        print("  Pas de verdict ⚠️")
        print()

    # Résumé des erreurs
    print("=" * 70)
    print("RÉSUMÉ DES ERREURS")
    print("=" * 70)
    error_count = 0
    if opening and opening.get("turns"):
        for t in opening.get("turns", []):
            if t.get("error"):
                error_count += 1
                print(f"  OPENING, {t.get('participant_id')}: {t.get('error')[:200]}")
    for r in rounds:
        for t in r.get("turns", []):
            if t.get("error"):
                error_count += 1
                print(f"  Round {r.get('round_number')}, {t.get('participant_id')}: "
                      f"{t.get('error')[:200]}")
    if error_count == 0:
        print("  Aucune erreur ✅")
    else:
        print(f"\n  Total: {error_count} erreur(s)")

    # Clés disponibles (debug)
    print()
    print("=" * 70)
    print("CLÉS DISPONIBLES DANS LE JSON (debug)")
    print("=" * 70)
    print(f"  Top-level keys: {list(debate.keys()) if isinstance(debate, dict) else type(debate)}")
    if v:
        print(f"  Verdict keys: {list(v.keys())}")


def _print_turn(t, indent="  "):
    """Affiche un tour de parole."""
    pid = t.get("participant_id", "?")
    tokens = t.get("tokens_used", 0)
    dur = t.get("duration_ms", 0)
    err = t.get("error")
    pos = t.get("position")
    tools = t.get("tool_calls", [])

    if err:
        print(f"{indent}❌ {pid:20s}: ERREUR — {err[:150]}")
        return

    if pos and isinstance(pos, dict):
        thesis = pos.get("thesis", "")[:80]
        conf = pos.get("confidence", "?")
        challenged = pos.get("challenged")
        print(f"{indent}✅ {pid:20s}: {tokens:6d} tok, {dur:6d}ms | conf={conf}")
        print(f"{indent}   Thèse: {thesis}")
        if challenged:
            target = pos.get("challenge_target", "?")
            print(f"{indent}   Challenge → {target}: {str(challenged)[:80]}")
    else:
        print(f"{indent}⚠️  {pid:20s}: {tokens:6d} tok, {dur:6d}ms | pas de position structurée")

    if tools:
        for tc in tools:
            name = tc.get("name", "?")
            if isinstance(tc, dict) and "function" in tc:
                name = tc["function"].get("name", name)
            print(f"{indent}   🔧 Tool: {name}")


if __name__ == "__main__":
    main()
