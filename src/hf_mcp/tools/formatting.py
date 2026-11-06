from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from hf_mcp.config import DEFAULT_TEMPLATES_DIR
from hf_mcp.draft_store import write_draft_artifact
from hf_mcp.registry import MAX_CONVERT_CHARS
from hf_mcp.flow import attach_hf_flow, build_hf_flow
from hf_mcp.formatting_engine import FormattingReport, prepare_formatting_report
from hf_mcp.templates import TemplateUnavailable, get_template, load_templates
from hf_mcp.transport import HFAPIError, build_error


def preflight_formatting(
    *,
    message: str | None = None,
    source_path: str | None = None,
    message_format: str = "markdown",
    draft_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact = write_draft_artifact(
        message, message_format, draft_dir=draft_dir, source_path=source_path
    )
    summary = artifact.summary()
    summary["content"] = [
        {
            "type": "text",
            "text": (
                "formatting.preflight prepared draft "
                f"{artifact.draft_id} with integrity {artifact.report.integrity}. "
                "The full MyCode is in structuredContent.mycode; "
                f"{len(artifact.report.conversion_findings)} conversion finding(s) "
                "are in structuredContent.conversion_findings."
            ),
        }
    ]
    structured_content = {
        "draft_id": artifact.draft_id,
        "path": artifact.path,
        "integrity": artifact.report.integrity,
        "issues": summary["issues"],
        "mycode": artifact.report.mycode,
        "conversion_findings": artifact.report.findings_payload(),
        "mycode_preview": summary["mycode_preview"],
        "simulated_agent_markdown_preview": summary["simulated_agent_markdown_preview"],
    }
    flow = build_hf_flow(
        tool_name="formatting.preflight",
        normalized_payload=structured_content,
    )
    summary["structuredContent"] = attach_hf_flow(structured_content, flow)
    return summary


def _local_result(text: str, structured: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
    }


def _issues_payload(report: FormattingReport) -> list[dict[str, object]]:
    return [asdict(issue) for issue in report.issues]


def convert_formatting(
    *, message: str, message_format: str = "markdown"
) -> dict[str, Any]:
    """Convert message to MyCode; pure, with no file and no network."""
    report = prepare_formatting_report(message, message_format)
    return _local_result(
        "formatting.convert produced MyCode with "
        f"{len(report.conversion_findings)} conversion finding(s) and "
        f"{len(report.issues)} issue(s); the MyCode is in structuredContent.mycode.",
        {
            "mycode": report.mycode,
            "conversion_findings": report.findings_payload(),
            "issues": _issues_payload(report),
        },
    )


def list_templates(*, templates_dir: str | Path) -> dict[str, Any]:
    templates, invalid_count = load_templates(templates_dir)
    return _local_result(
        f"Listed {len(templates)} template(s); {invalid_count} invalid.",
        {
            "templates": [template.summary() for template in templates],
            "invalid_count": invalid_count,
        },
    )


def render_template(
    *,
    templates_dir: str | Path,
    name: str,
    values: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        template = get_template(templates_dir, name)
    except TemplateUnavailable:
        raise HFAPIError(
            build_error(
                "RESOURCE_UNAVAILABLE", operation="local", tool="templates.render"
            )
        ) from None
    source_text = template.fill(values or {})
    if len(source_text) > MAX_CONVERT_CHARS:
        raise ValueError("The rendered template is too large.")
    report = prepare_formatting_report(source_text, template.message_format)
    return _local_result(
        f"Rendered template {template.name} with "
        f"{len(report.conversion_findings)} conversion finding(s).",
        {
            "name": template.name,
            "source_text": source_text,
            "mycode": report.mycode,
            "conversion_findings": report.findings_payload(),
        },
    )


def build_formatting_handlers(
    *,
    draft_dir: str | Path | None = None,
    templates_dir: str | Path = DEFAULT_TEMPLATES_DIR,
) -> dict[str, Any]:
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

    def _convert_handler(
        *, message: str, message_format: str = "markdown"
    ) -> dict[str, Any]:
        return convert_formatting(message=message, message_format=message_format)

    def _list_handler() -> dict[str, Any]:
        return list_templates(templates_dir=templates_dir)

    def _render_handler(
        *, name: str, values: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return render_template(templates_dir=templates_dir, name=name, values=values)

    return {
        "formatting.preflight": _preflight_handler,
        "formatting.convert": _convert_handler,
        "templates.list": _list_handler,
        "templates.render": _render_handler,
    }


__all__ = [
    "build_formatting_handlers",
    "convert_formatting",
    "list_templates",
    "preflight_formatting",
    "render_template",
]
