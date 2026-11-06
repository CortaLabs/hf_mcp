from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Literal

from .mycode import (
    ConversionFinding,
    MessageFormat,
    analyze_conversion,
    coerce_message_format,
    format_body_text,
    format_write_text,
)
from .write_preflight import WritePreflightError, validate_write_body

IssueSeverity = Literal["info", "warn", "error"]

_JSON_LIKE_CODE_PATTERN = re.compile(
    r"\[(?:code|php)\](?P<body>.*?)\[/\s*(?:code|php)\]", re.IGNORECASE | re.DOTALL
)


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
    conversion_findings: tuple[ConversionFinding, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "source_format": self.source_format,
            "source_text": self.source_text,
            "mycode": self.mycode,
            "simulated_hf_mycode": self.simulated_hf_mycode,
            "simulated_agent_markdown": self.simulated_agent_markdown,
            "integrity": self.integrity,
            "issues": [asdict(issue) for issue in self.issues],
            "conversion_findings": self.findings_payload(),
        }

    def findings_payload(self) -> list[dict[str, object]]:
        return [
            {
                "code": finding.code,
                "kind": finding.kind,
                "start": finding.start,
                "end": finding.end,
            }
            for finding in self.conversion_findings
        ]


def prepare_formatting_report(
    value: str, message_format: str = "mycode"
) -> FormattingReport:
    source_format = coerce_message_format(message_format, field_name="message_format")
    mycode = format_write_text(value, source_format)
    validation_issues = _validation_issues(mycode, source_format)
    mutation_issues = _mutation_issues(mycode)
    simulated_hf_mycode = simulate_hf_canonicalization(mycode)
    simulated_agent_markdown = format_body_text(simulated_hf_mycode, "markdown")
    issues = validation_issues + mutation_issues
    findings = analyze_conversion(value, source_format)
    return FormattingReport(
        source_format=source_format,
        source_text=value,
        mycode=mycode,
        simulated_hf_mycode=simulated_hf_mycode,
        simulated_agent_markdown=simulated_agent_markdown,
        integrity=_integrity_score(issues, findings),
        issues=issues,
        conversion_findings=findings,
    )


def simulate_hf_canonicalization(value: str) -> str:
    return value.replace('"', "&quot;").replace(">", "&gt;").replace("<", "&lt;")


def _validation_issues(
    mycode: str, source_format: MessageFormat
) -> tuple[FormattingIssue, ...]:
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
        if '"' in match.group("body")
        or "{" in match.group("body")
        or "}" in match.group("body")
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


def _integrity_score(
    issues: tuple[FormattingIssue, ...],
    findings: tuple[ConversionFinding, ...] = (),
) -> float:
    score = 1.0
    # Anything lost in conversion keeps integrity below 1.0 (0.04 each, capped).
    score -= min(0.2, 0.04 * sum(1 for item in findings if item.kind == "loss"))
    for issue in issues:
        if issue.severity == "error":
            score -= 0.35
        elif issue.severity == "warn":
            score -= min(0.2, 0.04 * max(1, issue.occurrences))
        else:
            score -= 0.01
    return max(0.0, round(score, 2))


__all__ = [
    "FormattingIssue",
    "FormattingReport",
    "prepare_formatting_report",
    "simulate_hf_canonicalization",
]
