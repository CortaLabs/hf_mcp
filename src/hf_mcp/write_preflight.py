from __future__ import annotations

import html
import re
from typing import Iterator, Literal
from urllib.parse import urlsplit

WriteSourceFormat = Literal["mycode", "markdown"]

_PLACEHOLDER_PATTERN = re.compile(r"\x00|HF_MCP_CODE|INLCODE|CODE\d")
_CONTROL_PATTERN = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CODE_TAG_PATTERN = re.compile(r"\[(/?)(code|php)\]", re.IGNORECASE)
_EMITTED_TAG_PATTERN = re.compile(
    r"\[(?P<close>/)?(?P<tag>b|i|s|url|img|quote|list)(?:=[^\]]*)?\]|\[\*\]",
    re.IGNORECASE,
)
_STRICT_TAGS: frozenset[str] = frozenset({"b", "i", "s", "url", "img", "quote", "list"})
_URL_ATTRIBUTE_PATTERN = re.compile(r"\[url\s*=(?P<dest>[^\]]*)\]", re.IGNORECASE)
# A body destination runs from an opener to the first closer of the same tag. The
# opener and closer are matched apart so an opener with no closer left is skipped
# at once instead of rescanning to the end of the text.
_URL_BODY_OPENER_PATTERN = re.compile(r"\[(?P<tag>url)\]", re.IGNORECASE)
_IMAGE_BODY_OPENER_PATTERN = re.compile(
    r"\[(?P<tag>img|uimg)(?:[ =][^\]]*)?\]", re.IGNORECASE
)
_DEST_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_DEST_SCHEME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_LINK_SCHEMES: frozenset[str] = frozenset({"http", "https"})
_IMAGE_SCHEMES: frozenset[str] = frozenset({"https"})


class WritePreflightError(ValueError):
    pass


def validate_write_body(value: str, *, source_format: WriteSourceFormat) -> None:
    _reject_control_or_placeholder_text(value)
    without_code_blocks = _remove_balanced_code_blocks(value)
    if source_format == "markdown":
        _validate_emitted_mycode_tags(without_code_blocks)
    _validate_destinations(without_code_blocks)


def _reject_control_or_placeholder_text(value: str) -> None:
    if _PLACEHOLDER_PATTERN.search(value):
        raise WritePreflightError(
            "Write body contains an internal formatter placeholder."
        )
    if _CONTROL_PATTERN.search(value):
        raise WritePreflightError("Write body contains unsupported control characters.")


def _remove_balanced_code_blocks(value: str) -> str:
    stack: list[tuple[str, int]] = []
    remove_ranges: list[tuple[int, int]] = []

    for match in _CODE_TAG_PATTERN.finditer(value):
        tag_name = match.group(2).lower()
        is_close = bool(match.group(1))
        if not is_close:
            stack.append((tag_name, match.start()))
            if len(stack) > 1:
                raise WritePreflightError("Write body contains nested code blocks.")
            continue

        if not stack:
            raise WritePreflightError(
                f"Write body contains closing {tag_name} tag without an opener."
            )
        open_tag, open_start = stack.pop()
        if open_tag != tag_name:
            raise WritePreflightError(
                f"Write body closes {tag_name} while {open_tag} is still open."
            )
        remove_ranges.append((open_start, match.end()))

    if stack:
        open_tag, _ = stack[-1]
        raise WritePreflightError(f"Write body contains unclosed {open_tag} block.")

    if not remove_ranges:
        return value

    pieces: list[str] = []
    cursor = 0
    for start, end in remove_ranges:
        pieces.append(value[cursor:start])
        cursor = end
    pieces.append(value[cursor:])
    return "".join(pieces)


def _finditer_closed(pattern: re.Pattern[str], text: str) -> Iterator[re.Match[str]]:
    """Scan only up to the last `]`: every bracketed tag pattern must end on one.

    An unterminated `[^\\]]*` attribute otherwise rescans to the end of the text
    from every `[`, which is quadratic on repeated openers. No match can end past
    the last `]`, so bounding the scan never changes a match.
    """
    return pattern.finditer(text, 0, text.rfind("]") + 1)


def _body_destinations(opener_pattern: re.Pattern[str], text: str) -> Iterator[str]:
    """Yield the text between each opener and the first closer of its tag."""
    end_of_scan = text.rfind("]") + 1
    without_closer: set[str] = set()
    position = 0
    while (opener := opener_pattern.search(text, position, end_of_scan)) is not None:
        tag = opener.group("tag")
        closer = None
        if tag.lower() not in without_closer:
            closer = re.compile(rf"\[/{re.escape(tag)}\]", re.IGNORECASE).search(
                text, opener.end()
            )
            if closer is None:
                # No closer follows this opener, so none follows any later one.
                without_closer.add(tag.lower())
        if closer is None:
            position = opener.start() + 1
            continue
        yield text[opener.end() : closer.start()]
        position = closer.end()


def _validate_destinations(value: str) -> None:
    attribute_destinations = (
        match.group("dest") for match in _finditer_closed(_URL_ATTRIBUTE_PATTERN, value)
    )
    for destinations, schemes, kind in (
        (attribute_destinations, _LINK_SCHEMES, "link"),
        (_body_destinations(_URL_BODY_OPENER_PATTERN, value), _LINK_SCHEMES, "link"),
        (
            _body_destinations(_IMAGE_BODY_OPENER_PATTERN, value),
            _IMAGE_SCHEMES,
            "image",
        ),
    ):
        for destination in destinations:
            _validate_destination(destination, schemes=schemes, kind=kind)


def _validate_destination(raw: str, *, schemes: frozenset[str], kind: str) -> None:
    # Messages are static on purpose: they must never echo the destination.
    unsafe = f"Write body contains an unsafe {kind} destination."
    view = html.unescape(raw)
    if _DEST_CONTROL_PATTERN.search(view):
        raise WritePreflightError(unsafe)
    view = view.strip(" ")
    if not view or any(ch.isspace() for ch in view):
        raise WritePreflightError(unsafe)
    if "\\" in view or "[" in view or "]" in view:
        raise WritePreflightError(unsafe)
    scheme_match = _DEST_SCHEME_PATTERN.match(view)
    if scheme_match is None or scheme_match.group(0)[:-1].casefold() not in schemes:
        raise WritePreflightError(unsafe)
    if not view[scheme_match.end() :].startswith("//"):
        raise WritePreflightError(unsafe)
    try:
        parts = urlsplit(view)
        host = parts.hostname
    except ValueError:
        raise WritePreflightError(unsafe) from None
    if not parts.netloc or not host or "@" in parts.netloc:
        raise WritePreflightError(unsafe)


def _validate_emitted_mycode_tags(value: str) -> None:
    stack: list[str] = []
    open_lists = 0

    for match in _finditer_closed(_EMITTED_TAG_PATTERN, value):
        raw_token = match.group(0).lower()
        if raw_token == "[*]":
            if not open_lists:
                raise WritePreflightError(
                    "Write body contains a list item outside a list block."
                )
            continue

        tag_name = match.group("tag").lower()
        if tag_name not in _STRICT_TAGS:
            continue

        if not match.group("close"):
            stack.append(tag_name)
            open_lists += tag_name == "list"
            continue

        if not stack:
            raise WritePreflightError(
                f"Write body contains closing {tag_name} tag without an opener."
            )
        open_tag = stack.pop()
        open_lists -= open_tag == "list"
        if open_tag != tag_name:
            raise WritePreflightError(
                f"Write body closes {tag_name} while {open_tag} is still open."
            )

    if stack:
        raise WritePreflightError(f"Write body contains unclosed {stack[-1]} tag.")


__all__ = ["WritePreflightError", "WriteSourceFormat", "validate_write_body"]
