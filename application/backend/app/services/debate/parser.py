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


# ============================================================
# Regex communes pour extraction des blocs marqueurs
# ============================================================
# Format souple : ≥3 tirets, espaces optionnels, case-insensitive
_RE_POSITION = re.compile(
    r'-{3,}\s*POSITION\s*-{3,}\s*\n(.+?)\n\s*-{3,}\s*END\s*-{3,}',
    re.DOTALL | re.IGNORECASE,
)
_RE_VERDICT = re.compile(
    r'-{3,}\s*VERDICT\s*-{3,}\s*\n(.+?)\n\s*-{3,}\s*END\s*-{3,}',
    re.DOTALL | re.IGNORECASE,
)
_RE_CHALLENGE = re.compile(
    r'-{3,}\s*CHALLENGE\s*-{3,}\s*\n(.+?)\n\s*-{3,}\s*END\s*-{3,}',
    re.DOTALL | re.IGNORECASE,
)
_RE_USER_QUESTION = re.compile(
    r'-{3,}\s*USER_QUESTION\s*-{3,}\s*\n(.+?)\n\s*-{3,}\s*END\s*-{3,}',
    re.DOTALL | re.IGNORECASE,
)


# ============================================================
# Sanitization YAML — Protection des caractères problématiques
# ============================================================

# Caractères qui cassent le parsing YAML dans les valeurs LLM :
# - backticks (`pvresize`) → char invalide en YAML
# - markdown bold (**texte**) → confondu avec ancres YAML
# - accolades/crochets ({}, []) → inline collections YAML
# On NE touche PAS : | > # ! @ * (seul) — opérateurs YAML valides
_YAML_UNSAFE_RE = re.compile(r'`|\*\*|[{}\[\]]')

# Pattern de liste numérotée (ex: "1. texte", "2) texte")
_NUMBERED_LIST_RE = re.compile(r'^\d+[.\)]\s')


def _needs_quoting(text: str) -> bool:
    """Vérifie si un texte contient des caractères problématiques pour YAML."""
    return bool(':' in text or _YAML_UNSAFE_RE.search(text))


def _quote_value(text: str) -> str:
    """Wrappe une valeur avec des guillemets doubles, en échappant les quotes internes."""
    if text.startswith('"') or text.startswith("'"):
        return text  # Déjà quoté
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _sanitize_yaml_block(raw: str) -> str:
    """
    Pré-traite un bloc YAML pour protéger les caractères problématiques.

    Les LLMs produisent souvent du texte qui casse yaml.safe_load() :
    - ':' dans les valeurs (ex: 'thesis: blabla (ex: LangChain)')
    - Backticks dans les arguments (ex: '- `pvresize` applique...')
    - Markdown bold (ex: '- **Compatibilité** du système')
    - Listes numérotées (ex: '1. **texte**' interprété comme clé YAML)
    - Tabs dans l'indentation (interdit en YAML)

    Solution : pour chaque ligne, si la valeur/contenu contient des
    caractères problématiques et n'est pas déjà quoté, on wrappe
    avec des guillemets doubles.
    """
    # Pré-traitement : tabs → 2 espaces (YAML n'accepte pas les tabs)
    raw = raw.replace('\t', '  ')

    lines = raw.split('\n')
    fixed = []
    for line in lines:
        stripped = line.strip()
        # Skip empty lines and comments
        if not stripped or stripped.startswith('#'):
            fixed.append(line)
            continue

        # List items: "  - texte avec `backtick`" ou "  - topic: blabla"
        list_match = re.match(r'^(\s*-\s*)(.+)$', line)
        if list_match:
            prefix, content = list_match.group(1), list_match.group(2)
            # Vérifier si c'est un key-value dans la liste: "- key: value"
            kv_in_list = re.match(r'^([\w.-]+)\s*:\s*(.+)$', content)
            if kv_in_list:
                # "- key: value" → quoter la VALUE si elle contient des chars spéciaux
                lkey, lval = kv_in_list.group(1), kv_in_list.group(2)
                if _needs_quoting(lval):
                    fixed.append(f'{prefix}{lkey}: {_quote_value(lval)}')
                    continue
            else:
                # Item de liste simple: "- texte avec `cmd` ou **bold**"
                if _needs_quoting(content):
                    fixed.append(prefix + _quote_value(content))
                    continue
            fixed.append(line)
            continue

        # Key-value: "key: value with `stuff` or **bold**"
        # [\w.-]+ pour supporter les clés avec tirets (llm-a) et dots (model.id)
        kv_match = re.match(r'^(\s*)([\w.-]+)\s*:\s*(.+)$', line)
        if kv_match:
            indent, key, value = kv_match.group(1), kv_match.group(2), kv_match.group(3)
            if _needs_quoting(value):
                fixed.append(f'{indent}{key}: {_quote_value(value)}')
                continue
            fixed.append(line)
            continue

        # Key-only: "key:" (valeur sur les lignes suivantes, ex: "summary:")
        if re.match(r'^(\s*)([\w.-]+)\s*:\s*$', line):
            fixed.append(line)
            continue

        # Catch-all : lignes non structurées qui casseraient YAML
        # Ex: "1. **Compatibilité du système**" (liste numérotée)
        # Ex: "**texte markdown**" (bold seul sur une ligne)
        # Ex: "`commande` fait ceci" (backtick en début de ligne)
        # Ces lignes n'ont pas la structure YAML key: value ni - item.
        # YAML les interpréterait comme des clés de mapping → erreur.
        # On les convertit en items de liste YAML quotés.
        if _needs_quoting(stripped) or _NUMBERED_LIST_RE.match(stripped):
            indent_match = re.match(r'^(\s*)', line)
            indent = indent_match.group(1) if indent_match else ""
            fixed.append(f'{indent}- {_quote_value(stripped)}')
            continue

        fixed.append(line)
    return '\n'.join(fixed)


# ============================================================
# safe_confidence — Conversion robuste
# ============================================================

def safe_confidence(value: Any, default: int = 50) -> int:
    """
    Convertit une valeur de confiance en entier 0-100, robuste aux formats LLM.

    Gère : 85, "85", "85/100", "85%", "0.85", 85.5, None, etc.

    Args:
        value: Valeur brute retournée par le LLM.
        default: Valeur par défaut si conversion impossible.

    Returns:
        Entier entre 0 et 100.
    """
    if value is None:
        return default

    # Déjà un int
    if isinstance(value, int):
        return max(0, min(100, value))

    # Float (0.85 ou 85.5)
    if isinstance(value, float):
        if value <= 1.0:
            return max(0, min(100, int(value * 100)))
        return max(0, min(100, int(value)))

    # String — nettoyer et parser
    s = str(value).strip()

    # "85/100" → prendre le numérateur
    if "/" in s:
        s = s.split("/")[0].strip()

    # "85%" → retirer le %
    s = s.replace("%", "").strip()

    try:
        f = float(s)
        if f <= 1.0 and "." in str(value):
            return max(0, min(100, int(f * 100)))
        return max(0, min(100, int(f)))
    except (ValueError, TypeError):
        logger.warning(f"⚠ Confidence non parsable '{value}' → défaut {default}")
        return default


# ============================================================
# parse_position — Extraction du bloc ---POSITION---
# ============================================================

def parse_position(text: str) -> Tuple[str, Optional[Position]]:
    """
    Sépare le texte libre et le bloc structuré ---POSITION---.

    Args:
        text: Réponse complète du LLM.

    Returns:
        (prose, Position|None) — le texte libre et la position structurée (None si non parsable).
    """
    match = _RE_POSITION.search(text)
    if not match:
        # 2e tentative : chercher thesis/confidence directement (certains LLMs
        # oublient les marqueurs mais structurent quand même leur position)
        return _fallback_extract_position(text, text.strip())

    prose = text[:match.start()].strip()
    try:
        sanitized = _sanitize_yaml_block(match.group(1))
        data = yaml.safe_load(sanitized)
        if not isinstance(data, dict):
            raise ValueError("Le bloc POSITION n'est pas un dict YAML valide")
    except Exception as e:
        logger.warning(f"⚠ Erreur parsing YAML du bloc POSITION : {e}")
        # Fallback : extraire thesis et confidence par regex depuis le texte brut
        return _fallback_extract_position(match.group(1), prose)

    # Coercer les arguments en strings (les LLMs retournent parfois
    # du YAML avec ":" dans les arguments → parsé en dict au lieu de str)
    raw_args = data.get("arguments", []) or []
    safe_args = []
    for a in raw_args:
        if isinstance(a, str):
            safe_args.append(a)
        elif isinstance(a, dict):
            # YAML a parsé "texte: suite" comme {texte: suite} — rejoindre
            parts = [f"{k}: {v}" if v is not None else str(k) for k, v in a.items()]
            safe_args.append("; ".join(parts))
        else:
            safe_args.append(str(a))

    position = Position(
        thesis=str(data.get("thesis", "")),
        confidence=safe_confidence(data.get("confidence"), 50),
        arguments=safe_args,
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


def _fallback_extract_position(raw: str, prose: str) -> Tuple[str, Optional[Position]]:
    """
    Fallback : extraire thesis et confidence par regex quand YAML échoue.

    Cherche les patterns 'thesis: ...' et 'confidence: N' dans le texte brut.
    """
    thesis_match = re.search(
        r'(?:thesis|thèse)\s*:\s*["\']?(.+?)["\']?\s*$',
        raw, re.MULTILINE | re.IGNORECASE,
    )
    conf_match = re.search(r'confidence\s*:\s*(\d+)', raw, re.IGNORECASE)

    if thesis_match:
        if conf_match:
            logger.info("⚡ Position extraite par fallback regex (thesis + confidence)")
        else:
            logger.info("⚡ Position extraite par fallback regex (thesis seule, confidence=50)")
        return prose, Position(
            thesis=thesis_match.group(1).strip(),
            confidence=int(conf_match.group(1)) if conf_match else 50,
            arguments=[],
        )

    logger.warning("⚠ Pas de position structurée trouvée (ni YAML ni fallback regex)")
    return prose, None


# ============================================================
# parse_verdict — Extraction du bloc ---VERDICT---
# ============================================================

def parse_verdict(text: str) -> Tuple[str, Dict[str, Any]]:
    """
    Parse le bloc ---VERDICT--- depuis la réponse du synthétiseur.

    Args:
        text: Réponse complète du synthétiseur.

    Returns:
        (prose, verdict_dict) — le texte libre et le verdict structuré.
    """
    match = _RE_VERDICT.search(text)
    if not match:
        logger.warning("⚠ Pas de bloc ---VERDICT--- dans la réponse du synthétiseur")
        # Fallback : tenter d'extraire verdict/confidence par regex
        return _fallback_extract_verdict(text)

    prose = text[:match.start()].strip()
    try:
        sanitized = _sanitize_yaml_block(match.group(1))
        data = yaml.safe_load(sanitized)
        if not isinstance(data, dict):
            raise ValueError("Le bloc VERDICT n'est pas un dict YAML valide")
    except Exception as e:
        logger.warning(f"⚠ Erreur parsing YAML du bloc VERDICT : {e}")
        # Fallback regex sur le contenu brut du bloc
        return _fallback_extract_verdict_from_block(match.group(1), prose)

    return prose, data


def _fallback_extract_verdict(text: str) -> Tuple[str, Dict[str, Any]]:
    """Fallback verdict : chercher verdict/confidence par regex dans le texte complet."""
    verdict_m = re.search(
        r'verdict\s*:\s*(consensus|consensus_partiel|dissensus)',
        text, re.IGNORECASE,
    )
    conf_m = re.search(r'confidence\s*:\s*(\d+)', text, re.IGNORECASE)
    summary_m = re.search(
        r'summary\s*:\s*[|>]?\s*\n?\s*(.+?)(?:\n\w|\n---|\Z)',
        text, re.DOTALL | re.IGNORECASE,
    )

    if verdict_m:
        logger.info("⚡ Verdict extrait par fallback regex")
        return text.strip(), {
            "verdict": verdict_m.group(1).lower(),
            "confidence": int(conf_m.group(1)) if conf_m else 50,
            "summary": summary_m.group(1).strip() if summary_m else "Extrait par fallback.",
        }

    return text.strip(), {
        "verdict": "error",
        "confidence": 0,
        "summary": "Le synthétiseur n'a pas produit de verdict structuré.",
    }


def _fallback_extract_verdict_from_block(raw: str, prose: str) -> Tuple[str, Dict[str, Any]]:
    """Fallback verdict depuis le contenu brut du bloc ---VERDICT---."""
    verdict_m = re.search(
        r'verdict\s*:\s*(consensus|consensus_partiel|dissensus)',
        raw, re.IGNORECASE,
    )
    conf_m = re.search(r'confidence\s*:\s*(\d+)', raw, re.IGNORECASE)

    if verdict_m:
        logger.info("⚡ Verdict extrait par fallback regex (bloc YAML invalide)")
        return prose, {
            "verdict": verdict_m.group(1).lower(),
            "confidence": int(conf_m.group(1)) if conf_m else 50,
            "summary": "Extrait par fallback (YAML invalide dans le bloc).",
        }

    return prose, {"verdict": "error", "confidence": 0, "summary": "YAML invalide dans le bloc VERDICT."}


# ============================================================
# parse_challenge — Extraction du bloc ---CHALLENGE---
# ============================================================

def parse_challenge(text: str) -> Optional[Dict[str, str]]:
    """
    Parse le bloc ---CHALLENGE--- depuis un retry anti-conformité.

    Args:
        text: Réponse au prompt de retry.

    Returns:
        Dict avec challenged, challenge_target, challenge_reason — ou None.
    """
    match = _RE_CHALLENGE.search(text)
    if not match:
        return None

    try:
        sanitized = _sanitize_yaml_block(match.group(1))
        data = yaml.safe_load(sanitized)
        if isinstance(data, dict) and "challenged" in data:
            return data
    except Exception as e:
        logger.warning(f"⚠ Erreur parsing bloc CHALLENGE : {e}")

    # Fallback regex : extraire challenged et challenge_reason
    raw = match.group(1)
    challenged_m = re.search(r'challenged\s*:\s*(\S+)', raw, re.IGNORECASE)
    reason_m = re.search(
        r'challenge_reason\s*:\s*[|>]?\s*\n?\s*(.+)',
        raw, re.DOTALL | re.IGNORECASE,
    )
    if challenged_m:
        logger.info("⚡ Challenge extrait par fallback regex")
        return {
            "challenged": challenged_m.group(1).strip(),
            "challenge_target": "",
            "challenge_reason": reason_m.group(1).strip()[:500] if reason_m else "",
        }

    return None


# ============================================================
# parse_user_question — Extraction du bloc ---USER_QUESTION---
# ============================================================

def parse_user_question(text: str) -> Optional[str]:
    """
    Extrait une question pour l'utilisateur depuis la réponse LLM.

    Args:
        text: Réponse complète du LLM.

    Returns:
        La question, ou None si pas de question.
    """
    match = _RE_USER_QUESTION.search(text)
    if match:
        return match.group(1).strip()
    return None
