"""Unit tests for newsletter_pod.shared_items extractors and item builder.

PDF, EPUB, and DOCX fixtures are constructed in-test using the same
libraries the extractors use, which keeps the suite self-contained
(no binary fixtures checked in) and verifies the round trip.
"""
from __future__ import annotations

import io

import pytest

from newsletter_pod.shared_items import (
    MAX_EXTRACTED_CHARS,
    MAX_UPLOAD_BYTES,
    REDDIT_MAX_COMMENTS,
    SHARE_FROM_NAME,
    SHARE_SENDER_DOMAIN,
    SHARE_SENDER_EMAIL,
    SharedItemError,
    build_shared_item,
    extract_from_docx,
    extract_from_epub,
    extract_from_pdf,
    extract_from_plain_text,
    extract_from_reddit,
    extract_from_url,
    normalize_extracted_text,
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _make_minimal_pdf(title: str, body_paragraphs: list[str]) -> bytes:
    # pypdf has no high-level "create a new PDF with this text" API, so we
    # use reportlab (test-only dep) to construct a one-page PDF the pypdf
    # extractor can re-parse. Keeps the suite self-contained: no binary
    # fixtures checked in, no skips on the happy path.
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab not installed (test-only dep)")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(title)
    y = 750
    for para in body_paragraphs:
        c.drawString(72, y, para)
        y -= 20
    c.save()
    return buf.getvalue()


def _make_epub(title: str, chapter_html: str) -> bytes:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("test-epub-id")
    book.set_title(title)
    book.set_language("en")
    chapter = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
    chapter.content = f"<html><body>{chapter_html}</body></html>"
    book.add_item(chapter)
    book.toc = (chapter,)
    book.spine = ["nav", chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    buf = io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()


def _make_docx(title: str, paragraphs: list[str]) -> bytes:
    from docx import Document

    doc = Document()
    doc.core_properties.title = title
    for para in paragraphs:
        doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# normalize_extracted_text
# ----------------------------------------------------------------------------


def test_normalize_collapses_whitespace_and_trims():
    text = "  hello\n\n  world\t\tfoo  "
    assert normalize_extracted_text(text) == "hello world foo"


def test_normalize_truncates_at_max_chars():
    text = "a" * (MAX_EXTRACTED_CHARS + 1000)
    result = normalize_extracted_text(text)
    assert len(result) <= MAX_EXTRACTED_CHARS + len(" [truncated]")
    assert result.endswith("[truncated]")


def test_normalize_empty_string():
    assert normalize_extracted_text("") == ""
    assert normalize_extracted_text("   \n\t  ") == ""


# ----------------------------------------------------------------------------
# Plain text
# ----------------------------------------------------------------------------


def test_extract_plain_text_returns_title_and_body():
    blob = "Headline goes here\n\nThis is the body paragraph.".encode("utf-8")
    title, body = extract_from_plain_text(blob)
    assert title == "Headline goes here"
    assert "body paragraph" in body


def test_extract_plain_text_empty_raises():
    with pytest.raises(SharedItemError):
        extract_from_plain_text(b"   \n  ")


def test_extract_plain_text_handles_non_utf8():
    # Latin-1 bytes that aren't valid UTF-8 — should fall back to replace mode.
    blob = "café".encode("latin-1")
    title, body = extract_from_plain_text(blob)
    # We expect *something* extractable, even if the encoding is mangled.
    assert body  # not empty


# ----------------------------------------------------------------------------
# URL fetcher (stubbed)
# ----------------------------------------------------------------------------


def test_extract_from_url_extracts_article_body():
    html = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>The Best Article</title>
        <meta property="og:title" content="OG Title">
      </head>
      <body>
        <nav>Home | About | Contact</nav>
        <header>Site header</header>
        <article>
          <h1>The Best Article</h1>
          <p>This is the first paragraph of the body.</p>
          <p>This is the second paragraph.</p>
        </article>
        <footer>Footer text</footer>
        <script>console.log("nope");</script>
      </body>
    </html>
    """.strip()

    def fake_fetcher(url):
        return (html.encode("utf-8"), "text/html; charset=utf-8")

    title, body = extract_from_url("https://example.com/post", fetcher=fake_fetcher)
    assert title == "The Best Article"
    assert "first paragraph" in body
    assert "second paragraph" in body
    # Skipped tags shouldn't leak into the body.
    assert "Home | About | Contact" not in body
    assert "Footer text" not in body
    assert "console.log" not in body


def test_extract_from_url_falls_back_to_main_then_body():
    html = """
    <html><head><title>T</title></head>
    <body>
      <main><p>Main content here.</p></main>
    </body></html>
    """

    def fake(url):
        return (html.encode("utf-8"), "text/html")

    title, body = extract_from_url("https://example.com/x", fetcher=fake)
    assert "Main content here" in body


def test_extract_from_url_falls_back_to_og_description_when_body_empty():
    html = """
    <html><head>
      <title>T</title>
      <meta property="og:description" content="OG fallback description">
    </head><body></body></html>
    """

    def fake(url):
        return (html.encode("utf-8"), "text/html")

    title, body = extract_from_url("https://example.com/x", fetcher=fake)
    assert "OG fallback description" in body


def test_extract_from_url_rejects_non_http_scheme():
    with pytest.raises(SharedItemError):
        extract_from_url("file:///etc/passwd", fetcher=lambda u: (b"", ""))
    with pytest.raises(SharedItemError):
        extract_from_url("javascript:alert(1)", fetcher=lambda u: (b"", ""))


def test_extract_from_url_routes_pdf_content_type_through_pdf_extractor():
    pdf_bytes = _make_minimal_pdf("From URL PDF", ["Body of the PDF."])

    def fake(url):
        return (pdf_bytes, "application/pdf")

    title, body = extract_from_url("https://example.com/file.pdf", fetcher=fake)
    assert "Body of the PDF" in body


# ----------------------------------------------------------------------------
# Reddit (old.reddit.com HTML, stubbed fetcher)
# ----------------------------------------------------------------------------


def _old_reddit_html(title, subreddit, selftext, comments, sidebar="Subreddit rules and description."):
    """Build a minimal old.reddit.com post page: a sidebar (must be ignored), a
    post selftext .md block, and comment .md blocks (marked data-type=comment)."""
    comment_html = "".join(
        f'<div class="comment" data-type="comment"><div class="entry">'
        f'<div class="usertext-body md-container"><div class="md"><p>{c}</p></div></div>'
        f'</div></div>'
        for c in comments
    )
    selftext_html = (
        f'<div class="usertext-body md-container"><div class="md"><p>{selftext}</p></div></div>'
        if selftext else ""
    )
    return (
        f"<html><head><title>{title} : {subreddit}</title></head><body>"
        f'<div class="side"><div class="md"><p>{sidebar}</p></div></div>'
        f'<div id="siteTable"><div class="thing"><div class="entry">{selftext_html}</div></div></div>'
        f'<div class="commentarea">{comment_html}</div>'
        f"</body></html>"
    ).encode("utf-8")


def test_extract_from_reddit_includes_selftext_and_comments():
    html = _old_reddit_html(
        "Interesting discussion", "python",
        "This is the original post body.",
        ["First comment.", "Second comment."],
    )
    captured = {}

    def fake(url):
        captured["url"] = url
        return (html, "text/html")

    title, body = extract_from_reddit(
        "https://www.reddit.com/r/python/comments/abc123/interesting_discussion/",
        fetcher=fake,
    )
    assert title == "Interesting discussion"  # " : python" suffix stripped
    assert "original post body" in body
    assert "Top comments:" in body
    assert "First comment." in body
    assert "Second comment." in body
    # Sidebar content must not leak into the body.
    assert "Subreddit rules" not in body
    # We should have fetched old.reddit.com, not the www host.
    assert captured["url"] == "https://old.reddit.com/r/python/comments/abc123/interesting_discussion/"


def test_extract_from_reddit_routed_via_extract_from_url():
    html = _old_reddit_html("Link post", "news", "", ["Only the comments have content."])

    def fake(url):
        return (html, "text/html")

    # extract_from_url should detect the reddit host and route to the reddit path.
    title, body = extract_from_url("https://reddit.com/r/news/comments/x/y/", fetcher=fake)
    assert title == "Link post"
    assert "Only the comments have content." in body


def test_extract_from_reddit_rewrites_host_and_strips_query():
    html = _old_reddit_html("T", "x", "Body.", [])
    captured = {}

    def fake(url):
        captured["url"] = url
        return (html, "text/html")

    extract_from_reddit(
        "https://www.reddit.com/r/x/comments/a/b/?utm_source=share",
        fetcher=fake,
    )
    assert captured["url"] == "https://old.reddit.com/r/x/comments/a/b/"


def test_extract_from_reddit_maps_short_link():
    html = _old_reddit_html("Short", "x", "Body via short link.", [])
    captured = {}

    def fake(url):
        captured["url"] = url
        return (html, "text/html")

    # redd.it/<id> -> old.reddit.com/comments/<id> (resolves to the permalink).
    title, body = extract_from_url("https://redd.it/abc123", fetcher=fake)
    assert captured["url"] == "https://old.reddit.com/comments/abc123"
    assert "Body via short link." in body


def test_extract_from_reddit_ignores_sidebar_md_blocks():
    html = _old_reddit_html(
        "T", "x", "The actual post.", ["A real comment."],
        sidebar="Do not include this sidebar text.",
    )

    def fake(url):
        return (html, "text/html")

    _title, body = extract_from_reddit("https://www.reddit.com/r/x/comments/a/b/", fetcher=fake)
    assert "The actual post." in body
    assert "A real comment." in body
    assert "Do not include this sidebar" not in body


def test_extract_from_reddit_caps_comment_count():
    many = [f"Comment number {i}." for i in range(REDDIT_MAX_COMMENTS + 5)]
    html = _old_reddit_html("T", "x", "Post.", many)

    def fake(url):
        return (html, "text/html")

    _title, body = extract_from_reddit("https://www.reddit.com/r/x/comments/a/b/", fetcher=fake)
    assert f"Comment number {REDDIT_MAX_COMMENTS - 1}." in body
    assert f"Comment number {REDDIT_MAX_COMMENTS}." not in body


def test_extract_from_reddit_falls_back_when_no_post_markup():
    # A page with no post/comment .md blocks (e.g. a subreddit listing) should
    # fall back to the generic article extractor over the same bytes.
    html = b"<html><head><title>Fallback</title></head><body><article><p>HTML body.</p></article></body></html>"

    def fake(url):
        return (html, "text/html")

    title, body = extract_from_reddit("https://www.reddit.com/r/python/", fetcher=fake)
    assert title == "Fallback"
    assert "HTML body." in body


# ----------------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------------


def test_extract_pdf_returns_title_and_body():
    pdf = _make_minimal_pdf("My PDF Title", [
        "First paragraph of the PDF.",
        "Second paragraph of the PDF.",
    ])
    title, body = extract_from_pdf(pdf)
    assert title == "My PDF Title"
    assert "First paragraph" in body
    assert "Second paragraph" in body


def test_extract_pdf_empty_raises():
    # A PDF with no text layer (we cheat by passing a non-PDF byte string).
    with pytest.raises(SharedItemError):
        extract_from_pdf(b"not a pdf at all")


# ----------------------------------------------------------------------------
# EPUB
# ----------------------------------------------------------------------------


def test_extract_epub_returns_title_and_body():
    epub_bytes = _make_epub("My EPUB Book", "<h1>Chapter</h1><p>EPUB body text here.</p>")
    title, body = extract_from_epub(epub_bytes)
    assert title == "My EPUB Book"
    assert "EPUB body text here" in body


def test_extract_epub_garbage_raises():
    with pytest.raises(SharedItemError):
        extract_from_epub(b"definitely not an epub")


# ----------------------------------------------------------------------------
# DOCX
# ----------------------------------------------------------------------------


def test_extract_docx_returns_title_and_body():
    docx_bytes = _make_docx("DOCX Title", [
        "First line of the docx.",
        "Second line of the docx.",
    ])
    title, body = extract_from_docx(docx_bytes)
    assert title == "DOCX Title"
    assert "First line" in body
    assert "Second line" in body


def test_extract_docx_garbage_raises():
    with pytest.raises(SharedItemError):
        extract_from_docx(b"not a docx")


# ----------------------------------------------------------------------------
# Size limits
# ----------------------------------------------------------------------------


def test_oversize_blob_rejected():
    huge = b"x" * (MAX_UPLOAD_BYTES + 1)
    with pytest.raises(SharedItemError):
        extract_from_plain_text(huge)
    with pytest.raises(SharedItemError):
        extract_from_pdf(huge)


# ----------------------------------------------------------------------------
# build_shared_item
# ----------------------------------------------------------------------------


def test_build_shared_item_deterministic_id():
    a = build_shared_item(
        user_id="user-1",
        title="My title",
        body_text="The body",
        article_url="https://example.com/a",
    )
    b = build_shared_item(
        user_id="user-1",
        title="My title",
        body_text="The body",
        article_url="https://example.com/a",
    )
    assert a.id == b.id, "same content for same user should produce same id"
    c = build_shared_item(
        user_id="user-2",
        title="My title",
        body_text="The body",
        article_url="https://example.com/a",
    )
    assert c.id != a.id, "different user should produce different id"


def test_build_shared_item_sets_share_metadata():
    item = build_shared_item(
        user_id="user-1",
        title="My title",
        body_text="The body",
        article_url=None,
    )
    assert item.kind == "share"
    assert item.from_email == SHARE_SENDER_EMAIL
    assert item.sender_domain == SHARE_SENDER_DOMAIN
    assert item.from_name == SHARE_FROM_NAME
    assert item.subject == "My title"
    assert item.message_id is None
    assert item.consumed_at is None


def test_build_shared_item_truncates_long_title():
    long_title = "x" * 500
    item = build_shared_item(
        user_id="user-1",
        title=long_title,
        body_text="body",
        article_url=None,
    )
    assert len(item.subject) <= 200
