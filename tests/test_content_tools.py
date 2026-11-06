"""formatting.convert, templates.list and templates.render: local, read-only content tools."""

from __future__ import annotations

import json
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
import mcp.types as types
import pytest
from mcp.client import Client

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import (
    DEFAULT_TEMPLATES_DIR,
    HFMCPSettings,
    PRESET_CAPABILITIES,
    PRESET_PARAMETER_FAMILIES,
    load_settings,
)
from hf_mcp.dispatcher import build_handlers
from hf_mcp.mycode import markdown_to_mycode
from hf_mcp.registry import (
    MAX_MESSAGE_CHARS,
    MAX_PATH_CHARS,
    MAX_SHORT_TEXT_CHARS,
    TOOLS,
    get_tool_spec,
)
from hf_mcp.server import build_server
from hf_mcp.templates import (
    MAX_TEMPLATE_BYTES,
    MAX_TEMPLATE_CANDIDATES,
    Placeholder,
    Template,
    load_templates,
)
from hf_mcp.token_store import TokenBundle
from hf_mcp.transport import HFTransport

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONTENT_TOOLS = ("formatting.convert", "templates.list", "templates.render")
MARKER = "tpl-fixture-marker-7c1e"

VALID_MD = """---
description: Release announcement
placeholders:
  title:
    description: Headline
    required: true
  note:
    description: Optional footer
    required: false
---
# {{title}}

Thanks for reading. {{note}}
"""

VALID_MYCODE = """---
description: Plain MyCode greeting
placeholders:
  who:
    description: Who to greet
---
[b]Hello {{who}}[/b]
"""

HOUSE_STYLE = """---
description: Synthetic house style
placeholders:
  headline:
    description: Heading text
  banner:
    description: Banner image URL
---
[css=68]
[center][size=5][b]{{headline}}[/b][/size][/center]
[center][img]{{banner}}[/img][/center]
"""


class _StubTokenStore:
    def require_bundle(self) -> TokenBundle:
        return TokenBundle(access_token="token", token_type="Bearer", scope=frozenset())


class _CountingTransport(HFTransport):
    def __init__(self) -> None:
        super().__init__(token_store=_StubTokenStore(), base_url="https://example.test")
        self.calls = 0

    def _post_json(self, route: str, payload: Any, headers: Any) -> dict[str, Any]:
        self.calls += 1
        return {}


def _settings(profile: str, **extra: Any) -> HFMCPSettings:
    return HFMCPSettings(
        profile=profile,
        enabled_capabilities=PRESET_CAPABILITIES[profile],
        enabled_parameter_families=PRESET_PARAMETER_FAMILIES[profile],
        **extra,
    )


def _server(settings: HFMCPSettings, transport: HFTransport | None = None) -> Any:
    policy = CapabilityPolicy(settings)
    return build_server(policy, build_handlers(policy, settings, transport))


def _session(server: Any, scenario: Callable[[Client], Awaitable[Any]]) -> Any:
    async def _run() -> Any:
        async with Client(server) as client:
            return await scenario(client)

    return anyio.run(_run)


def _tools(settings: HFMCPSettings, transport: HFTransport | None = None) -> dict:
    async def scenario(client: Client) -> dict[str, types.Tool]:
        return {tool.name: tool for tool in (await client.list_tools()).tools}

    return _session(_server(settings, transport), scenario)


def _call(server: Any, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    async def scenario(client: Client) -> types.CallToolResult:
        return await client.call_tool(name, arguments)

    return _session(server, scenario)


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    path = tmp_path / MARKER / "templates"
    path.mkdir(parents=True)
    return path


def _reader(templates_dir: Path) -> Any:
    return _server(_settings("reader", templates_dir=templates_dir))


def test_tool_counts_and_presets() -> None:
    assert len(TOOLS) == 27
    assert len(_tools(_settings("full_api"), _CountingTransport())) == 27
    reader = _tools(_settings("reader"), _CountingTransport())
    assert len(reader) == 18
    for name in CONTENT_TOOLS:
        assert name.replace(".", "_") in reader
    forum_operator = _tools(_settings("forum_operator"), _CountingTransport())
    assert all(name.replace(".", "_") in forum_operator for name in CONTENT_TOOLS)
    assert _tools(_settings("custom"), _CountingTransport()) == {}


def test_content_tool_rows_are_local_read_only_and_publish_no_internal_keys() -> None:
    for name in CONTENT_TOOLS:
        spec = get_tool_spec(name)
        assert spec.group == "local"
        assert spec.annotations == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    for tool in _tools(_settings("reader")).values():
        dumped = json.dumps(tool.model_dump(by_alias=True))
        assert "x-hf-" not in dumped
        assert "_meta" not in tool.model_dump(by_alias=True, exclude_none=True)


def test_default_templates_dir_sits_beside_drafts_and_is_configurable(
    tmp_path: Path,
) -> None:
    assert DEFAULT_TEMPLATES_DIR.name == "templates"
    assert load_settings(None, env={}).templates_dir.name == "templates"
    configured = tmp_path / "mine"
    settings = load_settings(None, env={"HF_MCP_TEMPLATES_DIR": str(configured)})
    assert settings.templates_dir == configured
    with pytest.raises(ValueError, match="absolute"):
        load_settings(None, env={"HF_MCP_TEMPLATES_DIR": "relative/dir"})


def _golden_markdown_cases() -> list[dict[str, Any]]:
    cases = json.loads((FIXTURES / "mycode_golden.json").read_text(encoding="utf-8"))
    return [case for case in cases if "markdown" in case]


def test_convert_matches_markdown_to_mycode_without_side_effects(
    tmp_path: Path,
) -> None:
    draft_dir = tmp_path / "drafts"
    draft_dir.mkdir()
    settings = _settings("reader", draft_dir=draft_dir, templates_dir=tmp_path / "t")
    transport = _CountingTransport()
    server = _server(settings, transport)
    before_tmp, before_drafts = _tree(tmp_path), _tree(draft_dir)
    cases = _golden_markdown_cases()
    assert cases
    for case in cases:
        result = _call(server, "formatting_convert", {"message": case["markdown"]})
        assert not result.is_error, case["id"]
        content = result.structured_content
        assert content["mycode"] == markdown_to_mycode(case["markdown"]), case["id"]
        assert set(content) == {"mycode", "conversion_findings", "issues"}
    assert transport.calls == 0
    assert _tree(tmp_path) == before_tmp
    assert _tree(draft_dir) == before_drafts


def test_convert_honours_message_format_and_rejects_bad_input(tmp_path: Path) -> None:
    server = _reader(tmp_path)
    raw = "[b]x[/b] **y**"
    mycode = _call(
        server, "formatting_convert", {"message": raw, "message_format": "mycode"}
    )
    assert mycode.structured_content["mycode"] == raw
    for bad in ({}, {"message": ""}, {"message": "x", "message_format": "html"}):
        assert _call(server, "formatting_convert", bad).is_error


def _fixture_directory(templates_dir: Path) -> None:
    (templates_dir / "release.md").write_text(VALID_MD, encoding="utf-8")
    (templates_dir / "greeting.mycode").write_text(VALID_MYCODE, encoding="utf-8")
    (templates_dir / "linked.md").symlink_to(templates_dir / "release.md")
    (templates_dir / "huge.md").write_text(
        VALID_MD + "x" * MAX_TEMPLATE_BYTES, encoding="utf-8"
    )
    (templates_dir / "undeclared.md").write_text(
        VALID_MD.replace("{{note}}", "{{note}} {{ghost}}"), encoding="utf-8"
    )
    (templates_dir / "Bad Name.md").write_text(VALID_MD, encoding="utf-8")


def test_list_shows_only_valid_templates_and_leaks_no_path(templates_dir: Path) -> None:
    _fixture_directory(templates_dir)
    result = _call(_reader(templates_dir), "templates_list", {})
    assert not result.is_error
    content = result.structured_content
    assert [t["name"] for t in content["templates"]] == ["greeting", "release"]
    assert content["invalid_count"] == 4
    release = content["templates"][1]
    assert release["message_format"] == "markdown"
    assert release["description"] == "Release announcement"
    assert release["placeholders"] == [
        {"key": "title", "description": "Headline", "required": True},
        {"key": "note", "description": "Optional footer", "required": False},
    ]
    assert MARKER not in json.dumps(result.model_dump(by_alias=True))


def test_missing_templates_directory_means_zero_templates(tmp_path: Path) -> None:
    result = _call(_reader(tmp_path / "absent"), "templates_list", {})
    assert result.structured_content == {"templates": [], "invalid_count": 0}


@pytest.mark.parametrize(
    "text",
    [
        "no front matter {{x}}",
        "---\ndescription: [unclosed\n---\nbody",
        "---\ndescription: d\nextra: 1\n---\nbody",
        "---\ndescription: d\nplaceholders:\n  x: {required: maybe}\n---\n{{x}}",
        "---\ndescription: d\nplaceholders:\n  x: {}\n---\nunused placeholder",
        "---\ndescription: d\nplaceholders:\n  Bad: {}\n---\n{{Bad}}",
        "---\ndescription: d\n---\nstray {{ brace",
    ],
)
def test_invalid_template_shapes_are_counted_not_listed(
    templates_dir: Path, text: str
) -> None:
    (templates_dir / "t.md").write_text(text, encoding="utf-8")
    assert load_templates(templates_dir) == ((), 1)


def test_render_fills_values_literally_and_matches_convert(templates_dir: Path) -> None:
    _fixture_directory(templates_dir)
    server = _reader(templates_dir)
    result = _call(
        server,
        "templates_render",
        {
            "name": "release",
            "values": {"title": "v2 {{note}}", "note": "see {{title}}"},
        },
    )
    assert not result.is_error
    content = result.structured_content
    assert content["name"] == "release"
    assert "# v2 {{note}}" in content["source_text"]
    assert "see {{title}}" in content["source_text"]
    converted = _call(server, "formatting_convert", {"message": content["source_text"]})
    assert content["mycode"] == converted.structured_content["mycode"]
    assert (
        content["conversion_findings"]
        == converted.structured_content["conversion_findings"]
    )

    optional_omitted = _call(
        server, "templates_render", {"name": "release", "values": {"title": "T"}}
    )
    assert "{{" not in optional_omitted.structured_content["source_text"]

    mycode_template = _call(
        server, "templates_render", {"name": "greeting", "values": {"who": "all"}}
    )
    assert mycode_template.structured_content["mycode"] == "[b]Hello all[/b]\n"
    assert MARKER not in json.dumps(result.model_dump(by_alias=True))


def test_render_errors(templates_dir: Path) -> None:
    _fixture_directory(templates_dir)
    server = _reader(templates_dir)

    missing = _call(server, "templates_render", {"name": "release", "values": {}})
    assert missing.is_error
    assert missing.structured_content["error"]["code"] == "INVALID_ARGUMENT"
    assert "title" in missing.structured_content["error"]["message"]

    unknown_key = _call(
        server,
        "templates_render",
        {"name": "release", "values": {"title": "T", "bogus": "x"}},
    )
    assert unknown_key.structured_content["error"]["code"] == "INVALID_ARGUMENT"
    assert "bogus" in unknown_key.structured_content["error"]["message"]

    for name, code in (
        ("nope", "RESOURCE_UNAVAILABLE"),
        ("linked", "RESOURCE_UNAVAILABLE"),
        ("undeclared", "RESOURCE_UNAVAILABLE"),
        ("huge", "RESOURCE_UNAVAILABLE"),
        ("../etc", "INVALID_ARGUMENT"),
        ("Bad Name", "INVALID_ARGUMENT"),
    ):
        result = _call(server, "templates_render", {"name": name})
        assert result.is_error, name
        assert result.structured_content["error"]["code"] == code, name
        assert MARKER not in json.dumps(result.model_dump(by_alias=True))
    unknown = _call(server, "templates_render", {"name": "nope"})
    assert unknown.structured_content["error"]["code"] == "RESOURCE_UNAVAILABLE"
    assert (
        _call(server, "templates_render", {"name": "release", "values": {"title": 3}})
    ).is_error


def test_house_style_template_renders_without_unknown_tag_findings(
    templates_dir: Path,
) -> None:
    (templates_dir / "house.mycode").write_text(
        HOUSE_STYLE.replace("[css=68]", "[css=68]\n[b]house[/b]"), encoding="utf-8"
    )
    fixture = (FIXTURES / "house_mycode.txt").read_text(encoding="utf-8")
    assert "[css=68]" in fixture
    result = _call(
        _reader(templates_dir),
        "templates_render",
        {
            "name": "house",
            "values": {
                "headline": "Weekend Build Log",
                "banner": "https://images.example.test/banner.png",
            },
        },
    )
    assert not result.is_error
    content = result.structured_content
    for tag in ("[css=68]", "[center]", "[size=5]", "[b]", "[img]"):
        assert tag in content["mycode"]
    assert not [f for f in content["conversion_findings"] if "unknown" in f["code"]]


def test_house_style_negative_control_flags_an_unknown_tag(
    templates_dir: Path,
) -> None:
    # The [css=68] house-style marker suppresses these findings, so the control
    # drops it: the same render path must then report the unknown tag.
    unknown = "[frobnicate]x[/frobnicate]"
    (templates_dir / "house.mycode").write_text(
        HOUSE_STYLE.replace("[css=68]", unknown), encoding="utf-8"
    )
    result = _call(
        _reader(templates_dir),
        "templates_render",
        {"name": "house", "values": {"headline": "H", "banner": "https://x.test/a"}},
    )
    assert not result.is_error
    codes = [f["code"] for f in result.structured_content["conversion_findings"]]
    assert "unknown_mycode_tag" in codes


def test_convert_input_at_the_cap_is_accepted_and_over_it_is_refused(
    tmp_path: Path,
) -> None:
    server = _reader(tmp_path)
    at_cap = _call(server, "formatting_convert", {"message": "a" * MAX_MESSAGE_CHARS})
    assert not at_cap.is_error
    over = _call(
        server, "formatting_convert", {"message": "a" * (MAX_MESSAGE_CHARS + 1)}
    )
    assert over.is_error
    assert over.structured_content["error"]["code"] == "INVALID_ARGUMENT"


def test_convert_is_idempotent_on_its_own_output(tmp_path: Path) -> None:
    server = _reader(tmp_path)
    cases = _golden_markdown_cases()
    assert cases
    for case in cases:
        first = _call(server, "formatting_convert", {"message": case["markdown"]})
        again = _call(
            server,
            "formatting_convert",
            {
                "message": first.structured_content["mycode"],
                "message_format": "mycode",
            },
        )
        assert not again.is_error, case["id"]
        assert again.structured_content["mycode"] == first.structured_content["mycode"]


def test_templates_list_and_render_make_zero_transport_calls(
    templates_dir: Path,
) -> None:
    _fixture_directory(templates_dir)
    transport = _CountingTransport()
    server = _server(_settings("reader", templates_dir=templates_dir), transport)
    assert not _call(server, "templates_list", {}).is_error
    rendered = _call(
        server, "templates_render", {"name": "release", "values": {"title": "T"}}
    )
    assert not rendered.is_error
    assert transport.calls == 0


def test_render_output_over_the_cap_is_refused(templates_dir: Path) -> None:
    _fixture_directory(templates_dir)
    result = _call(
        _reader(templates_dir),
        "templates_render",
        {"name": "release", "values": {"title": "t" * (MAX_MESSAGE_CHARS - 5)}},
    )
    assert result.is_error
    assert result.structured_content["error"]["code"] == "INVALID_ARGUMENT"


def test_render_values_summing_over_the_cap_are_refused_before_filling(
    templates_dir: Path,
) -> None:
    _fixture_directory(templates_dir)
    half = MAX_MESSAGE_CHARS // 2 + 1
    result = _call(
        _reader(templates_dir),
        "templates_render",
        {"name": "release", "values": {"title": "a" * half, "note": "b" * half}},
    )
    assert result.is_error
    error = result.structured_content["error"]
    assert error["code"] == "INVALID_ARGUMENT"
    assert "too large" in error["message"]


def _repeating_template(count: int) -> Template:
    return Template(
        name="repeat",
        description="d",
        message_format="markdown",
        placeholders=(Placeholder(key="a", description="d", required=True),),
        body="{{a}}" * count,
    )


def test_fill_refuses_a_repeated_placeholder_before_substituting() -> None:
    # 13,000 references to a 400,000-char value would build ~5 GB if filled.
    template = _repeating_template(13_000)
    tracemalloc.start()
    started = time.perf_counter()
    try:
        with pytest.raises(ValueError, match="too large"):
            template.fill({"a": "v" * 400_000})
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 10_000_000
    assert time.perf_counter() - started < 2.0


def test_fill_projected_output_at_the_limit_succeeds_and_one_over_is_refused() -> None:
    template = _repeating_template(5)
    value = "z" * (MAX_MESSAGE_CHARS // 5)
    assert MAX_MESSAGE_CHARS % 5 == 0
    assert len(template.fill({"a": value})) == MAX_MESSAGE_CHARS
    with pytest.raises(ValueError, match="too large"):
        template.fill({"a": value + "z"})


def test_fill_counts_missing_optional_values_as_empty_in_the_projection() -> None:
    template = Template(
        name="opt",
        description="d",
        message_format="markdown",
        placeholders=(Placeholder(key="a", description="d", required=False),),
        body="{{a}}" * 3 + "tail",
    )
    assert template.fill({}) == "tail"


def test_render_repeated_placeholder_over_the_cap_is_invalid_argument(
    templates_dir: Path,
) -> None:
    (templates_dir / "repeat.md").write_text(
        "---\ndescription: d\nplaceholders:\n  a:\n    description: d\n"
        "    required: true\n---\n" + "{{a}}" * 10_000,
        encoding="utf-8",
    )
    result = _call(
        _reader(templates_dir),
        "templates_render",
        {"name": "repeat", "values": {"a": "v" * 300_000}},
    )
    assert result.is_error
    assert result.structured_content["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    ("tool", "field", "limit", "extra"),
    [
        ("drafts_list", "title", MAX_SHORT_TEXT_CHARS, {}),
        ("drafts_list", "category", MAX_SHORT_TEXT_CHARS, {}),
        ("formatting_preflight", "source_path", MAX_PATH_CHARS, {}),
    ],
)
def test_new_text_limits_accept_the_limit_and_refuse_one_over(
    templates_dir: Path,
    tool: str,
    field: str,
    limit: int,
    extra: dict[str, Any],
) -> None:
    server = _reader(templates_dir)
    over = _call(server, tool, {field: "a" * (limit + 1), **extra})
    assert over.is_error
    assert over.structured_content["error"]["code"] == "INVALID_ARGUMENT"
    at_limit = _call(server, tool, {field: "a" * limit, **extra})
    error = (at_limit.structured_content or {}).get("error", {})
    assert error.get("code") != "INVALID_ARGUMENT" or "maxLength" not in str(error)


def test_name_collision_between_md_and_mycode_counts_as_invalid(
    templates_dir: Path,
) -> None:
    (templates_dir / "a.md").write_text(VALID_MD, encoding="utf-8")
    (templates_dir / "a.mycode").write_text(VALID_MD, encoding="utf-8")
    templates, invalid = load_templates(templates_dir)
    assert [t.name for t in templates] == ["a"]
    assert invalid == 1
    listed = _call(_reader(templates_dir), "templates_list", {})
    assert listed.structured_content["invalid_count"] == 1


def test_deeply_nested_front_matter_is_invalid_and_does_not_break_siblings(
    templates_dir: Path,
) -> None:
    nested = "---\ndescription: " + "[" * 30_000 + "\n---\nbody"
    (templates_dir / "deep.md").write_text(nested, encoding="utf-8")
    (templates_dir / "release.md").write_text(VALID_MD, encoding="utf-8")
    server = _reader(templates_dir)
    listed = _call(server, "templates_list", {})
    assert not listed.is_error
    assert [t["name"] for t in listed.structured_content["templates"]] == ["release"]
    assert listed.structured_content["invalid_count"] == 1
    rendered = _call(
        server, "templates_render", {"name": "release", "values": {"title": "T"}}
    )
    assert not rendered.is_error


def test_candidates_beyond_the_per_call_cap_count_as_invalid(
    templates_dir: Path,
) -> None:
    extra = 4
    for index in range(MAX_TEMPLATE_CANDIDATES + extra):
        (templates_dir / f"t{index:04d}.md").write_text(VALID_MD, encoding="utf-8")
    templates, invalid = load_templates(templates_dir)
    assert len(templates) == MAX_TEMPLATE_CANDIDATES
    assert invalid == extra
