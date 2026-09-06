from pathlib import Path

import yaml


def _find_project_root() -> Path:
    candidates = [Path("/workspace"), *Path(__file__).resolve().parents]
    for candidate in candidates:
        if (
            (candidate / "VERSION").exists()
            and (candidate / "application" / "backend").exists()
        ):
            return candidate
    raise RuntimeError("Project root not found")


ROOT = _find_project_root()
BACKEND = ROOT / "application" / "backend"


def test_release_version_files_are_in_sync():
    root_version = (ROOT / "VERSION").read_text().strip()
    backend_version = (BACKEND / "VERSION").read_text().strip()
    frontend_pkg = yaml.safe_load((ROOT / "application" / "frontend" / "package.json").read_text())
    frontend_lock = yaml.safe_load((ROOT / "application" / "frontend" / "package-lock.json").read_text())

    assert root_version == "0.3.0"
    assert backend_version == root_version
    assert frontend_pkg["version"] == root_version
    assert frontend_lock["version"] == root_version
    assert frontend_lock["packages"][""]["version"] == root_version


def test_openai_registry_uses_gpt_56_terra_as_default():
    """
    Le défaut OpenAI est gpt-5.6-terra (issue #2).

    gpt-5.4 reste dans la registry, actif et sélectionnable, mais n'est plus
    le défaut. Il sert aussi de fallback au synthétiseur
    (cf. test_debate_fallback_uses_gpt_54).
    """
    cfg = yaml.safe_load((BACKEND / "app" / "config" / "llm_models.yaml").read_text())

    terra = cfg["models"]["gpt-56-terra"]
    assert terra["display_name"] == "GPT-5.6 Terra"
    assert terra["provider"] == "openai"
    assert terra["api_model_id"] == "gpt-5.6-terra"
    assert terra["default"] is True
    assert terra["active"] is True

    legacy = cfg["models"]["gpt-54"]
    assert legacy["display_name"] == "GPT-5.4"
    assert legacy["provider"] == "openai"
    assert legacy["api_model_id"] == "gpt-5.4"
    assert legacy["context_window"] == 1_000_000
    assert legacy["default"] is False
    assert legacy["active"] is True
    # gpt-5.4 accepte encore "temperature" : aucune contrainte ne doit lui être
    # appliquée par effet de bord (critère d'acceptation #4 de l'issue #2).
    assert legacy.get("supports_temperature", True) is True
    assert not legacy.get("extra_params")

    assert "gpt-52" not in cfg["models"]


def test_gpt_56_terra_carries_its_api_constraints():
    """
    La contrainte API de gpt-5.6-terra est portée par la registry, et non par une
    heuristique de préfixe (point 5 de l'issue #2).

    reasoning_effort doit valoir exactement "none". Mesuré en réel le 06/09/2026 :
    toute valeur de raisonnement active ("low", "medium", "high", "xhigh") renvoie
    HTTP 400 dès que des function tools sont présents, et "minimal" n'existe pas
    pour ce modèle. AdviceRoom passant TOUJOURS les tools, une régression ici
    casserait 100% des appels au modèle par défaut.

    COUPLAGE : c'est ce même reasoning_effort="none" qui rend le paramètre
    "temperature" acceptable (0.0 à 2.0 mesurés OK). Sans lui, temperature=0.7
    renvoie 400. Les deux réglages doivent donc évoluer ensemble — d'où leur
    vérification conjointe dans ce test.
    """
    cfg = yaml.safe_load((BACKEND / "app" / "config" / "llm_models.yaml").read_text())
    terra = cfg["models"]["gpt-56-terra"]

    assert terra["extra_params"]["reasoning_effort"] == "none"
    # temperature conservée : sinon les 0.3 (verdict factuel), 0.7 (débat) et
    # 0.8 (anti-conformité) de l'orchestrateur seraient écrasés par le défaut 1.
    assert terra["supports_temperature"] is True


def test_claude_opus_5_omits_temperature():
    """
    claude-opus-5 rejette "temperature" (HTTP 400 `temperature is deprecated for
    this model`) — vérifié en réel. claude-opus-4-6 l'accepte toujours.
    """
    cfg = yaml.safe_load((BACKEND / "app" / "config" / "llm_models.yaml").read_text())

    assert cfg["models"]["claude-opus-5"]["supports_temperature"] is False
    legacy = cfg["models"]["claude-opus-46"]
    assert legacy.get("supports_temperature", True) is True


def test_debate_fallback_uses_gpt_54():
    cfg = yaml.safe_load((BACKEND / "app" / "config" / "debate.yaml").read_text())

    assert cfg["synthesizer"]["fallback_model"] == "gpt-54"


def test_admin_question_markdown_and_scroll_are_wired():
    admin_html = (BACKEND / "app" / "static" / "admin.html").read_text()

    assert "question-markdown" in admin_html
    assert "document.getElementById('dm-question').innerHTML=md(q)" in admin_html
    assert "document.getElementById('debates-list-view').style.display='';" in admin_html
    assert "max-height: min(320px, 45vh)" in admin_html


def test_cli_debate_start_is_aligned_with_admin_api():
    cli_client = (ROOT / "scripts" / "cli" / "client.py").read_text()
    cli_commands = (ROOT / "scripts" / "cli" / "commands.py").read_text()
    cli_shell = (ROOT / "scripts" / "cli" / "shell.py").read_text()
    admin_html = (BACKEND / "app" / "static" / "admin.html").read_text()
    caddyfile = (ROOT / "waf" / "Caddyfile").read_text()

    assert 'return await self._post("/admin/api/debates", body)' in cli_client
    assert "/admin/api/debates/{id}/stream" in cli_client
    assert "await client.list_models()" in cli_commands
    assert "await client.list_models()" in cli_shell
    assert "get_providers" not in cli_client
    assert "get_providers" not in cli_commands
    assert "get_providers" not in cli_shell
    assert "/api/v1/debates" not in cli_client
    assert "fetch('/admin/api/debates'" in admin_html
    assert "`/admin/api/debates/${data.debate_id}/stream`" in admin_html
    assert "`/admin/api/debates/${DM_DEBATE_ID}/cancel`" in admin_html
    assert "/api/v1/debates" not in admin_html
    assert "handle /admin/api/debates/*/stream" in caddyfile
    assert "flush_interval -1" in caddyfile


def test_admin_dashboard_model_health_is_wired():
    admin_html = (BACKEND / "app" / "static" / "admin.html").read_text()
    admin_api = (BACKEND / "app" / "admin" / "api.py").read_text()

    assert "model-health-grid" in admin_html
    assert "loadModelHealth(false)" in admin_html
    assert "api('/model-health')" in admin_html
    assert "renderModelHealthCard" in admin_html
    assert 'path == "/admin/api/model-health"' in admin_api
    assert "async def _api_model_health" in admin_api


def test_dashboard_last_debate_supports_markdown_and_scroll():
    admin_html = (BACKEND / "app" / "static" / "admin.html").read_text()

    assert "last-debate-question" in admin_html
    assert "last-debate-summary" in admin_html
    assert "max-height: min(180px, 24vh)" in admin_html
    assert "max-height: 140px" in admin_html
    assert "${md(last.question||'Sans titre')}" in admin_html
    assert "${md(v.summary)}" in admin_html
    assert "${esc(last.question||'Sans titre')}" not in admin_html
