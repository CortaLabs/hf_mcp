from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Literal, cast
from uuid import uuid4

from .mycode import MessageFormat, coerce_message_format, format_body_text, format_write_text
from .write_preflight import WritePreflightError, validate_write_body

IssueSeverity = Literal["info", "warn", "error"]
DraftStatus = Literal["draft", "ready", "approved", "archived"]
DEFAULT_DRAFT_DIR = Path.home() / ".config" / "hf_mcp" / "drafts"
_DRAFT_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_SOURCE_SUFFIXES = frozenset({".md", ".mycode", ".txt"})
_MAX_DRAFT_SOURCE_BYTES = 500_000
_DRAFT_STATUSES = {"draft", "ready", "approved", "archived"}

_JSON_LIKE_CODE_PATTERN = re.compile(r"\[(?:code|php)\](?P<body>.*?)\[/\s*(?:code|php)\]", re.IGNORECASE | re.DOTALL)
_DOUBLE_QUOTE_PATTERN = re.compile(r'"')
_GREATER_THAN_PATTERN = re.compile(r">")
_LESS_THAN_PATTERN = re.compile(r"<")


@dataclass(frozen=True, slots=True)
class FormattingIssue:
    code: str
    severity: IssueSeverity
    message: str
    occurrences: int = 1


@dataclass(frozen=True, slots=True)
class FormattingReport:
    source_format: MessageFormat
    source_text: str
    mycode: str
    simulated_hf_mycode: str
    simulated_agent_markdown: str
    integrity: float
    issues: tuple[FormattingIssue, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "source_format": self.source_format,
            "source_text": self.source_text,
            "mycode": self.mycode,
            "simulated_hf_mycode": self.simulated_hf_mycode,
            "simulated_agent_markdown": self.simulated_agent_markdown,
            "integrity": self.integrity,
            "issues": [asdict(issue) for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class DraftArtifact:
    draft_id: str
    path: str
    created_at: str
    metadata: "DraftMetadata"
    report: FormattingReport

    def summary(self) -> dict[str, object]:
        return {
            "draft_id": self.draft_id,
            "path": self.path,
            "created_at": self.created_at,
            "metadata": self.metadata.as_dict(),
            "integrity": self.report.integrity,
            "issues": [asdict(issue) for issue in self.report.issues],
            "issue_summary": _issue_summary(self.report.issues),
            "mycode_preview": _preview(self.report.mycode),
            "simulated_agent_markdown_preview": _preview(self.report.simulated_agent_markdown),
        }


@dataclass(frozen=True, slots=True)
class DraftMetadata:
    title: str | None = None
    category: str | None = None
    status: DraftStatus = "draft"
    scheduled_at: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "category": self.category,
            "status": self.status,
            "scheduled_at": self.scheduled_at,
        }


def prepare_formatting_report(value: str, message_format: str = "mycode") -> FormattingReport:
    source_format = coerce_message_format(message_format, field_name="message_format")
    mycode = format_write_text(value, source_format)
    validation_issues = _validation_issues(mycode, source_format)
    mutation_issues = _mutation_issues(mycode)
    simulated_hf_mycode = simulate_hf_canonicalization(mycode)
    simulated_agent_markdown = format_body_text(simulated_hf_mycode, "markdown")
    issues = validation_issues + mutation_issues
    return FormattingReport(
        source_format=source_format,
        source_text=value,
        mycode=mycode,
        simulated_hf_mycode=simulated_hf_mycode,
        simulated_agent_markdown=simulated_agent_markdown,
        integrity=_integrity_score(issues),
        issues=issues,
    )


def write_draft_artifact(
    value: str | None = None,
    message_format: str = "mycode",
    *,
    draft_dir: str | Path | None = None,
    source_path: str | Path | None = None,
) -> DraftArtifact:
    if value is not None and source_path is not None:
        raise ValueError("Provide either value or source_path, not both.")
    if value is None:
        if source_path is None:
            raise ValueError("A value or source_path is required.")
        value = read_cached_source_text(source_path, draft_dir=draft_dir)
    report = prepare_formatting_report(value, message_format)
    draft_id = uuid4().hex
    root = _resolve_draft_root(draft_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{draft_id}.json"
    payload = {
        "draft_id": draft_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": DraftMetadata().as_dict(),
        "report": report.as_dict(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return DraftArtifact(
        draft_id=draft_id,
        path=str(path),
        created_at=str(payload["created_at"]),
        metadata=DraftMetadata(),
        report=report,
    )


def read_cached_source_text(source_path: str | Path, *, draft_dir: str | Path | None = None) -> str:
    root = _resolve_draft_root(draft_dir)
    path = _resolve_confined_path(path=source_path, draft_root=root, require_exists=True)
    if path.suffix.lower() not in _SOURCE_SUFFIXES:
        raise ValueError("Draft source path must be a .md, .mycode, or .txt file.")
    if path.stat().st_size > _MAX_DRAFT_SOURCE_BYTES:
        raise ValueError("Draft source file is too large.")
    return path.read_text(encoding="utf-8")


def read_draft_artifact(
    *,
    draft_id: str | None = None,
    draft_path: str | Path | None = None,
    draft_dir: str | Path | None = None,
) -> DraftArtifact:
    path = _resolve_draft_path(draft_id=draft_id, draft_path=draft_path, draft_dir=draft_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Draft artifact payload must be an object.")

    stored_draft_id = payload.get("draft_id")
    stored_created_at = payload.get("created_at")
    metadata_payload = payload.get("metadata")
    report_payload = payload.get("report")
    if not isinstance(stored_draft_id, str) or not isinstance(report_payload, dict) or not isinstance(stored_created_at, str):
        raise ValueError("Draft artifact is missing draft_id, created_at, or report.")
    if draft_id is not None and stored_draft_id != draft_id:
        raise ValueError("Draft artifact id does not match the requested draft_id.")

    return DraftArtifact(
        draft_id=stored_draft_id,
        path=str(path),
        created_at=stored_created_at,
        metadata=_metadata_from_payload(metadata_payload),
        report=_report_from_payload(report_payload),
    )


def list_draft_artifacts(
    *,
    draft_dir: str | Path | None = None,
    status: DraftStatus | None = None,
    category: str | None = None,
    title: str | None = None,
    scheduled_before: str | None = None,
    scheduled_after: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DraftArtifact]:
    if limit < 0:
        raise ValueError("limit must be >= 0.")
    if offset < 0:
        raise ValueError("offset must be >= 0.")
    if status is not None:
        _coerce_draft_status(status)

    before_dt = _parse_optional_iso8601(scheduled_before, field_name="scheduled_before")
    after_dt = _parse_optional_iso8601(scheduled_after, field_name="scheduled_after")
    if before_dt is not None and after_dt is not None and before_dt <= after_dt:
        raise ValueError("scheduled_before must be later than scheduled_after.")

    root = _resolve_draft_root(draft_dir)
    if not root.exists():
        return []

    artifacts: list[DraftArtifact] = []
    for path in root.glob("*.json"):
        if not path.is_file():
            continue
        try:
            artifact = read_draft_artifact(draft_path=path, draft_dir=root)
        except (ValueError, FileNotFoundError, json.JSONDecodeError):
            continue
        if status is not None and artifact.metadata.status != status:
            continue
        if category is not None and artifact.metadata.category != category:
            continue
        if title is not None:
            current_title = artifact.metadata.title or ""
            if title.lower() not in current_title.lower():
                continue
        if before_dt is not None or after_dt is not None:
            scheduled_dt = _parse_optional_iso8601(artifact.metadata.scheduled_at, field_name="scheduled_at")
            if scheduled_dt is None:
                continue
            if before_dt is not None and not scheduled_dt < before_dt:
                continue
            if after_dt is not None and not scheduled_dt > after_dt:
                continue
        artifacts.append(artifact)

    sorted_artifacts = sorted(artifacts, key=_draft_sort_key)
    return sorted_artifacts[offset : offset + limit]


def update_draft_metadata(
    *,
    draft_id: str | None = None,
    draft_path: str | Path | None = None,
    draft_dir: str | Path | None = None,
    title: str | None = None,
    category: str | None = None,
    status: DraftStatus | None = None,
    scheduled_at: str | None = None,
) -> DraftArtifact:
    artifact = read_draft_artifact(draft_id=draft_id, draft_path=draft_path, draft_dir=draft_dir)
    metadata = DraftMetadata(
        title=artifact.metadata.title if title is None else title,
        category=artifact.metadata.category if category is None else category,
        status=artifact.metadata.status if status is None else _coerce_draft_status(status),
        scheduled_at=artifact.metadata.scheduled_at if scheduled_at is None else _normalize_optional_iso8601(
            scheduled_at,
            field_name="scheduled_at",
        ),
    )
    path = Path(artifact.path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Draft artifact payload must be an object.")
    payload["metadata"] = metadata.as_dict()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return read_draft_artifact(draft_path=path, draft_dir=draft_dir)


def delete_draft_artifact(
    *,
    draft_id: str | None = None,
    draft_path: str | Path | None = None,
    draft_dir: str | Path | None = None,
    confirm_delete: bool = False,
) -> dict[str, object]:
    if confirm_delete is not True:
        raise ValueError("delete_draft_artifact requires confirm_delete=True.")

    artifact = read_draft_artifact(draft_id=draft_id, draft_path=draft_path, draft_dir=draft_dir)
    path = Path(artifact.path)
    path.unlink(missing_ok=False)
    tombstone = artifact.summary()
    tombstone["deleted"] = True
    tombstone["deleted_at"] = datetime.now(timezone.utc).isoformat()
    return tombstone


def simulate_hf_canonicalization(value: str) -> str:
    simulated = value
    simulated = _DOUBLE_QUOTE_PATTERN.sub("&quot;", simulated)
    simulated = _GREATER_THAN_PATTERN.sub("&gt;", simulated)
    simulated = _LESS_THAN_PATTERN.sub("&lt;", simulated)
    return simulated


def _validation_issues(mycode: str, source_format: MessageFormat) -> tuple[FormattingIssue, ...]:
    try:
        validate_write_body(mycode, source_format=source_format)
    except WritePreflightError as exc:
        return (
            FormattingIssue(
                code="invalid_mycode",
                severity="error",
                message=str(exc),
            ),
        )
    return ()


def _mutation_issues(mycode: str) -> tuple[FormattingIssue, ...]:
    issues: list[FormattingIssue] = []
    quote_count = mycode.count('"')
    if quote_count:
        issues.append(
            FormattingIssue(
                code="double_quote_canonicalization",
                severity="warn",
                message="HF readback may canonicalize double quotes as quote entities.",
                occurrences=quote_count,
            )
        )

    greater_than_count = mycode.count(">")
    less_than_count = mycode.count("<")
    if greater_than_count or less_than_count:
        issues.append(
            FormattingIssue(
                code="angle_bracket_canonicalization",
                severity="warn",
                message="HF readback may HTML-escape angle brackets.",
                occurrences=greater_than_count + less_than_count,
            )
        )

    json_like_blocks = [
        match.group("body")
        for match in _JSON_LIKE_CODE_PATTERN.finditer(mycode)
        if '"' in match.group("body") or "{" in match.group("body") or "}" in match.group("body")
    ]
    if json_like_blocks:
        issues.append(
            FormattingIssue(
                code="json_code_block_lossy_medium",
                severity="warn",
                message="JSON-like code blocks may not round-trip copy-paste cleanly through HF readback.",
                occurrences=len(json_like_blocks),
            )
        )

    return tuple(issues)


def _integrity_score(issues: tuple[FormattingIssue, ...]) -> float:
    score = 1.0
    for issue in issues:
        if issue.severity == "error":
            score -= 0.35
        elif issue.severity == "warn":
            score -= min(0.2, 0.04 * max(1, issue.occurrences))
        else:
            score -= 0.01
    return max(0.0, round(score, 2))


def _preview(value: str, *, limit: int = 500) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _issue_summary(issues: tuple[FormattingIssue, ...]) -> dict[str, object]:
    counts = {"info": 0, "warn": 0, "error": 0}
    for issue in issues:
        counts[issue.severity] += 1
    return {
        "total": len(issues),
        "by_severity": counts,
    }


def _metadata_from_payload(payload: object) -> DraftMetadata:
    if payload is None:
        return DraftMetadata()
    if not isinstance(payload, dict):
        raise ValueError("Draft artifact metadata must be an object when present.")
    status = _coerce_draft_status(str(payload.get("status", "draft")))
    scheduled_at = _normalize_optional_iso8601(payload.get("scheduled_at"), field_name="scheduled_at")
    title = payload.get("title")
    category = payload.get("category")
    if title is not None and not isinstance(title, str):
        raise ValueError("Draft metadata title must be a string when provided.")
    if category is not None and not isinstance(category, str):
        raise ValueError("Draft metadata category must be a string when provided.")
    return DraftMetadata(
        title=title,
        category=category,
        status=status,
        scheduled_at=scheduled_at,
    )


def _normalize_optional_iso8601(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string in ISO-8601 format.")
    value = value.strip()
    if not value:
        return None
    parsed = _parse_iso8601(value, field_name=field_name)
    return parsed.isoformat()


def _parse_optional_iso8601(value: str | None, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    normalized = _normalize_optional_iso8601(value, field_name=field_name)
    if normalized is None:
        return None
    return _parse_iso8601(normalized, field_name=field_name)


def _parse_iso8601(value: str, *, field_name: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO-8601 datetime string.") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_draft_status(status: str) -> DraftStatus:
    if status not in _DRAFT_STATUSES:
        raise ValueError("status must be one of: draft, ready, approved, archived.")
    return cast(DraftStatus, status)


def _draft_sort_key(artifact: DraftArtifact) -> tuple[int, float, str, str]:
    created_at = _parse_optional_iso8601(artifact.created_at, field_name="created_at")
    if created_at is not None:
        return (0, -created_at.timestamp(), Path(artifact.path).name.lower(), artifact.path.lower())
    return (1, 0.0, Path(artifact.path).name.lower(), artifact.path.lower())


def _resolve_draft_path(
    *,
    draft_id: str | None,
    draft_path: str | Path | None,
    draft_dir: str | Path | None,
) -> Path:
    if not draft_id and draft_path is None:
        raise ValueError("A draft_id or draft_path is required.")
    if draft_id is not None and not _DRAFT_ID_PATTERN.fullmatch(draft_id):
        raise ValueError("draft_id must be a 32 character lowercase hex id.")

    root = _resolve_draft_root(draft_dir)
    if draft_id is not None:
        path = root / f"{draft_id}.json"
    else:
        path = Path(draft_path).expanduser()

    resolved = _resolve_confined_path(path=path, draft_root=root, require_exists=True)
    if resolved.suffix != ".json":
        raise ValueError("Draft artifact path must point to a JSON file.")
    return resolved


def _resolve_draft_root(draft_dir: str | Path | None) -> Path:
    root = DEFAULT_DRAFT_DIR if draft_dir is None else Path(draft_dir).expanduser()
    if not root.is_absolute():
        raise ValueError("Draft directory must be absolute.")
    return root.resolve(strict=False)


def _resolve_confined_path(*, path: str | Path, draft_root: Path, require_exists: bool) -> Path:
    candidate = Path(path).expanduser()
    resolved = candidate.resolve(strict=False)
    if draft_root != resolved and draft_root not in resolved.parents:
        raise ValueError("Draft path must be inside the configured draft directory.")
    if require_exists and not resolved.exists():
        raise FileNotFoundError(f"Draft artifact not found: {resolved}")
    return resolved


def _report_from_payload(payload: dict[str, object]) -> FormattingReport:
    issues_payload = payload.get("issues")
    if not isinstance(issues_payload, list):
        raise ValueError("Draft report is missing issues.")
    issues: list[FormattingIssue] = []
    for item in issues_payload:
        if not isinstance(item, dict):
            raise ValueError("Draft report issue entries must be objects.")
        severity = item.get("severity")
        if severity not in {"info", "warn", "error"}:
            raise ValueError("Draft report issue has an invalid severity.")
        issues.append(
            FormattingIssue(
                code=str(item.get("code", "")),
                severity=severity,
                message=str(item.get("message", "")),
                occurrences=int(item.get("occurrences", 1)),
            )
        )

    source_format = coerce_message_format(str(payload.get("source_format", "mycode")), field_name="source_format")
    return FormattingReport(
        source_format=source_format,
        source_text=str(payload.get("source_text", "")),
        mycode=str(payload.get("mycode", "")),
        simulated_hf_mycode=str(payload.get("simulated_hf_mycode", "")),
        simulated_agent_markdown=str(payload.get("simulated_agent_markdown", "")),
        integrity=float(payload.get("integrity", 0.0)),
        issues=tuple(issues),
    )


__all__ = [
    "DraftStatus",
    "DraftMetadata",
    "FormattingIssue",
    "FormattingReport",
    "DraftArtifact",
    "DEFAULT_DRAFT_DIR",
    "delete_draft_artifact",
    "list_draft_artifacts",
    "prepare_formatting_report",
    "read_cached_source_text",
    "read_draft_artifact",
    "simulate_hf_canonicalization",
    "update_draft_metadata",
    "write_draft_artifact",
]
