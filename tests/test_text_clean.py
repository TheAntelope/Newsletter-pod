from __future__ import annotations

import pytest

from newsletter_pod.text_clean import normalize_card_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        # HTML entities — the classic "strange characters" on a card.
        ("AT&amp;T raised prices &amp; cut staff", "AT&T raised prices & cut staff"),
        ("It&#39;s here &nbsp;now", "It's here now"),
        ("5 &lt; 10 &gt; 3", "5 < 10 > 3"),
        # HTML tags (including entity-encoded tags).
        ("<p>Hello <b>world</b></p>", "Hello world"),
        ("&lt;script&gt;alert(1)&lt;/script&gt;", "alert(1)"),
        # Markdown.
        ("**Bold** and *italic* text", "Bold and italic text"),
        ("***strong***", "strong"),
        ("## Heading here", "Heading here"),
        ("> quoted line", "quoted line"),
        ("Use the `code` block", "Use the code block"),
        ("See [the docs](https://x.com) now", "See the docs now"),
        ("Look ![alt](https://img.png) here", "Look here"),
        # LaTeX / equation markup.
        ("The energy $E=mc^2$ is famous", "The energy is famous"),
        ("Display $$\\int x dx$$ math", "Display math"),
        (r"Solve \(x^2\) today", "Solve today"),
        (r"Vector \[a + b\] here", "Vector here"),
        (r"Greek \alpha and \beta", "Greek and"),
        # Whitespace collapse.
        ("too    many\n\nspaces", "too many spaces"),
    ],
)
def test_normalize_strips_markup(raw, expected):
    assert normalize_card_text(raw) == expected


@pytest.mark.parametrize(
    "codepoint",
    ["\\u200b", "\\u200c", "\\u200d", "\\u200e", "\\u200f", "\\u2060", "\\ufeff"],
)
def test_normalize_drops_invisible_characters(codepoint):
    char = codepoint.encode().decode("unicode_escape")
    assert normalize_card_text(f"zero{char}width{char} gone") == "zerowidth gone"


@pytest.mark.parametrize(
    "raw",
    [
        # Legitimate prose that must NOT be mangled.
        "Spent $5 and $10 today",
        "I love C# and F# languages",
        "Compute a*b*c in your head",
        "Ranked #1 overall",
        "snake_case stays intact",
        "Plain sentence, nothing special.",
    ],
)
def test_normalize_preserves_legitimate_text(raw):
    assert normalize_card_text(raw) == raw


@pytest.mark.parametrize("value", [None, "", "   ", "\n\t"])
def test_normalize_empty_inputs(value):
    assert normalize_card_text(value) == ""


@pytest.mark.parametrize(
    "raw",
    [
        "AT&amp;T &lt;b&gt;bold&lt;/b&gt; **md** $x^2$ ​ text",
        "Plain text already clean.",
        "<p>tags &amp; entities</p>",
        "## Heading with `code` and [link](http://x)",
    ],
)
def test_normalize_is_idempotent(raw):
    once = normalize_card_text(raw)
    assert normalize_card_text(once) == once


def test_normalize_resolves_double_encoded_entities_over_passes():
    # Genuinely double-encoded entities converge to the decoded char — the one
    # intentional non-idempotent case, and it converges to the right answer.
    assert normalize_card_text("Tom &amp;amp; Jerry") == "Tom &amp; Jerry"
    assert normalize_card_text("Tom &amp; Jerry") == "Tom & Jerry"
