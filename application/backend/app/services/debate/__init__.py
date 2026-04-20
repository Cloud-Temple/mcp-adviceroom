"""
Debate Package — Moteur de débat AdviceRoom.

Composants :
- models.py : Dataclasses (Debate, Participant, Turn, Round, Position, Verdict)
- parser.py : Parser des réponses LLM (marqueurs YAML)
- orchestrator.py : DebateOrchestrator — chef d'orchestre du débat
- stability.py : StabilityDetector — détection de stabilité (arrêt adaptatif)
- personas.py : PersonaManager — attribution et gestion des personas
- verdict.py : VerdictSynthesizer — analyse trajectoire → verdict structuré
- context_builder.py : ContextBuilder — construction du contexte par participant
"""
from .models import (
    Debate,
    DebatePhase,
    DebateStatus,
    Participant,
    Position,
    Round,
    Turn,
    UserAnswer,
    Verdict,
    VerdictType,
    ChallengeQuality,
)

__all__ = [
    "Debate",
    "DebatePhase",
    "DebateStatus",
    "Participant",
    "Position",
    "Round",
    "Turn",
    "UserAnswer",
    "Verdict",
    "VerdictType",
    "ChallengeQuality",
]
