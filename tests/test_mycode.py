from __future__ import annotations

import sys
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.mycode import decode_double_quote_entities, format_body_text, markdown_to_mycode


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


def test_format_body_text_decodes_quote_entities_in_all_body_modes() -> None:
    source = '[code]{&quot;mode&quot;:&#34;raw&#x22;}[/code] output_mode=&quot;structured&quot;'

    assert format_body_text(source, "raw") == '[code]{"mode":"raw"}[/code] output_mode="structured"'
    assert format_body_text(source, "clean") == '{"mode":"raw"} output_mode="structured"'
    assert format_body_text(source, "markdown") == (
        "```\n"
        '{"mode":"raw"}\n'
        "```\n"
        ' output_mode="structured"'
    )


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
