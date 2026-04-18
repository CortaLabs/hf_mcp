from __future__ import annotations

from pathlib import Path


CALLBACK_PAGE = Path(__file__).resolve().parents[1] / "docs" / "oauth_callback.html"


def _read_callback_html() -> str:
    return CALLBACK_PAGE.read_text(encoding="utf-8")


def test_callback_asset_exists() -> None:
    assert CALLBACK_PAGE.exists()


def test_callback_asset_has_fixed_loopback_target() -> None:
    html = _read_callback_html()
    assert "http://127.0.0.1:8765/callback" in html


def test_callback_asset_forwards_only_allowed_oauth_params() -> None:
    html = _read_callback_html()
    assert 'const ALLOWED_PARAMS = ["code", "state", "error"]' in html
    assert "searchParams.get(key)" in html
    assert "forwardParams.set(key, value)" in html
    assert "searchParams.get(\"scope\")" not in html
    assert "searchParams.get(\"token\")" not in html


def test_callback_asset_avoids_runtime_and_network_coupling() -> None:
    html = _read_callback_html()
    lowered = html.lower()

    assert "fetch(" not in html
    assert "xmlhttprequest" not in lowered
    assert "hf api" not in lowered
    assert "api/v2" not in lowered


def test_callback_asset_has_operator_readable_guidance() -> None:
    html = _read_callback_html()
    assert "Authorization code received." in html
    assert "OAuth returned an error from Hack Forums." in html
    assert "No authorization code or OAuth error was found in this URL." in html
    assert "ensure hf-mcp auth bootstrap is running locally on 127.0.0.1:8765" in html


def test_callback_asset_contains_no_secret_material() -> None:
    html = _read_callback_html()
    lowered = html.lower()

    assert "client_secret" not in lowered
    assert "access_token" not in lowered
    assert "hf_mcp_client_secret" not in lowered
