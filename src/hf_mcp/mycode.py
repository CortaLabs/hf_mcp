from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Iterator, Literal, cast

BodyFormat = Literal["raw", "clean", "markdown"]
MessageFormat = Literal["mycode", "markdown"]

_VALID_BODY_FORMATS: frozenset[str] = frozenset({"raw", "clean", "markdown"})
_VALID_MESSAGE_FORMATS: frozenset[str] = frozenset({"mycode", "markdown"})
_CODE_BLOCK_PATTERN = re.compile(
    r"\[(code|php)\](.*?)\[/\1\]", re.IGNORECASE | re.DOTALL
)
_MARKDOWN_CODE_BLOCK_PATTERN = re.compile(
    r"```(?P<language>[a-zA-Z0-9_-]+)?\n?(?P<body>.*?)```", re.DOTALL
)
_MARKDOWN_INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+)`")
_MARKDOWN_BARE_URL_PATTERN = re.compile(r"https?://[^\s<>\x00]+", re.IGNORECASE)
_MARKDOWN_LIST_LINE_PATTERN = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-*]|\d+[.)])\s+(?P<body>.*)$"
)
_MARKDOWN_ORDERED_MARKER_PATTERN = re.compile(r"\d+[.)]")
_MARKDOWN_TILDE_FENCE_PATTERN = re.compile(
    r"(?m)^ {0,3}~{3,}[^\n]*(?:\n[\s\S]*?^ {0,3}~{3,}[^\n]*|\Z)"
)
_MARKDOWN_HEADING_PATTERN = re.compile(
    r"^ {0,3}#{1,6}[ \t]+(?P<text>.*?)(?:[ \t]+#+)?[ \t]*$"
)
_MARKDOWN_RULE_PATTERN = re.compile(
    r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$"
)
_QUOTE_PATTERN = re.compile(
    r"\[quote(?P<attrs>[^\]]*)\](?P<body>.*?)\[/quote\]", re.IGNORECASE | re.DOTALL
)
_LIST_PATTERN = re.compile(
    r"\[list(?:=[^\]]*)?\](?P<body>.*?)\[/list\]", re.IGNORECASE | re.DOTALL
)
_URL_WITH_TARGET_PATTERN = re.compile(
    r"\[url=(?P<url>[^\]]+)\](?P<body>.*?)\[/url\]", re.IGNORECASE | re.DOTALL
)
_URL_PATTERN = re.compile(r"\[url\](?P<url>.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_IMAGE_PATTERN = re.compile(
    r"\[(?:img|uimg)\](?P<url>.*?)\[/\s*(?:img|uimg)\]", re.IGNORECASE | re.DOTALL
)
_DOUBLE_QUOTE_ENTITY_PATTERN = re.compile(r"&(quot|#34|#x22);", re.IGNORECASE)
_SPOILER_TAG_PATTERN = re.compile(
    r"\[(?P<close>/)?spoiler(?P<attrs>=[^\]]*)?\]", re.IGNORECASE
)
_MYCODE_TAG_PATTERN = re.compile(
    r"\[(?P<close>/)?(?P<name>[a-zA-Z][a-zA-Z0-9_-]*)(?:=(?P<attr>[^\]]*))?\]",
    re.DOTALL,
)
_RAW_MYCODE_TAG_PATTERN = re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9_-]*(?:=[^\]]*)?\]|\[\*\]")
_MARKDOWN_SETEXT_PATTERN = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
_STRUCTURAL_TAGS: frozenset[str] = frozenset(
    {"url", "img", "uimg", "quote", "list", "code", "php"}
)
_ESCAPABLE = r"!\"#$%&'()*+,-./:;<=>?@[\]^_`{|}~"


@dataclass(frozen=True, slots=True)
class MyCodeRule:
    markdown_prefix: str = ""
    markdown_suffix: str = ""
    clean_prefix: str = ""
    clean_suffix: str = ""
    # Regex the tag attribute must fully match; None accepts any attribute.
    attribute: str | None = None
    # A void tag has no closing tag.
    void: bool = False


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


@dataclass(slots=True)
class _MappedText:
    text: str
    source_spans: list[tuple[int, int]]

    @classmethod
    def from_source(cls, value: str) -> _MappedText:
        """Map text to its source, folding CRLF and lone CR into LF."""
        characters: list[str] = []
        spans: list[tuple[int, int]] = []
        index = 0
        while index < len(value):
            if value[index] == "\r":
                width = 2 if value.startswith("\r\n", index) else 1
                characters.append("\n")
                spans.append((index, index + width))
                index += width
            else:
                characters.append(value[index])
                spans.append((index, index + 1))
                index += 1
        return cls("".join(characters), spans)

    def source_span(self, start: int, end: int) -> tuple[int, int]:
        spans = self.source_spans[start:end]
        if not spans:
            return 0, 0
        return min(span[0] for span in spans), max(span[1] for span in spans)

    def replace(self, start: int, end: int, replacement: str) -> None:
        source_span = self.source_span(start, end)
        self.text = self.text[:start] + replacement + self.text[end:]
        self.source_spans[start:end] = [source_span] * len(replacement)


class _Shield:
    """The one protection mechanism: swap text for an inert token, restore it last."""

    def __init__(self, source: str, label: str) -> None:
        attempt = 0
        while f"\x00HF_MCP_{label}_{attempt}_" in source:
            attempt += 1
        self._prefix = f"\x00HF_MCP_{label}_{attempt}_"
        self._items: list[str] = []

    def token(self, replacement: str) -> str:
        self._items.append(replacement)
        return f"{self._prefix}{len(self._items) - 1}\x00"

    def restore(self, text: str) -> str:
        # Later items may embed earlier tokens, so unwind in reverse.
        for index in reversed(range(len(self._items))):
            text = text.replace(f"{self._prefix}{index}\x00", self._items[index])
        return text


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
    "css": MyCodeRule(attribute=r"[0-9]+"),
    "hr": MyCodeRule(
        markdown_prefix="\n---\n", clean_prefix="\n---\n", attribute="", void=True
    ),
}


def _coerce_choice(
    raw_value: object, valid_values: frozenset[str], *, label: str, field_name: str
) -> str:
    if not isinstance(raw_value, str):
        raise ValueError(f"`{field_name}` must be a string.")
    value = raw_value.strip()
    if value not in valid_values:
        valid = ", ".join(sorted(valid_values))
        raise ValueError(f"Unknown {label} format '{value}'. Valid formats: {valid}.")
    return value


def coerce_body_format(raw_value: object, *, field_name: str) -> BodyFormat:
    return cast(
        BodyFormat,
        _coerce_choice(
            raw_value, _VALID_BODY_FORMATS, label="body", field_name=field_name
        ),
    )


def coerce_message_format(raw_value: object, *, field_name: str) -> MessageFormat:
    return cast(
        MessageFormat,
        _coerce_choice(
            raw_value, _VALID_MESSAGE_FORMATS, label="message", field_name=field_name
        ),
    )


def format_body_text(value: str, body_format: BodyFormat) -> str:
    if body_format == "raw":
        return value

    shield = _Shield(value, "PROTECTED_CODE")

    def _stash_code(match: re.Match[str]) -> str:
        code = match.group(2)
        if body_format == "markdown":
            longest_fence = max(
                (len(run) for run in re.findall(r"`+", code)), default=0
            )
            fence = "`" * max(3, longest_fence + 1)
            block = fence + "\n" + code + "\n" + fence
            return "\n" + shield.token(block) + "\n"
        return shield.token(code)

    text = _CODE_BLOCK_PATTERN.sub(_stash_code, value)
    text = _protect_malformed_markup(text, shield)
    text = _convert_spoilers(text)
    text = _convert_quotes(text, body_format)
    text = _convert_lists(text, body_format)
    text = _convert_links_and_images(text, body_format)
    text = _apply_tag_rules(text, body_format)
    # Some upstream payloads carry doubled escapes; unfold them in readable
    # text only. Shielded code and the raw/write paths keep backslashes as-is.
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    # HF HTML-escapes angle brackets on readback; undo only those, outside code.
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    return shield.restore(_tidy_text(text))


def _protect_malformed_markup(text: str, shield: _Shield) -> str:
    output: list[str] = []
    cursor = 0
    for start, end in _malformed_markup_ranges(text):
        output.append(text[cursor:start])
        output.append(shield.token(text[start:end]))
        cursor = end
    output.append(text[cursor:])
    return "".join(output)


def _malformed_markup_ranges(text: str) -> list[tuple[int, int]]:
    stack: list[tuple[str, int]] = []
    malformed_start: int | None = None
    malformed_ranges: list[tuple[int, int]] = []

    for match in _MYCODE_TAG_PATTERN.finditer(text):
        tag_name = match.group("name").lower()
        if not match.group("close"):
            if not _is_void_tag(tag_name):
                stack.append((tag_name, match.start()))
            continue

        matching_index = next(
            (
                index
                for index in range(len(stack) - 1, -1, -1)
                if stack[index][0] == tag_name
            ),
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
        malformed_ranges.append(
            (malformed_start if malformed_start is not None else stack[0][1], len(text))
        )
    return malformed_ranges


def _is_void_tag(name: str) -> bool:
    rule = TAG_RULES.get(name)
    return rule is not None and rule.void


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
            output.append(text[cursor : match.start()])
            title = (match.group("attrs") or "")[1:].strip()
            label = (
                f"Spoiler [{title}] (plaintext; not concealed):"
                if title
                else "Spoiler (plaintext; not concealed):"
            )
            output.append(f"{label}\n")
            cursor = match.end()
        elif index in paired_closings:
            output.append(text[cursor : match.start()])
            output.append("\nEnd spoiler")
            cursor = match.end()

    output.append(text[cursor:])
    return "".join(output)


def markdown_to_mycode(value: str) -> str:
    return _convert_markdown_to_mycode(value).text


def _mask(chars: list[str], start: int, end: int) -> None:
    for position in range(start, end):
        if chars[position] not in "\r\n":
            chars[position] = " "


def _convert_markdown_to_mycode(value: str) -> _ConversionResult:
    findings: list[ConversionFinding] = []
    shield = _Shield(value, "MARKDOWN")
    mapped = _MappedText.from_source(value)
    readable_protected_spans: list[tuple[int, int]] = []

    def protect_range(start: int, end: int, replacement: str) -> None:
        mapped.replace(start, end, shield.token(replacement))

    def finding(
        code: str,
        start: int,
        end: int,
        *,
        kind: Literal["unsupported", "loss"] = "unsupported",
    ) -> None:
        findings.append(ConversionFinding(code, kind, "mycode", start, end))

    # Tilde fences and pipe tables are located with backtick fences masked, so
    # their contents never read as a table; both are emitted verbatim or as code.
    analysis_chars = list(mapped.text)
    for match in _MARKDOWN_CODE_BLOCK_PATTERN.finditer(mapped.text):
        _mask(analysis_chars, match.start(), match.end())
    protected_source_ranges: list[tuple[int, int, str]] = []
    for match in _MARKDOWN_TILDE_FENCE_PATTERN.finditer("".join(analysis_chars)):
        protected_source_ranges.append(
            (match.start(), match.end(), "unsupported_fence")
        )
        _mask(analysis_chars, match.start(), match.end())
    for start, end in _iter_markdown_table_ranges("".join(analysis_chars)):
        protected_source_ranges.append((start, end, "table_as_code"))

    for start, end, code in sorted(
        protected_source_ranges, key=lambda item: item[0], reverse=True
    ):
        source_text = mapped.text[start:end]
        source_span = mapped.source_span(start, end)
        if code == "table_as_code":
            finding(code, *source_span, kind="loss")
            readable_protected_spans.append(source_span)
            body = source_text.rstrip("\n")
            protect_range(start, start + len(body), f"[code]\n{body}\n[/code]")
        else:
            finding(code, *source_span)
            protect_range(start, end, source_text)

    for match in reversed(list(_MARKDOWN_CODE_BLOCK_PATTERN.finditer(mapped.text))):
        readable_protected_spans.append(mapped.source_span(match.start(), match.end()))
        protect_range(
            match.start(),
            match.end(),
            _code_block(_dedent_fence_body(mapped.text, match)),
        )

    # Inline code is opaque to link and emphasis parsing. Brackets cannot be
    # escaped in MyCode, so only [code] can carry them literally.
    for match in reversed(list(_MARKDOWN_INLINE_CODE_PATTERN.finditer(mapped.text))):
        source_span = mapped.source_span(match.start(), match.end())
        readable_protected_spans.append(source_span)
        code = match.group(1)
        if "[" in code or "]" in code:
            finding("inline_code_as_block", *source_span, kind="loss")
            protect_range(match.start(), match.end(), f"[code]{code}[/code]")
        else:
            protect_range(match.start(), match.end(), f"[font=monospace]{code}[/font]")

    # Link recognition runs on the code tokens, so a code span in a destination
    # is opaque rather than whitespace or a title.
    for start, opening, label_end, destination_end in reversed(
        list(_iter_markdown_links(mapped.text))
    ):
        if destination_end is None:
            protect_range(start, len(mapped.text), mapped.text[start:])
            continue
        end = destination_end + 1
        current = mapped.text
        destination = current[label_end + 2 : destination_end]
        image = start < opening
        readable_protected_spans.extend(
            (
                mapped.source_span(opening, opening + 1),
                mapped.source_span(label_end, label_end + 1),
            )
        )
        if any(character.isspace() for character in destination):
            finding("link_title", *mapped.source_span(start, end))
            protect_range(start, end, current[start:end])
            continue

        label = current[opening + 1 : label_end]
        if image:
            if label:
                finding("image_alt_loss", *mapped.source_span(start, end), kind="loss")
                readable_protected_spans.append(
                    mapped.source_span(opening + 1, label_end)
                )
            rendered = f"[img]{destination}[/img]"
        else:
            label_mapped = _MappedText(
                label, mapped.source_spans[opening + 1 : label_end].copy()
            )
            _protect_escapes(label_mapped, shield)
            _protect_mycode_tags(label_mapped, shield)

            def label_unmatched(
                s: int, e: int, spans: _MappedText = label_mapped
            ) -> None:
                finding("unmatched_markdown_delimiter", *spans.source_span(s, e))

            converted_label = _convert_markdown_emphasis(
                label_mapped.text, on_unmatched=label_unmatched
            )
            rendered = f"[url={destination}]{converted_label}[/url]"
        protect_range(start, end, rendered)

    # Raw tags first so a bare URL cannot swallow the tag text that follows it.
    _protect_mycode_tags(mapped, shield)
    for match in reversed(list(_MARKDOWN_BARE_URL_PATTERN.finditer(mapped.text))):
        protect_range(match.start(), match.end(), match.group(0))

    _protect_escapes(mapped, shield)

    def unmatched(start: int, end: int) -> None:
        finding("unmatched_markdown_delimiter", *mapped.source_span(start, end))

    text = _convert_markdown_emphasis(mapped.text, on_unmatched=unmatched)
    text = _convert_markdown_blocks(text)
    findings.extend(
        _readable_projection_findings(value, protected_spans=readable_protected_spans)
    )
    # Tidy before restoring so shielded code keeps its blank lines and spaces.
    return _ConversionResult(
        shield.restore(_tidy_text(text)), _sorted_findings(findings)
    )


def _dedent_fence_body(text: str, fence: re.Match[str]) -> str:
    """Drop the opening fence's own indent from each body line (fence in a list item)."""
    line_start = text.rfind("\n", 0, fence.start()) + 1
    indent = len(text[line_start : fence.start()])
    if indent == 0 or text[line_start : fence.start()].strip():
        return fence.group("body")
    lines = fence.group("body").splitlines(keepends=True)
    return "".join(
        line[min(indent, len(line) - len(line.lstrip(" \t"))) :] for line in lines
    )


def _code_block(body: str) -> str:
    newline = "" if body.endswith("\n") else "\n"
    return f"[code]\n{body}{newline}[/code]"


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


def _iter_markdown_links(text: str) -> Iterator[tuple[int, int, int, int | None]]:
    pairs = _markdown_bracket_pairs(text)
    index = 0
    while index < len(text):
        image = text.startswith("![", index)
        opening = index + 1 if image else index
        if (
            _markdown_character_is_escaped(text, opening)
            or text[opening : opening + 1] != "["
        ):
            index += 1
            continue
        label_end = pairs.get(opening)
        if (
            label_end is None
            or label_end + 1 >= len(text)
            or text[label_end + 1] != "("
        ):
            index += 1
            continue
        destination_end = _markdown_destination_end(text, label_end + 1)
        yield index, opening, label_end, destination_end
        if destination_end is None:
            return
        index = destination_end + 1


def _markdown_bracket_pairs(text: str) -> dict[int, int]:
    """Map each matched `[` to its `]` in one pass, skipping escaped brackets."""
    pairs: dict[int, int] = {}
    stack: list[int] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\\":
            run_end = index
            while run_end < len(text) and text[run_end] == "\\":
                run_end += 1
            escapes = (run_end - index) % 2 and run_end < len(text)
            index = run_end + 1 if escapes and text[run_end] in _ESCAPABLE else run_end
            continue
        if character == "[":
            stack.append(index)
        elif character == "]" and stack:
            pairs[stack.pop()] = index
        index += 1
    return pairs


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
            if (end - index) % 2 and end < len(text) and text[end] in _ESCAPABLE
            else None
        )
        yield index, end, escaped_character
        index = escaped_character + 1 if escaped_character is not None else end


def _protect_mycode_tags(mapped: _MappedText, shield: _Shield) -> None:
    """Keep raw MyCode tags, including `[*]`, away from the emphasis scanner."""
    for match in reversed(list(_RAW_MYCODE_TAG_PATTERN.finditer(mapped.text))):
        if not _markdown_character_is_escaped(mapped.text, match.start()):
            mapped.replace(match.start(), match.end(), shield.token(match.group(0)))


def _protect_escapes(mapped: _MappedText, shield: _Shield) -> None:
    """Replace each escaped character with a token that carries the bare character."""
    for start, end, escaped_character in reversed(
        list(_markdown_escape_runs(mapped.text))
    ):
        run_length = end - start
        replacement = "\\" * (run_length // 2)
        if escaped_character is not None:
            replacement += shield.token(mapped.text[escaped_character])
            end = escaped_character + 1
        elif run_length % 2:
            replacement += "\\"
        mapped.replace(start, end, replacement)


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
            marker = next(
                (item for item in delimiters if text.startswith(item, index)), None
            )
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
            if (
                marker.startswith("_")
                and index > start
                and (text[index - 1].isalnum() or text[index - 1] == "_")
            ):
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


def _find_markdown_emphasis_close(
    text: str, marker: str, start: int, end: int
) -> int | None:
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
            if (
                marker.startswith("_")
                and run_end < end
                and (text[run_end].isalnum() or text[run_end] == "_")
            ):
                index = run_end
                continue
            if found == start or text[found - 1].isspace():
                index = run_end
                continue
            return found
        index = run_end
    return None


def _convert_markdown_blocks(text: str) -> str:
    """Line-level constructs: blockquotes, headings, rules and lists."""
    lines = text.replace("\r\n", "\n").split("\n")
    converted: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        end = index + 1
        if line.startswith(">"):
            while end < len(lines) and lines[end].startswith(">"):
                end += 1
            inner = _convert_markdown_blocks(
                "\n".join(item[1:].lstrip() for item in lines[index:end])
            )
            converted.append("[quote]" + inner.strip() + "[/quote]")
        elif (heading := _MARKDOWN_HEADING_PATTERN.match(line)) and heading.group(
            "text"
        ):
            converted.append(f"[b]{heading.group('text')}[/b]")
        elif _MARKDOWN_RULE_PATTERN.match(line):
            converted.append("[hr]")
        elif (first := _MARKDOWN_LIST_LINE_PATTERN.match(line)) is not None:
            items = [first]
            extras: dict[int, list[str]] = {}
            while end < len(lines) and not _MARKDOWN_RULE_PATTERN.match(lines[end]):
                item = _MARKDOWN_LIST_LINE_PATTERN.match(lines[end])
                if item is None:
                    # An indented protected block (code fence) belongs to the item.
                    if not lines[end].startswith((" ", "\t")) or not lines[
                        end
                    ].lstrip().startswith("\x00"):
                        break
                    extras.setdefault(len(items) - 1, []).append(lines[end].strip())
                else:
                    items.append(item)
                end += 1
            converted.append(_render_markdown_list(items, extras))
        elif (
            line.strip()
            and end < len(lines)
            and _MARKDOWN_SETEXT_PATTERN.match(lines[end])
        ):
            converted.append(f"[b]{line.strip()}[/b]")
            end += 1
        else:
            converted.append(line)
        index = end
    return "\n".join(converted)


def _render_markdown_list(
    items: list[re.Match[str]], extras: dict[int, list[str]]
) -> str:
    output: list[str] = []
    stack: list[tuple[int, bool]] = []  # (indent, ordered)

    def open_list(indent: int, ordered: bool) -> None:
        output.append("[list=1]" if ordered else "[list]")
        stack.append((indent, ordered))

    for position, item in enumerate(items):
        indent = len(item.group("indent").expandtabs(4))
        ordered = (
            _MARKDOWN_ORDERED_MARKER_PATTERN.fullmatch(item.group("marker")) is not None
        )
        while stack and indent < stack[-1][0]:
            output.append("[/list]")
            stack.pop()
        if not stack:
            open_list(indent, ordered)
        elif indent >= stack[-1][0] + 2:
            open_list(indent, ordered)
        elif stack[-1][1] != ordered:
            output.append("[/list]")
            open_list(stack.pop()[0], ordered)
        output.append(f"[*]{item.group('body').strip()}")
        output.extend(extras.get(position, ()))
    output.extend("[/list]" for _ in stack)
    return "\n".join(output)


def format_write_text(value: str, message_format: MessageFormat) -> str:
    if message_format == "mycode":
        return value
    return markdown_to_mycode(value)


def decode_double_quote_entities(value: str) -> str:
    return _DOUBLE_QUOTE_ENTITY_PATTERN.sub('"', value)


def analyze_conversion(
    value: str, message_format: MessageFormat
) -> tuple[ConversionFinding, ...]:
    if message_format == "markdown":
        return _convert_markdown_to_mycode(value).findings
    return _readable_projection_findings(value)


def _is_known_tag(match: re.Match[str]) -> bool:
    name = match.group("name").lower()
    if name in _STRUCTURAL_TAGS:
        return True
    rule = TAG_RULES.get(name)
    if rule is None:
        return False
    if match.group("close") or rule.attribute is None:
        return True
    return re.fullmatch(rule.attribute, match.group("attr") or "") is not None


def _readable_projection_findings(
    value: str,
    *,
    protected_spans: tuple[tuple[int, int], ...] | list[tuple[int, int]] = (),
) -> tuple[ConversionFinding, ...]:
    findings: list[ConversionFinding] = []
    masked = list(value)

    for match in _CODE_BLOCK_PATTERN.finditer(value):
        _mask(masked, match.start(), match.end())
    for start, end in protected_spans:
        _mask(masked, start, end)
    for start, end in _malformed_markup_ranges("".join(masked)):
        _mask(masked, start, end)

    text = "".join(masked)
    for match in _MYCODE_TAG_PATTERN.finditer(text):
        if not _is_known_tag(match):
            findings.append(
                ConversionFinding(
                    "unknown_mycode_tag",
                    "unsupported",
                    "readable",
                    match.start(),
                    match.end(),
                )
            )

    spoiler_stack: list[re.Match[str]] = []
    for match in _SPOILER_TAG_PATTERN.finditer(text):
        if not match.group("close"):
            spoiler_stack.append(match)
        elif spoiler_stack:
            opening = spoiler_stack.pop()
            findings.append(
                ConversionFinding(
                    "spoiler_plaintext_projection",
                    "loss",
                    "readable",
                    opening.start(),
                    match.end(),
                )
            )
    return _sorted_findings(findings)


def _sorted_findings(
    findings: list[ConversionFinding],
) -> tuple[ConversionFinding, ...]:
    return tuple(
        sorted(
            set(findings),
            key=lambda item: (item.start, item.end, item.stage, item.code),
        )
    )


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
        if rule.void:
            replacement = (
                rule.markdown_prefix if body_format == "markdown" else rule.clean_prefix
            )
            text = re.compile(rf"\[{re.escape(tag_name)}\]", re.IGNORECASE).sub(
                replacement.replace("\\", "\\\\"), text
            )
            continue
        attribute = (
            f"=(?:{rule.attribute})" if rule.attribute is not None else r"(?:=[^\]]*)?"
        )
        pattern = re.compile(
            rf"\[{re.escape(tag_name)}{attribute}\](.*?)\[/{re.escape(tag_name)}\]",
            re.IGNORECASE | re.DOTALL,
        )
        for _ in range(20):
            updated = pattern.sub(
                lambda match: _render_rule(rule, match.group(1), body_format), text
            )
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


__all__ = [
    "BodyFormat",
    "ConversionFinding",
    "MessageFormat",
    "TAG_RULES",
    "analyze_conversion",
    "coerce_body_format",
    "coerce_message_format",
    "decode_double_quote_entities",
    "format_body_text",
    "format_write_text",
    "markdown_to_mycode",
]
