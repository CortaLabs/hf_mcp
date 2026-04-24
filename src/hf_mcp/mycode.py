from __future__ import annotations

from dataclasses import dataclass
import html
import re
from typing import Literal

BodyFormat = Literal["raw", "clean", "markdown"]
MessageFormat = Literal["mycode", "markdown"]

_VALID_BODY_FORMATS: frozenset[str] = frozenset({"raw", "clean", "markdown"})
_VALID_MESSAGE_FORMATS: frozenset[str] = frozenset({"mycode", "markdown"})
_CODE_BLOCK_PATTERN = re.compile(r"\[(code|php)\](.*?)\[/\1\]", re.IGNORECASE | re.DOTALL)
_MARKDOWN_CODE_BLOCK_PATTERN = re.compile(r"```(?:[a-zA-Z0-9_-]+)?\n?(.*?)```", re.DOTALL)
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
_MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)")
_MARKDOWN_INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+)`")
_QUOTE_PATTERN = re.compile(r"\[quote(?P<attrs>[^\]]*)\](?P<body>.*?)\[/quote\]", re.IGNORECASE | re.DOTALL)
_LIST_PATTERN = re.compile(r"\[list(?:=[^\]]*)?\](?P<body>.*?)\[/list\]", re.IGNORECASE | re.DOTALL)
_URL_WITH_TARGET_PATTERN = re.compile(r"\[url=(?P<url>[^\]]+)\](?P<body>.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_URL_PATTERN = re.compile(r"\[url\](?P<url>.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_IMAGE_PATTERN = re.compile(r"\[(?:img|uimg)\](?P<url>.*?)\[/\s*(?:img|uimg)\]", re.IGNORECASE | re.DOTALL)
_UNKNOWN_TAG_PATTERN = re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9_-]*(?:=[^\]]*)?\](?!\()|\[\*\]", re.DOTALL)


@dataclass(frozen=True, slots=True)
class MyCodeRule:
    markdown_prefix: str = ""
    markdown_suffix: str = ""
    clean_prefix: str = ""
    clean_suffix: str = ""


TAG_RULES: dict[str, MyCodeRule] = {
    "b": MyCodeRule(markdown_prefix="**", markdown_suffix="**"),
    "strong": MyCodeRule(markdown_prefix="**", markdown_suffix="**"),
    "i": MyCodeRule(markdown_prefix="_", markdown_suffix="_"),
    "em": MyCodeRule(markdown_prefix="_", markdown_suffix="_"),
    "s": MyCodeRule(markdown_prefix="~~", markdown_suffix="~~"),
    "strike": MyCodeRule(markdown_prefix="~~", markdown_suffix="~~"),
    "u": MyCodeRule(),
    "color": MyCodeRule(),
    "size": MyCodeRule(),
    "font": MyCodeRule(),
    "align": MyCodeRule(),
    "center": MyCodeRule(),
    "left": MyCodeRule(),
    "right": MyCodeRule(),
    "spoiler": MyCodeRule(markdown_prefix="Spoiler: "),
}


def coerce_body_format(raw_value: object, *, field_name: str) -> BodyFormat:
    if not isinstance(raw_value, str):
        raise ValueError(f"`{field_name}` must be a string.")
    value = raw_value.strip()
    if value not in _VALID_BODY_FORMATS:
        valid = ", ".join(sorted(_VALID_BODY_FORMATS))
        raise ValueError(f"Unknown body format '{value}'. Valid formats: {valid}.")
    return value  # type: ignore[return-value]


def coerce_message_format(raw_value: object, *, field_name: str) -> MessageFormat:
    if not isinstance(raw_value, str):
        raise ValueError(f"`{field_name}` must be a string.")
    value = raw_value.strip()
    if value not in _VALID_MESSAGE_FORMATS:
        valid = ", ".join(sorted(_VALID_MESSAGE_FORMATS))
        raise ValueError(f"Unknown message format '{value}'. Valid formats: {valid}.")
    return value  # type: ignore[return-value]


def format_body_text(value: str, body_format: BodyFormat) -> str:
    if body_format == "raw":
        return value

    code_blocks: list[str] = []

    def _stash_code(match: re.Match[str]) -> str:
        code = match.group(2)
        if body_format == "markdown":
            replacement = f"\n```\n{code}\n```\n"
        else:
            replacement = code
        code_blocks.append(replacement)
        return f"\u0000HF_MCP_CODE_{len(code_blocks) - 1}\u0000"

    text = _CODE_BLOCK_PATTERN.sub(_stash_code, value)
    text = html.unescape(text)
    text = _convert_quotes(text, body_format)
    text = _convert_lists(text, body_format)
    text = _convert_links_and_images(text, body_format)
    text = _apply_tag_rules(text, body_format)
    text = _UNKNOWN_TAG_PATTERN.sub("", text)

    for index, replacement in enumerate(code_blocks):
        text = text.replace(f"\u0000HF_MCP_CODE_{index}\u0000", replacement)

    return _tidy_text(text)


def markdown_to_mycode(value: str) -> str:
    code_blocks: list[str] = []

    def _stash_code_block(match: re.Match[str]) -> str:
        code_blocks.append(f"[code]{match.group(1)}[/code]")
        return f"\u0000CODE{len(code_blocks) - 1}\u0000"

    text = _MARKDOWN_CODE_BLOCK_PATTERN.sub(_stash_code_block, value)
    text = _MARKDOWN_IMAGE_PATTERN.sub(lambda match: f"[img]{match.group(1)}[/img]", text)
    text = _MARKDOWN_LINK_PATTERN.sub(lambda match: f"[url={match.group(2)}]{match.group(1)}[/url]", text)
    text = _MARKDOWN_INLINE_CODE_PATTERN.sub(lambda match: f"[code]{match.group(1)}[/code]", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"[b]\1[/b]", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"[b]\1[/b]", text, flags=re.DOTALL)
    text = re.sub(r"~~(.+?)~~", r"[s]\1[/s]", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"[i]\1[/i]", text, flags=re.DOTALL)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"[i]\1[/i]", text, flags=re.DOTALL)
    text = _convert_markdown_blockquotes(text)
    text = _convert_markdown_lists(text)

    for index, replacement in enumerate(code_blocks):
        text = text.replace(f"\u0000CODE{index}\u0000", replacement)

    return _tidy_text(text)


def format_write_text(value: str, message_format: MessageFormat) -> str:
    if message_format == "mycode":
        return value
    return markdown_to_mycode(value)


def _convert_quotes(text: str, body_format: BodyFormat) -> str:
    def _replace(match: re.Match[str]) -> str:
        author = _quote_author(match.group("attrs"))
        body = format_body_text(match.group("body"), body_format)
        if body_format == "markdown":
            lines = [line for line in body.splitlines() if line.strip()]
            prefix = f"**{author}:**" if author else ""
            quote_lines = [prefix] if prefix else []
            quote_lines.extend(lines)
            return "\n".join(f"> {line}" if line else ">" for line in quote_lines)
        if author:
            return f"{author}:\n{body}"
        return body

    previous = None
    while previous != text:
        previous = text
        text = _QUOTE_PATTERN.sub(_replace, text)
    return text


def _quote_author(attrs: str) -> str:
    attrs = attrs.strip()
    if not attrs:
        return ""
    if attrs.startswith("="):
        attrs = attrs[1:].strip()
    if not attrs:
        return ""
    first = attrs.split(maxsplit=1)[0].strip()
    return first.strip("\"'")


def _convert_lists(text: str, body_format: BodyFormat) -> str:
    def _replace(match: re.Match[str]) -> str:
        items = [
            format_body_text(item.strip(), body_format)
            for item in re.split(r"\[\*\]", match.group("body"))
            if item.strip()
        ]
        if not items:
            return format_body_text(match.group("body"), body_format)
        marker = "- " if body_format == "markdown" else ""
        return "\n".join(f"{marker}{item}" for item in items)

    return _LIST_PATTERN.sub(_replace, text)


def _convert_links_and_images(text: str, body_format: BodyFormat) -> str:
    def _replace_target_link(match: re.Match[str]) -> str:
        url = match.group("url").strip().strip("\"'")
        label = format_body_text(match.group("body"), body_format).strip() or url
        if body_format == "markdown":
            return f"[{label}]({url})"
        return f"{label} ({url})" if label != url else url

    def _replace_link(match: re.Match[str]) -> str:
        url = format_body_text(match.group("url"), body_format).strip()
        return f"[{url}]({url})" if body_format == "markdown" else url

    def _replace_image(match: re.Match[str]) -> str:
        url = html.unescape(match.group("url").strip())
        return f"![]({url})" if body_format == "markdown" else url

    text = _URL_WITH_TARGET_PATTERN.sub(_replace_target_link, text)
    text = _URL_PATTERN.sub(_replace_link, text)
    text = _IMAGE_PATTERN.sub(_replace_image, text)
    return text


def _apply_tag_rules(text: str, body_format: BodyFormat) -> str:
    for tag_name, rule in TAG_RULES.items():
        pattern = re.compile(
            rf"\[{re.escape(tag_name)}(?:=[^\]]*)?\](.*?)\[/{re.escape(tag_name)}\]",
            re.IGNORECASE | re.DOTALL,
        )
        for _ in range(20):
            updated = pattern.sub(lambda match: _render_rule(rule, match.group(1), body_format), text)
            if updated == text:
                break
            text = updated
    return text


def _render_rule(rule: MyCodeRule, body: str, body_format: BodyFormat) -> str:
    rendered_body = format_body_text(body, body_format)
    if body_format == "markdown":
        return f"{rule.markdown_prefix}{rendered_body}{rule.markdown_suffix}"
    return f"{rule.clean_prefix}{rendered_body}{rule.clean_suffix}"


def _tidy_text(text: str) -> str:
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _convert_markdown_blockquotes(text: str) -> str:
    lines = text.splitlines()
    converted: list[str] = []
    quote_lines: list[str] = []

    def _flush_quote() -> None:
        if not quote_lines:
            return
        converted.append("[quote]" + "\n".join(quote_lines).strip() + "[/quote]")
        quote_lines.clear()

    for line in lines:
        if line.startswith(">"):
            quote_lines.append(line[1:].lstrip())
        else:
            _flush_quote()
            converted.append(line)
    _flush_quote()
    return "\n".join(converted)


def _convert_markdown_lists(text: str) -> str:
    lines = text.splitlines()
    converted: list[str] = []
    list_items: list[str] = []

    def _flush_list() -> None:
        if not list_items:
            return
        converted.append("[list]\n" + "\n".join(f"[*] {item}" for item in list_items) + "\n[/list]")
        list_items.clear()

    for line in lines:
        match = re.match(r"\s*[-*]\s+(.+)", line)
        if match:
            list_items.append(match.group(1).strip())
        else:
            _flush_list()
            converted.append(line)
    _flush_list()
    return "\n".join(converted)


__all__ = [
    "BodyFormat",
    "MessageFormat",
    "TAG_RULES",
    "coerce_body_format",
    "coerce_message_format",
    "format_body_text",
    "format_write_text",
    "markdown_to_mycode",
]
