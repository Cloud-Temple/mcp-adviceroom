"""
Response Parser — Parse les réponses LLM avec marqueurs YAML.

Les LLMs produisent du texte libre (prose markdown) suivi de blocs
structurés délimités par des marqueurs :
- ---POSITION--- / ---END---   (opening et debate)
- ---VERDICT--- / ---END---    (verdict)
- ---CHALLENGE--- / ---END---  (retry anti-conformité)
- ---USER_QUESTION--- / ---END---  (question à l'utilisateur)

Ref: DESIGN/architecture.md §12.6
"""
import logging
import re
from typing import Any, Dict, Optional, Tuple

import yaml

from .models import Position, ChallengeQuality

logger = logging.getLogger(__name__)


def parse_position(text: str) -> Tuple[str, Position]:
    """
    Sépare le texte libre et le bloc structuré ---POSITION---.

    Args:
        text: Réponse complète du LLM.

    Returns:
        (prose, Position) — le texte libre et la position structurée.
    """
    match = re.search(r'---POSITION---\n(.+?)\n---END---', text, re.DOTALL)
    if not match:
        # Fallback : pas de bloc structuré → position inconnue
        logger.warning("⚠ Pas de bloc ---POSITION--- dans la réponse LLM — fallback")
        return text.strip(), Position(
            thesis="Non structuré",
            confidence=50,
            arguments=[],
        )

    prose = text[:match.start()].strip()
    try:
        data = yaml.safe_load(match.group(1))
        if not isinstance(data, dict):
            raise ValueError("Le bloc POSITION n'est pas un dict YAML valide")
    except Exception as e:
        logger.warning(f"⚠ Erreur parsing YAML du bloc POSITION : {e}")
        return prose, Position(thesis="Parsing échoué", confidence=50, arguments=[])

    position = Position(
        thesis=str(data.get("thesis", "")),
        confidence=int(data.get("confidence", 50)),
        arguments=data.get("arguments", []) or [],
        challenged=data.get("challenged"),
        challenge_target=data.get("challenge_target"),
        challenge_reason=data.get("challenge_reason"),
        agrees_with=data.get("agrees_with", {}) or {},
        disagrees_with=data.get("disagrees_with", {}) or {},
    )

    # Évaluer la qualité du challenge
    if position.challenged and position.challenge_reason:
        if len(position.challenge_reason) >= 50:
            position.challenge_quality = ChallengeQuality.SUBSTANTIVE
        elif len(position.challenge_reason) >= 20:
            position.challenge_quality = ChallengeQuality.SUPERFICIAL
        else:
            position.challenge_quality = ChallengeQuality.SUPERFICIAL
    else:
        position.challenge_quality = ChallengeQuality.ABSENT

    return prose, position


def parse_verdict(text: str) -> Tuple[str, Dict[str, Any]]:
    """
    Parse le bloc ---VERDICT--- depuis la réponse du synthétiseur.

    Args:
        text: Réponse complète du synthétiseur.

    Returns:
        (prose, verdict_dict) — le texte libre et le verdict structuré.
    """
    match = re.search(r'---VERDICT---\n(.+?)\n---END---', text, re.DOTALL)
    if not match:
        logger.warning("⚠ Pas de bloc ---VERDICT--- dans la réponse du synthétiseur")
        return text.strip(), {
            "verdict": "error",
            "confidence": 0,
            "summary": "Le synthétiseur n'a pas produit de verdict structuré.",
        }

    prose = text[:match.start()].strip()
    try:
        data = yaml.safe_load(match.group(1))
        if not isinstance(data, dict):
            raise ValueError("Le bloc VERDICT n'est pas un dict YAML valide")
    except Exception as e:
        logger.warning(f"⚠ Erreur parsing YAML du bloc VERDICT : {e}")
        return prose, {"verdict": "error", "confidence": 0, "summary": str(e)}

    return prose, data


def parse_challenge(text: str) -> Optional[Dict[str, str]]:
    """
    Parse le bloc ---CHALLENGE--- depuis un retry anti-conformité.

    Args:
        text: Réponse au prompt de retry.

    Returns:
        Dict avec challenged, challenge_target, challenge_reason — ou None.
    """
    match = re.search(r'---CHALLENGE---\n(.+?)\n---END---', text, re.DOTALL)
    if not match:
        return None

    try:
        data = yaml.safe_load(match.group(1))
        if isinstance(data, dict) and "challenged" in data:
            return data
    except Exception as e:
        logger.warning(f"⚠ Erreur parsing bloc CHALLENGE : {e}")

    return None


def parse_user_question(text: str) -> Optional[str]:
    """
    Extrait une question pour l'utilisateur depuis la réponse LLM.

    Args:
        text: Réponse complète du LLM.

    Returns:
        La question, ou None si pas de question.
    """
    match = re.search(r'---USER_QUESTION---\n(.+?)\n---END---', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None
