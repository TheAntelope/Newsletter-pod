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

    secondary = ux.host_secondary_name.strip() if ux.host_secondary_name else ""
    allowed_roles = ["primary"]
    if ux.format == "solo_host" or not secondary:
        secondary_host_line = "Secondary host: none"
        host_structure.append("- Keep the script as a single-host narration.")
    elif ux.format == "rotating_guest":
        secondary_host_line = f"Current guest: {secondary}"
        host_structure.append(
            "- Both voices must speak. The guest contributes roughly 30-40% of the "
            "spoken words via reactions, follow-up questions, and short hand-offs; "
            "the primary host carries the remaining 60-70%."
        )
        host_structure.append(
            "- The script must contain at least 2 segments tagged role=secondary."
        )
        allowed_roles.append("secondary")
    else:
        secondary_host_line = f"Secondary host: {secondary}"
        host_structure.append(
            "- Both hosts must actually speak. Aim for roughly 60-70% of the spoken "
            "words from the primary host and 30-40% from the secondary host — real "
            "back-and-forth, not just naming the other host. Reactions, follow-up "
            "questions, and short hand-offs all count."
        )
        host_structure.append(
            "- The script must contain at least 2 segments tagged role=secondary."
        )
        allowed_roles.append("secondary")
    closing_requirements: list[str] = []
    if ux.include_top_takeaways:
        closing_requirements.append(
            f"- A brief wrap-up sentence, then the top {ux.key_findings_count} "
            "takeaways read out loud (one per item, single sentence each, "
            "spoken — not 'here are bullet points')."
        )
    if ux.weekly_update_commits:
        closing_requirements.append(
            "- A roughly one-minute \"This week at ClawCast\" segment narrated "
            "by the primary host, ending with a friendly note that the listener "
            "can share feedback from the home page of the ClawCast app."
        )
    closing_requirements.append(
        "- A short, clear sign-off naming the show and inviting the listener "
        "back (for example: \"That's the briefing for today — see you next "
        "time on ClawCast.\")."
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

    closing_word_budget = max(40, 25 * (1 + len(closing_requirements)))
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
        "REQUIRED closing phase (the script must always include this — do NOT skip "
        f"to save room; reserve roughly {closing_word_budget} words at the end for it):",
        *closing_requirements,
        "The very last words of the very last audio_segment MUST be the sign-off "
        "above. If you find yourself running out of room, shorten the body — never "
        "the closing. A script that ends mid-discussion is a defect.",
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
        "- Return `audio_segments` as ordered role-tagged segments.",
        f"- Tag each segment with `role`: one of {', '.join(allowed_roles)}. "
        f"`primary` = {ux.host_primary_name}"
        + (f"; `secondary` = {secondary}." if "secondary" in allowed_roles else "."),
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
