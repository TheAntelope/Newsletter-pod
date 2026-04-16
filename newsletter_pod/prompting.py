from __future__ import annotations

from collections import defaultdict
from datetime import date

from .models import PodcastUxConfig, SourceItem


def build_digest_prompt(items: list[SourceItem], run_date: date, ux: PodcastUxConfig) -> str:
    grouped: dict[str, list[SourceItem]] = defaultdict(list)
    for item in items:
        grouped[item.source_name].append(item)

    thin_day = len(items) <= 2
    runtime_label = (
        f"{ux.thin_day_minutes}-4 minutes"
        if thin_day
        else f"{ux.target_minutes}-{ux.max_minutes} minutes"
    )
    editorial_guidance = (
        "This is a thin-news day. Publish a shorter edition if there are only a few worthwhile items."
        if thin_day
        else "Select the most useful themes and omit lower-value items unless they add necessary context."
    )
    primary_host_line = f"Primary host: {ux.host_primary_name}"
    host_structure = [
        "- Open as a dated daily edition.",
        "- Use the primary host as the main narrator.",
    ]
    allowed_speakers = [ux.host_primary_name]

    secondary = ux.host_secondary_name.strip() if ux.host_secondary_name else ""
    if ux.format == "solo_host" or not secondary:
        secondary_host_line = "Secondary host: none"
        host_structure.append("- Keep the script as a single-host narration.")
    elif ux.format == "rotating_guest":
        secondary_host_line = f"Current guest: {secondary}"
        host_structure.append(
            "- Use the guest only for occasional interjections, clarifying questions, or brief reactions."
        )
        allowed_speakers.append(secondary)
    else:
        secondary_host_line = f"Secondary host: {secondary}"
        host_structure.append(
            "- Use the secondary host only for occasional interjections, clarifying questions, or brief reactions."
        )
        allowed_speakers.append(secondary)
    host_structure.append("- End with a brief wrap-up and the top 3 takeaways.")

    lines = [
        "You are producing a single dated daily podcast episode.",
        f"Episode date: {run_date.isoformat()}",
        f"Show format: {ux.format}",
        primary_host_line,
        secondary_host_line,
        f"Tone: {ux.tone}",
        "Audience: one person who wants the most useful updates quickly.",
        f"Goal: a short business-tech digest that runs approximately {runtime_label}.",
        "Editorial approach:",
        f"- {editorial_guidance}",
        "- Group related items into 2-4 top story blocks when possible.",
        "- Focus on the most useful themes, not a full recap of every newsletter item.",
        "On-air structure:",
        *host_structure,
        "Attribution requirements:",
        "- Keep spoken attribution light and natural by source name when relevant.",
        "- Keep show notes source-rich with links.",
        "Output requirements:",
        "- Return a dynamic `episode_title` in date-plus-main-theme style.",
        "- Return `show_notes` as markdown with source links.",
        "- Return `audio_segments` as ordered speaker-tagged segments.",
        f"- Allowed speakers are only: {', '.join(allowed_speakers)}.",
        "- Do not include stage directions.",
        "",
        "Newsletters to synthesize:",
    ]

    for source_name, source_items in grouped.items():
        lines.append(f"Source: {source_name}")
        for item in source_items:
            lines.append(f"- Title: {item.title}")
            lines.append(f"  Link: {item.link}")
            lines.append(f"  Summary: {item.summary}")
        lines.append("")

    return "\n".join(lines).strip()
