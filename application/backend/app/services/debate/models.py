"""
Debate Models — Dataclasses pour le moteur de débat.

Modèles de données pour les débats, participants, rounds, positions, et verdicts.
Ref: DESIGN/architecture.md §3, §12.6, §13
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================
# Enums
# ============================================================

class DebatePhase(str, Enum):
    """Phase du débat."""
    OPENING = "opening"
    DEBATE = "debate"
    VERDICT = "verdict"
    COMPLETED = "completed"
    ERROR = "error"
    PAUSED = "paused"  # En attente de réponse utilisateur


class DebateStatus(str, Enum):
    """Statut global du débat."""
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


class VerdictType(str, Enum):
    """Type de verdict."""
    CONSENSUS = "consensus"
    CONSENSUS_PARTIEL = "consensus_partiel"
    DISSENSUS = "dissensus"
    ERROR = "error"


class ChallengeQuality(str, Enum):
    """Qualité du challenge anti-conformité."""
    SUBSTANTIVE = "substantive"
    SUPERFICIAL = "superficial"
    ABSENT = "absent"


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class Position:
    """Position structurée d'un participant (parsée depuis les marqueurs YAML)."""
    thesis: str = ""
    confidence: int = 50
    arguments: List[str] = field(default_factory=list)
    challenged: Optional[str] = None
    challenge_target: Optional[str] = None
    challenge_reason: Optional[str] = None
    challenge_quality: ChallengeQuality = ChallengeQuality.ABSENT
    agrees_with: Dict[str, str] = field(default_factory=dict)
    disagrees_with: Dict[str, str] = field(default_factory=dict)
    sentiment: str = "neutral"  # pour/mitigé/contre — utilisé par StabilityDetector


@dataclass
class Participant:
    """Un participant au débat (un LLM avec son persona)."""
    id: str                          # ex: "gpt-oss-120b"
    model_id: str                    # ID du modèle dans llm_models.yaml
    provider: str                    # "llmaas", "openai", etc.
    display_name: str                # Nom affiché
    persona_id: str = ""             # ID du persona assigné
    persona_name: str = ""           # Nom du persona (ex: "Pragmatique")
    persona_description: str = ""    # Description du persona
    persona_icon: str = ""           # Emoji du persona
    persona_color: str = ""          # Couleur du persona
    active: bool = True              # Le participant est-il encore actif ?
    consecutive_skips: int = 0       # Rounds consécutifs skipés
    flags: List[str] = field(default_factory=list)


@dataclass
class Turn:
    """Un tour de parole d'un participant dans un round."""
    participant_id: str
    round_number: int
    phase: DebatePhase
    content: str = ""                # Texte libre (prose markdown)
    structured_position: Optional[Position] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    user_question: Optional[str] = None  # Question posée à l'utilisateur
    flags: List[str] = field(default_factory=list)
    tokens_used: int = 0
    duration_ms: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None      # Erreur si le tour a échoué


@dataclass
class Round:
    """Un round complet du débat (tous les participants)."""
    number: int
    turns: List[Turn] = field(default_factory=list)
    stability_score: Optional[float] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class UserAnswer:
    """Réponse de l'utilisateur à une question posée par un participant."""
    question: str
    answer: str
    asked_by: str                    # participant_id
    round_number: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Verdict:
    """Verdict du synthétiseur."""
    type: VerdictType = VerdictType.ERROR
    confidence: int = 0
    summary: str = ""
    agreement_points: List[str] = field(default_factory=list)
    divergence_points: List[Dict[str, Any]] = field(default_factory=list)
    recommendation: str = ""
    unresolved_questions: List[str] = field(default_factory=list)
    key_insights: List[str] = field(default_factory=list)
    synthesizer_model: str = ""
    tokens_used: int = 0
    duration_ms: int = 0


@dataclass
class Debate:
    """Un débat complet."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    question: str = ""
    status: DebateStatus = DebateStatus.CREATED
    phase: DebatePhase = DebatePhase.OPENING
    participants: List[Participant] = field(default_factory=list)
    opening_turns: List[Turn] = field(default_factory=list)
    rounds: List[Round] = field(default_factory=list)
    verdict: Optional[Verdict] = None
    user_answers: List[UserAnswer] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    total_tokens: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
