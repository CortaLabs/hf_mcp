from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Callable, Iterable, Iterator, Literal, cast

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
_CODE_OPENER_PATTERN = re.compile(r"\[(code|php)\]", re.IGNORECASE)
_CODE_CLOSER_PATTERNS: dict[str, re.Pattern[str]] = {
    "code": re.compile(r"\[/code\]", re.IGNORECASE),
    "php": re.compile(r"\[/php\]", re.IGNORECASE),
}
_QUOTE_CLOSER_PATTERN = re.compile(r"\[/quote\]", re.IGNORECASE)
_LIST_CLOSER_PATTERN = re.compile(r"\[/list\]", re.IGNORECASE)
_URL_CLOSER_PATTERN = re.compile(r"\[/url\]", re.IGNORECASE)
_IMAGE_CLOSER_PATTERN = re.compile(r"\[/\s*(?:img|uimg)\]", re.IGNORECASE)
_STRUCTURAL_TAGS: frozenset[str] = frozenset(
    {"url", "img", "uimg", "quote", "list", "code", "php"}
)
_LINE_BREAK_PATTERN = re.compile(r"\r\n?")
_NON_LINE_BREAK_PATTERN = re.compile(r"[^\r\n]")
_EMPHASIS_RUN_PATTERN = re.compile(r"\*+|_+|~+")
_ESCAPE_RUN_PATTERN = re.compile(r"\\+")
_LABEL_SPECIAL_PATTERN = re.compile(r"[\\\[\]*_~]")
_WHITESPACE_PATTERN = re.compile(r"\s")
_LINK_OPENING_PATTERN = re.compile(r"!?\[")
_BRACKET_OR_ESCAPE_PATTERN = re.compile(r"[\\\[\]]")
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
        if "\r" not in value:
            return cls(value, list(zip(range(len(value)), range(1, len(value) + 1))))
        pieces: list[str] = []
        spans: list[tuple[int, int]] = []
        cursor = 0
        for match in _LINE_BREAK_PATTERN.finditer(value):
            plain = value[cursor : match.start()]
            pieces.append(plain)
            spans.extend(
                zip(range(cursor, match.start()), range(cursor + 1, match.start() + 1))
            )
            pieces.append("\n")
            spans.append((match.start(), match.end()))
            cursor = match.end()
        pieces.append(value[cursor:])
        spans.extend(zip(range(cursor, len(value)), range(cursor + 1, len(value) + 1)))
        return cls("".join(pieces), spans)

    def source_span(self, start: int, end: int) -> tuple[int, int]:
        # Spans are ordered, so a range's first start and last end bound it.
        end = min(end, len(self.source_spans))
        if start >= end:
            return 0, 0
        return self.source_spans[start][0], self.source_spans[end - 1][1]

    def replace_many(self, edits: list[tuple[int, int, str]]) -> None:
        """Apply non-overlapping edits, given in any order, in one linear pass.

        Every edit addresses the text as it was before the call, and each
        replacement inherits the source span of the range it replaces.
        """
        if not edits:
            return
        text_parts: list[str] = []
        spans: list[tuple[int, int]] = []
        cursor = 0
        for start, end, replacement in sorted(edits, key=lambda item: item[0]):
            source_span = self.source_span(start, end)
            text_parts.append(self.text[cursor:start])
            text_parts.append(replacement)
            spans.extend(self.source_spans[cursor:start])
            spans.extend([source_span] * len(replacement))
            cursor = end
        text_parts.append(self.text[cursor:])
        spans.extend(self.source_spans[cursor:])
        self.text = "".join(text_parts)
        self.source_spans = spans


class _Shield:
    """The one protection mechanism: swap text for an inert token, restore it last."""

    def __init__(self, source: str, label: str, *, joiner: str = "_") -> None:
        # `joiner` lets a caller keep emphasis characters out of its tokens, so the
        # emphasis scanner never stops inside a token.
        attempt = 0
        while f"\x00HF{joiner}MCP{joiner}{label}{joiner}{attempt}{joiner}" in source:
            attempt += 1
        self._prefix = f"\x00HF{joiner}MCP{joiner}{label}{joiner}{attempt}{joiner}"
        self._token_pattern = re.compile(re.escape(self._prefix) + r"(\d+)\x00")
        self._items: list[str] = []

    def token(self, replacement: str) -> str:
        self._items.append(replacement)
        return f"{self._prefix}{len(self._items) - 1}\x00"

    def restore(self, text: str) -> str:
        # An item only embeds tokens minted before it, so expanding each token
        # recursively in one pass equals unwinding the items in reverse.
        def expand(match: re.Match[str]) -> str:
            index = int(match.group(1))
            if index >= len(self._items):
                return match.group(0)
            return self._token_pattern.sub(expand, self._items[index])

        return self._token_pattern.sub(expand, text)


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
    if "[" not in value and "&" not in value and "\\" not in value:
        # Every rewrite below starts from a `[`, `&` or `\`; plain text only tidies.
        return _tidy_text(value)

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

    text = _sub_matches(finditer_code_blocks(value), _stash_code, value)
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
    # Stack indices of each open tag name, so the nearest opener of a closing
    # tag is found without walking the stack.
    open_indices: dict[str, list[int]] = {}
    malformed_start: int | None = None
    malformed_ranges: list[tuple[int, int]] = []

    tag_names: dict[str, tuple[str, bool]] = {}  # raw name -> (lowercase, is void)

    for match in _finditer_closed(_MYCODE_TAG_PATTERN, text):
        raw_name = match.group("name")
        known = tag_names.get(raw_name)
        if known is None:
            lowered = raw_name.lower()
            known = tag_names[raw_name] = (lowered, _is_void_tag(lowered))
        tag_name, is_void = known
        if not match.group("close"):
            if not is_void:
                open_indices.setdefault(tag_name, []).append(len(stack))
                stack.append((tag_name, match.start()))
            continue

        indices = open_indices.get(tag_name)
        if not indices:
            if stack and malformed_start is None:
                malformed_start = stack[0][1]
            continue
        matching_index = indices[-1]

        if matching_index != len(stack) - 1:
            if malformed_start is None:
                malformed_start = stack[0][1]
        for dropped_name, _ in stack[matching_index:]:
            open_indices[dropped_name].pop()
        del stack[matching_index:]

        if malformed_start is not None and not stack:
            malformed_ranges.append((malformed_start, match.end()))
            malformed_start = None

    if stack:
        malformed_ranges.append(
            (malformed_start if malformed_start is not None else stack[0][1], len(text))
        )
    return malformed_ranges


def _finditer_closed(pattern: re.Pattern[str], text: str) -> Iterator[re.Match[str]]:
    """Scan only up to the last `]`, which every bracketed tag pattern must end on.

    A tag opener with an unterminated `[^\\]]*` attribute otherwise rescans to the
    end of the text from every `[`, which is quadratic on repeated openers. No
    match can end past the last `]`, so bounding the scan never changes a match.
    """
    return pattern.finditer(text, 0, text.rfind("]") + 1)


def finditer_paired(
    pattern: re.Pattern[str], closer: re.Pattern[str], text: str
) -> Iterator[re.Match[str]]:
    """Match an opener-to-closer pattern without rescanning for missing closers.

    A lazy `opener(.*?)closer` pattern retries every opener that no closer
    follows by scanning to the end of the text, which is quadratic on repeated
    openers. No match can end past the last closer, so bounding the scan there
    never changes a match.
    """
    last_closer_end = 0
    for last in closer.finditer(text):
        last_closer_end = last.end()
    return pattern.finditer(text, 0, last_closer_end)


def finditer_code_blocks(text: str) -> Iterator[re.Match[str]]:
    """Match `[code]...[/code]` and `[php]...[/php]` blocks in linear time.

    The block pattern pairs an opener with the closer of its own tag, so the
    bound `finditer_paired` uses (the last closer of either tag) lets every
    `[code]` opener rescan to the end of a text that only closes `[php]`. Each
    opener is instead tried only while a closer of its own tag still follows it,
    which never changes a match: past that point the pattern cannot match.
    """
    last_closer_start: dict[str, int] = {}
    for tag, closer in _CODE_CLOSER_PATTERNS.items():
        for last in closer.finditer(text):
            last_closer_start[tag] = last.start()
    position = 0
    while (opener := _CODE_OPENER_PATTERN.search(text, position)) is not None:
        position = opener.end()
        if last_closer_start.get(opener.group(1).lower(), -1) < position:
            continue
        match = _CODE_BLOCK_PATTERN.match(text, opener.start())
        if match is not None:
            position = match.end()
            yield match


def _sub_paired(
    pattern: re.Pattern[str],
    closer: re.Pattern[str],
    replace: Callable[[re.Match[str]], str],
    text: str,
) -> str:
    """`pattern.sub(replace, text)` built on `finditer_paired`."""
    return _sub_matches(finditer_paired(pattern, closer, text), replace, text)


def _sub_matches(
    matches: Iterable[re.Match[str]],
    replace: Callable[[re.Match[str]], str],
    text: str,
) -> str:
    """Replace every match of `matches` in `text` with `replace(match)`."""
    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor : match.start()])
        pieces.append(replace(match))
        cursor = match.end()
    if not pieces:
        return text
    pieces.append(text[cursor:])
    return "".join(pieces)


def _is_void_tag(name: str) -> bool:
    rule = TAG_RULES.get(name)
    return rule is not None and rule.void


def _convert_spoilers(text: str) -> str:
    matches = list(_finditer_closed(_SPOILER_TAG_PATTERN, text))
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


def _masked(text: str, ranges: Iterable[tuple[int, int]]) -> str:
    """Blank every character in `ranges` except line breaks, keeping all offsets."""
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(ranges):
        if end <= cursor:
            continue
        start = max(start, cursor)
        pieces.append(text[cursor:start])
        pieces.append(_NON_LINE_BREAK_PATTERN.sub(" ", text[start:end]))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _convert_markdown_to_mycode(value: str) -> _ConversionResult:
    findings: list[ConversionFinding] = []
    shield = _Shield(value, "MD", joiner="-")
    mapped = _MappedText.from_source(value)
    readable_protected_spans: list[tuple[int, int]] = []

    pending_edits: list[tuple[int, int, str]] = []

    def protect_range(start: int, end: int, replacement: str) -> None:
        # Each phase walks its matches last-to-first against one snapshot of the
        # text; the edits land together so a phase costs one pass, not one per match.
        pending_edits.append((start, end, shield.token(replacement)))

    def apply_protected() -> None:
        mapped.replace_many(pending_edits)
        pending_edits.clear()

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
    without_code = _masked(
        mapped.text,
        (m.span() for m in _MARKDOWN_CODE_BLOCK_PATTERN.finditer(mapped.text)),
    )
    protected_source_ranges: list[tuple[int, int, str]] = []
    fence_spans: list[tuple[int, int]] = []
    for match in _MARKDOWN_TILDE_FENCE_PATTERN.finditer(without_code):
        protected_source_ranges.append(
            (match.start(), match.end(), "unsupported_fence")
        )
        fence_spans.append(match.span())
    for start, end in _iter_markdown_table_ranges(_masked(without_code, fence_spans)):
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
    apply_protected()

    fences = list(_MARKDOWN_CODE_BLOCK_PATTERN.finditer(mapped.text))
    fence_line_starts = _line_starts(mapped.text, [m.start() for m in fences])
    for match, line_start in reversed(list(zip(fences, fence_line_starts))):
        readable_protected_spans.append(mapped.source_span(match.start(), match.end()))
        protect_range(
            match.start(),
            match.end(),
            _code_block(_dedent_fence_body(mapped.text, match, line_start)),
        )
    apply_protected()

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
    apply_protected()

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
        if _WHITESPACE_PATTERN.search(destination):
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
        elif not _LABEL_SPECIAL_PATTERN.search(label):
            # Nothing in the label is an escape, tag or emphasis, so it passes through.
            rendered = f"[url={destination}]{label}[/url]"
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
    apply_protected()

    # Raw tags first so a bare URL cannot swallow the tag text that follows it.
    _protect_mycode_tags(mapped, shield)
    for match in reversed(list(_MARKDOWN_BARE_URL_PATTERN.finditer(mapped.text))):
        protect_range(match.start(), match.end(), match.group(0))
    apply_protected()

    _protect_escapes(mapped, shield)

    def unmatched(start: int, end: int) -> None:
        finding("unmatched_markdown_delimiter", *mapped.source_span(start, end))

    text = _convert_markdown_emphasis(mapped.text, on_unmatched=unmatched)

    def blockquote_truncated() -> None:
        # Block conversion runs after emphasis rewriting, so the line has no
        # source offset; the finding covers the whole message.
        finding("blockquote_depth_truncated", 0, len(value), kind="loss")

    text = _convert_markdown_blocks(text, on_truncated=blockquote_truncated)
    findings.extend(
        _readable_projection_findings(value, protected_spans=readable_protected_spans)
    )
    # Tidy before restoring so shielded code keeps its blank lines and spaces.
    return _ConversionResult(
        shield.restore(_tidy_text(text)), _sorted_findings(findings)
    )


def _line_starts(text: str, positions: list[int]) -> list[int]:
    """Start of the line holding each ascending position, in one forward sweep."""
    starts: list[int] = []
    line_start = 0
    scanned = 0
    for position in positions:
        newline = text.rfind("\n", scanned, position)
        if newline >= 0:
            line_start = newline + 1
        scanned = position
        starts.append(line_start)
    return starts


def _dedent_fence_body(text: str, fence: re.Match[str], line_start: int) -> str:
    """Drop the opening fence's own indent from each body line (fence in a list item)."""
    indent = fence.start() - line_start
    # A non-space just before the fence settles it without copying the whole prefix.
    if indent == 0 or not text[fence.start() - 1].isspace():
        return fence.group("body")
    if text[line_start : fence.start()].strip():
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
    if "](" not in text:
        return  # a link needs its label to close straight into a destination
    pairs = _markdown_bracket_pairs(text)
    index = 0
    while (candidate := _LINK_OPENING_PATTERN.search(text, index)) is not None:
        index = candidate.start()
        image = text.startswith("![", index)
        opening = index + 1 if image else index
        if _markdown_character_is_escaped(text, opening):
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
    while (special := _BRACKET_OR_ESCAPE_PATTERN.search(text, index)) is not None:
        index = special.start()
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
    if index == 0 or text[index - 1] != "\\":
        return False
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
    for run in _ESCAPE_RUN_PATTERN.finditer(text):
        index, end = run.span()
        escaped_character = (
            end
            if (end - index) % 2 and end < len(text) and text[end] in _ESCAPABLE
            else None
        )
        yield index, end, escaped_character


def _protect_mycode_tags(mapped: _MappedText, shield: _Shield) -> None:
    """Keep raw MyCode tags, including `[*]`, away from the emphasis scanner."""
    edits: list[tuple[int, int, str]] = []
    for match in reversed(list(_finditer_closed(_RAW_MYCODE_TAG_PATTERN, mapped.text))):
        if not _markdown_character_is_escaped(mapped.text, match.start()):
            edits.append((match.start(), match.end(), shield.token(match.group(0))))
    mapped.replace_many(edits)


def _protect_escapes(mapped: _MappedText, shield: _Shield) -> None:
    """Replace each escaped character with a token that carries the bare character."""
    edits: list[tuple[int, int, str]] = []
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
        edits.append((start, end, replacement))
    mapped.replace_many(edits)


def _convert_markdown_emphasis(
    text: str,
    *,
    on_unmatched: Callable[[int, int], None] | None = None,
) -> str:
    delimiters = ("***", "___", "**", "__", "~~", "*", "_")

    def convert(start: int, end: int) -> str:
        output: list[str] = []
        # Earliest position from which a marker's close search already failed in
        # this span. Every opener begins right after a non-marker character, so a
        # failed search proves every later opener of that marker fails too.
        failed_from: dict[str, int] = {}
        index = start
        while index < end:
            run = _EMPHASIS_RUN_PATTERN.search(text, index, end)
            if run is None:
                output.append(text[index:end])
                break
            if run.start() > index:
                output.append(text[index : run.start()])
            index, run_end = run.span()
            # Only a run of exactly 1-3 `*`/`_` or 2 `~` is a delimiter; any other
            # run is literal text.
            marker = text[index:run_end]
            if marker not in delimiters:
                output.append(marker)
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

            if failed_from.get(marker, end + 1) <= run_end:
                closing = None
            else:
                closing = _find_markdown_emphasis_close(text, marker, run_end, end)
                if closing is None:
                    failed_from[marker] = run_end
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


_MAX_BLOCKQUOTE_DEPTH = 16


def _convert_markdown_blocks(
    text: str,
    depth: int = 0,
    on_truncated: Callable[[], None] | None = None,
) -> str:
    """Line-level constructs: blockquotes, headings, rules and lists.

    Blockquote nesting recurses once per level, so it stops at
    ``_MAX_BLOCKQUOTE_DEPTH``: deeper ``>`` markers stay literal text, which keeps
    the result deterministic and the Python stack bounded for any input size;
    ``on_truncated`` is called once per such line so the caller can report it.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    converted: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        end = index + 1
        if line.startswith(">") and depth >= _MAX_BLOCKQUOTE_DEPTH and on_truncated:
            on_truncated()
        if line.startswith(">") and depth < _MAX_BLOCKQUOTE_DEPTH:
            while end < len(lines) and lines[end].startswith(">"):
                end += 1
            inner = _convert_markdown_blocks(
                "\n".join(item[1:].lstrip() for item in lines[index:end]),
                depth + 1,
                on_truncated,
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


def convert_message(
    value: str, message_format: MessageFormat
) -> tuple[str, tuple[ConversionFinding, ...]]:
    """The MyCode to write and its conversion findings, from one conversion pass."""
    if message_format == "markdown":
        result = _convert_markdown_to_mycode(value)
        return result.text, result.findings
    return value, _readable_projection_findings(value)


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
    masked = _masked(
        value,
        [match.span() for match in finditer_code_blocks(value)] + list(protected_spans),
    )
    text = _masked(masked, _malformed_markup_ranges(masked))
    for match in _finditer_closed(_MYCODE_TAG_PATTERN, text):
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
    for match in _finditer_closed(_SPOILER_TAG_PATTERN, text):
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
        text = _sub_paired(_QUOTE_PATTERN, _QUOTE_CLOSER_PATTERN, _replace, text)
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

    return _sub_paired(_LIST_PATTERN, _LIST_CLOSER_PATTERN, _replace, text)


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

    text = _sub_paired(
        _URL_WITH_TARGET_PATTERN, _URL_CLOSER_PATTERN, _replace_target_link, text
    )
    text = _sub_paired(_URL_PATTERN, _URL_CLOSER_PATTERN, _replace_link, text)
    text = _sub_paired(_IMAGE_PATTERN, _IMAGE_CLOSER_PATTERN, _replace_image, text)
    return text


@lru_cache(maxsize=None)
def _void_tag_pattern(tag_name: str) -> re.Pattern[str]:
    return re.compile(rf"\[{re.escape(tag_name)}\]", re.IGNORECASE)


@lru_cache(maxsize=None)
def _paired_tag_patterns(
    tag_name: str, rule_attribute: str | None
) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """The opener-to-closer pattern and the closer pattern of a paired tag."""
    attribute = (
        f"=(?:{rule_attribute})" if rule_attribute is not None else r"(?:=[^\]]*)?"
    )
    pattern = re.compile(
        rf"\[{re.escape(tag_name)}{attribute}\](.*?)\[/{re.escape(tag_name)}\]",
        re.IGNORECASE | re.DOTALL,
    )
    closer = re.compile(rf"\[/{re.escape(tag_name)}\]", re.IGNORECASE)
    return pattern, closer


def _apply_tag_rules(text: str, body_format: BodyFormat) -> str:
    for tag_name, rule in TAG_RULES.items():
        if tag_name == "spoiler":
            continue
        if rule.void:
            replacement = (
                rule.markdown_prefix if body_format == "markdown" else rule.clean_prefix
            )
            text = _void_tag_pattern(tag_name).sub(
                replacement.replace("\\", "\\\\"), text
            )
            continue
        pattern, closer = _paired_tag_patterns(tag_name, rule.attribute)
        for _ in range(20):
            updated = _sub_paired(
                pattern,
                closer,
                lambda match: _render_rule(rule, match.group(1), body_format),
                text,
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
    # Anchor on the start of the run, or each space of a long run rescans it.
    text = re.sub(r"(?<![ \t])[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


__all__ = [
    "BodyFormat",
    "ConversionFinding",
    "MessageFormat",
    "TAG_RULES",
    "analyze_conversion",
    "coerce_body_format",
    "convert_message",
    "coerce_message_format",
    "decode_double_quote_entities",
    "format_body_text",
    "format_write_text",
    "markdown_to_mycode",
]
