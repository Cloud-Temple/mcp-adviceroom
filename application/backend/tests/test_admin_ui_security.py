"""
Tests de sécurité de la console admin (static/admin.html).

CRITICAL #3 de l'audit du 24/08/2026 — XSS STOCKÉ.

`loadWebLogs()` insérait `l.path` et `l.method` dans `innerHTML` sans
échappement. Ces valeurs viennent de la requête HTTP brute, journalisée par
LoggingMiddleware AVANT authentification : n'importe qui pouvait déposer un
payload par un simple `curl https://host/<charge-utile>`, qui s'exécutait
ensuite chez tout admin ouvrant l'onglet Activité — avec vol du token Bearer
conservé en localStorage.

admin.html n'est pas exécutable depuis pytest : ces tests vérifient donc des
invariants du source. Ils sont volontairement ciblés sur les deux propriétés
qui ferment la faille, pas sur la mise en forme.
"""
import re
from pathlib import Path

import pytest


def _find_project_root() -> Path:
    candidates = [Path("/workspace"), *Path(__file__).resolve().parents]
    for candidate in candidates:
        if (candidate / "VERSION").exists() and (candidate / "application").exists():
            return candidate
    raise RuntimeError("Project root not found")


ADMIN_HTML = (
    _find_project_root() / "application" / "backend" / "app" / "static" / "admin.html"
)


@pytest.fixture(scope="module")
def admin_source() -> str:
    return ADMIN_HTML.read_text()


def _function_body(source: str, name: str) -> str:
    """Extrait le corps d'une fonction JS par comptage d'accolades."""
    start = source.index(f"function {name}(")
    brace = source.index("{", start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[brace : i + 1]
    raise AssertionError(f"Fin de la fonction {name} introuvable")


class TestWebLogsXSS:

    def test_load_web_logs_never_writes_innerhtml(self, admin_source):
        """
        Le rendu des logs ne doit passer par aucun innerHTML.

        C'est l'invariant structurel : tant qu'aucun balisage n'est construit
        par concaténation, aucune donnée de requête ne peut devenir du code.
        """
        body = _function_body(admin_source, "loadWebLogs")
        assert "innerHTML" not in body, (
            "loadWebLogs() réintroduit innerHTML — la donnée de requête "
            "redeviendrait interprétable comme du balisage."
        )

    def test_request_fields_go_through_textcontent(self, admin_source):
        """path et method doivent être posés en textContent, jamais interpolés."""
        body = _function_body(admin_source, "loadWebLogs")

        assert "textContent" in body
        # Aucune interpolation de template littéral des champs hostiles.
        assert not re.search(r"\$\{\s*l\.path", body), "l.path interpolé dans un template"
        assert not re.search(r"\$\{\s*l\.method", body), "l.method interpolé dans un template"
        assert not re.search(r"\$\{\s*l\.status", body), "l.status interpolé dans un template"

    def test_path_length_is_bounded(self, admin_source):
        """Un path très long ne doit pas disloquer la console."""
        body = _function_body(admin_source, "loadWebLogs")
        assert "slice(0," in body or "substring(0," in body


class TestEscapeHelper:

    def test_esc_escapes_quotes(self, admin_source):
        """
        esc() doit neutraliser les guillemets, pas seulement < et >.

        Sans cela, une valeur interpolée dans un ATTRIBUT peut s'en échapper et
        injecter un gestionnaire d'événement — les chevrons ayant beau être
        échappés. C'est la cause du finding HIGH sur mdExport().
        """
        esc_line = next(
            line for line in admin_source.splitlines()
            if line.startswith("function esc(")
        )

        assert "&amp;" in esc_line
        assert "&lt;" in esc_line
        assert "&gt;" in esc_line
        assert "&quot;" in esc_line, "esc() n'échappe pas les guillemets doubles"
        assert "&#39;" in esc_line, "esc() n'échappe pas les apostrophes"

    def test_esc_escapes_ampersand_first(self, admin_source):
        """
        L'esperluette doit être remplacée en PREMIER.

        Dans l'ordre inverse, `&lt;` produit par un remplacement antérieur
        serait ré-échappé en `&amp;lt;` et s'afficherait littéralement.
        """
        esc_line = next(
            line for line in admin_source.splitlines()
            if line.startswith("function esc(")
        )
        assert esc_line.index("&amp;") < esc_line.index("&lt;")


class TestMarkdownExportLinks:
    """
    HIGH #4 — XSS dans le fichier HTML exporté par `mdExport()`.

    Trois défauts distincts :

    1. Une substitution `/\\"/g → '"'` réinjectait des guillemets bruts JUSTE
       APRÈS `esc()`, annulant l'échappement et rouvrant l'injection
       d'attribut. Elle n'était pas mentionnée dans l'audit.
    2. L'URL du lien était interpolée telle quelle dans `href`, ce qui laissait
       passer `javascript:` — un href parfaitement valide qui exécute du code
       au clic, et qu'échapper les chevrons ne bloque pas.
    3. Absence de `rel="noopener"`, alors que le fichier exporté s'ouvre hors
       de toute origine de confiance.
    """

    def test_escaping_is_not_undone(self, admin_source):
        """La substitution qui réinjectait des guillemets bruts doit rester supprimée."""
        body = _function_body(admin_source, "mdExport")
        assert r"""replace(/\\"/g,'"')""" not in body, (
            "mdExport réintroduit des guillemets bruts après esc() — "
            "l'échappement est annulé et l'injection d'attribut redevient possible."
        )

    def test_link_url_is_validated(self, admin_source):
        """L'URL passe par safeHref et n'est jamais interpolée directement."""
        assert "function safeHref(" in admin_source

        body = _function_body(admin_source, "mdExport")
        assert "safeHref(" in body, "mdExport n'appelle pas safeHref"
        # L'ancienne forme interpolait le groupe capturé dans href.
        assert '<a href="$2"' not in body, (
            "URL interpolée telle quelle dans href — protocole non validé"
        )

    def test_safe_href_allows_only_known_protocols(self, admin_source):
        """
        Whitelist et non blacklist.

        Une blacklist de `javascript:` se contourne par la casse, les
        caractères de contrôle ou des schémas exotiques ; seule une liste
        d'autorisation tient.
        """
        body = _function_body(admin_source, "safeHref")

        assert "https?:" in body
        assert "mailto:" in body
        # Les caractères de contrôle sont retirés avant le test de protocole :
        # "java\tscript:" est interprété comme "javascript:" par les navigateurs.
        assert r"\x00-\x20" in body
        assert "toLowerCase()" in body, "test de protocole sensible à la casse"
        assert "return null" in body, "aucune URL n'est refusée"

    def test_links_carry_noopener(self, admin_source):
        body = _function_body(admin_source, "mdExport")
        assert 'rel="noopener noreferrer"' in body
