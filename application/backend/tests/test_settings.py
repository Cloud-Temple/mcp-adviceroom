from pathlib import Path

from app.config.settings import Settings


def _find_project_root() -> Path:
    candidates = [Path("/workspace"), *Path(__file__).resolve().parents]
    for candidate in candidates:
        if (candidate / ".env.example").exists():
            return candidate
    raise RuntimeError("Project root not found")


def _clear_bootstrap_env(monkeypatch):
    monkeypatch.delenv("ADMIN_BOOTSTRAP_KEY", raising=False)
    monkeypatch.delenv("ADVICEROOM_BOOTSTRAP_KEY", raising=False)


def test_admin_bootstrap_key_reads_canonical_env(monkeypatch):
    _clear_bootstrap_env(monkeypatch)
    monkeypatch.setenv("ADMIN_BOOTSTRAP_KEY", "canonical-secret")

    settings = Settings(_env_file=None)

    assert settings.admin_bootstrap_key.get_secret_value() == "canonical-secret"


def test_admin_bootstrap_key_keeps_legacy_env_alias(monkeypatch):
    _clear_bootstrap_env(monkeypatch)
    monkeypatch.setenv("ADVICEROOM_BOOTSTRAP_KEY", "legacy-secret")

    settings = Settings(_env_file=None)

    assert settings.admin_bootstrap_key.get_secret_value() == "legacy-secret"


def test_admin_bootstrap_key_prefers_canonical_env(monkeypatch):
    _clear_bootstrap_env(monkeypatch)
    monkeypatch.setenv("ADMIN_BOOTSTRAP_KEY", "canonical-secret")
    monkeypatch.setenv("ADVICEROOM_BOOTSTRAP_KEY", "legacy-secret")

    settings = Settings(_env_file=None)

    assert settings.admin_bootstrap_key.get_secret_value() == "canonical-secret"


def test_env_example_documents_canonical_bootstrap_key():
    env_example = _find_project_root() / ".env.example"
    content = env_example.read_text()

    assert "ADMIN_BOOTSTRAP_KEY=" in content
    assert "ADVICEROOM_BOOTSTRAP_KEY=" not in content


# ============================================================
# Bootstrap admin — durcissement (CRITICAL #2, audit du 24/08/2026)
# ============================================================
#
# Le défaut valait "changeme-in-production". Le dépôt étant public, tout
# déploiement ayant omis de définir la variable accordait un accès admin total
# à une clé connue de quiconque lit le code.


def test_admin_bootstrap_key_has_no_guessable_default(monkeypatch):
    """Sans variable d'environnement, aucune clé exploitable ne doit exister."""
    _clear_bootstrap_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.admin_bootstrap_key.get_secret_value() == ""
    assert settings.admin_bootstrap_key.get_secret_value() != "changeme-in-production"
    assert settings.bootstrap_enabled is False


def test_bootstrap_disabled_rejects_every_token(monkeypatch):
    """Clé non configurée = bootstrap fermé, y compris pour la valeur historique."""
    _clear_bootstrap_env(monkeypatch)
    settings = Settings(_env_file=None)

    for candidate in ("changeme-in-production", "", "admin", "n'importe quoi"):
        assert settings.bootstrap_key_matches(candidate) is False, candidate


def test_empty_token_never_matches_empty_key(monkeypatch):
    """
    Garde contre compare_digest("", "") — qui vaut True.

    Sans le court-circuit sur les valeurs vides, un porteur SANS aucun secret
    obtiendrait un accès admin total dès que la clé n'est pas configurée.
    """
    _clear_bootstrap_env(monkeypatch)
    settings = Settings(_env_file=None)

    assert settings.admin_bootstrap_key.get_secret_value() == ""
    assert settings.bootstrap_key_matches("") is False


def test_configured_bootstrap_key_still_matches(monkeypatch):
    """Contre-test : une clé configurée doit toujours authentifier — et elle seule."""
    _clear_bootstrap_env(monkeypatch)
    monkeypatch.setenv("ADMIN_BOOTSTRAP_KEY", "une-vraie-cle-secrete")
    settings = Settings(_env_file=None)

    assert settings.bootstrap_enabled is True
    assert settings.bootstrap_key_matches("une-vraie-cle-secrete") is True
    assert settings.bootstrap_key_matches("une-vraie-cle-secret") is False
    assert settings.bootstrap_key_matches("") is False


def test_no_direct_bootstrap_comparison_outside_settings():
    """
    La comparaison doit rester centralisée dans bootstrap_key_matches().

    Un site qui comparerait directement contournerait le refus des valeurs
    vides et rouvrirait la faille. Ce test échouera si un nouvel appel direct
    apparaît ailleurs dans le code applicatif.
    """
    app_dir = _find_project_root() / "application" / "backend" / "app"
    offenders = []
    for py in app_dir.rglob("*.py"):
        text = py.read_text()
        if "compare_digest" in text and "admin_bootstrap_key" in text:
            for num, line in enumerate(text.splitlines(), 1):
                if "compare_digest" in line and "admin_bootstrap_key" in line:
                    # settings.py porte l'unique comparaison légitime.
                    if py.name != "settings.py":
                        offenders.append(f"{py.relative_to(app_dir)}:{num}")

    assert offenders == [], (
        "Comparaison directe de la clé de bootstrap hors settings.py : "
        f"{offenders}. Utiliser settings.bootstrap_key_matches(token)."
    )


# ============================================================
# Secrets — non-fuite dans les représentations (HIGH #3)
# ============================================================
#
# En `str` nu, `repr(settings)` imprimait les secrets EN CLAIR : une trace
# d'exception, un log de debug ou un dump de configuration suffisait à les
# exposer. SecretStr affiche `**********` et impose `.get_secret_value()`.

SECRET_FIELDS = (
    "admin_bootstrap_key",
    "llmaas_api_key",
    "google_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "s3_access_key",
    "s3_secret_key",
    "mcp_tools_token",
)

_MARKERS = {
    "ADMIN_BOOTSTRAP_KEY": "MARQUEUR-BOOTSTRAP-9f3a",
    "LLMAAS_API_KEY": "MARQUEUR-LLMAAS-9f3b",
    "GOOGLE_API_KEY": "MARQUEUR-GOOGLE-9f3c",
    "OPENAI_API_KEY": "MARQUEUR-OPENAI-9f3d",
    "ANTHROPIC_API_KEY": "MARQUEUR-ANTHROPIC-9f3e",
    "S3_ACCESS_KEY": "MARQUEUR-S3ACCESS-9f3f",
    "S3_SECRET_KEY": "MARQUEUR-S3SECRET-9f40",
    "MCP_TOOLS_TOKEN": "MARQUEUR-MCPTOOLS-9f41",
}


def _settings_with_markers(monkeypatch) -> Settings:
    _clear_bootstrap_env(monkeypatch)
    for env, value in _MARKERS.items():
        monkeypatch.setenv(env, value)
    return Settings(_env_file=None)


def test_all_declared_secrets_are_secretstr(monkeypatch):
    """
    Tout champ de la liste doit être typé SecretStr.

    Échoue si un secret est ajouté plus tard en `str` nu, ou si l'un des
    existants revient en arrière.
    """
    from pydantic import SecretStr

    settings = _settings_with_markers(monkeypatch)
    for field in SECRET_FIELDS:
        value = getattr(settings, field)
        assert isinstance(value, SecretStr), (
            f"{field} n'est pas un SecretStr — il fuirait dans repr(settings)"
        )


def test_no_secret_leaks_in_repr(monkeypatch):
    """Aucune valeur de secret ne doit apparaître dans repr()."""
    settings = _settings_with_markers(monkeypatch)
    rendered = repr(settings)

    for marker in _MARKERS.values():
        assert marker not in rendered, f"{marker} fuite dans repr(settings)"


def test_no_secret_leaks_in_str_or_dump(monkeypatch):
    """
    Ni str(), ni model_dump() ne doivent exposer les valeurs.

    model_dump() est le chemin le plus probable d'une fuite réelle : un
    endpoint de diagnostic qui sérialiserait la configuration.
    """
    settings = _settings_with_markers(monkeypatch)
    rendered = str(settings) + str(settings.model_dump())

    for marker in _MARKERS.values():
        assert marker not in rendered, f"{marker} fuite dans str/model_dump"


def test_secret_value_remains_readable(monkeypatch):
    """
    Contre-test : masquer ne doit pas casser la lecture délibérée.

    Un test qui vérifierait seulement l'absence des valeurs passerait aussi
    avec des secrets vides — ce qui casserait l'application en silence.
    """
    settings = _settings_with_markers(monkeypatch)

    assert settings.openai_api_key.get_secret_value() == _MARKERS["OPENAI_API_KEY"]
    assert settings.s3_secret_key.get_secret_value() == _MARKERS["S3_SECRET_KEY"]
    assert settings.bootstrap_key_matches(_MARKERS["ADMIN_BOOTSTRAP_KEY"]) is True
