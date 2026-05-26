from pathlib import Path

from app.config.settings import Settings


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
    env_example = Path(__file__).parents[3] / ".env.example"
    content = env_example.read_text()

    assert "ADMIN_BOOTSTRAP_KEY=" in content
    assert "ADVICEROOM_BOOTSTRAP_KEY=" not in content
