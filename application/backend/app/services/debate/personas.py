"""
PersonaManager — Attribution et gestion des personas pour les participants.

Chaque participant au débat reçoit un persona (angle d'analyse) qui influence
son system prompt. Les personas sont définis dans config/personas.yaml et
attribués automatiquement selon le nombre de participants, avec possibilité
d'override par l'utilisateur.

Ref: DESIGN/architecture.md §3.5, §12.3
Ref académique: [7] Persona-Driven Multi-Agent (COLING 2025)

Principes :
- Les personas maximisent la diversité des perspectives
- L'attribution automatique suit une table prédéfinie (2→5 participants)
- L'utilisateur peut overrider un persona pour un modèle spécifique
- Les définitions (nom, description, icône, couleur) viennent du YAML
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .models import Participant
from ...config.loader import get_personas

logger = logging.getLogger(__name__)

__all__ = ["PersonaManager", "PersonaDefinition"]


# ============================================================
# Dataclass pour une définition de persona
# ============================================================

@dataclass
class PersonaDefinition:
    """
    Définition complète d'un persona chargée depuis personas.yaml.

    Attributes:
        id: Clé YAML (ex: "pragmatique")
        name: Nom affiché (ex: "Pragmatique")
        description: Description du rôle (injectée dans le system prompt)
        icon: Emoji représentatif
        color: Couleur hex pour le frontend
    """
    id: str
    name: str
    description: str
    icon: str = ""
    color: str = ""


# ============================================================
# PersonaManager
# ============================================================

class PersonaManager:
    """
    Gère l'attribution des personas aux participants du débat.

    Workflow :
    1. Charger les définitions depuis personas.yaml
    2. Déterminer l'attribution selon le nombre de participants
    3. Appliquer les overrides utilisateur (si fournis)
    4. Peupler les champs persona de chaque Participant

    Usage :
        manager = PersonaManager()
        manager.assign_personas(participants, persona_overrides={"gpt-5.2": "expert_technique"})
    """

    def __init__(self) -> None:
        """Initialise le PersonaManager en chargeant les définitions YAML."""
        self._definitions: Dict[str, PersonaDefinition] = {}
        self._auto_assignment: Dict[int, List[str]] = {}
        self._load_config()

    def _load_config(self) -> None:
        """
        Charge les personas depuis personas.yaml via le config loader.

        Le fichier YAML contient :
        - definitions: dict des personas (id → {name, description, icon, color})
        - auto_assignment: dict N participants → [persona_ids]
        """
        config = get_personas()

        # Charger les définitions
        for persona_id, persona_cfg in config.get("definitions", {}).items():
            self._definitions[persona_id] = PersonaDefinition(
                id=persona_id,
                name=persona_cfg.get("name", persona_id),
                description=persona_cfg.get("description", ""),
                icon=persona_cfg.get("icon", ""),
                color=persona_cfg.get("color", ""),
            )

        # Charger la table d'attribution automatique
        for n_str, persona_ids in config.get("auto_assignment", {}).items():
            self._auto_assignment[int(n_str)] = persona_ids

        logger.info(
            f"✓ PersonaManager chargé : {len(self._definitions)} personas, "
            f"tables pour {list(self._auto_assignment.keys())} participants"
        )

    # ─── Accesseurs ──────────────────────────────────────────

    @property
    def definitions(self) -> Dict[str, PersonaDefinition]:
        """Retourne toutes les définitions de personas."""
        return self._definitions

    def get_persona(self, persona_id: str) -> Optional[PersonaDefinition]:
        """
        Retourne la définition d'un persona par son ID.

        Args:
            persona_id: Clé YAML (ex: "pragmatique")

        Returns:
            PersonaDefinition ou None si non trouvé.
        """
        return self._definitions.get(persona_id)

    def get_auto_assignment(self, n_participants: int) -> List[str]:
        """
        Retourne la liste ordonnée de persona IDs pour N participants.

        Si N n'a pas de table prédéfinie, on utilise la plus proche table ≤ N
        et on complète en cyclant sur les personas restants.

        Args:
            n_participants: Nombre de participants (1-5+).

        Returns:
            Liste de persona IDs (longueur = n_participants).
        """
        if n_participants <= 0:
            return []

        # Cas exact : table prédéfinie
        if n_participants in self._auto_assignment:
            return list(self._auto_assignment[n_participants])

        # Cas N > max : utiliser la plus grande table et compléter
        available_ns = sorted(self._auto_assignment.keys())
        if not available_ns:
            logger.warning("⚠ Aucune table d'auto-assignment — personas non attribués")
            return []

        # Trouver la table la plus proche ≤ N
        best_n = available_ns[-1]  # La plus grande par défaut
        base_assignment = list(self._auto_assignment[best_n])

        # Compléter si besoin en cyclant sur tous les personas définis
        all_ids = list(self._definitions.keys())
        result = base_assignment.copy()
        cycle_idx = 0
        while len(result) < n_participants:
            candidate = all_ids[cycle_idx % len(all_ids)]
            if candidate not in result:
                result.append(candidate)
            cycle_idx += 1
            # Sécurité : si on a fait un tour complet sans ajouter, forcer
            if cycle_idx > len(all_ids) * 2:
                result.append(all_ids[cycle_idx % len(all_ids)])
        return result[:n_participants]

    # ─── Attribution ─────────────────────────────────────────

    def assign_personas(
        self,
        participants: List[Participant],
        persona_overrides: Optional[Dict[str, str]] = None,
    ) -> List[Participant]:
        """
        Attribue un persona à chaque participant (in-place).

        Pipeline :
        1. Obtenir la table d'attribution automatique pour N participants
        2. Appliquer les overrides utilisateur (model_id → persona_id)
        3. Peupler les champs persona de chaque Participant

        Args:
            participants: Liste des participants (modifiés in-place).
            persona_overrides: Dict {model_id: persona_id} pour overrider
                               l'attribution automatique. Le persona_id peut
                               être un ID YAML (ex: "expert_technique") ou
                               un texte libre (description custom).

        Returns:
            La liste des participants avec personas attribués.
        """
        overrides = persona_overrides or {}
        n = len(participants)
        auto_ids = self.get_auto_assignment(n)

        for i, participant in enumerate(participants):
            # 1. Vérifier si override pour ce modèle
            override = overrides.get(participant.model_id)

            if override:
                persona = self._resolve_override(override)
            elif i < len(auto_ids):
                # 2. Attribution automatique
                persona = self.get_persona(auto_ids[i])
            else:
                persona = None

            # 3. Peupler les champs du Participant
            if persona:
                participant.persona_id = persona.id
                participant.persona_name = persona.name
                participant.persona_description = persona.description
                participant.persona_icon = persona.icon
                participant.persona_color = persona.color
            else:
                # Fallback : persona générique
                participant.persona_id = "generic"
                participant.persona_name = "Analyste"
                participant.persona_description = (
                    "Analyse la question sous tous ses angles avec objectivité."
                )
                logger.warning(
                    f"⚠ Pas de persona pour participant #{i} "
                    f"({participant.model_id}) — fallback générique"
                )

        assigned = [
            f"{p.model_id}→{p.persona_name}" for p in participants
        ]
        logger.info(f"✓ Personas attribués : {', '.join(assigned)}")

        return participants

    def _resolve_override(self, override_value: str) -> PersonaDefinition:
        """
        Résout un override : soit un persona_id connu, soit un texte libre.

        Args:
            override_value: Soit un ID YAML (ex: "expert_technique"),
                           soit un texte libre (ex: "Expert sécurité").

        Returns:
            PersonaDefinition (existante ou créée dynamiquement).
        """
        # Cas 1 : c'est un ID de persona connu
        known = self.get_persona(override_value)
        if known:
            return known

        # Cas 2 : texte libre → créer une PersonaDefinition dynamique
        logger.info(f"📝 Override persona custom : '{override_value}'")
        return PersonaDefinition(
            id="custom",
            name=override_value,
            description=f"Expert spécialisé : {override_value}. "
                        f"Analyse la question depuis cet angle d'expertise.",
            icon="🎯",
            color="#607D8B",
        )

    # ─── API publique ────────────────────────────────────────

    def list_personas(self) -> List[Dict[str, Any]]:
        """
        Liste toutes les personas disponibles (pour l'API REST).

        Returns:
            Liste de dicts avec id, name, description, icon, color.
        """
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "icon": p.icon,
                "color": p.color,
            }
            for p in self._definitions.values()
        ]
