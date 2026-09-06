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

    assert settings.admin_bootstrap_key == "canonical-secret"


def test_admin_bootstrap_key_keeps_legacy_env_alias(monkeypatch):
    _clear_bootstrap_env(monkeypatch)
    monkeypatch.setenv("ADVICEROOM_BOOTSTRAP_KEY", "legacy-secret")

    settings = Settings(_env_file=None)

    assert settings.admin_bootstrap_key == "legacy-secret"


def test_admin_bootstrap_key_prefers_canonical_env(monkeypatch):
    _clear_bootstrap_env(monkeypatch)
    monkeypatch.setenv("ADMIN_BOOTSTRAP_KEY", "canonical-secret")
    monkeypatch.setenv("ADVICEROOM_BOOTSTRAP_KEY", "legacy-secret")

    settings = Settings(_env_file=None)

    assert settings.admin_bootstrap_key == "canonical-secret"


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

    assert settings.admin_bootstrap_key == ""
    assert settings.admin_bootstrap_key != "changeme-in-production"
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

    assert settings.admin_bootstrap_key == ""
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
