"""Named post templates: load, validate and fill files from the templates directory.

A template is ``<name>.md`` (Markdown) or ``<name>.mycode`` (MyCode) directly in
``templates_dir``: UTF-8, at most ``MAX_TEMPLATE_BYTES``, opening with a ``---``
front-matter block (``description`` and ``placeholders``). Placeholders are written
``{{key}}``; every body placeholder must be declared and every declared key used.
Anything that fails these rules is *invalid*: it is counted, never listed, and no
path or file text reaches a caller.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from .registry import TEMPLATE_NAME_PATTERN

MAX_TEMPLATE_BYTES = 64 * 1024
PLACEHOLDER_KEY_PATTERN = "^[a-z][a-z0-9_]{0,31}$"

_NAME_RE = re.compile(TEMPLATE_NAME_PATTERN)
_KEY_RE = re.compile(PLACEHOLDER_KEY_PATTERN)
_PLACEHOLDER_RE = re.compile(r"\{\{([^{}]*)\}\}")
_SUFFIX_FORMATS: dict[str, Literal["markdown", "mycode"]] = {
    ".md": "markdown",
    ".mycode": "mycode",
}
_FRONT_MATTER_FENCE = "---"
_TOP_KEYS = frozenset({"description", "placeholders"})
_PLACEHOLDER_KEYS = frozenset({"description", "required"})


class TemplateUnavailable(LookupError):
    """No valid template has the requested name."""


@dataclass(frozen=True, slots=True)
class Placeholder:
    key: str
    description: str
    required: bool


@dataclass(frozen=True, slots=True)
class Template:
    name: str
    description: str
    message_format: Literal["markdown", "mycode"]
    placeholders: tuple[Placeholder, ...]
    body: str

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "message_format": self.message_format,
            "placeholders": [
                {
                    "key": item.key,
                    "description": item.description,
                    "required": item.required,
                }
                for item in self.placeholders
            ],
        }

    def fill(self, values: dict[str, str]) -> str:
        """Return the body with ``values`` inserted literally, in one pass."""
        declared = {item.key: item for item in self.placeholders}
        for key in values:
            if key not in declared:
                shown = key if _KEY_RE.fullmatch(key) else "(invalid key)"
                raise ValueError(f"Unknown template value: {shown}.")
        for item in self.placeholders:
            if item.required and item.key not in values:
                raise ValueError(f"Missing required template value: {item.key}.")
        return _PLACEHOLDER_RE.sub(
            lambda match: values.get(match.group(1), ""), self.body
        )


def load_templates(templates_dir: str | Path) -> tuple[tuple[Template, ...], int]:
    """Return ``(valid templates sorted by name, invalid_count)``.

    A missing or unreadable directory means zero templates. Only entries named
    ``*.md`` or ``*.mycode`` are candidates; each candidate that cannot be loaded
    counts once as invalid.
    """
    root = Path(templates_dir)
    try:
        entries = sorted(os.scandir(root), key=lambda entry: entry.name)
    except OSError:
        return (), 0
    templates: dict[str, Template] = {}
    invalid = 0
    for entry in entries:
        suffix = Path(entry.name).suffix
        if suffix not in _SUFFIX_FORMATS:
            continue
        template = _load_one(entry, _SUFFIX_FORMATS[suffix])
        if template is None or template.name in templates:
            invalid += 1
            continue
        templates[template.name] = template
    return tuple(templates[name] for name in sorted(templates)), invalid


def get_template(templates_dir: str | Path, name: str) -> Template:
    for template in load_templates(templates_dir)[0]:
        if template.name == name:
            return template
    raise TemplateUnavailable(name)


def _load_one(
    entry: os.DirEntry[str], message_format: Literal["markdown", "mycode"]
) -> Template | None:
    name = Path(entry.name).stem
    if not _NAME_RE.fullmatch(name):
        return None
    text = _read_regular_file(entry.path)
    if text is None:
        return None
    parsed = _parse(text)
    if parsed is None:
        return None
    description, placeholders, body = parsed
    return Template(name, description, message_format, placeholders, body)


def _read_regular_file(path: str) -> str | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(MAX_TEMPLATE_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    if len(data) > MAX_TEMPLATE_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _split_front_matter(text: str) -> tuple[str, str] | None:
    lines = text.lstrip("﻿").split("\n")
    if lines[0].rstrip("\r") != _FRONT_MATTER_FENCE:
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r") == _FRONT_MATTER_FENCE:
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :]).lstrip("\n")
    return None


def _parse(text: str) -> tuple[str, tuple[Placeholder, ...], str] | None:
    split = _split_front_matter(text)
    if split is None:
        return None
    raw_front, body = split
    try:
        front = yaml.safe_load(raw_front)
    except yaml.YAMLError:
        return None
    if not isinstance(front, dict) or not set(front) <= _TOP_KEYS:
        return None
    description = front.get("description", "")
    declared = front.get("placeholders") or {}
    if not isinstance(description, str) or not isinstance(declared, dict):
        return None
    placeholders: list[Placeholder] = []
    for key, spec in declared.items():
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
            return None
        spec = {} if spec is None else spec
        if not isinstance(spec, dict) or not set(spec) <= _PLACEHOLDER_KEYS:
            return None
        key_description = spec.get("description", "")
        required = spec.get("required", True)
        if not isinstance(key_description, str) or not isinstance(required, bool):
            return None
        placeholders.append(Placeholder(key, key_description, required))
    used = {match.group(1) for match in _PLACEHOLDER_RE.finditer(body)}
    if used != {item.key for item in placeholders}:
        return None
    if "{{" in _PLACEHOLDER_RE.sub("", body):
        return None
    return description, tuple(placeholders), body


__all__ = [
    "MAX_TEMPLATE_BYTES",
    "PLACEHOLDER_KEY_PATTERN",
    "Placeholder",
    "Template",
    "TemplateUnavailable",
    "get_template",
    "load_templates",
]
