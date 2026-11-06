from __future__ import annotations

from pathlib import Path

import pytest

from hf_mcp.draft_store import read_cached_source_text, write_draft_artifact
from hf_mcp.registry import MAX_MESSAGE_CHARS
from hf_mcp.tools.drafts import delete_draft, list_drafts, read_draft, update_draft

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"


def test_draft_source_ceiling_is_the_shared_limit_at_the_limit_and_one_over(
    tmp_path: Path,
) -> None:
    at_limit = tmp_path / "at-limit.md"
    at_limit.write_text("a" * MAX_MESSAGE_CHARS, encoding="utf-8")
    over = tmp_path / "over.md"
    over.write_text("a" * (MAX_MESSAGE_CHARS + 1), encoding="utf-8")

    assert len(read_cached_source_text(at_limit, draft_dir=tmp_path)) == (
        MAX_MESSAGE_CHARS
    )
    with pytest.raises(ValueError, match="too large"):
        read_cached_source_text(over, draft_dir=tmp_path)


def _action_tools(result: dict[str, object]) -> set[str]:
    structured = result.get("structuredContent")
    assert isinstance(structured, dict)
    flow = structured.get("_hf_flow")
    assert isinstance(flow, dict)
    actions = flow.get("next_actions")
    assert isinstance(actions, list)
    return {str(action.get("tool")) for action in actions if isinstance(action, dict)}


def test_list_and_read_draft_emit_local_flow_actions_only(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    first = write_draft_artifact("first body", draft_dir=draft_root)
    second = write_draft_artifact("second body", draft_dir=draft_root)

    listed = list_drafts(draft_dir=draft_root, limit=10, offset=0)
    assert listed["count"] == 2
    assert listed["structuredContent"]["count"] == 2
    assert _action_tools(listed) == {"drafts.read"}

    listed_actions = listed["structuredContent"]["_hf_flow"]["next_actions"]
    assert {action["arguments"]["draft_id"] for action in listed_actions} == {
        first.draft_id,
        second.draft_id,
    }
    for action in listed_actions:
        assert "draft_path" not in action.get("arguments", {})

    read_result = read_draft(draft_dir=draft_root, draft_id=first.draft_id)
    assert read_result["structuredContent"]["metadata"]["status"] == "draft"
    assert _action_tools(read_result) == {
        "drafts.update",
        "drafts.delete",
        "formatting.preflight",
    }


def test_update_and_delete_emit_local_followups_and_preserve_structured_metadata(
    tmp_path: Path,
) -> None:
    draft_root = tmp_path / "drafts"
    artifact = write_draft_artifact("mutable", draft_dir=draft_root)

    updated = update_draft(
        draft_dir=draft_root,
        draft_id=artifact.draft_id,
        title="Ops Note",
        category="ops",
        status="ready",
    )
    metadata = updated["structuredContent"]["metadata"]
    assert metadata["title"] == "Ops Note"
    assert metadata["category"] == "ops"
    assert metadata["status"] == "ready"
    assert _action_tools(updated) == {"drafts.list", "drafts.read"}

    deleted = delete_draft(
        draft_dir=draft_root,
        draft_id=artifact.draft_id,
        confirm_delete=True,
    )
    assert deleted["structuredContent"]["deleted"] is True
    assert _action_tools(deleted) == {"drafts.list"}


def test_read_returns_full_stored_mycode_while_list_keeps_previews(
    tmp_path: Path,
) -> None:
    source = (
        " ".join(f"word{n}" for n in range(600))
        + "\n\n![logo](https://example.com/a.png)"
    )
    artifact = write_draft_artifact(source, "markdown", draft_dir=tmp_path)

    read_result = read_draft(draft_dir=tmp_path, draft_id=artifact.draft_id)
    for payload in (read_result, read_result["structuredContent"]):
        assert payload["mycode"] == artifact.report.mycode
        assert len(payload["mycode"]) > 2000
        assert payload["source_text"] == source
        assert [f["code"] for f in payload["conversion_findings"]] == ["image_alt_loss"]

    listed = list_drafts(draft_dir=tmp_path)["drafts"][0]
    assert "mycode" not in listed
    assert "source_text" not in listed
    assert "conversion_findings" not in listed
    assert len(listed["mycode_preview"]) <= 500
