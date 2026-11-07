"""Near-linear-time guards for the Markdown-to-MyCode converter.

Each case is a pathological input at the 500,000 character cap that used to grow
at least quadratically through ``prepare_formatting_report``. CPU time is
measured, not wall time. CPU time still varies with machine load: a correct
converter takes 1.0 to 1.9 seconds on these inputs, while the quadratic versions
took minutes or more. The bound sits well clear of the first and far below the
second, and the doubling test below checks the growth rate directly.
"""

from __future__ import annotations

import re
import time

import pytest

from hf_mcp.formatting_engine import prepare_formatting_report
from hf_mcp.mycode import finditer_paired
from hf_mcp.write_preflight import WritePreflightError, validate_write_body

INPUT_CAP = 500_000
TIME_BOUND_SECONDS = 6.0

# name -> repeating unit. The first three are the reported patterns; the rest are
# neighbours that shared a super-linear step (per-opener rescans, per-token string
# rebuilds, per-character span bookkeeping, per-item regex compiles).
PATTERNS: dict[str, str] = {
    "star-word": "*a ",
    "backticks": "`",
    "my-bold-tags": "[b]",
    "underscore-word": "_a ",
    "my-italic-tags": "[i]",
    "url-openers": "[url=",
    "url-body-openers": "[url]",
    "image-openers": "[img]",
    "uimage-openers": "[uimg]",
    "code-openers": "[code]",
    "quote-openers": "[quote]",
    "list-openers": "[list]",
    "spoiler-openers": "[spoiler=",
    "attribute-openers": "[b=",
    "backtick-fences": "```\n",
    "tilde-fences": "~~~\n",
    "bold-star-word": "**a ",
    "bold-italic-star-word": "***a ",
    "strike-word": "~~a ",
    "spaces": " ",
    "tabs": "\t",
    "inline-code": "`a` ",
    "unterminated-links": "[a](",
    "links": "[a](b) ",
    "escaped-brackets": "\\[",
    "close-tags": "[/b]",
    "list-items": "[*]",
    "mixed-markup": "*_`[b]",
    "setext-headings": "a\n=\n",
    "bullet-lines": "- x\n",
    "horizontal-rule-tags": "[hr]",
}


def _cpu_seconds(text: str) -> float:
    started = time.process_time()
    prepare_formatting_report(text, "markdown")
    return time.process_time() - started


@pytest.mark.regression
@pytest.mark.parametrize("name", sorted(PATTERNS))
def test_markdown_conversion_stays_near_linear_at_the_input_cap(name: str) -> None:
    unit = PATTERNS[name]
    text = (unit * (INPUT_CAP // len(unit) + 1))[:INPUT_CAP]
    assert len(text) == INPUT_CAP

    elapsed = _cpu_seconds(text)

    assert elapsed < TIME_BOUND_SECONDS, f"{name}: {elapsed:.2f}s CPU at {INPUT_CAP}"


@pytest.mark.regression
@pytest.mark.parametrize(
    "name", ["star-word", "backticks", "my-bold-tags", "url-openers"]
)
def test_doubling_the_input_does_not_quadruple_the_time(name: str) -> None:
    unit = PATTERNS[name]
    small = (unit * (100_000 // len(unit) + 1))[:100_000]
    large = (unit * (400_000 // len(unit) + 1))[:400_000]

    small_seconds = max(_cpu_seconds(small), 0.02)
    large_seconds = _cpu_seconds(large)

    # Linear growth is a 4x ratio for a 4x input; quadratic growth is 16x.
    assert large_seconds / small_seconds < 10, (
        f"{name}: {small_seconds:.2f}s -> {large_seconds:.2f}s for a 4x input"
    )


@pytest.mark.regression
@pytest.mark.parametrize(
    ("opener", "closer", "text"),
    [
        (
            r"\[url\](?P<dest>.*?)\[/url\]",
            r"\[/url\]",
            "[url]a[/url] [url]b [url]c[/url] [url]",
        ),
        (r"\[b\](.*?)\[/b\]", r"\[/b\]", "[b][b]x[/b] y [/b] [b] z"),
        (r"\[b\](.*?)\[/b\]", r"\[/b\]", "no tags at all"),
        (r"\[b\](.*?)\[/b\]", r"\[/b\]", "[b]only an opener"),
    ],
)
def test_paired_scan_finds_exactly_the_matches_a_plain_scan_finds(
    opener: str, closer: str, text: str
) -> None:
    pattern = re.compile(opener, re.IGNORECASE | re.DOTALL)
    closer_pattern = re.compile(closer, re.IGNORECASE)

    bounded = [m.span() for m in finditer_paired(pattern, closer_pattern, text)]

    assert bounded == [m.span() for m in pattern.finditer(text)]


@pytest.mark.regression
@pytest.mark.parametrize(
    "body",
    [
        "[url]https://a.b[/url] [url]",
        "[url=https://a.b]x[/url] [url=",
        "[img]https://a.b/c.png[/img] [img]",
        "[uimg]https://a.b/c.png[/uimg] [img]",
        "[list][*]a[*]b[/list]",
        "[b]x[/b] [i]y[/i] [b",
    ],
)
def test_preflight_accepts_what_it_accepted_with_unterminated_openers(
    body: str,
) -> None:
    validate_write_body(body, source_format="mycode")


@pytest.mark.regression
@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("[img]a b[/img]", "unsafe image destination"),
        ("[uimg]http://a.b/c.png[/uimg]", "unsafe image destination"),
        ("[url]javascript:x[/url]", "unsafe link destination"),
        ("[url=ftp://a.b]x[/url]", "unsafe link destination"),
        (
            "[img]ok[/img] [img]https://a.b/c.png[/IMG] [uimg]x y[/uimg]",
            "unsafe image destination",
        ),
    ],
)
def test_preflight_still_rejects_unsafe_destinations(body: str, message: str) -> None:
    with pytest.raises(WritePreflightError, match=message):
        validate_write_body(body, source_format="mycode")


@pytest.mark.regression
def test_preflight_still_rejects_a_list_item_outside_a_list() -> None:
    with pytest.raises(WritePreflightError, match="list item outside a list"):
        validate_write_body("[b][*]x[/b]", source_format="markdown")
    validate_write_body("[list][b]y[/b][*]x[/list]", source_format="markdown")


@pytest.mark.regression
def test_deeply_nested_blockquotes_convert_without_recursion_error() -> None:
    from hf_mcp.tools.formatting import convert_formatting

    text = ">" * INPUT_CAP
    started = time.process_time()
    result = convert_formatting(message=text, message_format="markdown")
    elapsed = time.process_time() - started

    assert isinstance(result["structuredContent"]["mycode"], str)
    assert elapsed < TIME_BOUND_SECONDS, f"{elapsed:.2f}s CPU at {INPUT_CAP}"


@pytest.mark.regression
@pytest.mark.parametrize(
    ("opener", "closer"), [("[code]", "[/php]"), ("[img]", "[/uimg]")]
)
def test_mixed_closer_pairing_stays_near_linear(opener: str, closer: str) -> None:
    unit = opener + "x"
    body = unit * ((INPUT_CAP - len(closer)) // len(unit) + 1)
    text = (body[: INPUT_CAP - len(closer)]) + closer
    assert len(text) == INPUT_CAP

    elapsed = _cpu_seconds(text)

    assert elapsed < TIME_BOUND_SECONDS, f"{opener}/{closer}: {elapsed:.2f}s CPU"
