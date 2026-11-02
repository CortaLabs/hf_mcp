from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Iterator, Literal

BodyFormat = Literal["raw", "clean", "markdown"]
MessageFormat = Literal["mycode", "markdown"]

_VALID_BODY_FORMATS: frozenset[str] = frozenset({"raw", "clean", "markdown"})
_VALID_MESSAGE_FORMATS: frozenset[str] = frozenset({"mycode", "markdown"})
_CODE_BLOCK_PATTERN = re.compile(r"\[(code|php)\](.*?)\[/\1\]", re.IGNORECASE | re.DOTALL)
_MARKDOWN_CODE_BLOCK_PATTERN = re.compile(
    r"```(?P<language>[a-zA-Z0-9_-]+)?\n?(?P<body>.*?)```", re.DOTALL
)
_MARKDOWN_INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+)`")
_MARKDOWN_BARE_URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_MARKDOWN_LIST_LINE_PATTERN = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>[-*]|\d+[.)])\s+(?P<body>.*)$")
_MARKDOWN_TILDE_FENCE_PATTERN = re.compile(
    r"(?m)^ {0,3}~{3,}[^\n]*(?:\n[\s\S]*?^ {0,3}~{3,}[^\n]*|\Z)"
)
_MARKDOWN_UNSUPPORTED_BLOCK_LINE_PATTERN = re.compile(
    r"(?m)^ {0,3}(?:(?P<heading>#{1,6}[^\n]*)|(?P<hr>(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,}))$"
)
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


@dataclass(frozen=True, slots=True)
class ConversionFinding:
    code: str
    kind: Literal["unsupported", "loss"]
    stage: Literal["mycode", "readable"]
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _ConversionResult:
    text: str
    findings: tuple[ConversionFinding, ...]


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
    return _convert_markdown_to_mycode(value).text


def _convert_markdown_to_mycode(value: str) -> _ConversionResult:
    findings = _markdown_conversion_findings(value)
    protected: list[str] = []
    placeholder_prefix = _markdown_placeholder_prefix(value)

    def protect(replacement: str) -> str:
        protected.append(replacement)
        return f"{placeholder_prefix}{len(protected) - 1}\x00"

    # Shield whole unsupported constructs before converting code nested inside them.
    text = _protect_unsupported_markdown_blocks(value, protect)
    text = _protect_unsupported_markdown_lists(text, protect)
    text = _MARKDOWN_CODE_BLOCK_PATTERN.sub(
        lambda match: protect(f"[code]{match.group('body')}[/code]"), text
    )
    text = _MARKDOWN_INLINE_CODE_PATTERN.sub(
        lambda match: protect(f"[code]{match.group(1)}[/code]"), text
    )
    text = _protect_markdown_links(text, placeholder_prefix, protected)
    text = _protect_markdown_bare_urls(text, placeholder_prefix, protected)
    text = _protect_markdown_escapes(text, placeholder_prefix, protected)
    text = _convert_markdown_emphasis(text)
    text = _convert_markdown_blockquotes(text)
    text = _convert_markdown_lists(text)

    for index in reversed(range(len(protected))):
        text = text.replace(f"{placeholder_prefix}{index}\x00", protected[index])
    return _ConversionResult(_tidy_text(text), findings)


def _markdown_placeholder_prefix(value: str) -> str:
    attempt = 0
    while True:
        prefix = f"\x00HF_MCP_MARKDOWN_{attempt}_"
        if prefix not in value:
            return prefix
        attempt += 1


def _protect_unsupported_markdown_blocks(text: str, protect: Callable[[str], str]) -> str:
    # These constructs are intentionally preserved whole until their semantics
    # are part of the supported conversion subset.
    def protect_table(match: re.Match[str]) -> str:
        return protect(match.group(0))

    text = _MARKDOWN_TILDE_FENCE_PATTERN.sub(protect_table, text)
    text = _MARKDOWN_UNSUPPORTED_BLOCK_LINE_PATTERN.sub(protect_table, text)
    output: list[str] = []
    cursor = 0
    for start, end in _iter_markdown_table_ranges(text):
        output.append(text[cursor:start])
        output.append(protect(text[start:end]))
        cursor = end
    output.append(text[cursor:])
    return "".join(output)


def _iter_markdown_table_ranges(text: str) -> Iterator[tuple[int, int]]:
    lines = text.splitlines(keepends=True)
    offset = 0
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            offset += len(lines[index])
            index += 1
            continue
        start = offset
        end = index + 1
        offset += len(lines[index])
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            offset += len(lines[end])
            end += 1
        yield start, offset
        index = end


def _is_flat_unordered_list(matches: list[re.Match[str]]) -> bool:
    return all(
        not match.group("indent")
        and match.group("marker") in ("-", "*")
        and not re.match(r"\[[ xX]\](?:\s|$)", match.group("body"))
        for match in matches
    )


def _protect_unsupported_markdown_lists(text: str, protect: Callable[[str], str]) -> str:
    output: list[str] = []
    cursor = 0
    for start, end, matches in _iter_markdown_list_groups(text):
        output.append(text[cursor:start])
        group = text[start:end]
        output.append(group if _is_flat_unordered_list(matches) else protect(group))
        cursor = end
    output.append(text[cursor:])
    return "".join(output)


def _iter_markdown_list_groups(
    text: str,
) -> Iterator[tuple[int, int, list[re.Match[str]]]]:
    lines = text.splitlines(keepends=True)
    offset = 0
    index = 0
    while index < len(lines):
        first = _MARKDOWN_LIST_LINE_PATTERN.match(lines[index].rstrip("\r\n"))
        if first is None:
            offset += len(lines[index])
            index += 1
            continue
        start = offset
        end = index + 1
        matches = [first]
        offset += len(lines[index])
        while end < len(lines):
            match = _MARKDOWN_LIST_LINE_PATTERN.match(lines[end].rstrip("\r\n"))
            if match is None:
                break
            matches.append(match)
            offset += len(lines[end])
            end += 1
        yield start, offset, matches
        index = end


def _protect_markdown_links(text: str, placeholder_prefix: str, protected: list[str]) -> str:
    output: list[str] = []
    cursor = 0
    for index, open_bracket, label_end, destination_end in _iter_markdown_links(text):
        image = index < open_bracket
        if destination_end is None:
            output.append(text[cursor:index])
            protected.append(text[index:])
            output.append(f"{placeholder_prefix}{len(protected) - 1}\x00")
            cursor = len(text)
            break

        destination = text[label_end + 2:destination_end]
        whole_end = destination_end + 1
        if any(character.isspace() for character in destination):
            # Optional titles and other whitespace-bearing forms stay literal.
            replacement = text[index:whole_end]
        else:
            label = text[open_bracket + 1:label_end]
            rendered = f"[img]{destination}[/img]" if image else (
                f"[url={destination}]{_convert_markdown_inline(label)}[/url]"
            )
            replacement = rendered

        output.append(text[cursor:index])
        protected.append(replacement)
        output.append(f"{placeholder_prefix}{len(protected) - 1}\x00")
        cursor = whole_end
    output.append(text[cursor:])
    return "".join(output)


def _protect_markdown_bare_urls(
    text: str,
    placeholder_prefix: str,
    protected: list[str],
) -> str:
    def protect(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"{placeholder_prefix}{len(protected) - 1}\x00"

    return _MARKDOWN_BARE_URL_PATTERN.sub(protect, text)


def _iter_markdown_links(text: str) -> Iterator[tuple[int, int, int, int | None]]:
    index = 0
    while index < len(text):
        image = text.startswith("![", index)
        opening = index + 1 if image else index
        if _markdown_character_is_escaped(text, opening) or text[opening:opening + 1] != "[":
            index += 1
            continue
        label_end = _markdown_matching_bracket(text, opening)
        if label_end is None or label_end + 1 >= len(text) or text[label_end + 1] != "(":
            index += 1
            continue
        destination_end = _markdown_destination_end(text, label_end + 1)
        yield index, opening, label_end, destination_end
        if destination_end is None:
            return
        index = destination_end + 1


def _markdown_matching_bracket(text: str, opening: int) -> int | None:
    depth = 0
    index = opening
    while index < len(text):
        character = text[index]
        if character == "\\":
            run_end = index
            while run_end < len(text) and text[run_end] == "\\":
                run_end += 1
            if (run_end - index) % 2 and run_end < len(text) and text[run_end] in r"!\"#$%&'()*+,-./:;<=>?@[\]^_`{|}~":
                index = run_end + 1
                continue
            index = run_end
            continue
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _markdown_character_is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _markdown_destination_end(text: str, opening: int) -> int | None:
    depth = 1
    index = opening + 1
    while index < len(text):
        character = text[index]
        if character == "\\":
            run_end = index
            while run_end < len(text) and text[run_end] == "\\":
                run_end += 1
            if (run_end - index) % 2 and run_end < len(text):
                index = run_end + 1
                continue
            index = run_end
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _protect_markdown_escapes(text: str, placeholder_prefix: str, protected: list[str]) -> str:
    output: list[str] = []
    cursor = 0
    for start, end, escaped_character in _markdown_escape_runs(text):
        output.append(text[cursor:start])
        run_length = end - start
        output.append("\\" * (run_length // 2))
        if escaped_character is not None:
            protected.append(text[escaped_character])
            output.append(f"{placeholder_prefix}{len(protected) - 1}\x00")
            cursor = escaped_character + 1
        else:
            if run_length % 2:
                output.append("\\")
            cursor = end
    output.append(text[cursor:])
    return "".join(output)


def _markdown_escape_runs(text: str) -> Iterator[tuple[int, int, int | None]]:
    index = 0
    while index < len(text):
        if text[index] != "\\":
            index += 1
            continue
        end = index
        while end < len(text) and text[end] == "\\":
            end += 1
        escaped_character = (
            end
            if (end - index) % 2 and end < len(text) and text[end] in r"!\"#$%&'()*+,-./:;<=>?@[\]^_`{|}~"
            else None
        )
        yield index, end, escaped_character
        index = escaped_character + 1 if escaped_character is not None else end


def _convert_markdown_inline(value: str) -> str:
    protected: list[str] = []
    prefix = _markdown_placeholder_prefix(value)
    text = _protect_markdown_escapes(value, prefix, protected)
    text = _convert_markdown_emphasis(text)
    for index, replacement in enumerate(protected):
        text = text.replace(f"{prefix}{index}\x00", replacement)
    return text


def _convert_markdown_emphasis(
    text: str,
    *,
    on_unmatched: Callable[[int, int], None] | None = None,
) -> str:
    delimiters = ("***", "___", "**", "__", "~~", "*", "_")

    def convert(start: int, end: int) -> str:
        output: list[str] = []
        index = start
        while index < end:
            marker = next((item for item in delimiters if text.startswith(item, index)), None)
            if marker is None:
                output.append(text[index])
                index += 1
                continue
            run_end = index + len(marker)
            while run_end < end and text[run_end] == marker[0]:
                run_end += 1
            if run_end - index != len(marker):
                output.append(text[index:run_end])
                index = run_end
                continue
            if marker.startswith("_") and index > start and (text[index - 1].isalnum() or text[index - 1] == "_"):
                output.append(marker)
                index = run_end
                continue
            if run_end >= end or text[run_end].isspace():
                output.append(marker)
                index = run_end
                continue

            closing = _find_markdown_emphasis_close(text, marker, run_end, end)
            if closing is None or closing == run_end:
                if closing is None and on_unmatched is not None:
                    on_unmatched(index, run_end)
                output.append(marker)
                index = run_end
                continue
            inner = convert(run_end, closing)
            if marker in ("***", "___"):
                output.append(f"[b][i]{inner}[/i][/b]")
            elif marker in ("**", "__"):
                output.append(f"[b]{inner}[/b]")
            elif marker == "~~":
                output.append(f"[s]{inner}[/s]")
            else:
                output.append(f"[i]{inner}[/i]")
            index = closing + len(marker)
        return "".join(output)

    return convert(0, len(text))


def _find_markdown_emphasis_close(text: str, marker: str, start: int, end: int) -> int | None:
    index = start
    while index < end:
        found = text.find(marker, index, end)
        if found < 0:
            return None
        run_start = found
        while run_start > start and text[run_start - 1] == marker[0]:
            run_start -= 1
        run_end = found + len(marker)
        while run_end < end and text[run_end] == marker[0]:
            run_end += 1
        if run_end - run_start == len(marker) and found == run_start:
            if marker.startswith("_") and run_end < end and (text[run_end].isalnum() or text[run_end] == "_"):
                index = run_end
                continue
            if found == start or text[found - 1].isspace():
                index = run_end
                continue
            return found
        index = run_end
    return None


def format_write_text(value: str, message_format: MessageFormat) -> str:
    if message_format == "mycode":
        return value
    return markdown_to_mycode(value)


def decode_double_quote_entities(value: str) -> str:
    return _DOUBLE_QUOTE_ENTITY_PATTERN.sub('"', value)


def analyze_conversion(value: str, message_format: MessageFormat) -> tuple[ConversionFinding, ...]:
    if message_format == "markdown":
        return _convert_markdown_to_mycode(value).findings
    return _mycode_projection_findings(value)


def _markdown_conversion_findings(value: str) -> tuple[ConversionFinding, ...]:
    findings: list[ConversionFinding] = []
    code_findings: list[ConversionFinding] = []
    literal_ranges: list[tuple[int, int]] = []
    masked = list(value)
    readable_mask = list(value)

    def add(code: str, start: int, end: int, kind: Literal["unsupported", "loss"] = "unsupported") -> None:
        findings.append(ConversionFinding(code, kind, "mycode", start, end))

    def mask(start: int, end: int) -> None:
        for position in range(start, end):
            if masked[position] not in "\r\n":
                masked[position] = " "

    def mask_readable(start: int, end: int) -> None:
        for position in range(start, end):
            if readable_mask[position] not in "\r\n":
                readable_mask[position] = " "

    # These are the same code constructs stashed by the Markdown converter.
    for match in _MARKDOWN_CODE_BLOCK_PATTERN.finditer(value):
        if match.group("language"):
            code_findings.append(
                ConversionFinding(
                    "fence_language_loss",
                    "loss",
                    "mycode",
                    match.start("language"),
                    match.end("language"),
                )
            )
        mask(match.start(), match.end())
        mask_readable(match.start(), match.end())
    for match in _MARKDOWN_INLINE_CODE_PATTERN.finditer("".join(masked)):
        code_findings.append(
            ConversionFinding(
                "inline_code_block_conversion",
                "loss",
                "mycode",
                match.start(),
                match.end(),
            )
        )
        mask(match.start(), match.end())
        mask_readable(match.start(), match.end())

    text = "".join(masked)

    # Unsupported fenced code using tildes is protected by the converter as a whole.
    for match in _MARKDOWN_TILDE_FENCE_PATTERN.finditer(text):
        add("unsupported_fence", match.start(), match.end())
        literal_ranges.append((match.start(), match.end()))
        mask(match.start(), match.end())
    text = "".join(masked)

    for match in _MARKDOWN_UNSUPPORTED_BLOCK_LINE_PATTERN.finditer(text):
        add("heading" if match.group("heading") else "horizontal_rule", match.start(), match.end())
        literal_ranges.append((match.start(), match.end()))
        mask(match.start(), match.end())

    # Pipe rows are the same table ranges protected by the converter.
    for start, end in _iter_markdown_table_ranges(text):
        add("table", start, end)
        literal_ranges.append((start, end))
        for position in range(start, end):
            if masked[position] not in "\r\n":
                masked[position] = " "

    # List shape is the same group iterator consumed by the output pass.
    text = "".join(masked)
    for start, end, matches in _iter_markdown_list_groups(text):
        if not _is_flat_unordered_list(matches):
            if any(re.match(r"\[[ xX]\](?:\s|$)", item.group("body")) for item in matches):
                code = "task_list"
            elif any(item.group("indent") for item in matches):
                code = "nested_list"
            else:
                code = "ordered_list"
            add(code, start, end)
            literal_ranges.append((start, end))
            mask(start, end)

    # Link recognition is shared with the output pass. Preserve the same portions
    # from delimiter recognition that the converter shields or leaves literal.
    text = "".join(masked)
    for start, opening, label_end, destination_end in _iter_markdown_links(text):
        if destination_end is None:
            literal_ranges.append((start, len(masked)))
            for position in range(start, len(masked)):
                if masked[position] not in "\r\n":
                    masked[position] = " "
            continue
        end = destination_end + 1
        destination = text[label_end + 2:destination_end]
        has_title = any(character.isspace() for character in destination)
        is_image = start < opening
        mask_readable(opening, opening + 1)
        mask_readable(label_end, label_end + 1)
        if has_title:
            add("link_title", start, end)
            literal_ranges.append((start, end))
            for position in range(start, end):
                if masked[position] not in "\r\n":
                    masked[position] = " "
        else:
            if is_image and text[opening + 1:label_end]:
                add("image_alt_loss", start, end, "loss")
                literal_ranges.append((opening + 1, label_end))
                mask_readable(opening + 1, label_end)
            literal_ranges.append((label_end + 1, end))
            for position in range(label_end + 1, end):
                if masked[position] not in "\r\n":
                    masked[position] = " "

    for match in _MARKDOWN_BARE_URL_PATTERN.finditer("".join(masked)):
        literal_ranges.append((match.start(), match.end()))
        for position in range(match.start(), match.end()):
            if masked[position] not in "\r\n":
                masked[position] = " "

    # Escaped delimiter characters are shielded by the same escape-run parser
    # used before the converter's emphasis pass.
    for _, _, escaped_character in _markdown_escape_runs("".join(masked)):
        if escaped_character is not None:
            masked[escaped_character] = " "
    _convert_markdown_emphasis(
        "".join(masked),
        on_unmatched=lambda start, end: add(
            "unmatched_markdown_delimiter", start, end
        ),
    )

    findings.extend(
        finding
        for finding in code_findings
        if not any(
            finding.start < end and start < finding.end
            for start, end in literal_ranges
        )
    )
    for _, opening, label_end, destination_end in _iter_markdown_links(value):
        if destination_end is not None:
            mask_readable(opening, opening + 1)
            mask_readable(label_end, label_end + 1)
    findings.extend(
        _readable_projection_findings("".join(readable_mask), code_already_masked=True)
    )

    return _sorted_findings(findings)


def _mycode_projection_findings(value: str) -> tuple[ConversionFinding, ...]:
    return _readable_projection_findings(value)


def _readable_projection_findings(
    value: str,
    *,
    code_already_masked: bool = False,
) -> tuple[ConversionFinding, ...]:
    findings: list[ConversionFinding] = []
    masked = list(value)

    def mask(start: int, end: int) -> None:
        for position in range(start, end):
            if masked[position] not in "\r\n":
                masked[position] = " "

    if not code_already_masked:
        for match in _CODE_BLOCK_PATTERN.finditer(value):
            mask(match.start(), match.end())
    text = "".join(masked)
    known_tags = set(TAG_RULES) | {"url", "img", "uimg", "quote", "list", "code", "php"}
    for match in _MYCODE_TAG_PATTERN.finditer(text):
        name = match.group("name").lower()
        if name not in known_tags:
            findings.append(ConversionFinding("unknown_mycode_tag", "unsupported", "readable", match.start(), match.end()))

    spoiler_stack: list[re.Match[str]] = []
    for match in _SPOILER_TAG_PATTERN.finditer(text):
        if not match.group("close"):
            spoiler_stack.append(match)
        elif spoiler_stack:
            opening = spoiler_stack.pop()
            findings.append(ConversionFinding("spoiler_plaintext_projection", "loss", "readable", opening.start(), match.end()))
    return _sorted_findings(findings)


def _sorted_findings(findings: list[ConversionFinding]) -> tuple[ConversionFinding, ...]:
    return tuple(sorted(set(findings), key=lambda item: (item.start, item.end, item.stage, item.code)))


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
    lines = text.split("\n")
    converted: list[str] = []
    index = 0

    while index < len(lines):
        first = _MARKDOWN_LIST_LINE_PATTERN.match(lines[index])
        if first is None:
            converted.append(lines[index])
            index += 1
            continue

        end = index + 1
        matches = [first]
        while end < len(lines):
            match = _MARKDOWN_LIST_LINE_PATTERN.match(lines[end])
            if match is None:
                break
            matches.append(match)
            end += 1

        if _is_flat_unordered_list(matches):
            items = [match.group("body").strip() for match in matches]
            converted.append("[list]\n" + "\n".join(f"[*] {item}" for item in items) + "\n[/list]")
        else:
            converted.extend(lines[index:end])
        index = end
    return "\n".join(converted)


__all__ = [
    "BodyFormat",
    "ConversionFinding",
    "MessageFormat",
    "TAG_RULES",
    "coerce_body_format",
    "coerce_message_format",
    "analyze_conversion",
    "decode_double_quote_entities",
    "format_body_text",
    "format_write_text",
    "markdown_to_mycode",
]
