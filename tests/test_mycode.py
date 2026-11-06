from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import cast

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp import mycode  # noqa: E402
from hf_mcp.mycode import (  # noqa: E402
    TAG_RULES,
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
        "[quote=\"alice\" pid='1'][b]Heads up[/b][/quote]\n"
        "[url=https://example.test]link[/url]\n"
        "[img]https://example.test/a.png[/img]\n"
        "[list][*]one[*]two[/list]\n"
        '[code]{"keep":"exact"}[/code]'
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
        " \tleft\r\n\r\n&quot; &#34; &#x22; \\n\nright  ",
        "literal ``` fence marker",
    )
    for payload in payloads:
        for tag in ("code", "php"):
            source = f"[{tag}]{payload}[/{tag}]"
            assert format_body_text(source, "clean") == payload

            markdown = format_body_text(source, "markdown")
            longest_fence = max(
                (len(run) for run in re.findall(r"`+", payload)), default=0
            )
            fence = "`" * max(3, longest_fence + 1)
            opening = f"{fence}\n"
            closing = f"\n{fence}"
            assert markdown.startswith(opening)
            assert markdown.endswith(closing)
            assert markdown[len(opening) : -len(closing)] == payload


@pytest.mark.regression
def test_read_projection_preserves_literal_entities() -> None:
    source = r"&quot; &#34; &#x22; &amp; &#91;b&#93;"
    assert format_body_text(source, "clean") == source
    assert format_body_text(source, "markdown") == source
    # HF's readback angle-bracket entities decode outside code, never inside it.
    assert format_body_text("&lt;tag&gt;", "clean") == "<tag>"
    assert format_body_text("[code]&lt;tag&gt;[/code]", "clean") == "&lt;tag&gt;"


def test_readable_text_unfolds_doubled_escapes_but_code_keeps_them() -> None:
    assert format_body_text(r"one\n two", "clean") == "one\n two"
    assert format_body_text(r"[code]a\nb[/code]", "clean") == r"a\nb"
    assert markdown_to_mycode(r"literal\n stays literal") == r"literal\n stays literal"


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
        '```json\n{"keep":"exact"}\n```'
    )

    assert markdown_to_mycode(source) == (
        "[b]Bold[/b] and [i]italic[/i]\n"
        "[url=https://example.test]link[/url]\n"
        "[img]https://example.test/a.png[/img]\n"
        "[list]\n"
        "[*]one\n"
        "[*]two\n"
        "[/list]\n"
        "[quote]quoted[/quote]\n\n"
        '[code]\n{"keep":"exact"}\n[/code]'
    )


def test_markdown_to_mycode_protects_inline_code_from_emphasis_rules() -> None:
    source = (
        'Use `body_format="markdown"` and `message_format="markdown"`.\n'
        "Keep `snake_case_value` literal while **bold** still converts."
    )

    assert markdown_to_mycode(source) == (
        'Use [font=monospace]body_format="markdown"[/font] and [font=monospace]message_format="markdown"[/font].\n'
        "Keep [font=monospace]snake_case_value[/font] literal while [b]bold[/b] still converts."
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

    assert (
        markdown_to_mycode(f"[docs]({destination})") == f"[url={destination}]docs[/url]"
    )
    assert markdown_to_mycode(f"[docs]({escaped_destination})") == (
        f"[url={escaped_destination}]docs[/url]"
    )
    assert markdown_to_mycode(r"[literal \*x*](url)") == "[url=url]literal *x*[/url]"
    assert markdown_to_mycode(r"\[docs](url)") == "[docs](url)"
    assert markdown_to_mycode("[Use `code`](https://x.test)") == (
        "[url=https://x.test]Use [font=monospace]code[/font][/url]"
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
        "[list]\n[*]one\n[/list]\n\n[list]\n[*]two\n[/list]"
    )
    assert markdown_to_mycode("- parent\n  - child\n- sibling") == (
        "[list]\n[*]parent\n[list]\n[*]child\n[/list]\n[*]sibling\n[/list]"
    )
    assert markdown_to_mycode("- **parent**\n  - *child*") == (
        "[list]\n[*][b]parent[/b]\n[list]\n[*][i]child[/i]\n[/list]\n[/list]"
    )
    assert markdown_to_mycode("1. ordered\n- unordered") == (
        "[list=1]\n[*]ordered\n[/list]\n[list]\n[*]unordered\n[/list]"
    )
    assert markdown_to_mycode("- a\n    - b\n        - c\n- d") == (
        "[list]\n[*]a\n[list]\n[*]b\n[list]\n[*]c\n[/list]\n[/list]\n[*]d\n[/list]"
    )
    assert markdown_to_mycode("- [ ] todo\n- [x] done") == (
        "[list]\n[*][ ] todo\n[*][x] done\n[/list]"
    )
    assert (
        markdown_to_mycode("> - quoted item\n> text")
        == "[quote][list]\n[*]quoted item\n[/list]\ntext[/quote]"
    )


@pytest.mark.regression
def test_markdown_rules_and_headings_use_line_anchors() -> None:
    for rule in ("---", "***", "___", "* * *", "- - -"):
        assert markdown_to_mycode(f"a\n\n{rule}\n\nb") == "a\n\n[hr]\n\nb", rule
    assert markdown_to_mycode("--- inline text") == "--- inline text"
    assert markdown_to_mycode("###### six\n#nospace") == "[b]six[/b]\n#nospace"
    assert markdown_to_mycode("## closed ##") == "[b]closed[/b]"
    assert markdown_to_mycode("\\# literal") == "# literal"
    assert (
        markdown_to_mycode("## **x** and [d](u)")
        == "[b][b]x[/b] and [url=u]d[/url][/b]"
    )


@pytest.mark.regression
def test_markdown_unsupported_constructs_preserved() -> None:
    source = (
        '[docs](https://example.org/page "optional title")\n'
        "~~~python\nprint('keep')\n~~~"
    )
    assert markdown_to_mycode(source) == source
    assert {finding.code for finding in analyze_conversion(source, "markdown")} == {
        "link_title",
        "unsupported_fence",
    }


GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "mycode_golden.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", GOLDEN, ids=[case["id"] for case in GOLDEN])
def test_golden_corpus(case: dict[str, object]) -> None:
    markdown = str(case["markdown"])
    assert markdown_to_mycode(markdown) == case["mycode"]
    assert {
        finding.code for finding in analyze_conversion(markdown, "markdown")
    } == set(cast(list[str], case["findings"]))


def test_golden_outputs_hold_no_markdown_block_syntax_outside_code() -> None:
    for case in GOLDEN:
        output = str(case["mycode"])
        assert "\\[" not in output, case["id"]
        outside_code = re.sub(r"\[code\].*?\[/code\]", "", output, flags=re.DOTALL)
        for line in outside_code.splitlines():
            assert not re.match(r"(#|1\. |- |---|\|)", line), (case["id"], line)


def test_all_exports_the_original_public_names() -> None:
    original = {
        "BodyFormat",
        "MessageFormat",
        "TAG_RULES",
        "coerce_body_format",
        "coerce_message_format",
        "decode_double_quote_entities",
        "format_body_text",
        "format_write_text",
        "markdown_to_mycode",
    }
    assert original <= set(mycode.__all__)


@pytest.mark.regression
def test_house_tags_css_and_hr_are_known() -> None:
    assert TAG_RULES["css"].attribute is not None and TAG_RULES["hr"].void
    house = "[css=68][center]x[/center][/css]\n[hr]\n[b]y[/b]"
    assert analyze_conversion(house, "mycode") == ()
    assert format_body_text("a[hr]b", "clean") == "a\n---\nb"
    assert format_body_text("[css=68]kept[/css]", "markdown") == "kept"
    for bad in ("[css=x]y[/css]", "[css]y[/css]", "[hr=1]"):
        found = [
            f
            for f in analyze_conversion(bad, "mycode")
            if f.code == "unknown_mycode_tag"
        ]
        assert (
            found and bad[found[0].start : found[0].end] == bad.split("]")[0] + "]"
        ), bad
    assert format_body_text("[css=x]y[/css]", "clean") == "[css=x]y[/css]"


@pytest.mark.regression
def test_markdown_code_payload_identity() -> None:
    payload = "\x00CODE0\x00 \x00INLCODE0\x00 **literal** [docs](https://x.test/a_(b))"
    source = f"```python\n{payload}\n``` and `**inline** [x](url)`"
    rendered = markdown_to_mycode(source)

    assert (
        rendered == f"[code]\n{payload}\n[/code] and [code]**inline** [x](url)[/code]"
    )


@pytest.mark.regression
def test_markdown_terminates_on_malformed_input() -> None:
    malformed = "[label](https://example.org/" + "(" * 1200 + "*unfinished"
    assert markdown_to_mycode(malformed) == malformed
    unclosed_link = "[label](https://example.org/*leave this literal*"
    assert markdown_to_mycode(unclosed_link) == unclosed_link
    assert markdown_to_mycode("*" * 3000 + "unfinished") == "*" * 3000 + "unfinished"


def test_conversion_analysis_supported_basics() -> None:
    assert (
        analyze_conversion("**bold** and [docs](https://example.test)", "markdown")
        == ()
    )
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
        "link_title": '[docs](https://example.test "title")',
        "unsupported_fence": "~~~python\nprint(1)\n~~~",
        "unmatched_markdown_delimiter": "unfinished **bold",
    }
    for code, source in cases.items():
        findings = analyze_conversion(source, "markdown")
        assert any(
            finding.code == code and finding.kind == "unsupported"
            for finding in findings
        ), code
        assert markdown_to_mycode(source) == format_write_text(source, "markdown")

    # Constructs that now convert cleanly report nothing.
    for converted in (
        "# heading",
        "1. a\n2. b",
        "- a\n  - b",
        "---",
        "- [ ] todo",
        "```python\nx\n```",
    ):
        assert analyze_conversion(converted, "markdown") == (), converted

    assert analyze_conversion("*ok*tail", "markdown") == ()
    assert markdown_to_mycode("*ok*tail") == "[i]ok[/i]tail"
    assert analyze_conversion("\\*literal", "markdown") == ()
    assert markdown_to_mycode("\\*literal") == "*literal"
    destination = "[x](https://x.test/a_*tail)"
    assert analyze_conversion(destination, "markdown") == ()
    assert markdown_to_mycode(destination) == "[url=https://x.test/a_*tail]x[/url]"

    titled_image = '![alt](https://x.test "title")'
    assert {
        finding.code for finding in analyze_conversion(titled_image, "markdown")
    } == {"link_title"}

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
    assert (
        markdown_spoiler[spoiler_finding.start : spoiler_finding.end]
        == markdown_spoiler
    )
    markdown_unknown = "[mystery]text[/mystery]"
    unknown_finding = next(
        finding
        for finding in analyze_conversion(markdown_unknown, "markdown")
        if finding.code == "unknown_mycode_tag"
    )
    assert unknown_finding.stage == "readable"
    assert markdown_unknown[unknown_finding.start : unknown_finding.end] == "[mystery]"


def test_conversion_analysis_loss_families() -> None:
    cases = (
        ("image_alt_loss", "![description](https://example.test/image.png)"),
        ("inline_code_as_block", "Use `[literal]` here"),
        ("table_as_code", "| a |\n|---|\n| 1 |"),
    )
    for code, source in cases:
        assert any(
            finding.code == code and finding.kind == "loss"
            for finding in analyze_conversion(source, "markdown")
        ), code
    for quiet in (
        "![](https://example.test/image.png)",
        "Use `literal` here",
        "```python\nx\n```",
    ):
        assert analyze_conversion(quiet, "markdown") == (), quiet
    spoiler = analyze_conversion("[spoiler=title]secret[/spoiler]", "mycode")
    assert any(
        finding.code == "spoiler_plaintext_projection"
        and finding.kind == "loss"
        and finding.stage == "readable"
        for finding in spoiler
    )
    assert not any(finding.code == "unknown_mycode_tag" for finding in spoiler)
    assert any(
        finding.code == "unknown_mycode_tag"
        for finding in analyze_conversion("[unknown]keep[/unknown]", "mycode")
    )


def test_conversion_analysis_source_spans() -> None:
    span_cases = (
        ("image_alt_loss", "雪 ![alt](image.png)", "![alt](image.png)", "markdown"),
        ("inline_code_as_block", "雪 Use `[x]`", "`[x]`", "markdown"),
        ("table_as_code", "雪\n| a |\n|---|\n", "| a |\n|---|\n", "markdown"),
        ("link_title", '[docs](url "title")', '[docs](url "title")', "markdown"),
        (
            "spoiler_plaintext_projection",
            "雪[spoiler]x[/spoiler]",
            "[spoiler]x[/spoiler]",
            "mycode",
        ),
        ("unknown_mycode_tag", "[unknown]x[/unknown]", "[unknown]", "mycode"),
    )
    for code, value, expected_span, message_format in span_cases:
        match = next(
            item
            for item in analyze_conversion(value, message_format)
            if item.code == code
        )
        assert value[match.start : match.end] == expected_span, code


def test_conversion_analysis_ignores_protected_content() -> None:
    source = "```\n# not a heading\n| a |\n``` and `**literal**`"
    assert analyze_conversion(source, "markdown") == ()
    assert (
        markdown_to_mycode(source)
        == "[code]\n# not a heading\n| a |\n[/code] and [font=monospace]**literal**[/font]"
    )
    mycode_source = "[code][unknown][spoiler]literal[/spoiler][/unknown][/code]"
    assert analyze_conversion(mycode_source, "mycode") == ()
    assert analyze_conversion("\\# not a heading\n\\- [ ] literal", "markdown") == ()

    protected_markdown = (
        "[code][spoiler]secret[/spoiler][mystery]x[/mystery][/code]",
        "[php][spoiler]secret[/spoiler][mystery]x[/mystery][/php]",
    )
    for protected in protected_markdown:
        assert markdown_to_mycode(protected) == protected
        assert analyze_conversion(protected, "markdown") == ()


def test_conversion_analysis_is_deterministic() -> None:
    source = "![alt](x)\n| a |\n\n| b |"
    findings = analyze_conversion(source, "markdown")
    assert findings == analyze_conversion(source, "markdown")
    assert findings == tuple(
        sorted(findings, key=lambda f: (f.start, f.end, f.stage, f.code))
    )
    assert len(findings) == len(set(findings))
    assert sum(finding.code == "table_as_code" for finding in findings) == 2
    assert ConversionFinding.__dataclass_params__.frozen
    assert hasattr(ConversionFinding, "__slots__")


def test_conversion_analysis_does_not_attest_uri_safety() -> None:
    source = "[click](javascript:alert(1))"
    findings = analyze_conversion(source, "markdown")
    assert findings == ()
    assert tuple(ConversionFinding.__dataclass_fields__) == (
        "code",
        "kind",
        "stage",
        "start",
        "end",
    )


def test_conversion_analysis_shares_composed_protection_decisions() -> None:
    linked_emphasis = "**[docs](https://example.test)**"
    assert (
        markdown_to_mycode(linked_emphasis)
        == "[b][url=https://example.test]docs[/url][/b]"
    )
    assert analyze_conversion(linked_emphasis, "markdown") == ()

    discarded_image_alt = "![*alt](https://example.test)"
    assert markdown_to_mycode(discarded_image_alt) == "[img]https://example.test[/img]"
    assert tuple(
        f.code for f in analyze_conversion(discarded_image_alt, "markdown")
    ) == ("image_alt_loss",)

    malformed_spoiler = "[spoiler][b]secret[/spoiler][/b]"
    assert format_body_text(malformed_spoiler, "markdown") == malformed_spoiler
    assert analyze_conversion(malformed_spoiler, "mycode") == ()

    code_destination = "[x](`[u]`)"
    assert markdown_to_mycode(code_destination) == "[url=[code][u][/code]]x[/url]"
    findings = analyze_conversion(code_destination, "markdown")
    assert tuple(f.code for f in findings) == ("inline_code_as_block",)
    assert (findings[0].start, findings[0].end) == (4, 9)


def test_conversion_analysis_orders_findings_by_source() -> None:
    source = "| a |\n\n![alt](x)\n\n| b |"
    findings = analyze_conversion(source, "markdown")
    assert tuple((f.code, source[f.start : f.end]) for f in findings) == (
        ("table_as_code", "| a |\n"),
        ("image_alt_loss", "![alt](x)"),
        ("table_as_code", "| b |"),
    )


def test_conversion_analysis_reports_unmatched_link_label_delimiters() -> None:
    malformed = "preface [**broken](url)"

    assert markdown_to_mycode(malformed) == "preface [url=url]**broken[/url]"
    findings = analyze_conversion(malformed, "markdown")
    assert tuple(
        (
            finding.code,
            finding.start,
            finding.end,
            malformed[finding.start : finding.end],
        )
        for finding in findings
    ) == (("unmatched_markdown_delimiter", 9, 11, "**"),)

    supported = "preface [**bold**](url)"
    assert markdown_to_mycode(supported) == "preface [url=url][b]bold[/b][/url]"
    assert analyze_conversion(supported, "markdown") == ()


@pytest.mark.regression
def test_markdown_code_bodies_keep_blank_runs_and_trailing_spaces() -> None:
    body = "def a():\n    pass  \n\n\ndef b():\n    pass\n"
    assert markdown_to_mycode(f"```python\n{body}```") == f"[code]\n{body}[/code]"


@pytest.mark.regression
def test_markdown_setext_headings_and_rule_placement() -> None:
    assert markdown_to_mycode("Sub\n---") == "[b]Sub[/b]"
    assert markdown_to_mycode("Title\n=====") == "[b]Title[/b]"
    assert markdown_to_mycode("a\n\n---\n\nb") == "a\n\n[hr]\n\nb"
    assert markdown_to_mycode("---\ntext") == "[hr]\ntext"
    assert analyze_conversion("Title\n=====\nSub\n---", "markdown") == ()


@pytest.mark.regression
def test_markdown_raw_mycode_tags_survive_emphasis_scanner() -> None:
    assert markdown_to_mycode("[*]a\n[*]b") == "[*]a\n[*]b"
    assert (
        markdown_to_mycode("[list]\n[*]a\n[*]b\n[/list]")
        == "[list]\n[*]a\n[*]b\n[/list]"
    )
    assert markdown_to_mycode("[*]*x* and [color=red]_y_[/color]") == (
        "[*][i]x[/i] and [color=red][i]y[/i][/color]"
    )
    assert markdown_to_mycode("[url=https://e.com/a_b_c]**go**[/url]") == (
        "[url=https://e.com/a_b_c][b]go[/b][/url]"
    )


@pytest.mark.regression
def test_markdown_normalizes_line_endings_and_keeps_spans() -> None:
    assert markdown_to_mycode("a\r\nb") == "a\nb"
    assert markdown_to_mycode("a\rb") == "a\nb"
    assert markdown_to_mycode("```py\r\nx\r\n```") == "[code]\nx\n[/code]"
    source = "a\r\n| x |"
    finding = analyze_conversion(source, "markdown")[0]
    assert finding.code == "table_as_code"
    assert source[finding.start : finding.end] == "| x |"


@pytest.mark.regression
def test_markdown_unmatched_brackets_are_linear() -> None:
    started = time.perf_counter()
    assert markdown_to_mycode("[" * 10_000) == "[" * 10_000
    assert markdown_to_mycode("[a](" * 2_000 + "b") == "[a](" * 2_000 + "b"
    assert time.perf_counter() - started < 1.0


def test_markdown_probe_shapes() -> None:
    assert markdown_to_mycode("") == ""
    assert analyze_conversion("", "markdown") == ()
    assert markdown_to_mycode(
        "[d](https://e.com/a_(b)_c) and https://e.com/x_y_z)"
    ) == ("[url=https://e.com/a_(b)_c]d[/url] and https://e.com/x_y_z)")
    assert markdown_to_mycode("a\\\\b") == "a\\b"
    assert markdown_to_mycode("| `x` | y |\n|---|---|\n| 1 | 2 |") == (
        "[code]\n| `x` | y |\n|---|---|\n| 1 | 2 |\n[/code]"
    )
    assert markdown_to_mycode("- a\n  1. x\n  2. y\n- b") == (
        "[list]\n[*]a\n[list=1]\n[*]x\n[*]y\n[/list]\n[*]b\n[/list]"
    )
    assert markdown_to_mycode("- item\n  ```\n  code\n  ```\n- next") == (
        "[list]\n[*]item\n[code]\ncode\n[/code]\n[*]next\n[/list]"
    )


def test_markdown_long_thread_body() -> None:
    unit_source = (
        "## Update {n}\n\nSome **bold** text with `code` and [link](https://e.com/a).\n\n"
        "- one\n- two\n\n> quote\n\n---\n\n"
    )
    unit_expected = (
        "[b]Update {n}[/b]\n\nSome [b]bold[/b] text with [font=monospace]code[/font] "
        "and [url=https://e.com/a]link[/url].\n\n"
        "[list]\n[*]one\n[*]two\n[/list]\n\n[quote]quote[/quote]\n\n[hr]\n\n"
    )
    source = "".join(unit_source.format(n=n) for n in range(200))
    expected = "".join(unit_expected.format(n=n) for n in range(200)).strip()
    assert markdown_to_mycode(source) == expected
    assert analyze_conversion(source, "markdown") == ()


def test_house_mycode_layout_passes_through_unchanged() -> None:
    fixture = Path(__file__).parent / "fixtures" / "house_mycode.txt"
    body = fixture.read_text(encoding="utf-8").removesuffix("\n")
    for tag in (
        "[css=68]",
        "[center]",
        "[size=7]",
        "[hr]",
        "[*]",
        "[align=",
        "[color=",
    ):
        assert tag in body, tag
    assert markdown_to_mycode(body) == body
    assert not any(
        finding.kind == "loss" for finding in analyze_conversion(body, "markdown")
    )
