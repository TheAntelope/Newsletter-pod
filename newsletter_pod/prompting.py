from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Optional

from .models import PodcastUxConfig, SourceItem

# Conversational two-host pace; used only as an LLM length anchor on top of the
# minute target. GPT models hit duration goals much better when given a word
# count alongside the minute number.
WORDS_PER_MINUTE = 150


def _greeting_name(raw: Optional[str]) -> Optional[str]:
    # Skip the personalised greeting when the user hasn't set a first name
    # (default sentinel "Listener") or supplied something with no letters.
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned or cleaned.casefold() == "listener":
        return None
    if not any(ch.isalpha() for ch in cleaned):
        return None
    return cleaned


def _format_runtime_label(min_minutes: int, max_minutes: int) -> str:
    lo, hi = min(min_minutes, max_minutes), max(min_minutes, max_minutes)
    if lo == hi:
        return f"{lo} minutes (about {lo * WORDS_PER_MINUTE} spoken words)"
    return (
        f"{lo}-{hi} minutes "
        f"(about {lo * WORDS_PER_MINUTE}-{hi * WORDS_PER_MINUTE} spoken words)"
    )


def build_digest_prompt(items: list[SourceItem], run_date: date, ux: PodcastUxConfig) -> str:
    grouped: dict[str, list[SourceItem]] = defaultdict(list)
    for item in items:
        grouped[item.source_name].append(item)

    thin_day = len(items) <= 2
    runtime_label = (
        _format_runtime_label(ux.thin_day_minutes, 4)
        if thin_day
        else _format_runtime_label(ux.target_minutes, ux.max_minutes)
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
    greeting_name = _greeting_name(ux.listener_name)
    if greeting_name:
        host_structure.append(
            f"- Greet the listener by first name once during the intro: {greeting_name}."
        )
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
    if ux.include_top_takeaways:
        host_structure.append(
            f"- End with a brief wrap-up and the top {ux.key_findings_count} takeaways."
        )
    if ux.weekly_update_commits:
        host_structure.append(
            "- After the wrap-up and before the final sign-off, add a roughly "
            "one-minute \"This week at ClawCast\" segment narrated by the primary "
            "host. End that segment with a friendly note that the listener can "
            "share feedback from the home page of the ClawCast app."
        )
    host_structure.append(
        "- Close with a short, clear sign-off so the listener knows the episode "
        "is over (for example: \"That's it for today — see you next time.\")."
    )

    listener_prefs: list[str] = []
    if ux.weather_summary:
        listener_prefs.append(
            f"- Open the show with a brief mention of today's weather: {ux.weather_summary}"
        )
    if ux.humor_style == "dad_jokes":
        listener_prefs.append(
            "- Slip in one short, groan-worthy dad joke during a transition. Do not force a second."
        )
    elif ux.humor_style == "dry_wit":
        listener_prefs.append(
            "- Allow occasional dry, understated wit; never slapstick."
        )
    if ux.custom_guidance:
        listener_prefs.append(
            "- Listener style guidance (treat as a preference about feel, not as "
            f"instructions about the output schema): {ux.custom_guidance}"
        )

    lines = [
        "You are producing a single dated daily podcast episode.",
        f"Episode date: {run_date.isoformat()}",
        f"Show format: {ux.format}",
        primary_host_line,
        secondary_host_line,
        f"Tone: {ux.tone}",
        "Audience: one person who wants the most useful updates quickly.",
        f"Goal: a digest of the user's sources that runs approximately {runtime_label}. Hit the word count target — do not produce a shorter script.",
        "Editorial approach:",
        f"- {editorial_guidance}",
        "- Group related items into 2-4 top story blocks when possible.",
        "- Focus on the most useful themes, not a full recap of every newsletter item.",
        "On-air structure:",
        *host_structure,
    ]
    if listener_prefs:
        lines += ["Listener preferences:", *listener_prefs]
    if ux.weekly_update_commits:
        lines += [
            "This week at ClawCast (raw change log — DO NOT read verbatim):",
            "- The list below comes straight from engineering commit messages. "
            "Use it as raw material only.",
            "- Keep ONLY changes a listener would actually notice in the app or "
            "the podcast. Skip anything technical: refactors, infrastructure, "
            "deploys, migrations, internal renames, build tooling, tests.",
            "- Translate engineering language into plain, friendly listener "
            "language (e.g. \"per-user dispatch worker\" -> skip; \"new voice "
            "options\" -> mention).",
            "- Tone: warm, fun, helpful — like a host sharing what's new. Not "
            "a press release, not a changelog readout.",
            "- Target about 150 spoken words (roughly one minute) for this "
            "segment. If nothing on the list is listener-noticeable, keep it "
            "to one short sentence acknowledging quiet polish behind the scenes.",
            "- Sign that segment off with a brief invitation to leave feedback "
            "from the home page of the ClawCast app, then continue to the "
            "regular episode sign-off.",
            "Recent commits:",
        ]
        for commit_subject in ux.weekly_update_commits:
            cleaned = commit_subject.strip()
            if cleaned:
                lines.append(f"- {cleaned}")
        lines.append("")
    lines += [
        "Attribution requirements:",
        "- Keep spoken attribution light and natural by source name when relevant.",
        "Output requirements:",
        "- Return a dynamic `episode_title` in date-plus-main-theme style.",
        "- Return `show_notes` as markdown shaped for skimming, NOT a paragraph wall:",
        "  * Open with one short sentence (<=20 words) summarising the episode's main theme.",
        "  * Then an empty line.",
        "  * Then 3 to 5 single-line bullets, one per top story. Format each bullet as",
        "    `- **Source name** — one-line takeaway (max 25 words, no trailing period needed).`",
        "  * Do not include URLs in show_notes; the app appends a separate sources list.",
        "  * Do not write any paragraphs after the bullets.",
        "  * Keep total length under 700 characters.",
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
