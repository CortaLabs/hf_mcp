from __future__ import annotations

import hashlib
import re
from pathlib import Path


DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
INDEX_PAGE = DOCS_DIR / "index.html"
STYLESHEET = DOCS_DIR / "styles.css"
SCRIPT = DOCS_DIR / "app.js"
CALLBACK_PAGE = DOCS_DIR / "oauth_callback.html"
CALLBACK_SHA256 = "51a73ca4359b088577d5d3ffb087055d30f940c657a12a2d562a622be39532dd"
PUBLIC_DOCS_BANNED_TERMS = (
    "council",
    "blueprint",
    "forge",
    "atlas",
    "crucible",
    "arbiter",
    "witness",
    "lens",
    "sentinel",
    "mantis",
    "phase plan",
    "architecture guide",
    "checklist",
    "internal planning",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_docs_site_assets_exist() -> None:
    assert INDEX_PAGE.exists()
    assert STYLESHEET.exists()
    assert SCRIPT.exists()


def test_index_contains_required_commands_and_callback_targets() -> None:
    html = _read(INDEX_PAGE)

    assert "pip install hf-mcp" in html
    assert "hf-mcp setup init" in html
    assert "hf-mcp auth bootstrap" in html
    assert "hf-mcp doctor" in html
    assert "hf-mcp serve" in html
    assert "https://cortalabs.github.io/hf_mcp/oauth_callback.html" in html
    assert "http://127.0.0.1:8765/callback" in html


def test_index_links_existing_docs_and_project_destinations() -> None:
    html = _read(INDEX_PAGE)

    assert 'href="configuration.md"' in html
    assert 'href="coverage_matrix.md"' in html
    assert 'href="export_boundary.md"' in html
    assert 'href="security_model.md"' in html
    assert 'href="oauth_callback.html"' in html
    assert 'href="https://github.com/cortalabs/hf_mcp"' in html
    assert 'href="https://pypi.org/project/hf-mcp/"' in html
    assert 'href="styles.css"' in html
    assert 'src="app.js"' in html


def test_index_excludes_internal_planning_language() -> None:
    html = _read(INDEX_PAGE).lower()

    for banned in PUBLIC_DOCS_BANNED_TERMS:
        assert banned not in html


def test_index_primary_navigation_is_plain_html_anchors() -> None:
    html = _read(INDEX_PAGE)

    nav_match = re.search(
        r'<nav\s+aria-label="Primary">\s*<ul class="inline-nav">(?P<body>.*?)</ul>\s*</nav>',
        html,
        re.DOTALL,
    )
    assert nav_match is not None

    nav_html = nav_match.group("body")
    expected_sections = ("setup", "callback", "docs", "links")

    for section_id in expected_sections:
        assert f'href="#{section_id}"' in nav_html


def test_callback_artifact_hash_is_unchanged() -> None:
    digest = hashlib.sha256(CALLBACK_PAGE.read_bytes()).hexdigest()
    assert digest == CALLBACK_SHA256
