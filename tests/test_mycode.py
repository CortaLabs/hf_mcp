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
    ConversionFinding,
    analyze_conversion,
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


@pytest.mark.regression
def test_markdown_balanced_destinations() -> None:
    destination = "https://example.org/a_(b)/c?x=a%2Fb&raw=&quot;"
    escaped_destination = r"https://example.org/a\(b\)/c"

    assert markdown_to_mycode(f"[docs]({destination})") == f"[url={destination}]docs[/url]"
    assert markdown_to_mycode(f"[docs]({escaped_destination})") == (
        f"[url={escaped_destination}]docs[/url]"
    )
    assert markdown_to_mycode(r"[literal \*x*](url)") == "[url=url]literal *x*[/url]"
    assert markdown_to_mycode(r"\[docs](url)") == "[docs](url)"
    assert markdown_to_mycode("[Use `code`](https://x.test)") == (
        "[url=https://x.test]Use [code]code[/code][/url]"
    )
    image = "https://example.org/a_b*(c).png"
    assert markdown_to_mycode(f"![alt]({image})") == f"[img]{image}[/img]"
    assert markdown_to_mycode("[docs](https://example.org/a_(b)/c)") == (
        "[url=https://example.org/a_(b)/c]docs[/url]"
    )


@pytest.mark.regression
def test_markdown_escape_parity() -> None:
    slash = chr(92)
    for run_length in range(5):
        source = slash * run_length + "*x*"
        prefix = slash * (run_length // 2)
        expected = prefix + ("*x*" if run_length % 2 else "[i]x[/i]")
        assert markdown_to_mycode(source) == expected

    assert markdown_to_mycode(r"literal\n stays literal") == r"literal\n stays literal"
    assert markdown_to_mycode(r"escaped \_underscore\_") == "escaped _underscore_"


@pytest.mark.regression
def test_markdown_nested_emphasis() -> None:
    converted = (
        ("***both styles***", "[b][i]both styles[/i][/b]"),
        ("**bold _nested_**", "[b]bold [i]nested[/i][/b]"),
        ("*outer **bold** outer*", "[i]outer [b]bold[/b] outer[/i]"),
        ("~~strike **bold**~~", "[s]strike [b]bold[/b][/s]"),
    )
    for source, expected in converted:
        output = markdown_to_mycode(source)
        assert output == expected
        _assert_balanced_emphasis_tags(output)

    assert markdown_to_mycode("unmatched ** stays and intraword a_b_c stays") == (
        "unmatched ** stays and intraword a_b_c stays"
    )


def _assert_balanced_emphasis_tags(value: str) -> None:
    stack: list[str] = []
    for match in re.finditer(r"\[(?P<close>/)?(?P<tag>b|i|s)\]", value):
        tag = match.group("tag")
        if match.group("close"):
            assert stack and stack.pop() == tag
        else:
            stack.append(tag)
    assert stack == []


@pytest.mark.regression
def test_markdown_flat_list_boundaries() -> None:
    assert markdown_to_mycode("- one\n\n* two") == (
        "[list]\n[*] one\n[/list]\n\n[list]\n[*] two\n[/list]"
    )
    nested = "- parent\n  - child\n- sibling"
    assert markdown_to_mycode(nested) == nested
    styled_nested = "- **parent**\n  - *child*\n- sibling"
    assert markdown_to_mycode(styled_nested) == styled_nested
    mixed = "1. ordered\n- unordered"
    assert markdown_to_mycode(mixed) == mixed
    task = "- [ ] todo\n- [x] done"
    assert markdown_to_mycode(task) == task


@pytest.mark.regression
def test_markdown_unsupported_constructs_preserved() -> None:
    source = (
        "# heading\n"
        "\n| a | b |\n| - | - |\n| x | y |\n"
        "\n---\n"
        "[docs](https://example.org/page \"optional title\")\n"
        "~~~python\nprint('keep')\n~~~"
    )
    assert markdown_to_mycode(source) == source


@pytest.mark.regression
def test_markdown_code_payload_identity() -> None:
    payload = "\x00CODE0\x00 \x00INLCODE0\x00 **literal** [docs](https://x.test/a_(b))"
    source = f"```python\n{payload}\n``` and `**inline** [x](url)`"
    rendered = markdown_to_mycode(source)

    assert rendered == f"[code]{payload}\n[/code] and [code]**inline** [x](url)[/code]"


@pytest.mark.regression
def test_markdown_terminates_on_malformed_input() -> None:
    malformed = "[label](https://example.org/" + "(" * 1200 + "*unfinished"
    assert markdown_to_mycode(malformed) == malformed
    unclosed_link = "[label](https://example.org/*leave this literal*"
    assert markdown_to_mycode(unclosed_link) == unclosed_link
    assert markdown_to_mycode("*" * 3000 + "unfinished") == "*" * 3000 + "unfinished"


def test_conversion_analysis_supported_basics() -> None:
    assert analyze_conversion("**bold** and [docs](https://example.test)", "markdown") == ()
    assert analyze_conversion("[b]bold[/b] &quot; &#34; &#x22;", "mycode") == ()
    assert markdown_to_mycode("**bold**") == "[b]bold[/b]"
    assert format_write_text("**bold**", "markdown") == markdown_to_mycode("**bold**")
    destination_a = "[docs](https://a.example.test)"
    destination_b = "[docs](https://b.example.test)"
    payload_a = "```text\nfirst payload\n```"
    payload_b = "```text\nsecond payload\n```"
    assert analyze_conversion(destination_a, "markdown") == ()
    assert analyze_conversion(destination_b, "markdown") == ()
    assert markdown_to_mycode(destination_a) != markdown_to_mycode(destination_b)
    assert markdown_to_mycode(payload_a) != markdown_to_mycode(payload_b)
    assert analyze_conversion("--- inline text", "markdown") == ()


def test_conversion_analysis_unsupported_families() -> None:
    cases = {
        "nested_list": "- parent\n  - child",
        "ordered_list": "1. first\n2. second",
        "task_list": "- [ ] todo\n- [x] done",
        "heading": "# heading",
        "table": "| a | b |\n| - | - |",
        "horizontal_rule": "---",
        "link_title": '[docs](https://example.test \"title\")',
        "unsupported_fence": "~~~python\nprint(1)\n~~~",
        "unmatched_markdown_delimiter": "unfinished **bold",
    }
    for code, source in cases.items():
        findings = analyze_conversion(source, "markdown")
        assert any(finding.code == code and finding.kind == "unsupported" for finding in findings), code
        assert markdown_to_mycode(source) == format_write_text(source, "markdown")

    assert analyze_conversion("*ok*tail", "markdown") == ()
    assert markdown_to_mycode("*ok*tail") == "[i]ok[/i]tail"
    assert analyze_conversion("\\*literal", "markdown") == ()
    assert markdown_to_mycode("\\*literal") == "*literal"
    destination = "[x](https://x.test/a_*tail)"
    assert analyze_conversion(destination, "markdown") == ()
    assert markdown_to_mycode(destination) == "[url=https://x.test/a_*tail]x[/url]"

    titled_image = '![alt](https://x.test "title")'
    image_findings = analyze_conversion(titled_image, "markdown")
    assert {finding.code for finding in image_findings} == {"link_title"}
    nested_code = "- parent\n  - `code`"
    assert markdown_to_mycode(nested_code) == nested_code
    nested_findings = analyze_conversion(nested_code, "markdown")
    assert {finding.code for finding in nested_findings} == {"nested_list"}
    nested_image = "- parent\n  - ![alt](url)"
    assert markdown_to_mycode(nested_image) == nested_image
    assert {finding.code for finding in analyze_conversion(nested_image, "markdown")} == {
        "nested_list"
    }

    bare_url = "https://example.org/*keep*"
    assert markdown_to_mycode(bare_url) == bare_url
    assert analyze_conversion(bare_url, "markdown") == ()

    markdown_spoiler = "[spoiler]secret[/spoiler]"
    spoiler_finding = next(
        finding
        for finding in analyze_conversion(markdown_spoiler, "markdown")
        if finding.code == "spoiler_plaintext_projection"
    )
    assert spoiler_finding.stage == "readable"
    assert markdown_spoiler[spoiler_finding.start:spoiler_finding.end] == markdown_spoiler
    markdown_unknown = "[mystery]text[/mystery]"
    unknown_finding = next(
        finding
        for finding in analyze_conversion(markdown_unknown, "markdown")
        if finding.code == "unknown_mycode_tag"
    )
    assert unknown_finding.stage == "readable"
    assert markdown_unknown[unknown_finding.start:unknown_finding.end] == "[mystery]"


def test_conversion_analysis_loss_families() -> None:
    cases = (
        ("image_alt_loss", "![description](https://example.test/image.png)"),
        ("inline_code_block_conversion", "Use `literal` here"),
        ("fence_language_loss", "```python\nprint(1)\n```"),
    )
    for code, source in cases:
        assert any(
            finding.code == code and finding.kind == "loss"
            for finding in analyze_conversion(source, "markdown")
        )
    assert not any(
        finding.code == "image_alt_loss"
        for finding in analyze_conversion("![](https://example.test/image.png)", "markdown")
    )
    spoiler = analyze_conversion("[spoiler=title]secret[/spoiler]", "mycode")
    assert any(
        finding.code == "spoiler_plaintext_projection"
        and finding.kind == "loss"
        and finding.stage == "readable"
        for finding in spoiler
    )
    assert not any(
        finding.code == "unknown_mycode_tag"
        for finding in analyze_conversion("[spoiler=title]secret[/spoiler]", "mycode")
    )
    assert any(
        finding.code == "unknown_mycode_tag"
        for finding in analyze_conversion("[unknown]keep[/unknown]", "mycode")
    )


def test_conversion_analysis_source_spans() -> None:
    source = "雪\n# heading"
    finding = next(
        finding for finding in analyze_conversion(source, "markdown") if finding.code == "heading"
    )
    assert (finding.start, finding.end) == (2, len(source))
    assert source[finding.start:finding.end] == "# heading"
    assert (finding.start, finding.end) == (2, 11)

    span_cases = (
        ("image_alt_loss", "雪 ![alt](image.png)", "![alt](image.png)", "markdown"),
        ("inline_code_block_conversion", "Use `literal`", "`literal`", "markdown"),
        ("fence_language_loss", "```python\nbody\n```", "python", "markdown"),
        ("link_title", '[docs](url \"title\")', '[docs](url \"title\")', "markdown"),
        ("spoiler_plaintext_projection", "雪[spoiler]x[/spoiler]", "[spoiler]x[/spoiler]", "mycode"),
        ("unknown_mycode_tag", "[unknown]x[/unknown]", "[unknown]", "mycode"),
    )
    for code, value, expected_span, message_format in span_cases:
        match = next(
            item for item in analyze_conversion(value, message_format) if item.code == code
        )
        assert value[match.start:match.end] == expected_span, code


def test_conversion_analysis_ignores_protected_content() -> None:
    source = "```\n# not a heading\n- [ ] not a task\n``` and `**literal**`"
    markdown_findings = analyze_conversion(source, "markdown")
    assert {finding.code for finding in markdown_findings} == {"inline_code_block_conversion"}
    assert not any(f.code in {"heading", "task_list"} for f in markdown_findings)
    mycode = "[code][unknown][spoiler]literal[/spoiler][/unknown][/code]"
    assert analyze_conversion(mycode, "mycode") == ()
    assert analyze_conversion("\\# not a heading\n\\- [ ] literal", "markdown") == ()

    protected_markdown = (
        "[code][spoiler]secret[/spoiler][mystery]x[/mystery][/code]",
        "[php][spoiler]secret[/spoiler][mystery]x[/mystery][/php]",
    )
    for source in protected_markdown:
        assert markdown_to_mycode(source) == source
        assert analyze_conversion(source, "markdown") == ()


def test_conversion_analysis_is_deterministic() -> None:
    source = "![alt](x)\n# heading\n# heading"
    findings = analyze_conversion(source, "markdown")
    assert findings == analyze_conversion(source, "markdown")
    assert findings == tuple(sorted(findings, key=lambda f: (f.start, f.end, f.stage, f.code)))
    assert len(findings) == len(set(findings))
    assert sum(finding.code == "heading" for finding in findings) == 2
    assert ConversionFinding.__dataclass_params__.frozen
    assert hasattr(ConversionFinding, "__slots__")


def test_conversion_analysis_does_not_attest_uri_safety() -> None:
    source = "[click](javascript:alert(1))"
    findings = analyze_conversion(source, "markdown")
    assert findings == ()
    assert tuple(ConversionFinding.__dataclass_fields__) == (
        "code", "kind", "stage", "start", "end"
    )


def test_conversion_analysis_shares_composed_protection_decisions() -> None:
    linked_emphasis = "**[docs](https://example.test)**"
    assert markdown_to_mycode(linked_emphasis) == "[b][url=https://example.test]docs[/url][/b]"
    assert analyze_conversion(linked_emphasis, "markdown") == ()

    discarded_image_alt = "![*alt](https://example.test)"
    assert markdown_to_mycode(discarded_image_alt) == "[img]https://example.test[/img]"
    assert tuple(f.code for f in analyze_conversion(discarded_image_alt, "markdown")) == (
        "image_alt_loss",
    )

    malformed_spoiler = "[spoiler][b]secret[/spoiler][/b]"
    assert format_body_text(malformed_spoiler, "markdown") == malformed_spoiler
    assert analyze_conversion(malformed_spoiler, "mycode") == ()

    code_destination = "[x](`url`)"
    assert markdown_to_mycode(code_destination) == "[url=[code]url[/code]]x[/url]"
    findings = analyze_conversion(code_destination, "markdown")
    assert tuple(f.code for f in findings) == ("inline_code_block_conversion",)
    assert (findings[0].start, findings[0].end) == (4, 9)
