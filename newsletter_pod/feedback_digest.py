from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import requests

from .translation import OPENAI_DEFAULT_BASE_URL, TranslationError, _extract_output_text
from .user_models import FeedbackRecord, UserRecord

logger = logging.getLogger(__name__)


JOB_STATE_NAME = "feedback_weekly_digest"


def summarize_feedback_with_llm(
    records: list[FeedbackRecord],
    *,
    api_key: Optional[str],
    text_model: str,
    base_url: Optional[str] = None,
    timeout_seconds: int = 60,
) -> str:
    """Ask the text model to synthesize themes across the week's feedback. The
    model sees only the English text (falling back to raw_text when translation
    wasn't available) so it isn't asked to translate as well as summarize."""
    if not api_key:
        raise TranslationError("OpenAI API key is not configured")
    if not records:
        return ""

    instruction_lines = [
        "You are summarizing user feedback for a product founder.",
        "Identify the recurring themes, pain points, feature requests, and praise.",
        "Group by theme, not by individual user.",
        "Be concise: 4-8 bullet points total, each one sentence.",
        "Quote distinctive user wording sparingly when it sharpens the point.",
        "If there is only one item, paraphrase it in one sentence.",
        "Return plain text only — no markdown headings, no preamble.",
    ]

    lines: list[str] = []
    for index, record in enumerate(records, start=1):
        text = (record.english_text or record.raw_text or "").strip()
        if not text:
            continue
        lines.append(f"[{index}] ({record.source}) {text}")

    payload = {
        "model": text_model,
        "input": [
            {
                "role": "system",
                "content": [
                    {"type": "input_text", "text": "\n".join(instruction_lines)}
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "\n".join(lines)}
                ],
            },
        ],
    }

    endpoint = _build_endpoint(base_url)
    response = requests.post(
        endpoint,
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return _extract_output_text(response.json())


def format_digest_email(
    records: list[FeedbackRecord],
    *,
    summary: Optional[str],
    since: Optional[datetime],
    now: datetime,
    users_by_id: dict[str, UserRecord],
) -> tuple[str, str]:
    """Build (subject, body) for the weekly digest. Records are expected to be
    sorted newest-first. `since=None` indicates this is the first-ever digest
    and therefore contains everything ever submitted."""

    window_label = _format_window_label(since, now)
    count = len(records)

    if count == 0:
        subject = f"ClawCast feedback digest — no feedback {window_label}"
        body_lines = [
            f"No feedback {window_label}.",
            "",
            "The weekly digest will fire again next week.",
        ]
        return subject, "\n".join(body_lines)

    noun = "item" if count == 1 else "items"
    qualifier = " (all-time, first digest)" if since is None else ""
    subject = (
        f"ClawCast feedback digest — {count} {noun} {window_label}{qualifier}"
    )

    body_lines: list[str] = []
    body_lines.append(f"Feedback {window_label}: {count} {noun}{qualifier}.")
    body_lines.append("")
    if summary:
        body_lines.append("Summary")
        body_lines.append("-------")
        body_lines.append(summary.strip())
        body_lines.append("")

    body_lines.append("Raw feedback (newest first)")
    body_lines.append("---------------------------")
    for record in records:
        body_lines.extend(_format_record(record, users_by_id))
        body_lines.append("")

    return subject, "\n".join(body_lines).rstrip() + "\n"


def _format_record(
    record: FeedbackRecord, users_by_id: dict[str, UserRecord]
) -> list[str]:
    user = users_by_id.get(record.user_id)
    when = record.created_at.strftime("%Y-%m-%d %H:%M UTC")
    user_label = _format_user_label(record.user_id, user)
    header = f"- {when} | {user_label} | source={record.source}"

    lines = [header]
    raw = (record.raw_text or "").strip()
    english = (record.english_text or "").strip()
    if english and english != raw:
        lines.append(f"  EN: {english}")
        lines.append(f"  RAW: {raw}")
    else:
        lines.append(f"  {raw}")
    return lines


def _format_user_label(user_id: str, user: Optional[UserRecord]) -> str:
    if user is None:
        return f"user={user_id}"
    parts = [f"user={user_id}"]
    if user.display_name and user.display_name != "Listener":
        parts.append(user.display_name)
    if user.email:
        parts.append(user.email)
    return " ".join(parts)


def _format_window_label(since: Optional[datetime], now: datetime) -> str:
    if since is None:
        return "(all time)"
    since_str = since.strftime("%Y-%m-%d")
    now_str = now.strftime("%Y-%m-%d")
    if since_str == now_str:
        return f"on {now_str}"
    return f"from {since_str} to {now_str}"


def _build_endpoint(base_url: Optional[str]) -> str:
    base = (base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/responses"
    return f"{base}/v1/responses"
