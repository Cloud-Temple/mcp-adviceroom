# -*- coding: utf-8 -*-
"""
Configuration globale du CLI AdviceRoom.

Variables d'environnement :
    ADVICEROOM_URL   — URL du backend (défaut: http://localhost:8000)
    ADVICEROOM_TOKEN — Token admin Bearer
"""

import os

BASE_URL = os.environ.get("ADVICEROOM_URL", "http://localhost:8000")
TOKEN = os.environ.get("ADVICEROOM_TOKEN", "")
