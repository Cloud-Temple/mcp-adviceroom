"""
Tests PersonaManager — Attribution et gestion des personas.

Couvre :
- Chargement des définitions depuis la config YAML mockée
- Attribution automatique pour 2, 3, 4, 5 participants
- Overrides utilisateur (persona connu + texte libre)
- Cas limites : 0 participant, 1 participant (pas de table), 6+ participants
- Fallback générique quand pas de persona
- Listing des personas pour l'API

Ref: DESIGN/architecture.md §3.5
"""
import pytest

from app.services.debate.personas import PersonaManager, PersonaDefinition
from app.services.debate.models import Participant
from tests.conftest import make_participant


# ============================================================
# Tests de chargement
# ============================================================

class TestPersonaManagerLoading:
    """Tests du chargement des définitions et tables d'attribution."""

    def test_load_definitions(self, mock_personas_config):
        """Vérifie que les 5 personas sont chargés depuis la config."""
        manager = PersonaManager()
        assert len(manager.definitions) == 5

    def test_load_definition_fields(self, mock_personas_config):
        """Vérifie que tous les champs d'un persona sont chargés correctement."""
        manager = PersonaManager()
        pragmatique = manager.get_persona("pragmatique")

        assert pragmatique is not None
        assert pragmatique.id == "pragmatique"
        assert pragmatique.name == "Pragmatique"
        assert "coût-bénéfice" in pragmatique.description
        assert pragmatique.icon == "💼"
        assert pragmatique.color == "#4CAF50"

    def test_load_all_personas(self, mock_personas_config):
        """Vérifie que tous les personas attendus sont présents."""
        manager = PersonaManager()
        expected = {"pragmatique", "analyste_risques", "expert_technique",
                    "avocat_du_diable", "visionnaire"}
        assert set(manager.definitions.keys()) == expected

    def test_get_unknown_persona_returns_none(self, mock_personas_config):
        """Un persona inconnu retourne None."""
        manager = PersonaManager()
        assert manager.get_persona("inexistant") is None


# ============================================================
# Tests d'auto-assignment
# ============================================================

class TestAutoAssignment:
    """Tests des tables d'attribution automatique."""

    def test_auto_assign_2(self, mock_personas_config):
        """2 participants → Pragmatique + Avocat du diable."""
        manager = PersonaManager()
        result = manager.get_auto_assignment(2)
        assert result == ["pragmatique", "avocat_du_diable"]

    def test_auto_assign_3(self, mock_personas_config):
        """3 participants → Pragmatique + Analyste risques + Expert technique."""
        manager = PersonaManager()
        result = manager.get_auto_assignment(3)
        assert result == ["pragmatique", "analyste_risques", "expert_technique"]

    def test_auto_assign_4(self, mock_personas_config):
        """4 participants → les 4 premiers personas."""
        manager = PersonaManager()
        result = manager.get_auto_assignment(4)
        assert len(result) == 4
        assert result[0] == "pragmatique"
        assert "avocat_du_diable" in result

    def test_auto_assign_5(self, mock_personas_config):
        """5 participants → tous les personas."""
        manager = PersonaManager()
        result = manager.get_auto_assignment(5)
        assert len(result) == 5
        assert result == [
            "pragmatique", "analyste_risques", "expert_technique",
            "avocat_du_diable", "visionnaire"
        ]

    def test_auto_assign_0(self, mock_personas_config):
        """0 participants → liste vide."""
        manager = PersonaManager()
        assert manager.get_auto_assignment(0) == []

    def test_auto_assign_negative(self, mock_personas_config):
        """Nombre négatif → liste vide (pas de crash)."""
        manager = PersonaManager()
        assert manager.get_auto_assignment(-1) == []

    def test_auto_assign_1_fallback(self, mock_personas_config):
        """1 participant (pas de table prédéfinie) → fallback sur table 2, tronquée à 1."""
        manager = PersonaManager()
        result = manager.get_auto_assignment(1)
        # Doit retourner exactement 1 persona (pas de crash)
        assert len(result) == 1

    def test_auto_assign_6_extends(self, mock_personas_config):
        """6 participants (> max 5) → 5 + 1 ajouté par cycle."""
        manager = PersonaManager()
        result = manager.get_auto_assignment(6)
        assert len(result) == 6
        # Les 5 premiers doivent être la table complète
        assert result[:5] == [
            "pragmatique", "analyste_risques", "expert_technique",
            "avocat_du_diable", "visionnaire"
        ]


# ============================================================
# Tests d'attribution aux participants
# ============================================================

class TestAssignPersonas:
    """Tests de l'attribution de personas aux Participant dataclasses."""

    def test_assign_2_participants(self, mock_personas_config, participants_2):
        """Attribution correcte pour 2 participants."""
        manager = PersonaManager()
        manager.assign_personas(participants_2)

        assert participants_2[0].persona_name == "Pragmatique"
        assert participants_2[1].persona_name == "Avocat du diable"

    def test_assign_5_participants(self, mock_personas_config, participants_5):
        """Attribution correcte pour 5 participants (cas complet)."""
        manager = PersonaManager()
        manager.assign_personas(participants_5)

        names = [p.persona_name for p in participants_5]
        assert names == [
            "Pragmatique", "Analyste risques", "Expert technique",
            "Avocat du diable", "Visionnaire"
        ]

    def test_assign_populates_all_fields(self, mock_personas_config, participants_2):
        """Vérifie que TOUS les champs persona sont peuplés."""
        manager = PersonaManager()
        manager.assign_personas(participants_2)

        p = participants_2[0]
        assert p.persona_id == "pragmatique"
        assert p.persona_name == "Pragmatique"
        assert "coût-bénéfice" in p.persona_description
        assert p.persona_icon == "💼"
        assert p.persona_color == "#4CAF50"

    def test_assign_returns_same_list(self, mock_personas_config, participants_2):
        """assign_personas retourne la même liste (mutation in-place)."""
        manager = PersonaManager()
        result = manager.assign_personas(participants_2)
        assert result is participants_2

    def test_assign_empty_list(self, mock_personas_config):
        """Liste vide → pas de crash."""
        manager = PersonaManager()
        result = manager.assign_personas([])
        assert result == []


# ============================================================
# Tests des overrides
# ============================================================

class TestPersonaOverrides:
    """Tests des overrides de persona par l'utilisateur."""

    def test_override_with_known_persona_id(self, mock_personas_config, participants_2):
        """Override avec un ID persona connu (ex: expert_technique)."""
        manager = PersonaManager()
        manager.assign_personas(
            participants_2,
            persona_overrides={"claude-opus-46": "expert_technique"},
        )

        # Le premier garde son auto-assignment
        assert participants_2[0].persona_name == "Pragmatique"
        # Le second a l'override
        assert participants_2[1].persona_name == "Expert technique"
        assert participants_2[1].persona_id == "expert_technique"

    def test_override_with_free_text(self, mock_personas_config, participants_2):
        """Override avec un texte libre (ex: 'Expert sécurité')."""
        manager = PersonaManager()
        manager.assign_personas(
            participants_2,
            persona_overrides={"claude-opus-46": "Expert sécurité"},
        )

        assert participants_2[1].persona_name == "Expert sécurité"
        assert participants_2[1].persona_id == "custom"
        assert "Expert sécurité" in participants_2[1].persona_description

    def test_override_nonexistent_model_ignored(self, mock_personas_config, participants_2):
        """Override pour un model_id absent → ignoré sans erreur."""
        manager = PersonaManager()
        manager.assign_personas(
            participants_2,
            persona_overrides={"model-inexistant": "visionnaire"},
        )

        # Les 2 participants gardent leur auto-assignment
        assert participants_2[0].persona_name == "Pragmatique"
        assert participants_2[1].persona_name == "Avocat du diable"

    def test_override_multiple(self, mock_personas_config, participants_3):
        """Plusieurs overrides simultanés."""
        manager = PersonaManager()
        manager.assign_personas(
            participants_3,
            persona_overrides={
                "gpt-oss-120b": "visionnaire",
                "gemini-31-pro": "Expert DevOps",
            },
        )

        assert participants_3[0].persona_name == "Visionnaire"
        assert participants_3[1].persona_name == "Analyste risques"  # auto
        assert participants_3[2].persona_name == "Expert DevOps"  # custom


# ============================================================
# Tests de l'API publique
# ============================================================

class TestListPersonas:
    """Tests du listing des personas pour l'API REST."""

    def test_list_returns_all(self, mock_personas_config):
        """list_personas retourne les 5 personas."""
        manager = PersonaManager()
        result = manager.list_personas()
        assert len(result) == 5

    def test_list_dict_keys(self, mock_personas_config):
        """Chaque entrée contient les clés attendues."""
        manager = PersonaManager()
        result = manager.list_personas()

        for persona in result:
            assert "id" in persona
            assert "name" in persona
            assert "description" in persona
            assert "icon" in persona
            assert "color" in persona

    def test_list_pragmatique_present(self, mock_personas_config):
        """Le persona Pragmatique est dans la liste."""
        manager = PersonaManager()
        result = manager.list_personas()
        ids = [p["id"] for p in result]
        assert "pragmatique" in ids
