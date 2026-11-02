from __future__ import annotations

from dataclasses import dataclass
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
_MARKDOWN_ASTERISK_EMPHASIS_PATTERN = re.compile(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])", re.DOTALL)
_MARKDOWN_UNDERSCORE_EMPHASIS_PATTERN = re.compile(r"(?<![\w_])_(?![\s_])(.+?)(?<![\s_])_(?![\w_])", re.DOTALL)
_QUOTE_PATTERN = re.compile(r"\[quote(?P<attrs>[^\]]*)\](?P<body>.*?)\[/quote\]", re.IGNORECASE | re.DOTALL)
_LIST_PATTERN = re.compile(r"\[list(?:=[^\]]*)?\](?P<body>.*?)\[/list\]", re.IGNORECASE | re.DOTALL)
_URL_WITH_TARGET_PATTERN = re.compile(r"\[url=(?P<url>[^\]]+)\](?P<body>.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_URL_PATTERN = re.compile(r"\[url\](?P<url>.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_IMAGE_PATTERN = re.compile(r"\[(?:img|uimg)\](?P<url>.*?)\[/\s*(?:img|uimg)\]", re.IGNORECASE | re.DOTALL)
_DOUBLE_QUOTE_ENTITY_PATTERN = re.compile(r"&(quot|#34|#x22);", re.IGNORECASE)
_SPOILER_TAG_PATTERN = re.compile(r"\[(?P<close>/)?spoiler(?P<attrs>=[^\]]*)?\]", re.IGNORECASE)
_MYCODE_TAG_PATTERN = re.compile(
    r"\[(?P<close>/)?(?P<name>[a-zA-Z][a-zA-Z0-9_-]*)(?:=[^\]]*)?\]",
    re.DOTALL,
)


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
    placeholder_prefix = _code_placeholder_prefix(value)

    def _stash_code(match: re.Match[str]) -> str:
        code = match.group(2)
        if body_format == "markdown":
            longest_fence = max((len(run) for run in re.findall(r"`+", code)), default=0)
            fence = "`" * max(3, longest_fence + 1)
            replacement = f"{fence}\n{code}\n{fence}"
        else:
            replacement = code
        code_blocks.append(replacement)
        placeholder = f"{placeholder_prefix}{len(code_blocks) - 1}\x00"
        return f"\n{placeholder}\n" if body_format == "markdown" else placeholder

    text = _CODE_BLOCK_PATTERN.sub(_stash_code, value)
    text, malformed_blocks = _protect_malformed_markup(text, placeholder_prefix)
    text = _convert_spoilers(text)
    text = _convert_quotes(text, body_format)
    text = _convert_lists(text, body_format)
    text = _convert_links_and_images(text, body_format)
    text = _apply_tag_rules(text, body_format)
    text = _tidy_text(text)

    for index, replacement in enumerate(malformed_blocks):
        text = text.replace(f"{placeholder_prefix}LITERAL{index}\x00", replacement)
    for index, replacement in enumerate(code_blocks):
        text = text.replace(f"{placeholder_prefix}{index}\x00", replacement)

    return text


def _code_placeholder_prefix(value: str) -> str:
    attempt = 0
    while True:
        prefix = f"\x00HF_MCP_PROTECTED_CODE_{attempt}_"
        if prefix not in value:
            return prefix
        attempt += 1


def _protect_malformed_markup(text: str, placeholder_prefix: str) -> tuple[str, list[str]]:
    stack: list[tuple[str, int]] = []
    malformed_start: int | None = None
    malformed_ranges: list[tuple[int, int]] = []

    for match in _MYCODE_TAG_PATTERN.finditer(text):
        tag_name = match.group("name").lower()
        if not match.group("close"):
            stack.append((tag_name, match.start()))
            continue

        matching_index = next(
            (index for index in range(len(stack) - 1, -1, -1) if stack[index][0] == tag_name),
            None,
        )
        if matching_index is None:
            if stack and malformed_start is None:
                malformed_start = stack[0][1]
            continue

        if matching_index != len(stack) - 1:
            if malformed_start is None:
                malformed_start = stack[0][1]
            del stack[matching_index:]
        else:
            stack.pop()

        if malformed_start is not None and not stack:
            malformed_ranges.append((malformed_start, match.end()))
            malformed_start = None

    if stack:
        malformed_ranges.append((malformed_start if malformed_start is not None else stack[0][1], len(text)))

    if not malformed_ranges:
        return text, []

    literal_blocks: list[str] = []
    output: list[str] = []
    cursor = 0
    for index, (start, end) in enumerate(malformed_ranges):
        output.append(text[cursor:start])
        literal_blocks.append(text[start:end])
        output.append(f"{placeholder_prefix}LITERAL{index}\x00")
        cursor = end
    output.append(text[cursor:])
    return "".join(output), literal_blocks


def _convert_spoilers(text: str) -> str:
    matches = list(_SPOILER_TAG_PATTERN.finditer(text))
    open_stack: list[int] = []
    paired_openings: set[int] = set()
    paired_closings: set[int] = set()

    for index, match in enumerate(matches):
        if not match.group("close"):
            open_stack.append(index)
        elif open_stack:
            opening_index = open_stack.pop()
            paired_openings.add(opening_index)
            paired_closings.add(index)

    output: list[str] = []
    cursor = 0
    for index, match in enumerate(matches):
        if index in paired_openings:
            output.append(text[cursor:match.start()])
            title = (match.group("attrs") or "")[1:].strip()
            label = f"Spoiler [{title}] (plaintext; not concealed):" if title else "Spoiler (plaintext; not concealed):"
            output.append(f"{label}\n")
            cursor = match.end()
        elif index in paired_closings:
            output.append(text[cursor:match.start()])
            output.append("\nEnd spoiler")
            cursor = match.end()

    output.append(text[cursor:])
    return "".join(output)


def markdown_to_mycode(value: str) -> str:
    code_blocks: list[str] = []
    inline_code_blocks: list[str] = []

    def _stash_code_block(match: re.Match[str]) -> str:
        code_blocks.append(f"[code]{match.group(1)}[/code]")
        return f"\u0000CODE{len(code_blocks) - 1}\u0000"

    def _stash_inline_code(match: re.Match[str]) -> str:
        inline_code_blocks.append(f"[code]{match.group(1)}[/code]")
        return f"\u0000INLCODE{len(inline_code_blocks) - 1}\u0000"

    text = _MARKDOWN_CODE_BLOCK_PATTERN.sub(_stash_code_block, value)
    text = _MARKDOWN_INLINE_CODE_PATTERN.sub(_stash_inline_code, text)
    text = _MARKDOWN_IMAGE_PATTERN.sub(lambda match: f"[img]{match.group(1)}[/img]", text)
    text = _MARKDOWN_LINK_PATTERN.sub(lambda match: f"[url={match.group(2)}]{match.group(1)}[/url]", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"[b]\1[/b]", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"[b]\1[/b]", text, flags=re.DOTALL)
    text = re.sub(r"~~(.+?)~~", r"[s]\1[/s]", text, flags=re.DOTALL)
    text = _MARKDOWN_ASTERISK_EMPHASIS_PATTERN.sub(r"[i]\1[/i]", text)
    text = _MARKDOWN_UNDERSCORE_EMPHASIS_PATTERN.sub(r"[i]\1[/i]", text)
    text = _convert_markdown_blockquotes(text)
    text = _convert_markdown_lists(text)

    for index, replacement in enumerate(code_blocks):
        text = text.replace(f"\u0000CODE{index}\u0000", replacement)
    for index, replacement in enumerate(inline_code_blocks):
        text = text.replace(f"\u0000INLCODE{index}\u0000", replacement)

    return _tidy_text(text)


def format_write_text(value: str, message_format: MessageFormat) -> str:
    if message_format == "mycode":
        return value
    return markdown_to_mycode(value)


def decode_double_quote_entities(value: str) -> str:
    return _DOUBLE_QUOTE_ENTITY_PATTERN.sub('"', value)


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
        url = match.group("url").strip()
        return f"![]({url})" if body_format == "markdown" else url

    text = _URL_WITH_TARGET_PATTERN.sub(_replace_target_link, text)
    text = _URL_PATTERN.sub(_replace_link, text)
    text = _IMAGE_PATTERN.sub(_replace_image, text)
    return text


def _apply_tag_rules(text: str, body_format: BodyFormat) -> str:
    for tag_name, rule in TAG_RULES.items():
        if tag_name == "spoiler":
            continue
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
    "decode_double_quote_entities",
    "format_body_text",
    "format_write_text",
    "markdown_to_mycode",
]
