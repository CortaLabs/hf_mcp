from __future__ import annotations

import hashlib
import re
from pathlib import Path


DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
INDEX_PAGE = DOCS_DIR / "index.html"
STYLESHEET = DOCS_DIR / "styles.css"
SCRIPT = DOCS_DIR / "app.js"
CALLBACK_PAGE = DOCS_DIR / "oauth_callback.html"
README_PAGE = Path(__file__).resolve().parents[1] / "README.md"
TOOL_OVERVIEW_PAGE = DOCS_DIR / "tool_overview.md"
EXAMPLES_PAGE = DOCS_DIR / "examples.md"
COVERAGE_MATRIX_PAGE = DOCS_DIR / "coverage_matrix.md"
EXPORT_BOUNDARY_PAGE = DOCS_DIR / "export_boundary.md"
READS_SKILL_PAGE = Path(__file__).resolve().parents[1] / "skills" / "hf-mcp-reads" / "SKILL.md"
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


def test_docs_publish_compounding_flow_contract_without_relaxing_write_guards() -> None:
    readme = _read(README_PAGE)
    tool_overview = _read(TOOL_OVERVIEW_PAGE)
    examples = _read(EXAMPLES_PAGE)
    coverage = _read(COVERAGE_MATRIX_PAGE)
    export_boundary = _read(EXPORT_BOUNDARY_PAGE)
    reads_skill = _read(READS_SKILL_PAGE)

    assert "forums.index" in readme
    assert "forums_index" in readme
    assert "_hf_flow" in readme
    assert "supported" in readme
    assert "`bytes.read`" in readme
    assert "draft/preflight tools" in readme
    assert "successful results from existing guarded" in readme
    assert "confirmed or stubbed execution" in readme
    assert "forums.index" in tool_overview
    assert "forums_index" in tool_overview
    assert "_hf_flow" in tool_overview
    assert "supported extended reads (`bytes.read`" in tool_overview
    assert "sigmarket.order.read" in tool_overview
    assert "draft/preflight tools" in tool_overview
    assert "successful results from existing guarded" in tool_overview
    assert "confirmed or stubbed execution" in tool_overview
    assert "Concrete chain:" in examples
    assert "`forums.index` -> `forums.read` -> `threads.read` -> `posts.read`" in examples
    assert "maintained package data and can drift from live HF" in examples
    assert "forums.read` still requires `fid`; it is not root discovery" in examples
    assert "forums_index" in examples
    assert "_hf_flow" in examples
    assert "supported extended reads" in examples
    assert "`bytes.read`" in examples
    assert "draft/preflight tools" in examples
    assert "successful results from existing guarded" in examples
    assert "confirmed or stubbed execution" in examples
    assert "forums.index" in coverage
    assert "local catalog-backed root discovery" in coverage
    assert "can drift from live HF" in coverage
    assert "forums.read` remains `fid`-required and is not root discovery" in export_boundary
    assert "_hf_flow" in export_boundary
    assert "supported extended reads" in export_boundary
    assert "`bytes.read`" in export_boundary
    assert "draft/preflight tools" in export_boundary
    assert "successful results from existing guarded" in export_boundary
    assert "confirmed or stubbed execution" in export_boundary
    assert "forums.index" in reads_skill
    assert "forums_index" in reads_skill
    assert "confirm_live=true" in readme
    assert "confirm_live=true" in export_boundary
    for stale_doc in (readme, tool_overview, examples, export_boundary):
        assert "core reads only" not in stale_doc
        assert "forums.index and core reads only" not in stale_doc
        assert "Draft/write flow metadata is planned" not in stale_doc
        assert "draft/write flow metadata is planned" not in stale_doc
