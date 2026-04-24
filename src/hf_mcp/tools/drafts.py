from __future__ import annotations

from pathlib import Path
from typing import Any

from hf_mcp.formatting_engine import (
    delete_draft_artifact,
    list_draft_artifacts,
    read_draft_artifact,
    update_draft_metadata,
)


def _selector_kwargs(*, draft_id: str | None, draft_path: str | Path | None) -> dict[str, Any]:
    has_draft_id = draft_id is not None
    has_draft_path = draft_path is not None
    if has_draft_id == has_draft_path:
        raise ValueError("Provide exactly one of draft_id or draft_path.")
    return {"draft_id": draft_id, "draft_path": draft_path}


def list_drafts(
    *,
    draft_dir: str | Path,
    status: str | None = None,
    category: str | None = None,
    title: str | None = None,
    scheduled_before: str | None = None,
    scheduled_after: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    artifacts = list_draft_artifacts(
        draft_dir=draft_dir,
        status=status,
        category=category,
        title=title,
        scheduled_before=scheduled_before,
        scheduled_after=scheduled_after,
        limit=limit,
        offset=offset,
    )
    summaries = [artifact.summary() for artifact in artifacts]
    return {
        "drafts": summaries,
        "count": len(summaries),
        "limit": limit,
        "offset": offset,
        "content": [
            {
                "type": "text",
                "text": f"Listed {len(summaries)} draft artifact(s) from local cache.",
            }
        ],
        "structuredContent": {
            "drafts": summaries,
            "count": len(summaries),
            "limit": limit,
            "offset": offset,
        },
    }


def read_draft(
    *,
    draft_dir: str | Path,
    draft_id: str | None = None,
    draft_path: str | Path | None = None,
) -> dict[str, Any]:
    selector = _selector_kwargs(draft_id=draft_id, draft_path=draft_path)
    artifact = read_draft_artifact(draft_dir=draft_dir, **selector)
    summary = artifact.summary()
    return {
        **summary,
        "content": [
            {
                "type": "text",
                "text": f"Loaded draft {artifact.draft_id} from local cache.",
            }
        ],
        "structuredContent": summary,
    }


def update_draft(
    *,
    draft_dir: str | Path,
    draft_id: str | None = None,
    draft_path: str | Path | None = None,
    title: str | None = None,
    category: str | None = None,
    status: str | None = None,
    scheduled_at: str | None = None,
) -> dict[str, Any]:
    selector = _selector_kwargs(draft_id=draft_id, draft_path=draft_path)
    artifact = update_draft_metadata(
        draft_dir=draft_dir,
        title=title,
        category=category,
        status=status,
        scheduled_at=scheduled_at,
        **selector,
    )
    summary = artifact.summary()
    return {
        **summary,
        "content": [
            {
                "type": "text",
                "text": f"Updated metadata for draft {artifact.draft_id}.",
            }
        ],
        "structuredContent": summary,
    }


def delete_draft(
    *,
    draft_dir: str | Path,
    draft_id: str | None = None,
    draft_path: str | Path | None = None,
    confirm_delete: bool = False,
) -> dict[str, Any]:
    selector = _selector_kwargs(draft_id=draft_id, draft_path=draft_path)
    tombstone = delete_draft_artifact(
        draft_dir=draft_dir,
        confirm_delete=confirm_delete,
        **selector,
    )
    return {
        **tombstone,
        "content": [
            {
                "type": "text",
                "text": f"Deleted draft {tombstone['draft_id']} from local cache.",
            }
        ],
        "structuredContent": tombstone,
    }


def build_draft_handlers(draft_dir: str | Path) -> dict[str, Any]:
    def _list_handler(
        *,
        status: str | None = None,
        category: str | None = None,
        title: str | None = None,
        scheduled_before: str | None = None,
        scheduled_after: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return list_drafts(
            draft_dir=draft_dir,
            status=status,
            category=category,
            title=title,
            scheduled_before=scheduled_before,
            scheduled_after=scheduled_after,
            limit=limit,
            offset=offset,
        )

    def _read_handler(
        *,
        draft_id: str | None = None,
        draft_path: str | Path | None = None,
    ) -> dict[str, Any]:
        return read_draft(draft_dir=draft_dir, draft_id=draft_id, draft_path=draft_path)

    def _update_handler(
        *,
        draft_id: str | None = None,
        draft_path: str | Path | None = None,
        title: str | None = None,
        category: str | None = None,
        status: str | None = None,
        scheduled_at: str | None = None,
    ) -> dict[str, Any]:
        return update_draft(
            draft_dir=draft_dir,
            draft_id=draft_id,
            draft_path=draft_path,
            title=title,
            category=category,
            status=status,
            scheduled_at=scheduled_at,
        )

    def _delete_handler(
        *,
        draft_id: str | None = None,
        draft_path: str | Path | None = None,
        confirm_delete: bool = False,
    ) -> dict[str, Any]:
        return delete_draft(
            draft_dir=draft_dir,
            draft_id=draft_id,
            draft_path=draft_path,
            confirm_delete=confirm_delete,
        )

    return {
        "drafts.list": _list_handler,
        "drafts.read": _read_handler,
        "drafts.update": _update_handler,
        "drafts.delete": _delete_handler,
    }


__all__ = [
    "build_draft_handlers",
    "delete_draft",
    "list_drafts",
    "read_draft",
    "update_draft",
]
