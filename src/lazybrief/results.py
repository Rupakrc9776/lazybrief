"""Validation and formatting for model-generated briefs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal


class ResultValidationError(ValueError):
    """Raised when a model response does not match the expected brief shape."""


_ACTION_VERBS = (
    "add|analyze|ask|build|call|check|clean|complete|confirm|contact|create|"
    "decide|deliver|deploy|discuss|document|draft|email|evaluate|fix|finish|"
    "follow up|gather|implement|investigate|launch|merge|migrate|organize|"
    "prepare|publish|read|refactor|remove|reply|review|revise|run|schedule|"
    "send|share|start|submit|test|track|update|verify|write"
)
_ACTION_CUE = re.compile(
    rf"\b(?:will|must|should|need(?:s)? to|have to|has to|agreed to|"
    rf"decided to|plan(?:s|ned)? to|committed to)\s+(?:{_ACTION_VERBS})\b"
    rf"|\basked\s+\w+\s+to\s+(?:{_ACTION_VERBS})\b",
    re.IGNORECASE,
)
_IMPERATIVE_CUE = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:(?:task|todo|action item):\s*)?(?:please\s+)?"
    r"(?:review|update|send|create|prepare|ask|test|fix|complete|schedule|"
    r"follow up|confirm|write|read|share|check)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Insight:
    type: Literal["source_fact", "interpretation"]
    text: str
    evidence: list[str]


@dataclass(frozen=True)
class ActionItem:
    task: str
    evidence: list[str]


@dataclass(frozen=True)
class BriefResult:
    summary: str
    insights: list[Insight]
    action_items: list[ActionItem]

    def to_markdown(self) -> str:
        """Format the complete brief for display and download."""
        lines = ["# LazyBrief", "", "## Summary", "", self.summary, "", "## Key insights", ""]
        if self.insights:
            for insight in self.insights:
                label = (
                    "Source-based"
                    if insight.type == "source_fact"
                    else "AI interpretation"
                )
                lines.append(f"- **{label}:** {insight.text}")
                if insight.type == "interpretation":
                    for evidence in insight.evidence:
                        lines.append(f"  - Context cited by model: “{evidence}”")
        else:
            lines.append("- No key insights were returned.")

        lines.extend(["", "## Action items", ""])
        if self.action_items:
            for item in self.action_items:
                lines.append(f"- [ ] {item.task}")
        else:
            lines.append("- No explicit action items found.")
        return "\n".join(lines).strip() + "\n"


def parse_model_response(raw: str, source_text: str) -> BriefResult:
    """Parse model JSON and map cited segment IDs to exact source text."""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ResultValidationError(
            "The model returned malformed JSON. Try again or use a shorter document."
        ) from exc

    if not isinstance(payload, dict):
        raise ResultValidationError("The model response must be a JSON object.")
    if set(payload) != {"summary", "insights"}:
        raise ResultValidationError("The model response has an unexpected JSON shape.")

    summary = _required_text(payload, "summary", 4_000)
    raw_insights = payload.get("insights")
    source_segments = split_source_segments(source_text)
    if not isinstance(raw_insights, list) or len(raw_insights) > 5:
        raise ResultValidationError("The model returned an invalid insights list.")

    insights: list[Insight] = []
    seen_source_facts: set[str] = set()
    for item in raw_insights:
        if not isinstance(item, dict):
            raise ResultValidationError("An insight is not in the expected format.")
        kind = item.get("type")
        text = _required_text(item, "text", 1_000)
        if kind == "source_fact":
            evidence = _resolve_evidence_ids(
                item.get("evidence_ids"), source_segments, required=True
            )
            for source in evidence:
                if source not in seen_source_facts:
                    insights.append(
                        Insight(type="source_fact", text=source, evidence=[source])
                    )
                    seen_source_facts.add(source)
            continue
        elif kind == "interpretation":
            evidence = _resolve_evidence_ids(
                item.get("evidence_ids"), source_segments, required=False
            )
        else:
            raise ResultValidationError("An insight has an unsupported type.")
        insights.append(Insight(type=kind, text=text, evidence=evidence))

    action_items = [
        ActionItem(task=source, evidence=[source])
        for source in source_segments
        if _is_explicit_action(source)
    ]

    return BriefResult(
        summary=summary,
        insights=insights,
        action_items=action_items,
    )


def _required_text(payload: dict[str, object], key: str, max_length: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ResultValidationError(f"The model returned an invalid {key} field.")
    return value.strip()


def split_source_segments(source_text: str) -> list[str]:
    """Split source text into numbered, verbatim citation units."""
    segments: list[str] = []
    paragraphs = re.split(r"\n\s*\n+", source_text.strip())
    for paragraph in paragraphs:
        list_items = re.split(
            r"\n(?=\s*(?:[-*+]\s+|\d+[.)]\s+))",
            paragraph,
        )
        for item in list_items:
            normalized = re.sub(r"\s+", " ", item.strip())
            segments.extend(
                segment
                for segment in re.split(r"(?<=[.!?])\s+", normalized)
                if segment
            )
    return segments


def extract_action_candidates(source_text: str) -> list[str]:
    """Return verbatim source sentences with explicit task/commitment cues."""
    return [
        source
        for source in split_source_segments(source_text)
        if _is_explicit_action(source)
    ]


def _resolve_evidence_ids(
    evidence_ids: object,
    source_segments: list[str],
    *,
    required: bool,
    max_count: int = 3,
) -> list[str]:
    if not isinstance(evidence_ids, list) or len(evidence_ids) > max_count:
        raise ResultValidationError("The model returned invalid source segment IDs.")
    if required and not evidence_ids:
        raise ResultValidationError("A source-based claim needs a source segment.")
    if any(
        type(segment_id) is not int
        or segment_id < 1
        or segment_id > len(source_segments)
        for segment_id in evidence_ids
    ):
        raise ResultValidationError("The model cited a segment ID that does not exist.")
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ResultValidationError("The model returned duplicate source segment IDs.")
    return [source_segments[segment_id - 1] for segment_id in evidence_ids]


def _is_explicit_action(source: str) -> bool:
    return bool(_ACTION_CUE.search(source) or _IMPERATIVE_CUE.search(source))
