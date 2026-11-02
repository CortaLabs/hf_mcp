from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.mycode import (
    decode_double_quote_entities,
    format_body_text,
    format_write_text,
    markdown_to_mycode,
)

pytestmark = [pytest.mark.core, pytest.mark.formatting]


def test_format_body_text_converts_common_mycode_to_markdown() -> None:
    source = (
        '[quote="alice" pid=\'1\'][b]Heads up[/b][/quote]\n'
        "[url=https://example.test]link[/url]\n"
        "[img]https://example.test/a.png[/img]\n"
        "[list][*]one[*]two[/list]\n"
        "[code]{\"keep\":\"exact\"}[/code]"
    )

    assert format_body_text(source, "markdown") == (
        "> **alice:**\n"
        "> **Heads up**\n"
        "[link](https://example.test)\n"
        "![](https://example.test/a.png)\n"
        "- one\n"
        "- two\n\n"
        "```\n"
        '{"keep":"exact"}\n'
        "```"
    )


def test_format_body_text_can_strip_mycode_noise_without_markdown() -> None:
    source = "[align=center][color=red]Hi[/color][/align] [url=https://example.test]site[/url]"

    assert format_body_text(source, "clean") == "Hi site (https://example.test)"
    assert format_body_text(source, "raw") == source


@pytest.mark.regression
def test_raw_body_is_identity() -> None:
    values = (
        "",
        " \t\r\n ",
        "雪 ☃️ café",
        "&quot; &#34; &#x22; &lt;tag&gt; &amp;",
        r"literal\n escape",
        "first\rsecond\r\nthird\n",
        "[b]unterminated[/i] [unknown]text[/unknown]",
    )
    for source in values:
        assert format_body_text(source, "raw") == source


@pytest.mark.regression
def test_mycode_write_is_identity() -> None:
    values = (
        "",
        " \t\r\n ",
        "雪 ☃️ café",
        "&quot; &#34; &#x22; &lt;tag&gt; &amp;",
        r"literal\n escape",
        "first\rsecond\r\nthird\n",
        "[b]unterminated[/i] [unknown]text[/unknown]",
    )
    for source in values:
        assert format_write_text(source, "mycode") == source


@pytest.mark.regression
def test_read_projection_preserves_code_payload() -> None:
    payloads = (
        ' \tleft\r\n\r\n&quot; &#34; &#x22; \\n\nright  ',
        "literal ``` fence marker",
    )
    for payload in payloads:
        for tag in ("code", "php"):
            source = f"[{tag}]{payload}[/{tag}]"
            assert format_body_text(source, "clean") == payload

            markdown = format_body_text(source, "markdown")
            longest_fence = max((len(run) for run in re.findall(r"`+", payload)), default=0)
            fence = "`" * max(3, longest_fence + 1)
            opening = f"{fence}\n"
            closing = f"\n{fence}"
            assert markdown.startswith(opening)
            assert markdown.endswith(closing)
            assert markdown[len(opening) : -len(closing)] == payload


@pytest.mark.regression
def test_read_projection_preserves_literal_entities() -> None:
    source = r"&quot; &#34; &#x22; &lt;tag&gt; &amp; &#91;b&#93; literal\n escape"
    assert format_body_text(source, "clean") == source
    assert format_body_text(source, "markdown") == source


@pytest.mark.regression
def test_read_projection_preserves_spoiler_boundaries() -> None:
    source = "[spoiler=title]outer [spoiler=inner]secret[/spoiler] tail[/spoiler]"
    expected = (
        "Spoiler [title] (plaintext; not concealed):\n"
        "outer Spoiler [inner] (plaintext; not concealed):\n"
        "secret\nEnd spoiler tail\nEnd spoiler"
    )
    for body_format in ("clean", "markdown"):
        assert format_body_text(source, body_format) == expected


@pytest.mark.regression
def test_read_projection_retains_unknown_markup() -> None:
    source = "before [unknown=attr]keep[/unknown] [b]open[/i] [u]unclosed [spoiler=title]also unclosed"
    for body_format in ("clean", "markdown"):
        rendered = format_body_text(source, body_format)
        assert "[unknown=attr]keep[/unknown]" in rendered
        assert "[b]open[/i]" in rendered
        assert "[u]unclosed" in rendered
        assert "[spoiler=title]also unclosed" in rendered


@pytest.mark.regression
def test_read_projection_placeholder_collision() -> None:
    source = (
        "literal \x00HF_MCP_CODE_0\x00 and \x00HF_MCP_PROTECTED_CODE_0_0\x00 "
        "[code]payload\nline[/code]"
    )
    for body_format in ("clean", "markdown"):
        rendered = format_body_text(source, body_format)
        assert "literal \x00HF_MCP_CODE_0\x00" in rendered
        assert "\x00HF_MCP_PROTECTED_CODE_0_0\x00" in rendered
        assert "payload\nline" in rendered
        assert "HF_MCP_CODE_1" not in rendered
        assert "\x00HF_MCP_PROTECTED_CODE_1_0\x00" not in rendered


@pytest.mark.regression
def test_read_projection_retains_crossed_markup() -> None:
    source = "[b][i]crossed[/b][/i]"
    for body_format in ("clean", "markdown"):
        assert format_body_text(source, body_format) == source


@pytest.mark.regression
def test_read_projection_preserves_deeply_nested_spoiler_boundaries() -> None:
    depth = 1100
    source = "[spoiler]" * depth + "payload" + "[/spoiler]" * depth

    rendered = format_body_text(source, "markdown")

    assert rendered.count("Spoiler (plaintext; not concealed):") == depth
    assert rendered.count("End spoiler") == depth
    assert "payload" in rendered
    assert rendered.startswith("Spoiler (plaintext; not concealed):\n")
    assert rendered.endswith("End spoiler")


def test_decode_double_quote_entities_does_not_decode_other_html_entities() -> None:
    source = "&lt;tag attr=&quot;ok&#34;&gt;AT&amp;T&#x22;"

    assert decode_double_quote_entities(source) == '&lt;tag attr="ok"&gt;AT&amp;T"'


def test_markdown_to_mycode_converts_common_agent_markdown() -> None:
    source = (
        "**Bold** and _italic_\n"
        "[link](https://example.test)\n"
        "![alt](https://example.test/a.png)\n"
        "- one\n"
        "- two\n"
        "> quoted\n\n"
        "```json\n{\"keep\":\"exact\"}\n```"
    )

    assert markdown_to_mycode(source) == (
        "[b]Bold[/b] and [i]italic[/i]\n"
        "[url=https://example.test]link[/url]\n"
        "[img]https://example.test/a.png[/img]\n"
        "[list]\n"
        "[*] one\n"
        "[*] two\n"
        "[/list]\n"
        "[quote]quoted[/quote]\n\n"
        "[code]{\"keep\":\"exact\"}\n[/code]"
    )


def test_markdown_to_mycode_protects_inline_code_from_emphasis_rules() -> None:
    source = (
        'Use `body_format="markdown"` and `message_format="markdown"`.\n'
        "Keep `snake_case_value` literal while **bold** still converts."
    )

    assert markdown_to_mycode(source) == (
        'Use [code]body_format="markdown"[/code] and [code]message_format="markdown"[/code].\n'
        "Keep [code]snake_case_value[/code] literal while [b]bold[/b] still converts."
    )


def test_markdown_to_mycode_does_not_italicize_snake_case_or_urls() -> None:
    source = (
        "body_format and message_format stay literal.\n"
        "snake_case_value stays literal.\n"
        "https://github.com/CortaLabs/hf_mcp stays literal.\n"
        "normal _italic_ and *emphasis* still convert."
    )

    assert markdown_to_mycode(source) == (
        "body_format and message_format stay literal.\n"
        "snake_case_value stays literal.\n"
        "https://github.com/CortaLabs/hf_mcp stays literal.\n"
        "normal [i]italic[/i] and [i]emphasis[/i] still convert."
    )
