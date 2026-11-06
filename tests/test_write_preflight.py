from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hf_mcp.formatting_engine import prepare_formatting_report, write_draft_artifact
from hf_mcp.tools.write_documented import create_thread_live, reply_to_thread_live
from hf_mcp.write_preflight import WritePreflightError, validate_write_body

SOURCES = ("mycode", "markdown")

UNSAFE_LINK_DESTINATIONS = [
    "javascript:alert(1)",
    "javascript&#58;alert(1)",
    "JaVaScRiPt:alert(1)",
    "\tjavascript:alert(1)",
    "\njavascript:alert(1)",
    "\thttps://example.com",
    "\nhttps://example.com",
    "&#9;https://example.com",
    "java\tscript:alert(1)",
    "data:text/html;base64,AAAA",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "ftp://example.com/x",
    "mailto:a@example.com",
    "//evil.example",
    "https://user@host.example",
    "https://user:pw@host.example",
    "https:\\\\evil.example",
    "https://example.com\\@evil.example",
    "https://exa mple.com",
    "https:example.com",
    "/relative/path",
    "https://",
    "",
]
UNSAFE_IMAGE_DESTINATIONS = [
    *UNSAFE_LINK_DESTINATIONS,
    "http://example.com/a.png",
]


def _link_forms(dest: str) -> list[str]:
    return [f"[url={dest}]text[/url]", f"[url]{dest}[/url]"]


def _image_forms(dest: str) -> list[str]:
    return [f"[img]{dest}[/img]", f"[uimg]{dest}[/uimg]"]


@pytest.mark.parametrize("source_format", SOURCES)
@pytest.mark.parametrize("dest", UNSAFE_LINK_DESTINATIONS)
def test_unsafe_link_destinations_are_rejected(source_format: str, dest: str) -> None:
    for body in _link_forms(dest):
        with pytest.raises(WritePreflightError) as excinfo:
            validate_write_body(body, source_format=source_format)  # type: ignore[arg-type]
        if dest.strip():
            assert dest.strip() not in str(excinfo.value)


@pytest.mark.parametrize("source_format", SOURCES)
@pytest.mark.parametrize("dest", UNSAFE_IMAGE_DESTINATIONS)
def test_unsafe_image_destinations_are_rejected(source_format: str, dest: str) -> None:
    for body in _image_forms(dest):
        with pytest.raises(WritePreflightError) as excinfo:
            validate_write_body(body, source_format=source_format)  # type: ignore[arg-type]
        if dest.strip():
            assert dest.strip() not in str(excinfo.value)


SAFE_MYCODE_BODIES = [
    "[url=https://example.com/a?b=1#c]site[/url]",
    "[url=http://example.com]site[/url]",
    "[url]https://example.com/path[/url]",
    "[url]http://example.com/path[/url]",
    "[url]HTTPS://Example.com[/url]",
    "[img]https://example.com/a.png[/img]",
    "[img=100x100]https://example.com/a.png[/img]",
    "plain text without links",
]


@pytest.mark.parametrize("body", SAFE_MYCODE_BODIES)
def test_safe_destinations_reach_transport_byte_identical(body: str) -> None:
    transport = _CountingTransport()
    create_thread_live(
        transport=transport,  # type: ignore[arg-type]
        fid=1,
        subject="s",
        message=body,
        confirm_live=True,
        message_format="mycode",
    )
    reply_to_thread_live(
        transport=transport,  # type: ignore[arg-type]
        tid=1,
        message=body,
        confirm_live=True,
        message_format="mycode",
    )
    assert [c["asks"] for c in transport.calls] == [
        {"threads": {"_fid": 1, "_subject": "s", "_message": body}},
        {"posts": {"_tid": 1, "_message": body}},
    ]


@pytest.mark.parametrize("source_format", SOURCES)
@pytest.mark.parametrize("body", SAFE_MYCODE_BODIES)
def test_safe_destinations_pass_validation(body: str, source_format: str) -> None:
    validate_write_body(body, source_format=source_format)  # type: ignore[arg-type]


def test_safe_markdown_links_convert_to_exact_mycode_at_transport() -> None:
    transport = _CountingTransport()
    reply_to_thread_live(
        transport=transport,  # type: ignore[arg-type]
        tid=1,
        message="[a](https://example.com) ![i](https://example.com/a.png)",
        confirm_live=True,
        message_format="markdown",
    )
    assert [c["asks"] for c in transport.calls] == [
        {
            "posts": {
                "_tid": 1,
                "_message": (
                    "[url=https://example.com]a[/url] "
                    "[img]https://example.com/a.png[/img]"
                ),
            }
        }
    ]


@pytest.mark.parametrize(
    "text",
    [
        "![a](javascript:x)",
        "[a](javascript:x)",
        "[a](data:text/html,x)",
        "[a](//evil.example)",
        "[a](https://user@host.example)",
    ],
)
def test_unsafe_markdown_destinations_are_flagged_in_report(text: str) -> None:
    report = prepare_formatting_report(text, "markdown")
    assert any(issue.severity == "error" for issue in report.issues)
    assert report.integrity < 1.0


@pytest.mark.parametrize("text", ["<javascript:x>", "[r][1]\n\n[1]: javascript:x"])
def test_markdown_autolink_and_reference_link_stay_literal_text(text: str) -> None:
    # The converter emits these as literal text, not [url]/[img] tags, so they
    # are not clickable destinations in the posted MyCode.
    report = prepare_formatting_report(text, "markdown")
    assert "[url" not in report.mycode.lower()
    assert "[img" not in report.mycode.lower()


@pytest.mark.parametrize("source_format", SOURCES)
@pytest.mark.parametrize(
    "body", ["[url =javascript:x]y[/url]", "[url\t=javascript:x]y[/url]"]
)
def test_whitespace_before_equals_does_not_bypass_validation(
    body: str, source_format: str
) -> None:
    with pytest.raises(WritePreflightError):
        validate_write_body(body, source_format=source_format)  # type: ignore[arg-type]


@pytest.mark.parametrize("source_format", SOURCES)
def test_ipv6_literal_links_are_rejected(source_format: str) -> None:
    # Documented limitation: bracketed IPv6 hosts collide with the bracket
    # delimiter rule and are rejected.
    with pytest.raises(WritePreflightError):
        validate_write_body(
            "[url=http://[::1]/x]a[/url]",
            source_format=source_format,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("source_format", SOURCES)
def test_urls_inside_code_blocks_are_not_validated(source_format: str) -> None:
    body = (
        "[code][url=javascript:alert(1)]x[/url][/code]"
        "[php][img]data:text/html,x[/img][/php]"
    )
    validate_write_body(body, source_format=source_format)  # type: ignore[arg-type]


def test_unsafe_link_outside_code_block_is_still_rejected_next_to_code() -> None:
    body = "[code]ok[/code][url=javascript:alert(1)]x[/url]"
    with pytest.raises(WritePreflightError):
        validate_write_body(body, source_format="mycode")


@pytest.mark.parametrize("source_format", SOURCES)
def test_prepare_formatting_report_flags_unsafe_destination(
    source_format: str,
) -> None:
    report = prepare_formatting_report(
        "[url=javascript:alert(1)]x[/url]", source_format
    )
    assert any(issue.severity == "error" for issue in report.issues)
    assert report.integrity < 1.0


def test_prepare_formatting_report_markdown_link_is_flagged() -> None:
    report = prepare_formatting_report("[click](javascript:alert(1))", "markdown")
    assert any(issue.severity == "error" for issue in report.issues)
    assert report.integrity < 1.0


class _CountingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def write(
        self, *, asks: dict[str, Any], helper: str | None = None
    ) -> dict[str, Any]:
        self.calls.append({"asks": asks, "helper": helper})
        return {"ok": True}


UNSAFE_TEXT = "[url=javascript&#58;alert(1)]x[/url]"


@pytest.mark.parametrize("message_format", SOURCES)
def test_threads_create_and_posts_reply_reject_unsafe_text_before_transport(
    message_format: str,
) -> None:
    transport = _CountingTransport()
    with pytest.raises(WritePreflightError):
        create_thread_live(
            transport=transport,  # type: ignore[arg-type]
            fid=1,
            subject="s",
            message=UNSAFE_TEXT,
            confirm_live=True,
            message_format=message_format,
        )
    with pytest.raises(WritePreflightError):
        reply_to_thread_live(
            transport=transport,  # type: ignore[arg-type]
            tid=1,
            message=UNSAFE_TEXT,
            confirm_live=True,
            message_format=message_format,
        )
    assert transport.calls == []


@pytest.mark.parametrize("source_format", SOURCES)
def test_threads_create_and_posts_reply_reject_unsafe_draft_before_transport(
    tmp_path: Path, source_format: str
) -> None:
    transport = _CountingTransport()
    artifact = write_draft_artifact(UNSAFE_TEXT, source_format, draft_dir=tmp_path)
    with pytest.raises(WritePreflightError):
        create_thread_live(
            transport=transport,  # type: ignore[arg-type]
            fid=1,
            subject="s",
            draft_id=artifact.draft_id,
            confirm_live=True,
            draft_dir=tmp_path,
        )
    with pytest.raises(WritePreflightError):
        reply_to_thread_live(
            transport=transport,  # type: ignore[arg-type]
            tid=1,
            draft_id=artifact.draft_id,
            confirm_live=True,
            draft_dir=tmp_path,
        )
    assert transport.calls == []
