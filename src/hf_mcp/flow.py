from __future__ import annotations

from collections.abc import Collection, Mapping
import re
from typing import Any

from hf_mcp import __version__

FLOW_KEY: str = "_hf_flow"
_FLOW_VERSION = 1
_SERVER_NAME = "hf-mcp"
_DRAFT_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_CHILD_KEYS = ("children", "child_forums", "childforums", "forums", "subforums")

# Entity kinds, in the order the envelope reports them (as "<kind>_ids").
_REPORTED_KINDS = (
    "forum thread post user contract dispute rating sigmarket_listing".split()
)

# kind -> key groups. Each group yields at most one id: the first key holding a
# positive id wins.
_KeyGroups = tuple[tuple[str, ...], ...]
_ROW_USER_KEYS = (
    "from_uid to_uid from to fromid toid target_uid inituid otheruid muid "
    "claimantuid defendantuid buyer seller"
).split()
_ARGUMENT_USER_KEYS = (
    "target_uid from_uid to_uid seller buyer claimantuid defendantuid".split()
)
_ROW_KEYS: dict[str, _KeyGroups] = {
    "forum": (("fid",),),
    "thread": (("tid",), ("dispute_tid",)),
    "post": (("pid",),),
    "user": (("uid",), *((key,) for key in _ROW_USER_KEYS)),
    "contract": (("cid", "contractid"),),
    "dispute": (("cdid", "did"), ("idispute",), ("odispute",)),
    "rating": (("crid",), ("ibrating",), ("obrating",)),
    "sigmarket_listing": (("smid", "oid"),),
}
_ARGUMENT_KEYS: dict[str, _KeyGroups] = {
    "forum": (("fid",),),
    "thread": (("tid",),),
    "post": (("pid",),),
    "user": (("uid",), *((key,) for key in _ARGUMENT_USER_KEYS)),
    "contract": (("cid", "contract_id"),),
    "dispute": (("cdid", "dispute_id", "did"),),
    "rating": (("crid",),),
    "sigmarket_listing": (("smid", "oid"),),
}

# Relation table: entry tool -> ordered rules. A rule fires once per id of its
# entity kind (ascending) and emits each template in order. A template is
# "target_tool:argument:label" ("{}" in the label receives the id); an empty
# argument means no arguments and a trailing "!" requires confirmation. Pseudo
# kinds: "once" always fires, "drafts" fires once when any draft id exists.
_Rule = tuple[str, tuple[str, ...]]


def _r(kind: str, *templates: str) -> _Rule:
    return (kind, templates)


_USER = "users.read:uid:Load user {}"
_FORUM = "forums.read:fid:Load forum {}"
_LIST = "drafts.list::List local drafts"
_LEDGER = ("bytes.read:uid:Load bytes ledger for user {}", _USER)
_RATINGS = "bratings.read:cid:Load B-ratings for contract {}"
_TRANSFER = "bytes.transfer:target_uid:Prepare bytes transfer to user {}!"
_OPEN = "drafts.read:draft_id:Open draft {}"
_UPDATE = "drafts.update:draft_id:Update metadata for draft {}"

_RELATIONS: dict[str, tuple[_Rule, ...]] = {
    "forums.index": (_r("forum", _FORUM),),
    "forums.read": (
        _r("forum", "threads.read:fid:Load threads in forum {}"),
        _r("child_forum", "forums.read:fid:Load child forum {}"),
    ),
    "threads.read": (
        _r("thread", "posts.read:tid:Load posts in thread {}"),
        _r("user", _USER),
        _r("forum", _FORUM),
    ),
    "posts.read": (
        _r("thread", "threads.read:tid:Load thread {}"),
        _r("user", _USER),
        _r("forum", _FORUM),
        _r("post", "posts.read:pid:Reload post {}"),
    ),
    "threads.create": (
        _r(
            "thread",
            "threads.read:tid:Load thread {}",
            "posts.read:tid:Load posts in thread {}",
        ),
        _r("forum", _FORUM),
    ),
    "posts.reply": (_r("thread", "posts.read:tid:Load posts in thread {}"),),
    "bytes.read": (_r("user", *_LEDGER, _TRANSFER),),
    **{
        tool: (_r("user", *_LEDGER),)
        for tool in ("bytes.transfer", "bytes.deposit", "bytes.withdraw", "bytes.bump")
    },
    "contracts.read": (
        _r("contract", "disputes.read:cid:Load disputes for contract {}", _RATINGS),
        _r("dispute", "disputes.read:cdid:Load dispute {}"),
        _r("rating", "bratings.read:crid:Load B-rating {}"),
        _r("thread", "threads.read:tid:Load contract thread {}"),
        _r("user", _USER),
    ),
    "disputes.read": (
        _r("dispute", "disputes.read:cdid:Reload dispute {}"),
        _r("contract", "contracts.read:cid:Load contract {}", _RATINGS),
        _r("thread", "threads.read:tid:Load dispute thread {}"),
        _r("user", _USER),
    ),
    "bratings.read": (
        _r("rating", "bratings.read:crid:Reload B-rating {}"),
        _r("contract", "contracts.read:cid:Load contract {}"),
        _r("user", _USER),
    ),
    "sigmarket.market.read": (
        _r(
            "user",
            _USER,
            "sigmarket.order.read:uid:Load signature market orders for user {}",
        ),
    ),
    "sigmarket.order.read": (
        _r(
            "sigmarket_listing",
            "sigmarket.order.read:smid:Reload signature market order {}",
        ),
        _r(
            "user",
            _USER,
            "sigmarket.market.read:uid:Load signature market listing for user {}",
        ),
    ),
    "formatting.preflight": (_r("drafts", _LIST), _r("draft", _OPEN, _UPDATE)),
    "drafts.list": (_r("draft", _OPEN),),
    "drafts.read": (
        _r("draft", _UPDATE, "drafts.delete:draft_id:Delete draft {}!"),
        _r("once", "formatting.preflight::Run another local formatting preflight"),
    ),
    "drafts.update": (
        _r("once", _LIST),
        _r("draft", "drafts.read:draft_id:Re-open draft {}"),
    ),
    "drafts.delete": (_r("once", _LIST),),
}


def _coerce_positive_id(raw_value: Any) -> int | None:
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value if raw_value > 0 else None
    if isinstance(raw_value, str):
        try:
            parsed = int(raw_value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _coerce_draft_id(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None
    draft_id = raw_value.strip().lower()
    return draft_id if _DRAFT_ID_PATTERN.fullmatch(draft_id) else None


def _as_rows(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = payload.get(key)
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, Mapping)]
    return []


def _descendants(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    for child_key in _CHILD_KEYS:
        children = node.get(child_key)
        for child in children if isinstance(children, list) else ():
            if isinstance(child, Mapping):
                found.append(child)
                found.extend(_descendants(child))
    return found


def _flow_root_key(tool_name: str) -> str:
    return {
        "sigmarket.market.read": "sigmarket/market",
        "sigmarket.order.read": "sigmarket/order",
        "admin.high_risk.read": "admin/high-risk/read",
    }.get(tool_name, tool_name.split(".", 1)[0])


def _collect_ids(
    mapping: Mapping[str, Any],
    spec: Mapping[str, _KeyGroups],
    into: dict[str, set[Any]],
) -> None:
    for kind, groups in spec.items():
        for keys in groups:
            for key in keys:
                found = _coerce_positive_id(mapping.get(key))
                if found is not None:
                    into[kind].add(found)
                    break


def _collect_entities(
    tool_name: str, payload: Mapping[str, Any], arguments: Mapping[str, Any]
) -> dict[str, set[Any]]:
    entities: dict[str, set[Any]] = {
        kind: set() for kind in (*_ROW_KEYS, "child_forum", "draft")
    }
    rows = _as_rows(payload, _flow_root_key(tool_name))
    for row in rows:
        _collect_ids(row, _ROW_KEYS, entities)
        firstpost = row.get("firstpost")
        author = firstpost.get("author") if isinstance(firstpost, Mapping) else None
        if isinstance(author, Mapping):
            _collect_ids(author, {"user": (("uid",),)}, entities)
    _collect_ids(arguments, _ARGUMENT_KEYS, entities)
    if tool_name == "forums.index" and isinstance(payload.get("nodes"), list):
        for root in (n for n in payload["nodes"] if isinstance(n, Mapping)):
            for node in (root, *_descendants(root)):
                if not node.get("is_category"):
                    _collect_ids(node, {"forum": (("fid",),)}, entities)
    if tool_name == "forums.read":
        for row in rows:
            for child in _descendants(row):
                _collect_ids(child, {"child_forum": (("fid",),)}, entities)
    for candidate in (
        arguments.get("draft_id"),
        payload.get("draft_id"),
        *(row.get("draft_id") for row in _as_rows(payload, "drafts")),
    ):
        if (draft_id := _coerce_draft_id(candidate)) is not None:
            entities["draft"].add(draft_id)
    entities["drafts"] = {True} if entities["draft"] else set()
    entities["once"] = {True}
    return entities


def _add_action(
    actions: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    *,
    target_tool: str,
    action_arguments: Mapping[str, Any],
    label: str,
    requires_confirmation: bool = False,
) -> None:
    """Append one deduplicated action; skip it if any argument is unusable."""
    normalized: dict[str, Any] = {}
    for key, value in action_arguments.items():
        coerced = (
            (value.strip() or None)
            if isinstance(value, str)
            else _coerce_positive_id(value)
        )
        if coerced is None:
            return
        normalized[str(key)] = coerced
    action_key = (target_tool, repr(sorted(normalized.items())))
    if action_key in seen:
        return
    seen.add(action_key)
    actions.append(
        {"tool": target_tool, "arguments": normalized, "label": label}
        | ({"requires_confirmation": True} if requires_confirmation else {})
    )


def build_hf_flow(
    *,
    tool_name: str,
    normalized_payload: Mapping[str, Any],
    arguments: Mapping[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    entities = _collect_entities(tool_name, normalized_payload, arguments or {})
    actions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kind, templates in _RELATIONS.get(tool_name, ()):
        for entity_id in sorted(entities[kind]):
            for template in templates:
                target_tool, argument, label = template.rstrip("!").split(":", 2)
                _add_action(
                    actions,
                    seen,
                    target_tool=target_tool,
                    action_arguments={argument: entity_id} if argument else {},
                    label=label.format(entity_id),
                    requires_confirmation=template.endswith("!"),
                )
    source_value = (source or "").strip()
    return {
        "version": _FLOW_VERSION,
        "server": {"name": _SERVER_NAME, "version": __version__},
        "entry_tool": tool_name,
        "breadcrumbs": (
            [source_value, tool_name]
            if source_value and source_value != tool_name
            else [tool_name]
        ),
        "entities": {
            f"{kind}_ids": sorted(
                entities[kind] | (entities["child_forum"] if kind == "forum" else set())
            )
            for kind in _REPORTED_KINDS
        },
        "next_actions": actions,
    }


def attach_hf_flow(
    normalized_payload: dict[str, Any], flow: Mapping[str, Any]
) -> dict[str, Any]:
    payload_with_flow = dict(normalized_payload)
    payload_with_flow[FLOW_KEY] = dict(flow)
    return payload_with_flow


def prune_flow_actions(
    structured_content: Mapping[str, Any], enabled_tools: Collection[str]
) -> dict[str, Any]:
    """Return a copy whose flow keeps only actions that target enabled tools."""
    pruned = dict(structured_content)
    flow = pruned.get(FLOW_KEY)
    if isinstance(flow, Mapping) and isinstance(flow.get("next_actions"), list):
        pruned[FLOW_KEY] = {
            **flow,
            "next_actions": [
                action
                for action in flow["next_actions"]
                if not isinstance(action, Mapping)
                or action.get("tool") in enabled_tools
            ],
        }
    return pruned


__all__ = ["FLOW_KEY", "attach_hf_flow", "build_hf_flow", "prune_flow_actions"]
