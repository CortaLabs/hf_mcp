"""The tool table: the one place a tool is declared.

Each ``ToolSpec`` row carries the tool's name, capability, description, input
schema, output schema and annotation flags. Policy, presets and published
schemas are derived from ``TOOLS``. Every input property carries its parameter
family under ``x-hf-family``; ``x-hf-wire`` marks properties whose name or limit
mirrors the Hack Forums v2 wire. Both keys are internal and never published.

This module is a leaf: it imports nothing from ``hf_mcp``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

Operation = Literal["read", "write", "local"]
Group = Literal["core_read", "extended_read", "write", "local"]

DRAFT_ID_PATTERN = "^[a-f0-9]{32}$"
TEMPLATE_NAME_PATTERN = "^[a-z0-9][a-z0-9_-]{0,63}$"
# One ceiling for every free-text message/source: tool arguments, converter
# input, rendered templates and draft source files.
MAX_MESSAGE_CHARS = 500_000
# Ceilings for the remaining free-text kinds: titles, categories and subjects
# share the short-text limit; filesystem selectors share the path limit.
MAX_SHORT_TEXT_CHARS = 512
MAX_PATH_CHARS = 4096

FAMILY_KEY = "x-hf-family"
WIRE_KEY = "x-hf-wire"

_OUTPUT_FAMILY = "output.options"
_DRAFT_STATUSES = ["draft", "ready", "approved", "archived"]
_MESSAGE_FORMATS = ["mycode", "markdown"]
_DRAFT_ID_DESCRIPTION = "Optional cached formatting.preflight draft id to publish without resending message text."
_DRAFT_PATH_DESCRIPTION = "Optional cached formatting.preflight JSON artifact path inside the hf_mcp draft cache directory."


def mcp_tool_name(canonical_name: str) -> str:
    """Return the public MCP-safe name for a canonical tool id."""
    return canonical_name.replace(".", "_")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    capability: str
    operation: Operation
    group: Group
    description: str
    input_schema: dict[str, Any]
    required_families: frozenset[str]
    output_schema: dict[str, Any] | None
    read_only: bool
    destructive: bool
    idempotent: bool
    open_world: bool

    @property
    def mcp_name(self) -> str:
        return mcp_tool_name(self.name)

    @property
    def families(self) -> frozenset[str]:
        return frozenset(
            prop[FAMILY_KEY] for prop in self.input_schema["properties"].values()
        )

    @property
    def annotations(self) -> dict[str, object]:
        return {
            "readOnlyHint": self.read_only,
            "destructiveHint": self.destructive,
            "idempotentHint": self.idempotent,
            "openWorldHint": self.open_world,
        }


def _p(family: str, type_: str, *, wire: bool = False, **schema: Any) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": type_, **schema, FAMILY_KEY: family}
    if wire:
        prop[WIRE_KEY] = True
    return prop


def _id(family: str, *, wire: bool = False) -> dict[str, Any]:
    return _p(family, "integer", minimum=1, wire=wire)


def _ids(family: str, *names: str, wire: tuple[str, ...] = ()) -> dict[str, Any]:
    return {name: _id(family, wire=name in wire) for name in names}


def _paging(*, per_page: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "page": _p("filters.pagination", "integer", minimum=1, default=1),
        "per_page": per_page
        or _p(
            "filters.pagination",
            "integer",
            minimum=1,
            maximum=30,
            default=30,
            wire=True,
        ),
    }


def _timestamp(family: str) -> dict[str, Any]:
    return _p(family, "string", format="date-time", maxLength=MAX_SHORT_TEXT_CHARS)


def _flag(family: str, default: bool, *, wire: bool = False) -> dict[str, Any]:
    return _p(family, "boolean", default=default, wire=wire)


def _output() -> dict[str, Any]:
    return {
        "output_mode": _p(
            _OUTPUT_FAMILY,
            "string",
            enum=["readable", "structured", "raw"],
            default="readable",
            wire=True,
        ),
        "include_raw_payload": _flag(_OUTPUT_FAMILY, False, wire=True),
        "body_format": _p(
            _OUTPUT_FAMILY,
            "string",
            enum=["raw", "clean", "markdown"],
            default="markdown",
            description="How BBCode/MyCode body fields should be exposed in structuredContent.",
        ),
    }


def _confirm_live() -> dict[str, Any]:
    return {"confirm_live": _p("confirm.live", "boolean", const=True)}


def _draft_selector() -> dict[str, Any]:
    return {
        "draft_id": _p("drafts.selector", "string", pattern=DRAFT_ID_PATTERN),
        "draft_path": _p(
            "drafts.selector", "string", minLength=1, maxLength=MAX_PATH_CHARS
        ),
    }


def _write_content(*, subject: bool = False) -> dict[str, Any]:
    family = "writes.content"
    props: dict[str, Any] = {}
    if subject:
        props["subject"] = _p(
            family, "string", minLength=1, maxLength=MAX_SHORT_TEXT_CHARS
        )
    props.update(
        message=_p(family, "string", minLength=1, maxLength=MAX_MESSAGE_CHARS),
        draft_id=_p(
            family,
            "string",
            pattern=DRAFT_ID_PATTERN,
            description=_DRAFT_ID_DESCRIPTION,
        ),
        draft_path=_p(
            family,
            "string",
            minLength=1,
            maxLength=MAX_PATH_CHARS,
            description=_DRAFT_PATH_DESCRIPTION,
        ),
        message_format=_p(
            family,
            "string",
            enum=_MESSAGE_FORMATS,
            default="mycode",
            description="Input format for message; markdown is converted to Hack Forums MyCode before writing.",
        ),
    )
    return props


_WRITE_CONTENT_ANY = ("message", "draft_id", "draft_path")
_DRAFT_SELECTOR_ANY = ("draft_id", "draft_path")


def _tool(
    name: str,
    capability: str,
    group: Group,
    description: str,
    properties: dict[str, Any],
    *,
    operation: Operation | None = None,
    required: tuple[str, ...] = (),
    any_of: tuple[str, ...] = (),
    required_families: tuple[str, ...] = (),
    flags: tuple[bool, bool, bool, bool],
) -> ToolSpec:
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": deepcopy(properties),
    }
    if required:
        schema["required"] = list(required)
    if any_of:
        schema["anyOf"] = [{"required": [field]} for field in any_of]
    remote = group != "local"
    read_only, destructive, idempotent, open_world = flags
    if operation is None:
        operation = "write" if group == "write" else "read" if remote else "local"
    return ToolSpec(
        name=name,
        capability=capability,
        operation=operation,
        group=group,
        description=description,
        input_schema=schema,
        required_families=frozenset(required_families),
        output_schema=(
            None
            if operation == "write"
            else {"type": "object", "additionalProperties": True}
        ),
        read_only=read_only,
        destructive=destructive,
        idempotent=idempotent,
        open_world=open_world,
    )


_REMOTE_READ = (True, False, True, True)
_LOCAL_READ = (True, False, True, False)
_REMOTE_WRITE = (False, True, False, True)
_LOCAL_WRITE = (False, False, False, False)


def _read(
    name: str,
    group: Group,
    description: str,
    properties: dict[str, Any],
    **kw: Any,
) -> ToolSpec:
    return _tool(
        name,
        name,
        group,
        description,
        {**properties, **_output()},
        flags=_REMOTE_READ,
        **kw,
    )


def _write(
    name: str,
    description: str,
    properties: dict[str, Any],
    **kw: Any,
) -> ToolSpec:
    return _tool(
        name,
        name,
        "write",
        description,
        properties,
        flags=_REMOTE_WRITE,
        **kw,
    )


_PAGED_SUFFIX = "with pagination and readable, structured, or raw output."

TOOLS: tuple[ToolSpec, ...] = (
    _read(
        "me.read",
        "core_read",
        "Read the current account's profile; advanced fields are optional. Output supports readable, structured, or raw modes.",
        {
            "include_basic_fields": _flag("fields.me.basic", True, wire=True),
            "include_advanced_fields": _flag("fields.me.advanced", False, wire=True),
        },
    ),
    _read(
        "users.read",
        "core_read",
        "Read a public user profile by user ID, with optional profile fields, pagination, and readable, structured, or raw output.",
        {
            **_ids("selectors.user", "uid"),
            "include_profile_fields": _flag("fields.users.profile", True, wire=True),
            **_paging(),
        },
        required=("uid",),
        required_families=("selectors.user",),
    ),
    _tool(
        "forums.index",
        "forums.read",
        "local",
        "Discover root forums and categories from the packaged local catalog without a selector. Entries may lag live forum changes; output can be readable, structured, or raw.",
        {
            "view": _p(_OUTPUT_FAMILY, "string", enum=["flat", "tree"], default="flat"),
            "include_inactive": _flag(_OUTPUT_FAMILY, False),
            **_output(),
        },
        operation="read",
        flags=_LOCAL_READ,
    ),
    _read(
        "forums.read",
        "core_read",
        f"Read forum details by forum ID, {_PAGED_SUFFIX}",
        {**_ids("selectors.forum", "fid"), **_paging()},
        required=("fid",),
        required_families=("selectors.forum",),
    ),
    _read(
        "threads.read",
        "core_read",
        "Browse threads by forum, thread, or user selector; optionally include first-post content. Supports pagination and readable, structured, or raw output.",
        {
            **_ids("selectors.forum", "fid"),
            **_ids("selectors.thread", "tid", "uid"),
            **_paging(),
        },
        any_of=("fid", "tid", "uid"),
    ),
    _read(
        "posts.read",
        "core_read",
        "Read posts by thread, post, or user selector; optionally include post bodies. Supports pagination and readable, structured, or raw output.",
        {
            **_ids("selectors.post", "pid"),
            **_ids("selectors.thread", "tid", "uid"),
            "include_post_body": _flag("fields.posts.body", True, wire=True),
            **_paging(),
        },
        any_of=("pid", "tid", "uid"),
    ),
    _read(
        "bytes.read",
        "extended_read",
        "Read a user's Bytes account or transaction entries with supported filters, pagination, and optional amount fields; output can be readable, structured, or raw.",
        {
            **_ids(
                "selectors.bytes",
                "id",
                "uid",
                "from_uid",
                "to_uid",
                "target_uid",
                wire=("id", "from_uid", "to_uid"),
            ),
            "include_amount": _flag("fields.bytes.amount", True, wire=True),
            "page": _p("filters.pagination", "integer", minimum=1),
            "per_page": _p("filters.pagination", "integer", minimum=1, wire=True),
        },
    ),
    _read(
        "contracts.read",
        "extended_read",
        f"Browse contract records by supported contract or user selector, {_PAGED_SUFFIX}",
        {
            **_ids("selectors.contract", "cid", "uid", wire=("cid",)),
            **_paging(),
        },
    ),
    _read(
        "disputes.read",
        "extended_read",
        f"Browse disputes by supported dispute or participant selector, {_PAGED_SUFFIX}",
        {
            **_ids(
                "selectors.dispute",
                "cdid",
                "cid",
                "uid",
                "claimantuid",
                "defendantuid",
                wire=("cdid", "cid", "claimantuid", "defendantuid"),
            ),
            **_paging(),
        },
    ),
    _read(
        "bratings.read",
        "extended_read",
        f"Browse b-rating records by supported user or contract selector, {_PAGED_SUFFIX}",
        {
            **_ids(
                "selectors.user",
                "crid",
                "cid",
                "uid",
                "from_uid",
                "to_uid",
                wire=("crid", "cid", "from_uid", "to_uid"),
            ),
            **_paging(),
        },
    ),
    _read(
        "sigmarket.market.read",
        "extended_read",
        f"Browse Signature Market listings by supported listing or user selector, {_PAGED_SUFFIX}",
        {**_ids("selectors.sigmarket", "uid"), **_paging()},
    ),
    _read(
        "sigmarket.order.read",
        "extended_read",
        f"Browse Signature Market orders by supported order, listing, or user selector, {_PAGED_SUFFIX}",
        {
            **_ids(
                "selectors.sigmarket",
                "smid",
                "oid",
                "uid",
                "seller",
                "buyer",
                wire=("smid", "oid", "seller", "buyer"),
            ),
            **_paging(),
        },
    ),
    _read(
        "admin.high_risk.read",
        "extended_read",
        "Read high-risk admin data when enabled. Supports pagination and readable, structured, or raw output.",
        _paging(),
    ),
    _tool(
        "formatting.preflight",
        "formatting.preflight",
        "local",
        "Check how MyCode or Markdown formats as Hack Forums MyCode and report conversion findings; preflight can save a local draft.",
        {
            "message": _p(
                "formatting.content",
                "string",
                minLength=1,
                maxLength=MAX_MESSAGE_CHARS,
            ),
            "source_path": _p(
                "formatting.content",
                "string",
                minLength=1,
                maxLength=MAX_PATH_CHARS,
                description="Optional .md, .mycode, or .txt source file inside the hf_mcp draft cache directory.",
            ),
            "message_format": _p(
                "formatting.content",
                "string",
                enum=_MESSAGE_FORMATS,
                default="markdown",
                description="Input format to simulate before any live write.",
            ),
        },
        operation="read",
        any_of=("message", "source_path"),
        required_families=("formatting.content",),
        flags=(False, False, False, False),
    ),
    _tool(
        "formatting.convert",
        "formatting.convert",
        "local",
        "Convert Markdown or MyCode to Hack Forums MyCode and report conversion findings and issues; nothing is saved and nothing is sent.",
        {
            "message": _p(
                "formatting.convert",
                "string",
                minLength=1,
                maxLength=MAX_MESSAGE_CHARS,
            ),
            "message_format": _p(
                "formatting.convert",
                "string",
                enum=_MESSAGE_FORMATS,
                default="markdown",
                description="Input format of message.",
            ),
        },
        operation="read",
        required=("message",),
        required_families=("formatting.convert",),
        flags=_LOCAL_READ,
    ),
    _tool(
        "templates.list",
        "templates.read",
        "local",
        "List the named post templates in the local templates directory with their placeholders; invalid template files are only counted.",
        {},
        operation="read",
        flags=_LOCAL_READ,
    ),
    _tool(
        "templates.render",
        "templates.read",
        "local",
        "Fill a named local template with string values and return its source text and Hack Forums MyCode; nothing is saved and nothing is sent.",
        {
            "name": _p("templates.render", "string", pattern=TEMPLATE_NAME_PATTERN),
            "values": _p(
                "templates.render",
                "object",
                additionalProperties={"type": "string", "maxLength": MAX_MESSAGE_CHARS},
                default={},
            ),
        },
        operation="read",
        required=("name",),
        required_families=("templates.render",),
        flags=_LOCAL_READ,
    ),
    _tool(
        "drafts.list",
        "drafts.read",
        "local",
        "List local drafts with optional status, category, title, or schedule filters and paginated results.",
        {
            "status": _p("drafts.filters", "string", enum=_DRAFT_STATUSES),
            "category": _p(
                "drafts.filters", "string", minLength=1, maxLength=MAX_SHORT_TEXT_CHARS
            ),
            "title": _p(
                "drafts.filters", "string", minLength=1, maxLength=MAX_SHORT_TEXT_CHARS
            ),
            "scheduled_before": _timestamp("drafts.filters"),
            "scheduled_after": _timestamp("drafts.filters"),
            "limit": _p("drafts.filters", "integer", minimum=0, default=50),
            "offset": _p("drafts.filters", "integer", minimum=0, default=0),
        },
        operation="read",
        flags=_LOCAL_READ,
    ),
    _tool(
        "drafts.read",
        "drafts.read",
        "local",
        "Read a local draft by its draft ID and inspect its source, formatted content, and stored metadata.",
        _draft_selector(),
        operation="read",
        any_of=_DRAFT_SELECTOR_ANY,
        required_families=("drafts.selector",),
        flags=_LOCAL_READ,
    ),
    _tool(
        "drafts.update",
        "drafts.write",
        "local",
        "Update title, category, status, or scheduled-time metadata on a selected local draft; content is not sent to Hack Forums.",
        {
            **_draft_selector(),
            "title": _p("drafts.metadata", "string", maxLength=MAX_SHORT_TEXT_CHARS),
            "category": _p("drafts.metadata", "string", maxLength=MAX_SHORT_TEXT_CHARS),
            "status": _p("drafts.metadata", "string", enum=_DRAFT_STATUSES),
            "scheduled_at": _timestamp("drafts.metadata"),
        },
        operation="write",
        any_of=_DRAFT_SELECTOR_ANY,
        required_families=("drafts.selector", "drafts.metadata"),
        flags=_LOCAL_WRITE,
    ),
    _tool(
        "drafts.delete",
        "drafts.write",
        "local",
        "Delete a selected local draft after explicit confirmation; this removes the local artifact without contacting Hack Forums.",
        {
            **_draft_selector(),
            "confirm_delete": _p("drafts.confirm_delete", "boolean", const=True),
        },
        operation="write",
        required=("confirm_delete",),
        any_of=_DRAFT_SELECTOR_ANY,
        required_families=("drafts.selector", "drafts.confirm_delete"),
        flags=(False, True, False, False),
    ),
    _write(
        "threads.create",
        "Send a live thread-creation request to a selected forum with a subject and message. Requires explicit live confirmation.",
        {
            **_ids("selectors.forum", "fid"),
            **_write_content(subject=True),
            **_confirm_live(),
        },
        required=("fid", "subject", "confirm_live"),
        any_of=_WRITE_CONTENT_ANY,
        required_families=("selectors.forum", "writes.content", "confirm.live"),
    ),
    _write(
        "posts.reply",
        "Send a reply to a selected thread with message content and explicit live confirmation.",
        {
            **_ids("selectors.thread", "tid"),
            **_write_content(),
            **_confirm_live(),
        },
        required=("tid", "confirm_live"),
        any_of=_WRITE_CONTENT_ANY,
        required_families=("selectors.thread", "writes.content", "confirm.live"),
    ),
    _write(
        "bytes.transfer",
        "Send a live Bytes transfer to a selected user with an amount and explicit live confirmation.",
        {
            **_ids("selectors.bytes", "target_uid"),
            "amount": _p("writes.bytes", "integer", minimum=1),
            **_confirm_live(),
        },
        required=("confirm_live", "target_uid", "amount"),
        required_families=("selectors.bytes", "writes.bytes", "confirm.live"),
    ),
    _write(
        "bytes.deposit",
        "Send a live Bytes deposit request with an amount and explicit live confirmation.",
        {
            "amount": _p("writes.bytes", "integer", minimum=100),
            **_confirm_live(),
        },
        required=("amount", "confirm_live"),
        required_families=("writes.bytes", "confirm.live"),
    ),
    _write(
        "bytes.withdraw",
        "Send a live Bytes withdrawal request with an amount and explicit live confirmation.",
        {
            "amount": _p("writes.bytes", "integer", minimum=100),
            **_confirm_live(),
        },
        required=("amount", "confirm_live"),
        required_families=("writes.bytes", "confirm.live"),
    ),
    _write(
        "bytes.bump",
        "Send a live Bytes bump request for a selected thread with explicit live confirmation.",
        {**_ids("selectors.thread", "tid"), **_confirm_live()},
        required=("tid", "confirm_live"),
        required_families=("selectors.thread", "confirm.live"),
    ),
)


def _index(specs: tuple[ToolSpec, ...]) -> dict[str, ToolSpec]:
    by_name = {spec.name: spec for spec in specs}
    if len(by_name) != len(specs) or len({s.mcp_name for s in specs}) != len(specs):
        raise ValueError("Duplicate tool names in registry.TOOLS.")
    return by_name


_BY_NAME: dict[str, ToolSpec] = _index(TOOLS)


def get_tool_spec(name: str) -> ToolSpec:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"Unknown tool '{name}'.") from None


def get_specs(group: Group) -> tuple[ToolSpec, ...]:
    return tuple(spec for spec in TOOLS if spec.group == group)


__all__ = [
    "DRAFT_ID_PATTERN",
    "FAMILY_KEY",
    "MAX_MESSAGE_CHARS",
    "MAX_PATH_CHARS",
    "MAX_SHORT_TEXT_CHARS",
    "TEMPLATE_NAME_PATTERN",
    "TOOLS",
    "WIRE_KEY",
    "ToolSpec",
    "get_specs",
    "get_tool_spec",
    "mcp_tool_name",
]
