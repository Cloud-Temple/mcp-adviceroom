"""
Config Loader — Chargeur YAML avec lazy singletons.

Charge les fichiers de configuration YAML depuis app/config/.
Chaque fichier est chargé une seule fois (lazy singleton).

Ref: DESIGN/architecture.md §12.5
"""
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).parent


def load_config(filename: str) -> dict:
    """Charge un fichier YAML de configuration."""
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Config non trouvée : {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================
# Lazy singletons
# ============================================================

_prompts = None
_personas = None
_debate = None
_tools = None


def get_prompts() -> dict:
    """Charge et retourne les system prompts."""
    global _prompts
    if _prompts is None:
        _prompts = load_config("prompts.yaml")
    return _prompts


def get_personas() -> dict:
    """Charge et retourne les personas."""
    global _personas
    if _personas is None:
        _personas = load_config("personas.yaml")
    return _personas


def get_debate_config() -> dict:
    """Charge et retourne la config du protocole de débat."""
    global _debate
    if _debate is None:
        _debate = load_config("debate.yaml")
    return _debate


def get_tools_config() -> dict:
    """Charge et retourne la config des outils."""
    global _tools
    if _tools is None:
        _tools = load_config("tools.yaml")
    return _tools


def reload_all() -> None:
    """Force le rechargement de toutes les configs (utile pour les tests)."""
    global _prompts, _personas, _debate, _tools
    _prompts = None
    _personas = None
    _debate = None
    _tools = None
