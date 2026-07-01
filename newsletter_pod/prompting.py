from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Optional

from .blueprint import ShowBlueprint
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


def _segment_plan_lines(
    blueprint: ShowBlueprint,
    ux: PodcastUxConfig,
    skip_closing: bool,
    market_hints: Optional[list[str]] = None,
) -> list[str]:
    """Turn the blueprint's enabled sections into an ordered, budgeted plan the
    script LLM must follow, tagging each produced segment with its `section`.

    Sections are gated by what's actually available for this episode: weather is
    dropped when the per-user gate left no summary, the closing is dropped on the
    live path (a separate stage-2 call owns it), announcements are dropped when
    there's nothing to announce, and the market section only appears when
    relevance-matched hints were supplied (Phase E).
    """
    announcements_text = (blueprint.closing.announcements_text or "").strip()
    plan: list[str] = []
    n = 0
    for section in blueprint.enabled_sections():
        kind = section.kind
        if kind == "weather" and not ux.weather_summary:
            continue
        if kind == "closing" and skip_closing:
            continue
        if kind == "market" and not market_hints:
            continue
        if kind == "announcements" and not announcements_text:
            continue

        n += 1
        words = section.effective_words()
        if kind == "story_block":
            max_blocks = section.max_blocks or 4
            detail = (
                f"section=story_block — the {max_blocks} most useful stories, each its "
                f"own segment of about {words} spoken words. Group related items into a "
                "single block rather than reading every item."
            )
        elif kind == "cold_open":
            detail = (
                f"section=cold_open — about {words} spoken words. Open the episode with a "
                "hook and one sentence on what today is about."
            )
        elif kind == "headlines":
            detail = (
                f"section=headlines — about {words} spoken words. A fast scan of today's "
                "top items, one clause each, before the detail."
            )
        elif kind == "weather":
            detail = (
                f"section=weather — about {words} spoken words. Work in today's weather: "
                f"{ux.weather_summary}"
            )
        elif kind == "market":
            detail = (
                f"section=market — about {words} spoken words. Fold in the prediction-market "
                "context below as colour on a related story (cite as current odds, not fact)."
            )
        elif kind == "announcements":
            detail = (
                f'section=announcements — read this announcement aloud, naturally: '
                f'"{announcements_text}"'
            )
        elif kind == "closing":
            detail = (
                f"section=closing — about {words} spoken words. Wrap up and sign off."
            )
            if blueprint.closing.signoff_override:
                detail += f' End on: "{blueprint.closing.signoff_override.strip()}"'
        else:  # pragma: no cover - enum keeps this unreachable
            detail = f"section={kind} — about {words} spoken words."

        if section.instructions and section.instructions.strip():
            detail += f" {section.instructions.strip()}"
        plan.append(f"{n}. {detail}")

    return [
        "Segment plan — produce `audio_segments` in EXACTLY this order and tag each "
        "segment with its `section`. Do NOT add, drop, reorder, or merge sections. "
        "Every section except `story_block` appears at most once; `story_block` may "
        "repeat (one segment per story):",
        *plan,
    ]


def build_digest_prompt(
    items: list[SourceItem],
    run_date: date,
    ux: PodcastUxConfig,
    skip_closing: bool = False,
    market_hints: Optional[list[str]] = None,
) -> str:
    grouped: dict[str, list[SourceItem]] = defaultdict(list)
    for item in items:
        grouped[item.source_name].append(item)

    has_podcast = any(item.kind == "podcast" for item in items)

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
    if not skip_closing:
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
    elif ux.humor_style == "witty":
        listener_prefs.append(
            "- Work in quick, clever asides and sharp turns of phrase; keep them "
            "brief and smart rather than goofy."
        )
    elif ux.humor_style == "sarcastic":
        listener_prefs.append(
            "- Allow light, knowing sarcasm about the day's absurdities; keep it "
            "good-natured, never mean-spirited, and use it sparingly."
        )
    elif ux.humor_style == "punny":
        listener_prefs.append(
            "- Slip in the occasional pun or bit of wordplay on a transition; "
            "groan-worthy is fine, but don't overdo it."
        )
    elif ux.humor_style == "silly":
        listener_prefs.append(
            "- Keep an upbeat, playful energy with the occasional silly aside; "
            "warm and fun rather than understated."
        )
    if ux.custom_guidance:
        listener_prefs.append(
            "- Listener style guidance (treat as a preference about feel, not as "
            f"instructions about the output schema): {ux.custom_guidance}"
        )

    anchor_phrases: list[str] = []
    if ux.listener_anchors:
        seen_anchors: set[str] = set()
        for raw in ux.listener_anchors:
            cleaned = (raw or "").strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen_anchors:
                continue
            seen_anchors.add(key)
            anchor_phrases.append(cleaned)
            if len(anchor_phrases) >= 8:
                break

    if ux.blueprint is not None:
        # Blueprint drives the section structure; keep the role guidance
        # (host_structure) which is orthogonal to sections.
        structure_block = [
            "Editorial approach:",
            f"- {editorial_guidance}",
            "- Focus on the most useful themes, not a full recap of every newsletter item.",
            "On-air structure:",
            *host_structure,
            *_segment_plan_lines(ux.blueprint, ux, skip_closing, market_hints),
        ]
    else:
        structure_block = [
            "Editorial approach:",
            f"- {editorial_guidance}",
            "- Group related items into 2-4 top story blocks when possible.",
            "- Focus on the most useful themes, not a full recap of every newsletter item.",
            "On-air structure:",
            *host_structure,
        ]

    lines = [
        "You are producing a single dated daily podcast episode.",
        f"Episode date: {run_date.isoformat()}",
        f"Show format: {ux.format}",
        primary_host_line,
        secondary_host_line,
        f"Tone: {ux.tone}",
        "Audience: one person who wants the most useful updates quickly.",
        f"Goal: a digest of the user's sources that runs approximately {runtime_label}. Hit the word count target — do not produce a shorter script.",
        *structure_block,
    ]
    if skip_closing:
        lines.append(
            "Do NOT include takeaways or a sign-off in this script. A separate "
            "closing segment will be generated and appended to the end. Use all "
            "of your word budget on the body."
        )
    else:
        closing_word_budget = max(40, 25 * (1 + len(closing_requirements)))
        lines += [
            "REQUIRED closing phase (the script must always include this — do NOT skip "
            f"to save room; reserve roughly {closing_word_budget} words at the end for it):",
            *closing_requirements,
            "The very last words of the very last audio_segment MUST be the sign-off "
            "above. If you find yourself running out of room, shorten the body — never "
            "the closing. A script that ends mid-discussion is a defect.",
        ]
    if listener_prefs:
        lines += ["Listener preferences:", *listener_prefs]
    if market_hints:
        lines += [
            "Prediction-market context (weave in naturally where it fits a story "
            f"above — at most {len(market_hints)} time(s); cite as current odds, "
            "not fact, and attribute to Polymarket):",
            *market_hints,
        ]
    if anchor_phrases:
        lines += [
            "Listener anchors (things the listener volunteered when they joined or "
            "recently engaged with — names, publications, topics, or phrases):",
            *[f"- {phrase}" for phrase in anchor_phrases],
            (
                "If today's items naturally connect to one of these anchors, "
                "acknowledge the connection briefly and conversationally in the "
                "relevant segment — at most once across the whole episode. Paraphrase, "
                "do not quote verbatim, and never read the list aloud or stack multiple "
                "callbacks. If nothing today connects, do not force a reference."
            ),
        ]
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
            (
                "- End that segment with a brief invitation to leave feedback "
                "from the home page of the ClawCast app."
                if skip_closing
                else "- Sign that segment off with a brief invitation to leave feedback "
                "from the home page of the ClawCast app, then continue to the "
                "regular episode sign-off."
            ),
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
        *(
            [
                "- Items under a \"Podcast:\" heading come from a podcast — attribute "
                "them as an episode (e.g. \"on the latest episode of <name>\"), never "
                "as a newsletter, and summarise from the show notes provided."
            ]
            if has_podcast
            else []
        ),
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
        label = "Podcast" if any(i.kind == "podcast" for i in source_items) else "Source"
        lines.append(f"{label}: {source_name}")
        for item in source_items:
            lines.append(f"- Title: {item.title}")
            lines.append(f"  Link: {item.link}")
            lines.append(f"  Summary: {item.summary}")
        lines.append("")

    return "\n".join(lines).strip()


SHOW_NAME = "ClawCast"


def build_closing_prompt(body_transcript: str, ux: PodcastUxConfig) -> str:
    """Stage-2 prompt: write the closing segment given the finished body.

    Returns a user-message body for a small follow-up call. Output is exactly
    one spoken closing read by the primary host, containing takeaways (when
    enabled) and a sign-off naming the show.
    """
    primary = ux.host_primary_name
    signoff_override = None
    if ux.blueprint is not None and ux.blueprint.closing.signoff_override:
        signoff_override = ux.blueprint.closing.signoff_override.strip()
    parts: list[str] = []
    if ux.include_top_takeaways and ux.key_findings_count > 0:
        parts.append(
            f"- Exactly {ux.key_findings_count} key takeaways from the episode "
            "body, read out as single spoken sentences (not bullets, not "
            f'"here are bullet points"). Lead in with one short transition '
            "sentence."
        )
    if signoff_override:
        parts.append(
            f'- End on this exact sign-off: "{signoff_override}"'
        )
    else:
        parts.append(
            f"- A brief sign-off naming the show ({SHOW_NAME}) and inviting the "
            "listener back next time. Example phrasing: \"That's the briefing for "
            f"today — see you next time on {SHOW_NAME}.\""
        )

    lines = [
        "You are writing the closing segment for a podcast episode whose body "
        "has already been recorded. The body transcript is below. Write the "
        f"closing as a single spoken segment delivered by {primary}.",
        "Required content (in order):",
        *parts,
        "Constraints:",
        "- Output ONE spoken segment. Plain prose, no stage directions, no "
        "speaker labels in the output.",
        "- Reference content that actually appeared in the body — do not "
        "invent new stories.",
        "- Keep total length under 700 words.",
        "- The very last words MUST be the sign-off.",
        "",
        "Episode body transcript:",
        body_transcript,
    ]
    return "\n".join(lines).strip()


def fallback_closing_text() -> str:
    """Deterministic closing used if the stage-2 call fails."""
    return f"That's the briefing for today — see you next time on {SHOW_NAME}."
