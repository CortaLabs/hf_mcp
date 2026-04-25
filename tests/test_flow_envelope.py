from __future__ import annotations

import sys
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.flow import FLOW_KEY, attach_hf_flow, build_hf_flow


def _action_tools(flow: dict[str, object]) -> list[str]:
    actions = flow.get("next_actions")
    assert isinstance(actions, list)
    return [str(action.get("tool")) for action in actions if isinstance(action, dict)]


def _actions_as_tuples(flow: dict[str, object]) -> set[tuple[str, tuple[tuple[str, int], ...]]]:
    actions = flow.get("next_actions")
    assert isinstance(actions, list)

    normalized: set[tuple[str, tuple[tuple[str, int], ...]]] = set()
    for action in actions:
        assert isinstance(action, dict)
        tool = action.get("tool")
        args = action.get("arguments")
        if not isinstance(tool, str):
            continue
        if not isinstance(args, dict):
            continue
        normalized.add((tool, tuple(sorted((str(key), int(value)) for key, value in args.items()))))
    return normalized


def test_attach_hf_flow_preserves_endpoint_root_keys_and_adds_sibling() -> None:
    payload = {
        "posts": [{"pid": "7", "tid": "123", "subject": "Hello"}],
        "page": "1",
    }

    flow = build_hf_flow(tool_name="posts.read", normalized_payload=payload, arguments={"tid": 123})
    enriched = attach_hf_flow(payload, flow)

    assert FLOW_KEY == "_hf_flow"
    assert enriched["posts"] == payload["posts"]
    assert enriched["page"] == "1"
    assert isinstance(enriched[FLOW_KEY], dict)


def test_build_hf_flow_sets_version_and_breadcrumbs_from_source() -> None:
    flow = build_hf_flow(
        tool_name="forums.read",
        normalized_payload={"forums": [{"fid": "375"}]},
        arguments={"fid": 375},
        source="forums.index",
    )

    assert flow["version"] == 1
    assert flow["breadcrumbs"] == ["forums.index", "forums.read"]


def test_forums_read_actions_include_threads_and_child_forums_only_with_real_child_fids() -> None:
    payload = {
        "forums": [
            {
                "fid": "375",
                "name": "General",
                "children": [
                    {"fid": "901", "name": "Subforum"},
                    {"fid": "0", "name": "Invalid"},
                    {"name": "Missing"},
                ],
            }
        ]
    }

    flow = build_hf_flow(tool_name="forums.read", normalized_payload=payload, arguments={"fid": 375})

    entities = flow["entities"]
    assert entities["forum_ids"] == [375, 901]
    actions = _actions_as_tuples(flow)
    assert ("threads.read", (("fid", 375),)) in actions
    assert ("forums.read", (("fid", 901),)) in actions
    assert ("forums.read", (("fid", 375),)) not in actions


def test_threads_read_actions_include_posts_users_and_forums_when_ids_exist() -> None:
    payload = {
        "threads": [
            {
                "tid": "6324346",
                "fid": "12",
                "uid": "5",
                "firstpost": {"author": {"uid": "44"}},
            }
        ]
    }

    flow = build_hf_flow(tool_name="threads.read", normalized_payload=payload, arguments={"fid": 12})

    entities = flow["entities"]
    assert entities["thread_ids"] == [6324346]
    assert entities["forum_ids"] == [12]
    assert entities["user_ids"] == [5, 44]
    actions = _actions_as_tuples(flow)
    assert ("posts.read", (("tid", 6324346),)) in actions
    assert ("users.read", (("uid", 5),)) in actions
    assert ("users.read", (("uid", 44),)) in actions
    assert ("forums.read", (("fid", 12),)) in actions


def test_posts_read_actions_include_post_specific_rereads_only_when_pid_exists() -> None:
    flow_without_pid = build_hf_flow(
        tool_name="posts.read",
        normalized_payload={"posts": [{"subject": "No identifiers"}]},
        arguments={},
    )
    assert flow_without_pid["next_actions"] == []

    flow_with_ids = build_hf_flow(
        tool_name="posts.read",
        normalized_payload={"posts": [{"pid": "7", "tid": "6324346", "uid": "5", "fid": "12"}]},
        arguments={},
    )
    actions = _actions_as_tuples(flow_with_ids)
    assert ("posts.read", (("pid", 7),)) in actions
    assert ("threads.read", (("tid", 6324346),)) in actions
    assert ("users.read", (("uid", 5),)) in actions
    assert ("forums.read", (("fid", 12),)) in actions


def test_extended_flow_collects_contract_dispute_rating_and_sigmarket_entities() -> None:
    contracts_flow = build_hf_flow(
        tool_name="contracts.read",
        normalized_payload={
            "contracts": [
                {
                    "cid": "7",
                    "tid": "1234",
                    "inituid": "99",
                    "otheruid": "77",
                    "idispute": "11",
                    "odispute": "12",
                    "ibrating": "31",
                    "obrating": "32",
                }
            ]
        },
        arguments={},
    )
    entities = contracts_flow["entities"]
    assert entities["contract_ids"] == [7]
    assert entities["dispute_ids"] == [11, 12]
    assert entities["rating_ids"] == [31, 32]
    assert entities["thread_ids"] == [1234]
    assert entities["user_ids"] == [77, 99]

    order_flow = build_hf_flow(
        tool_name="sigmarket.order.read",
        normalized_payload={"sigmarket/order": [{"smid": "17", "buyer": "2047020", "seller": "1"}]},
        arguments={},
    )
    assert order_flow["entities"]["sigmarket_listing_ids"] == [17]
    assert order_flow["entities"]["user_ids"] == [1, 2047020]


def test_extended_flow_next_actions_include_expected_read_pivots_and_confirmation_gate() -> None:
    bytes_flow = build_hf_flow(
        tool_name="bytes.read",
        normalized_payload={"bytes": [{"uid": "42"}]},
        arguments={},
    )
    bytes_actions = _actions_as_tuples(bytes_flow)
    assert ("users.read", (("uid", 42),)) in bytes_actions
    assert ("bytes.transfer", (("target_uid", 42),)) in bytes_actions
    transfer_actions = [action for action in bytes_flow["next_actions"] if action["tool"] == "bytes.transfer"]
    assert transfer_actions
    assert all(action.get("requires_confirmation") is True for action in transfer_actions)

    disputes_flow = build_hf_flow(
        tool_name="disputes.read",
        normalized_payload={"disputes": [{"cdid": "11", "contractid": "7", "dispute_tid": "4321", "claimantuid": "9"}]},
        arguments={},
    )
    disputes_actions = _actions_as_tuples(disputes_flow)
    assert ("contracts.read", (("cid", 7),)) in disputes_actions
    assert ("threads.read", (("tid", 4321),)) in disputes_actions
    assert ("users.read", (("uid", 9),)) in disputes_actions
    assert ("bratings.read", (("cid", 7),)) in disputes_actions

    market_flow = build_hf_flow(
        tool_name="sigmarket.market.read",
        normalized_payload={"sigmarket/market": [{"uid": "2047020"}]},
        arguments={},
    )
    market_actions = _actions_as_tuples(market_flow)
    assert ("users.read", (("uid", 2047020),)) in market_actions
    assert ("sigmarket.order.read", (("uid", 2047020),)) in market_actions


def test_write_flow_next_actions_include_post_action_reads_when_ids_exist() -> None:
    thread_create_flow = build_hf_flow(
        tool_name="threads.create",
        normalized_payload={"threads": [{"tid": "6324346", "fid": "375"}]},
        arguments={"fid": 375},
    )
    thread_actions = _actions_as_tuples(thread_create_flow)
    assert ("threads.read", (("tid", 6324346),)) in thread_actions
    assert ("posts.read", (("tid", 6324346),)) in thread_actions
    assert ("forums.read", (("fid", 375),)) in thread_actions

    reply_flow = build_hf_flow(
        tool_name="posts.reply",
        normalized_payload={"posts": [{"tid": "6324346", "pid": "9001"}]},
        arguments={"tid": 6324346},
    )
    reply_actions = _actions_as_tuples(reply_flow)
    assert ("posts.read", (("tid", 6324346),)) in reply_actions

    bytes_transfer_flow = build_hf_flow(
        tool_name="bytes.transfer",
        normalized_payload={"bytes": [{"uid": "2047020"}]},
        arguments={"target_uid": 2047020},
    )
    transfer_actions = _actions_as_tuples(bytes_transfer_flow)
    assert ("bytes.read", (("uid", 2047020),)) in transfer_actions
    assert ("users.read", (("uid", 2047020),)) in transfer_actions

    no_id_bytes_flow = build_hf_flow(
        tool_name="bytes.deposit",
        normalized_payload={"ok": True},
        arguments={},
    )
    assert no_id_bytes_flow["next_actions"] == []


def test_formatting_preflight_flow_targets_local_draft_tools_only_when_artifact_exists() -> None:
    flow = build_hf_flow(
        tool_name="formatting.preflight",
        normalized_payload={"draft_id": "a" * 32},
        arguments={},
    )

    action_tools = _action_tools(flow)
    assert set(action_tools) == {"drafts.list", "drafts.read", "drafts.update"}
    assert all(not tool.startswith(("threads.", "posts.", "bytes.")) for tool in action_tools)

    no_artifact_flow = build_hf_flow(
        tool_name="formatting.preflight",
        normalized_payload={"integrity": 1.0},
        arguments={},
    )
    assert no_artifact_flow["next_actions"] == []


def test_local_draft_flow_chain_emits_local_followups_only() -> None:
    draft_one = "a" * 32
    draft_two = "b" * 32
    list_flow = build_hf_flow(
        tool_name="drafts.list",
        normalized_payload={"drafts": [{"draft_id": draft_one}, {"draft_id": draft_two}]},
        arguments={},
    )
    assert set(_action_tools(list_flow)) == {"drafts.read"}

    read_flow = build_hf_flow(
        tool_name="drafts.read",
        normalized_payload={"draft_id": draft_one},
        arguments={},
    )
    assert set(_action_tools(read_flow)) == {"drafts.update", "drafts.delete", "formatting.preflight"}

    update_flow = build_hf_flow(
        tool_name="drafts.update",
        normalized_payload={"draft_id": draft_one},
        arguments={},
    )
    assert set(_action_tools(update_flow)) == {"drafts.list", "drafts.read"}

    delete_flow = build_hf_flow(
        tool_name="drafts.delete",
        normalized_payload={"draft_id": draft_one, "deleted": True},
        arguments={},
    )
    assert set(_action_tools(delete_flow)) == {"drafts.list"}
