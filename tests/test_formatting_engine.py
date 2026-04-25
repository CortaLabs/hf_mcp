from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import hf_mcp.formatting_engine as formatting_engine
from hf_mcp.formatting_engine import (
    DraftMetadata,
    prepare_formatting_report,
    delete_draft_artifact,
    list_draft_artifacts,
    read_cached_source_text,
    read_draft_artifact,
    simulate_hf_canonicalization,
    update_draft_metadata,
    write_draft_artifact,
)
from hf_mcp.tools.formatting import preflight_formatting


def test_formatting_report_models_known_hf_quote_mutations() -> None:
    report = prepare_formatting_report(
        '```json\n{"tool":"posts.reply","message_format":"markdown"}\n```',
        "markdown",
    )

    assert report.source_format == "markdown"
    assert report.mycode == '[code]{"tool":"posts.reply","message_format":"markdown"}\n[/code]'
    assert "&quot;tool&quot;" in report.simulated_hf_mycode
    assert report.integrity < 1.0
    assert {issue.code for issue in report.issues} >= {
        "double_quote_canonicalization",
        "json_code_block_lossy_medium",
    }


def test_formatting_report_models_angle_bracket_mutation() -> None:
    report = prepare_formatting_report("Use draft.prepare -> draft.review -> draft.publish", "markdown")

    assert "-&gt;" in report.simulated_hf_mycode
    assert "draft.prepare -> draft.review -> draft.publish" in report.simulated_agent_markdown
    assert any(issue.code == "angle_bracket_canonicalization" for issue in report.issues)


def test_formatting_report_keeps_clean_list_posts_high_integrity() -> None:
    report = prepare_formatting_report(
        "**Update**\n\n- body_format markdown\n- message_format markdown\n- hf-mcp-reads guidance",
        "markdown",
    )

    assert report.mycode == (
        "[b]Update[/b]\n\n"
        "[list]\n"
        "[*] body_format markdown\n"
        "[*] message_format markdown\n"
        "[*] hf-mcp-reads guidance\n"
        "[/list]"
    )
    assert report.integrity == 1.0
    assert report.issues == ()


def test_formatting_report_surfaces_invalid_generated_mycode() -> None:
    report = prepare_formatting_report("[list]\n[*] item", "markdown")

    assert report.integrity < 1.0
    assert report.issues[0].severity == "error"
    assert report.issues[0].code == "invalid_mycode"


def test_simulate_hf_canonicalization_is_predictable_and_narrow() -> None:
    assert simulate_hf_canonicalization('{"a": "b"} -> <tag>') == (
        "{&quot;a&quot;: &quot;b&quot;} -&gt; &lt;tag&gt;"
    )


def test_write_draft_artifact_persists_full_report_and_returns_compact_summary(tmp_path: Path) -> None:
    artifact = write_draft_artifact(
        "**Update**\n\n- body_format markdown\n- message_format markdown",
        "markdown",
        draft_dir=tmp_path,
    )
    summary = artifact.summary()

    assert Path(artifact.path).exists()
    assert Path(artifact.path).parent == tmp_path
    assert summary["draft_id"] == artifact.draft_id
    assert summary["metadata"] == DraftMetadata().as_dict()
    assert isinstance(summary["created_at"], str)
    assert summary["integrity"] == 1.0
    assert "mycode_preview" in summary
    assert "simulated_agent_markdown_preview" in summary
    assert "issue_summary" in summary
    assert '"source_text"' in Path(artifact.path).read_text(encoding="utf-8")
    assert '"metadata"' in Path(artifact.path).read_text(encoding="utf-8")


def test_cached_source_file_can_be_preflighted_and_loaded_from_default_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(formatting_engine, "DEFAULT_DRAFT_DIR", tmp_path / "default-drafts")
    source_path = formatting_engine.DEFAULT_DRAFT_DIR / "approval-draft.md"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("**Approved**\n\n- posted from disk", encoding="utf-8")

    artifact = write_draft_artifact(
        message_format="markdown",
        source_path=source_path,
        draft_dir=formatting_engine.DEFAULT_DRAFT_DIR,
    )
    loaded = read_draft_artifact(draft_id=artifact.draft_id, draft_dir=formatting_engine.DEFAULT_DRAFT_DIR)

    assert read_cached_source_text(
        source_path,
        draft_dir=formatting_engine.DEFAULT_DRAFT_DIR,
    ) == "**Approved**\n\n- posted from disk"
    assert loaded.draft_id == artifact.draft_id
    assert loaded.report.mycode == "[b]Approved[/b]\n\n[list]\n[*] posted from disk\n[/list]"


def test_draft_cache_rejects_paths_outside_tmp_cache(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    draft_root.mkdir(parents=True, exist_ok=True)
    outside_path = tmp_path / "outside.md"
    outside_path.write_text("nope", encoding="utf-8")

    with pytest.raises(ValueError, match="configured draft directory"):
        read_cached_source_text(outside_path, draft_dir=draft_root)


def test_source_path_rejects_disallowed_suffix_inside_configured_root(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    draft_root.mkdir(parents=True, exist_ok=True)
    source_path = draft_root / "approval-draft.html"
    source_path.write_text("<b>nope</b>", encoding="utf-8")

    with pytest.raises(ValueError, match=".md, .mycode, or .txt"):
        write_draft_artifact(message_format="markdown", source_path=source_path, draft_dir=draft_root)


def test_read_draft_artifact_resolves_draft_id_within_configured_root(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    artifact = write_draft_artifact(
        "**Update**\n\n- draft metadata",
        "markdown",
        draft_dir=draft_root,
    )

    loaded = read_draft_artifact(draft_id=artifact.draft_id, draft_dir=draft_root)

    assert Path(loaded.path).parent == draft_root
    assert loaded.draft_id == artifact.draft_id


def test_read_draft_artifact_rejects_draft_path_traversal_outside_configured_root(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    draft_root.mkdir(parents=True, exist_ok=True)
    outside_json = tmp_path / "outside.json"
    outside_json.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="configured draft directory"):
        read_draft_artifact(draft_path=outside_json, draft_dir=draft_root)


def test_read_draft_artifact_defaults_metadata_for_legacy_payload_shape(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    draft_root.mkdir(parents=True, exist_ok=True)
    artifact = write_draft_artifact("legacy payload", draft_dir=draft_root)
    artifact_path = Path(artifact.path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload.pop("metadata", None)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    loaded = read_draft_artifact(draft_id=artifact.draft_id, draft_dir=draft_root)

    assert loaded.metadata.status == "draft"
    assert loaded.metadata.title is None
    assert loaded.metadata.category is None
    assert loaded.metadata.scheduled_at is None


def test_list_draft_artifacts_filters_and_paginates(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    first = write_draft_artifact("first", draft_dir=draft_root)
    second = write_draft_artifact("second", draft_dir=draft_root)
    third = write_draft_artifact("third", draft_dir=draft_root)

    update_draft_metadata(
        draft_id=first.draft_id,
        draft_dir=draft_root,
        title="Alpha note",
        category="ops",
        status="draft",
    )
    update_draft_metadata(
        draft_id=second.draft_id,
        draft_dir=draft_root,
        title="Beta note",
        category="ops",
        status="ready",
    )
    update_draft_metadata(
        draft_id=third.draft_id,
        draft_dir=draft_root,
        title="Gamma",
        category="release",
        status="approved",
    )

    artifacts = list_draft_artifacts(draft_dir=draft_root)
    assert [item.draft_id for item in artifacts] == [third.draft_id, second.draft_id, first.draft_id]

    ready = list_draft_artifacts(draft_dir=draft_root, status="ready")
    assert [item.draft_id for item in ready] == [second.draft_id]

    ops = list_draft_artifacts(draft_dir=draft_root, category="ops")
    assert [item.draft_id for item in ops] == [second.draft_id, first.draft_id]

    beta = list_draft_artifacts(draft_dir=draft_root, title="beta")
    assert [item.draft_id for item in beta] == [second.draft_id]

    paged = list_draft_artifacts(draft_dir=draft_root, limit=1, offset=1)
    assert [item.draft_id for item in paged] == [second.draft_id]


def test_update_draft_metadata_mutates_metadata_only(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    artifact = write_draft_artifact(
        "**Update**\n\n- body_format markdown\n- message_format markdown",
        "markdown",
        draft_dir=draft_root,
    )
    path = Path(artifact.path)
    before = path.read_text(encoding="utf-8")

    updated = update_draft_metadata(
        draft_id=artifact.draft_id,
        draft_dir=draft_root,
        title="Release Draft",
        category="release",
        status="ready",
        scheduled_at="2026-05-01T09:00:00+00:00",
    )
    after = path.read_text(encoding="utf-8")
    before_payload = json.loads(before)
    after_payload = json.loads(after)

    assert updated.metadata.title == "Release Draft"
    assert updated.metadata.category == "release"
    assert updated.metadata.status == "ready"
    assert updated.metadata.scheduled_at == "2026-05-01T09:00:00+00:00"
    assert updated.report.source_text == artifact.report.source_text
    assert updated.report.mycode == artifact.report.mycode
    assert '"title": "Release Draft"' in after
    assert '"category": "release"' in after
    assert '"status": "ready"' in after
    assert '"scheduled_at": "2026-05-01T09:00:00+00:00"' in after
    assert before_payload["report"] == after_payload["report"]


def test_update_draft_metadata_limits_status_to_exact_lifecycle_values(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    artifact = write_draft_artifact("status guard", draft_dir=draft_root)

    for status in ("draft", "ready", "approved", "archived"):
        updated = update_draft_metadata(
            draft_id=artifact.draft_id,
            draft_dir=draft_root,
            status=status,
        )
        assert updated.metadata.status == status

    with pytest.raises(ValueError, match="draft, ready, approved, archived"):
        update_draft_metadata(
            draft_id=artifact.draft_id,
            draft_dir=draft_root,
            status="scheduled",
        )


def test_delete_draft_artifact_requires_confirm_and_confines_paths(tmp_path: Path) -> None:
    draft_root = tmp_path / "drafts"
    artifact = write_draft_artifact("delete me", draft_dir=draft_root)
    path = Path(artifact.path)

    with pytest.raises(ValueError, match="confirm_delete=True"):
        delete_draft_artifact(draft_id=artifact.draft_id, draft_dir=draft_root)

    tombstone = delete_draft_artifact(draft_id=artifact.draft_id, draft_dir=draft_root, confirm_delete=True)
    assert tombstone["deleted"] is True
    assert tombstone["draft_id"] == artifact.draft_id
    assert tombstone["path"] == str(path)
    assert path.exists() is False

    outside_json = tmp_path / "outside.json"
    outside_json.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="configured draft directory"):
        delete_draft_artifact(draft_path=outside_json, draft_dir=draft_root, confirm_delete=True)


def test_preflight_formatting_emits_local_hf_flow_actions_only(tmp_path: Path) -> None:
    result = preflight_formatting(
        message="Local-only preflight body",
        message_format="markdown",
        draft_dir=tmp_path,
    )

    structured = result["structuredContent"]
    assert "_hf_flow" in structured
    flow = structured["_hf_flow"]
    tools = {action["tool"] for action in flow["next_actions"]}
    assert tools == {"drafts.list", "drafts.read", "drafts.update"}
    assert all(not tool.startswith(("threads.", "posts.", "bytes.")) for tool in tools)
    for action in flow["next_actions"]:
        assert "draft_path" not in action.get("arguments", {})
