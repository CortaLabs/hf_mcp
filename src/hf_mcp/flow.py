from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

FLOW_KEY: str = "_hf_flow"
_FLOW_VERSION = 1
_DRAFT_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def _coerce_positive_id(raw_value: Any) -> int | None:
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value if raw_value > 0 else None
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            return None
        try:
            parsed = int(stripped)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _as_rows(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = payload.get(key)
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, Mapping)]
    return []


def _iter_child_nodes(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    child_nodes: list[Mapping[str, Any]] = []
    for child_key in ("children", "child_forums", "childforums", "forums", "subforums"):
        raw_children = node.get(child_key)
        if not isinstance(raw_children, list):
            continue
        for entry in raw_children:
            if isinstance(entry, Mapping):
                child_nodes.append(entry)
    return child_nodes


def _collect_child_forum_ids(rows: list[Mapping[str, Any]]) -> set[int]:
    child_forum_ids: set[int] = set()

    def _walk(node: Mapping[str, Any]) -> None:
        for child_node in _iter_child_nodes(node):
            child_fid = _coerce_positive_id(child_node.get("fid"))
            if child_fid is not None:
                child_forum_ids.add(child_fid)
            _walk(child_node)

    for row in rows:
        _walk(row)
    return child_forum_ids


def _build_breadcrumbs(*, tool_name: str, source: str | None) -> list[str]:
    if source is None:
        return [tool_name]
    source_value = source.strip()
    if not source_value or source_value == tool_name:
        return [tool_name]
    return [source_value, tool_name]


def _flow_root_key(tool_name: str) -> str:
    if tool_name == "sigmarket.market.read":
        return "sigmarket/market"
    if tool_name == "sigmarket.order.read":
        return "sigmarket/order"
    if tool_name == "admin.high_risk.read":
        return "admin/high-risk/read"
    return tool_name.split(".", 1)[0]


def _coerce_draft_id(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None
    draft_id = raw_value.strip().lower()
    if not draft_id:
        return None
    if _DRAFT_ID_PATTERN.fullmatch(draft_id) is None:
        return None
    return draft_id


def _collect_local_draft_ids(
    *,
    normalized_payload: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> set[str]:
    draft_ids: set[str] = set()
    argument_draft_id = _coerce_draft_id(arguments.get("draft_id"))
    if argument_draft_id is not None:
        draft_ids.add(argument_draft_id)

    payload_draft_id = _coerce_draft_id(normalized_payload.get("draft_id"))
    if payload_draft_id is not None:
        draft_ids.add(payload_draft_id)

    for row in _as_rows(normalized_payload, "drafts"):
        row_draft_id = _coerce_draft_id(row.get("draft_id"))
        if row_draft_id is not None:
            draft_ids.add(row_draft_id)

    return draft_ids


def _collect_entity_ids(
    *,
    tool_name: str,
    normalized_payload: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> tuple[set[int], set[int], set[int], set[int], set[int], set[int], set[int], set[int], set[int]]:
    forum_ids: set[int] = set()
    thread_ids: set[int] = set()
    post_ids: set[int] = set()
    user_ids: set[int] = set()
    child_forum_ids: set[int] = set()
    contract_ids: set[int] = set()
    dispute_ids: set[int] = set()
    rating_ids: set[int] = set()
    sigmarket_listing_ids: set[int] = set()

    root_key = _flow_root_key(tool_name)
    rows = _as_rows(normalized_payload, root_key)

    for row in rows:
        forum_id = _coerce_positive_id(row.get("fid"))
        if forum_id is not None:
            forum_ids.add(forum_id)

        thread_id = _coerce_positive_id(row.get("tid"))
        if thread_id is not None:
            thread_ids.add(thread_id)

        post_id = _coerce_positive_id(row.get("pid"))
        if post_id is not None:
            post_ids.add(post_id)

        user_id = _coerce_positive_id(row.get("uid"))
        if user_id is not None:
            user_ids.add(user_id)

        for user_key in (
            "from_uid",
            "to_uid",
            "from",
            "to",
            "fromid",
            "toid",
            "target_uid",
            "inituid",
            "otheruid",
            "muid",
            "claimantuid",
            "defendantuid",
            "buyer",
            "seller",
        ):
            related_uid = _coerce_positive_id(row.get(user_key))
            if related_uid is not None:
                user_ids.add(related_uid)

        contract_id = _coerce_positive_id(row.get("cid"))
        if contract_id is None:
            contract_id = _coerce_positive_id(row.get("contractid"))
        if contract_id is not None:
            contract_ids.add(contract_id)

        dispute_id = _coerce_positive_id(row.get("cdid"))
        if dispute_id is None:
            dispute_id = _coerce_positive_id(row.get("did"))
        if dispute_id is not None:
            dispute_ids.add(dispute_id)

        for dispute_key in ("idispute", "odispute"):
            related_dispute_id = _coerce_positive_id(row.get(dispute_key))
            if related_dispute_id is not None:
                dispute_ids.add(related_dispute_id)

        rating_id = _coerce_positive_id(row.get("crid"))
        if rating_id is not None:
            rating_ids.add(rating_id)
        for rating_key in ("ibrating", "obrating"):
            related_rating_id = _coerce_positive_id(row.get(rating_key))
            if related_rating_id is not None:
                rating_ids.add(related_rating_id)

        sigmarket_id = _coerce_positive_id(row.get("smid"))
        if sigmarket_id is None:
            sigmarket_id = _coerce_positive_id(row.get("oid"))
        if sigmarket_id is not None:
            sigmarket_listing_ids.add(sigmarket_id)

        dispute_thread_id = _coerce_positive_id(row.get("dispute_tid"))
        if dispute_thread_id is not None:
            thread_ids.add(dispute_thread_id)

        firstpost = row.get("firstpost")
        if isinstance(firstpost, Mapping):
            author = firstpost.get("author")
            if isinstance(author, Mapping):
                author_uid = _coerce_positive_id(author.get("uid"))
                if author_uid is not None:
                    user_ids.add(author_uid)

    argument_forum_id = _coerce_positive_id(arguments.get("fid"))
    if argument_forum_id is not None:
        forum_ids.add(argument_forum_id)

    argument_thread_id = _coerce_positive_id(arguments.get("tid"))
    if argument_thread_id is not None:
        thread_ids.add(argument_thread_id)

    argument_post_id = _coerce_positive_id(arguments.get("pid"))
    if argument_post_id is not None:
        post_ids.add(argument_post_id)

    argument_user_id = _coerce_positive_id(arguments.get("uid"))
    if argument_user_id is not None:
        user_ids.add(argument_user_id)

    for user_arg in ("target_uid", "from_uid", "to_uid", "seller", "buyer", "claimantuid", "defendantuid"):
        arg_uid = _coerce_positive_id(arguments.get(user_arg))
        if arg_uid is not None:
            user_ids.add(arg_uid)

    argument_contract_id = _coerce_positive_id(arguments.get("cid"))
    if argument_contract_id is None:
        argument_contract_id = _coerce_positive_id(arguments.get("contract_id"))
    if argument_contract_id is not None:
        contract_ids.add(argument_contract_id)

    argument_dispute_id = _coerce_positive_id(arguments.get("cdid"))
    if argument_dispute_id is None:
        argument_dispute_id = _coerce_positive_id(arguments.get("dispute_id"))
    if argument_dispute_id is None:
        argument_dispute_id = _coerce_positive_id(arguments.get("did"))
    if argument_dispute_id is not None:
        dispute_ids.add(argument_dispute_id)

    argument_rating_id = _coerce_positive_id(arguments.get("crid"))
    if argument_rating_id is not None:
        rating_ids.add(argument_rating_id)

    argument_sigmarket_id = _coerce_positive_id(arguments.get("smid"))
    if argument_sigmarket_id is None:
        argument_sigmarket_id = _coerce_positive_id(arguments.get("oid"))
    if argument_sigmarket_id is not None:
        sigmarket_listing_ids.add(argument_sigmarket_id)

    if tool_name == "forums.index":
        nodes = normalized_payload.get("nodes")
        if isinstance(nodes, list):
            for node in nodes:
                if not isinstance(node, Mapping):
                    continue
                if bool(node.get("is_category")):
                    continue
                fid = _coerce_positive_id(node.get("fid"))
                if fid is not None:
                    forum_ids.add(fid)

    if tool_name == "forums.read":
        child_forum_ids = _collect_child_forum_ids(rows)

    return (
        forum_ids,
        thread_ids,
        post_ids,
        user_ids,
        child_forum_ids,
        contract_ids,
        dispute_ids,
        rating_ids,
        sigmarket_listing_ids,
    )


def build_hf_flow(
    *,
    tool_name: str,
    normalized_payload: Mapping[str, Any],
    arguments: Mapping[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    resolved_arguments = arguments or {}
    (
        forum_ids,
        thread_ids,
        post_ids,
        user_ids,
        child_forum_ids,
        contract_ids,
        dispute_ids,
        rating_ids,
        sigmarket_listing_ids,
    ) = _collect_entity_ids(
        tool_name=tool_name,
        normalized_payload=normalized_payload,
        arguments=resolved_arguments,
    )

    entities = {
        "forum_ids": sorted(forum_ids | child_forum_ids),
        "thread_ids": sorted(thread_ids),
        "post_ids": sorted(post_ids),
        "user_ids": sorted(user_ids),
        "contract_ids": sorted(contract_ids),
        "dispute_ids": sorted(dispute_ids),
        "rating_ids": sorted(rating_ids),
        "sigmarket_listing_ids": sorted(sigmarket_listing_ids),
    }

    next_actions: list[dict[str, Any]] = []
    seen_actions: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    def _append_action(
        *,
        target_tool: str,
        normalized_arguments: Mapping[str, Any],
        label: str,
        requires_confirmation: bool = False,
    ) -> None:
        action_key = (
            target_tool,
            tuple(sorted((str(key), repr(value)) for key, value in normalized_arguments.items())),
        )
        if action_key in seen_actions:
            return
        seen_actions.add(action_key)
        action: dict[str, Any] = {
            "tool": target_tool,
            "arguments": dict(normalized_arguments),
            "label": label,
        }
        if requires_confirmation:
            action["requires_confirmation"] = True
        next_actions.append(action)

    def _add_action(
        *,
        target_tool: str,
        action_arguments: Mapping[str, int],
        label: str,
        requires_confirmation: bool = False,
    ) -> None:
        normalized_args: dict[str, int] = {}
        for key, value in action_arguments.items():
            coerced = _coerce_positive_id(value)
            if coerced is None:
                return
            normalized_args[str(key)] = coerced
        _append_action(
            target_tool=target_tool,
            normalized_arguments=normalized_args,
            label=label,
            requires_confirmation=requires_confirmation,
        )

    def _add_local_action(
        *,
        target_tool: str,
        action_arguments: Mapping[str, str],
        label: str,
        requires_confirmation: bool = False,
    ) -> None:
        normalized_args: dict[str, str] = {}
        for key, value in action_arguments.items():
            if not isinstance(value, str):
                return
            stripped = value.strip()
            if not stripped:
                return
            normalized_args[str(key)] = stripped
        _append_action(
            target_tool=target_tool,
            normalized_arguments=normalized_args,
            label=label,
            requires_confirmation=requires_confirmation,
        )

    draft_ids = _collect_local_draft_ids(normalized_payload=normalized_payload, arguments=resolved_arguments)

    if tool_name == "forums.index":
        for forum_id in sorted(forum_ids):
            _add_action(
                target_tool="forums.read",
                action_arguments={"fid": forum_id},
                label=f"Load forum {forum_id}",
            )
    elif tool_name == "forums.read":
        for forum_id in sorted(forum_ids):
            _add_action(
                target_tool="threads.read",
                action_arguments={"fid": forum_id},
                label=f"Load threads in forum {forum_id}",
            )
        for child_forum_id in sorted(child_forum_ids):
            _add_action(
                target_tool="forums.read",
                action_arguments={"fid": child_forum_id},
                label=f"Load child forum {child_forum_id}",
            )
    elif tool_name == "threads.read":
        for thread_id in sorted(thread_ids):
            _add_action(
                target_tool="posts.read",
                action_arguments={"tid": thread_id},
                label=f"Load posts in thread {thread_id}",
            )
        for user_id in sorted(user_ids):
            _add_action(
                target_tool="users.read",
                action_arguments={"uid": user_id},
                label=f"Load user {user_id}",
            )
        for forum_id in sorted(forum_ids):
            _add_action(
                target_tool="forums.read",
                action_arguments={"fid": forum_id},
                label=f"Load forum {forum_id}",
            )
    elif tool_name == "posts.read":
        for thread_id in sorted(thread_ids):
            _add_action(
                target_tool="threads.read",
                action_arguments={"tid": thread_id},
                label=f"Load thread {thread_id}",
            )
        for user_id in sorted(user_ids):
            _add_action(
                target_tool="users.read",
                action_arguments={"uid": user_id},
                label=f"Load user {user_id}",
            )
        for forum_id in sorted(forum_ids):
            _add_action(
                target_tool="forums.read",
                action_arguments={"fid": forum_id},
                label=f"Load forum {forum_id}",
            )
        for post_id in sorted(post_ids):
            _add_action(
                target_tool="posts.read",
                action_arguments={"pid": post_id},
                label=f"Reload post {post_id}",
            )
    elif tool_name == "threads.create":
        for thread_id in sorted(thread_ids):
            _add_action(
                target_tool="threads.read",
                action_arguments={"tid": thread_id},
                label=f"Load thread {thread_id}",
            )
            _add_action(
                target_tool="posts.read",
                action_arguments={"tid": thread_id},
                label=f"Load posts in thread {thread_id}",
            )
        for forum_id in sorted(forum_ids):
            _add_action(
                target_tool="forums.read",
                action_arguments={"fid": forum_id},
                label=f"Load forum {forum_id}",
            )
    elif tool_name == "posts.reply":
        for thread_id in sorted(thread_ids):
            _add_action(
                target_tool="posts.read",
                action_arguments={"tid": thread_id},
                label=f"Load posts in thread {thread_id}",
            )
    elif tool_name in {"bytes.read", "bytes.transfer", "bytes.deposit", "bytes.withdraw", "bytes.bump"}:
        for user_id in sorted(user_ids):
            _add_action(
                target_tool="bytes.read",
                action_arguments={"uid": user_id},
                label=f"Load bytes ledger for user {user_id}",
            )
            _add_action(
                target_tool="users.read",
                action_arguments={"uid": user_id},
                label=f"Load user {user_id}",
            )
            if tool_name == "bytes.read":
                _add_action(
                    target_tool="bytes.transfer",
                    action_arguments={"target_uid": user_id},
                    label=f"Prepare bytes transfer to user {user_id}",
                    requires_confirmation=True,
                )
    elif tool_name == "contracts.read":
        for contract_id in sorted(contract_ids):
            _add_action(
                target_tool="disputes.read",
                action_arguments={"cid": contract_id},
                label=f"Load disputes for contract {contract_id}",
            )
            _add_action(
                target_tool="bratings.read",
                action_arguments={"cid": contract_id},
                label=f"Load B-ratings for contract {contract_id}",
            )
        for dispute_id in sorted(dispute_ids):
            _add_action(
                target_tool="disputes.read",
                action_arguments={"cdid": dispute_id},
                label=f"Load dispute {dispute_id}",
            )
        for rating_id in sorted(rating_ids):
            _add_action(
                target_tool="bratings.read",
                action_arguments={"crid": rating_id},
                label=f"Load B-rating {rating_id}",
            )
        for thread_id in sorted(thread_ids):
            _add_action(
                target_tool="threads.read",
                action_arguments={"tid": thread_id},
                label=f"Load contract thread {thread_id}",
            )
        for user_id in sorted(user_ids):
            _add_action(
                target_tool="users.read",
                action_arguments={"uid": user_id},
                label=f"Load user {user_id}",
            )
    elif tool_name == "disputes.read":
        for dispute_id in sorted(dispute_ids):
            _add_action(
                target_tool="disputes.read",
                action_arguments={"cdid": dispute_id},
                label=f"Reload dispute {dispute_id}",
            )
        for contract_id in sorted(contract_ids):
            _add_action(
                target_tool="contracts.read",
                action_arguments={"cid": contract_id},
                label=f"Load contract {contract_id}",
            )
            _add_action(
                target_tool="bratings.read",
                action_arguments={"cid": contract_id},
                label=f"Load B-ratings for contract {contract_id}",
            )
        for thread_id in sorted(thread_ids):
            _add_action(
                target_tool="threads.read",
                action_arguments={"tid": thread_id},
                label=f"Load dispute thread {thread_id}",
            )
        for user_id in sorted(user_ids):
            _add_action(
                target_tool="users.read",
                action_arguments={"uid": user_id},
                label=f"Load user {user_id}",
            )
    elif tool_name == "bratings.read":
        for rating_id in sorted(rating_ids):
            _add_action(
                target_tool="bratings.read",
                action_arguments={"crid": rating_id},
                label=f"Reload B-rating {rating_id}",
            )
        for contract_id in sorted(contract_ids):
            _add_action(
                target_tool="contracts.read",
                action_arguments={"cid": contract_id},
                label=f"Load contract {contract_id}",
            )
        for user_id in sorted(user_ids):
            _add_action(
                target_tool="users.read",
                action_arguments={"uid": user_id},
                label=f"Load user {user_id}",
            )
    elif tool_name == "sigmarket.market.read":
        for user_id in sorted(user_ids):
            _add_action(
                target_tool="users.read",
                action_arguments={"uid": user_id},
                label=f"Load user {user_id}",
            )
            _add_action(
                target_tool="sigmarket.order.read",
                action_arguments={"uid": user_id},
                label=f"Load signature market orders for user {user_id}",
            )
    elif tool_name == "sigmarket.order.read":
        for sigmarket_listing_id in sorted(sigmarket_listing_ids):
            _add_action(
                target_tool="sigmarket.order.read",
                action_arguments={"smid": sigmarket_listing_id},
                label=f"Reload signature market order {sigmarket_listing_id}",
            )
        for user_id in sorted(user_ids):
            _add_action(
                target_tool="users.read",
                action_arguments={"uid": user_id},
                label=f"Load user {user_id}",
            )
            _add_action(
                target_tool="sigmarket.market.read",
                action_arguments={"uid": user_id},
                label=f"Load signature market listing for user {user_id}",
            )
    elif tool_name == "formatting.preflight":
        if draft_ids:
            _append_action(
                target_tool="drafts.list",
                normalized_arguments={},
                label="List local drafts",
            )
        for draft_id in sorted(draft_ids):
            _add_local_action(
                target_tool="drafts.read",
                action_arguments={"draft_id": draft_id},
                label=f"Open draft {draft_id}",
            )
            _add_local_action(
                target_tool="drafts.update",
                action_arguments={"draft_id": draft_id},
                label=f"Update metadata for draft {draft_id}",
            )
    elif tool_name == "drafts.list":
        for draft_id in sorted(draft_ids):
            _add_local_action(
                target_tool="drafts.read",
                action_arguments={"draft_id": draft_id},
                label=f"Open draft {draft_id}",
            )
    elif tool_name == "drafts.read":
        for draft_id in sorted(draft_ids):
            _add_local_action(
                target_tool="drafts.update",
                action_arguments={"draft_id": draft_id},
                label=f"Update metadata for draft {draft_id}",
            )
            _add_local_action(
                target_tool="drafts.delete",
                action_arguments={"draft_id": draft_id},
                label=f"Delete draft {draft_id}",
                requires_confirmation=True,
            )
        _append_action(
            target_tool="formatting.preflight",
            normalized_arguments={},
            label="Run another local formatting preflight",
        )
    elif tool_name == "drafts.update":
        _append_action(
            target_tool="drafts.list",
            normalized_arguments={},
            label="List local drafts",
        )
        for draft_id in sorted(draft_ids):
            _add_local_action(
                target_tool="drafts.read",
                action_arguments={"draft_id": draft_id},
                label=f"Re-open draft {draft_id}",
            )
    elif tool_name == "drafts.delete":
        _append_action(
            target_tool="drafts.list",
            normalized_arguments={},
            label="List local drafts",
        )

    return {
        "version": _FLOW_VERSION,
        "entry_tool": tool_name,
        "breadcrumbs": _build_breadcrumbs(tool_name=tool_name, source=source),
        "entities": entities,
        "next_actions": next_actions,
    }


def attach_hf_flow(normalized_payload: dict[str, Any], flow: Mapping[str, Any]) -> dict[str, Any]:
    payload_with_flow = dict(normalized_payload)
    payload_with_flow[FLOW_KEY] = dict(flow)
    return payload_with_flow


__all__ = ["FLOW_KEY", "attach_hf_flow", "build_hf_flow"]
