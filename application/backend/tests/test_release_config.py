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

    assert root_version == "0.1.13"
    assert backend_version == root_version
    assert frontend_pkg["version"] == root_version


def test_openai_registry_uses_gpt_54_as_default():
    cfg = yaml.safe_load((BACKEND / "app" / "config" / "llm_models.yaml").read_text())
    model = cfg["models"]["gpt-54"]

    assert model["display_name"] == "GPT-5.4"
    assert model["provider"] == "openai"
    assert model["api_model_id"] == "gpt-5.4"
    assert model["context_window"] == 1_000_000
    assert model["default"] is True
    assert "gpt-52" not in cfg["models"]


def test_debate_fallback_uses_gpt_54():
    cfg = yaml.safe_load((BACKEND / "app" / "config" / "debate.yaml").read_text())

    assert cfg["synthesizer"]["fallback_model"] == "gpt-54"


def test_admin_question_markdown_and_scroll_are_wired():
    admin_html = (BACKEND / "app" / "static" / "admin.html").read_text()

    assert "question-markdown" in admin_html
    assert "document.getElementById('dm-question').innerHTML=md(q)" in admin_html
    assert "document.getElementById('debates-list-view').style.display='';" in admin_html
    assert "max-height: min(320px, 45vh)" in admin_html
