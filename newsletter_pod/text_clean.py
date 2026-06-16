"""Shared sanitizer for user-facing card text.

Card summaries reach the swipe deck and the next-pod queue from several
pipelines — RSS ingest, the LLM card-summarizer, Reddit/Substack shares, and
inbound email bodies — and historically each cleaned (or didn't clean) text its
own way. The result was "strange characters" on cards: undecoded HTML entities
(``&amp;``, ``&#39;``), raw markdown (``**bold**``, ``## heading``), and
equation markup (``$E=mc^2$``, ``\\(x\\)``) leaking straight through.

`normalize_card_text` is the single source of truth. It is applied both where
text is produced (ingest, LLM output) and again at serialization, so it MUST be
idempotent for normal inputs — ``normalize_card_text(normalize_card_text(x))``
equals ``normalize_card_text(x)``. The only non-idempotent case is genuinely
multiply-encoded entities (``&amp;amp;``), which converge to the correct fully
decoded character over successive passes — which is the desired behaviour.

The transforms are deliberately conservative to avoid mangling legitimate prose:
prices (``$5 and $10``), identifiers (``C#``, ``snake_case``, ``a*b*c``) and
ranks (``#1``) are left untouched. Math is only stripped when it is
unambiguously delimited.
"""
from __future__ import annotations

import html
import re

# Letter/`!`-anchored so only real HTML tags (and comments/CDATA) match — a bare
# "<[^>]+>" would eat comparison spans like "5 < 10 > 3" once entities decode.
_HTML_TAG = re.compile(r"</?[a-zA-Z!][^>]*>")
_WHITESPACE = re.compile(r"\s+")

# Zero-width / bidi / control characters that render as boxes or nothing at all.
# Tab/newline/CR are intentionally excluded — they are collapsed as whitespace.
# ​-‏: ZWSP, ZWNJ, ZWJ, LRM, RLM. ‪-‮: bidi embeddings.
# ⁠: word joiner. ﻿: BOM. Plus the C0 control range.
_INVISIBLE = re.compile(
    "[\\u200b-\\u200f\\u202a-\\u202e\\u2060\\ufeff"
    "\x00-\x08\x0b\x0c\x0e-\x1f]"
)

# --- LaTeX / equation markup -------------------------------------------------
# Display + bracketed forms use unambiguous delimiters (never currency), so the
# whole blob is dropped.
_LATEX_DISPLAY = re.compile(r"\$\$.+?\$\$", re.DOTALL)
_LATEX_PAREN = re.compile(r"\\\(.+?\\\)", re.DOTALL)
_LATEX_BRACKET = re.compile(r"\\\[.+?\\\]", re.DOTALL)
# Inline ``$...$`` only when the contents look like math — guards against
# "$5 and $10" being treated as a single span.
_LATEX_INLINE = re.compile(r"\$(?=\S)([^$\n]{1,160})\$")
_MATH_SIGNAL = re.compile(r"[\\^_{}=]")
# Bare TeX commands left over outside delimiters (\alpha, \frac, ...).
_TEX_COMMAND = re.compile(r"\\[a-zA-Z]+")

# --- Markdown ----------------------------------------------------------------
_MD_IMAGE = re.compile(r"!\[[^\]\n]*\]\([^)\n]+\)")
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\n]+\)")
_MD_CODE = re.compile(r"`+([^`]*)`+")
# Balanced * / ** / *** emphasis, but only when it brackets text and is not
# glued to a word char (so "a*b*c" and bare "*" survive).
_MD_EMPHASIS = re.compile(r"(?<![\w*])(\*{1,3})(\S(?:[^*\n]*?\S)?)\1(?![\w*])")
# Leading ATX heading / blockquote markers ("## H", "> quote").
_MD_LEADING = re.compile(r"(?m)^\s{0,3}(?:#{1,6}\s+|>\s?)")


def _strip_inline_math(match: re.Match[str]) -> str:
    inner = match.group(1)
    return "" if _MATH_SIGNAL.search(inner) else match.group(0)


def normalize_card_text(text: str | None) -> str:
    """Return card-safe plain text: entities decoded, tags/markdown/LaTeX and
    invisible characters removed, whitespace collapsed.

    Idempotent for normal inputs. Safe to call multiple times across the
    ingest -> summarize -> serialize pipeline.
    """
    if not text:
        return ""
    s = str(text)
    # Decode entities BEFORE stripping tags so encoded markup (``&lt;b&gt;``)
    # and real tags both resolve the same way — and so the pass is idempotent.
    s = html.unescape(s)
    s = _HTML_TAG.sub(" ", s)
    # Equation markup.
    s = _LATEX_DISPLAY.sub(" ", s)
    s = _LATEX_PAREN.sub(" ", s)
    s = _LATEX_BRACKET.sub(" ", s)
    s = _LATEX_INLINE.sub(_strip_inline_math, s)
    s = _TEX_COMMAND.sub(" ", s)
    # Markdown.
    s = _MD_IMAGE.sub(" ", s)
    s = _MD_LINK.sub(r"\1", s)
    s = _MD_CODE.sub(r"\1", s)
    s = _MD_LEADING.sub("", s)
    s = _MD_EMPHASIS.sub(r"\2", s)
    # Invisible / control characters.
    s = _INVISIBLE.sub("", s)
    # Collapse whitespace last.
    return _WHITESPACE.sub(" ", s).strip()
