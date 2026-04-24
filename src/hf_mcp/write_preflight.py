from __future__ import annotations

import re
from typing import Literal

WriteSourceFormat = Literal["mycode", "markdown"]

_PLACEHOLDER_PATTERN = re.compile(r"\x00|HF_MCP_CODE|INLCODE|CODE\d")
_CONTROL_PATTERN = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CODE_TAG_PATTERN = re.compile(r"\[(/?)(code|php)\]", re.IGNORECASE)
_EMITTED_TAG_PATTERN = re.compile(
    r"\[(?P<close>/)?(?P<tag>b|i|s|url|img|quote|list)(?:=[^\]]*)?\]|\[\*\]",
    re.IGNORECASE,
)
_STRICT_TAGS: frozenset[str] = frozenset({"b", "i", "s", "url", "img", "quote", "list"})


class WritePreflightError(ValueError):
    pass


def validate_write_body(value: str, *, source_format: WriteSourceFormat) -> None:
    _reject_control_or_placeholder_text(value)
    without_code_blocks = _remove_balanced_code_blocks(value)
    if source_format == "markdown":
        _validate_emitted_mycode_tags(without_code_blocks)


def _reject_control_or_placeholder_text(value: str) -> None:
    if _PLACEHOLDER_PATTERN.search(value):
        raise WritePreflightError("Write body contains an internal formatter placeholder.")
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
            raise WritePreflightError(f"Write body contains closing {tag_name} tag without an opener.")
        open_tag, open_start = stack.pop()
        if open_tag != tag_name:
            raise WritePreflightError(f"Write body closes {tag_name} while {open_tag} is still open.")
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


def _validate_emitted_mycode_tags(value: str) -> None:
    stack: list[str] = []

    for match in _EMITTED_TAG_PATTERN.finditer(value):
        raw_token = match.group(0).lower()
        if raw_token == "[*]":
            if "list" not in stack:
                raise WritePreflightError("Write body contains a list item outside a list block.")
            continue

        tag_name = match.group("tag").lower()
        if tag_name not in _STRICT_TAGS:
            continue

        if not match.group("close"):
            stack.append(tag_name)
            continue

        if not stack:
            raise WritePreflightError(f"Write body contains closing {tag_name} tag without an opener.")
        open_tag = stack.pop()
        if open_tag != tag_name:
            raise WritePreflightError(f"Write body closes {tag_name} while {open_tag} is still open.")

    if stack:
        raise WritePreflightError(f"Write body contains unclosed {stack[-1]} tag.")


__all__ = ["WritePreflightError", "WriteSourceFormat", "validate_write_body"]
