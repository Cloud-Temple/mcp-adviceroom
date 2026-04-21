#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AdviceRoom CLI — Administration et débats multi-LLM.

Aligné 1:1 avec les endpoints /admin/api/* du backend.
3 couches : Click (scriptable), Shell interactif, Display Rich.

Usage :
    python scripts/adviceroom_cli.py --help
    python scripts/adviceroom_cli.py health
    python scripts/adviceroom_cli.py whoami
    python scripts/adviceroom_cli.py models
    python scripts/adviceroom_cli.py logs
    python scripts/adviceroom_cli.py llm-activity
    python scripts/adviceroom_cli.py token list
    python scripts/adviceroom_cli.py token create mon-agent -p read,write
    python scripts/adviceroom_cli.py token revoke abc12345
    python scripts/adviceroom_cli.py debate list
    python scripts/adviceroom_cli.py debate get DEBATE_ID
    python scripts/adviceroom_cli.py debate delete DEBATE_ID
    python scripts/adviceroom_cli.py debate start "Ma question" -m gpt-52,claude-opus-46
    python scripts/adviceroom_cli.py shell

Variables d'environnement :
    ADVICEROOM_URL   — URL du backend (défaut: http://localhost:8000)
    ADVICEROOM_TOKEN — Token admin Bearer
"""

import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports relatifs
sys.path.insert(0, str(Path(__file__).parent))

from cli.commands import cli

if __name__ == "__main__":
    cli()
