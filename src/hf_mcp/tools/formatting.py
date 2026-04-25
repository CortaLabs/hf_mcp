from __future__ import annotations

from pathlib import Path
from typing import Any

from hf_mcp.formatting_engine import write_draft_artifact
from hf_mcp.flow import attach_hf_flow, build_hf_flow


def preflight_formatting(
    *,
    message: str | None = None,
    source_path: str | None = None,
    message_format: str = "markdown",
    draft_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact = write_draft_artifact(message, message_format, draft_dir=draft_dir, source_path=source_path)
    summary = artifact.summary()
    summary["content"] = [
        {
            "type": "text",
            "text": (
                "formatting.preflight prepared draft "
                f"{artifact.draft_id} with integrity {artifact.report.integrity}."
            ),
        }
    ]
    structured_content = {
        "draft_id": artifact.draft_id,
        "path": artifact.path,
        "integrity": artifact.report.integrity,
        "issues": summary["issues"],
        "mycode_preview": summary["mycode_preview"],
        "simulated_agent_markdown_preview": summary["simulated_agent_markdown_preview"],
    }
    flow = build_hf_flow(
        tool_name="formatting.preflight",
        normalized_payload=structured_content,
    )
    summary["structuredContent"] = attach_hf_flow(structured_content, flow)
    return summary


def build_formatting_handlers(*, draft_dir: str | Path | None = None) -> dict[str, Any]:
    def _preflight_handler(
        *,
        message: str | None = None,
        source_path: str | None = None,
        message_format: str = "markdown",
    ) -> dict[str, Any]:
        return preflight_formatting(
            message=message,
            source_path=source_path,
            message_format=message_format,
            draft_dir=draft_dir,
        )

    return {"formatting.preflight": _preflight_handler}


__all__ = ["build_formatting_handlers", "preflight_formatting"]
