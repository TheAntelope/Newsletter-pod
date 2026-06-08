"""User-uploaded content via the iOS Share extension / POST /v1/items/shared.

Accepts URLs and files (PDF, EPUB, plain text, .docx). Extracts text, builds an
InboundEmailItem with kind="share", and lets the generation pipeline
force-include it in the user's next pod (see
ControlPlaneService.process_user_generation, where kind="share" items bypass
the per-tier item cap, swipe-filtering, and the ranker).

Extraction is intentionally best-effort: a paywalled URL or a PDF with no
embedded text layer yields a short body, but we still build the item so the
user sees their share land in the queue (the LLM segment will be brief).
Hard failures (oversize upload, totally unparseable format) raise
SharedItemError and the endpoint maps that to a 400.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Callable, Optional
from urllib.parse import urlsplit, urlunsplit

import requests

from .user_models import InboundEmailItem
from .utils import utc_now

logger = logging.getLogger(__name__)

# Practical upper bound on stored body. ~50k chars ≈ a long article (~10k
# words); anything bigger gets truncated. Keeps Firestore writes bounded and
# stops a single share from dominating the LLM prompt window.
MAX_EXTRACTED_CHARS = 50_000
# Hard upload limit, matching the Mailgun inbound webhook's effective limit.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# Bound on URL fetches so a slow page can't stall the share endpoint.
URL_FETCH_TIMEOUT_SECONDS = 15
URL_FETCH_USER_AGENT = (
    "Mozilla/5.0 (compatible; ClawCast-Share/1.0; +https://theclawcast.com)"
)
# Reddit 403/429s our bot-shaped UA, and its post pages are JS-rendered with no
# server-side article body, so the generic HTML extractor finds nothing. We hit
# the public .json endpoint with a browser-ish UA instead — it returns the post
# title, selftext, and the comment tree as structured data. See extract_from_reddit.
REDDIT_HOSTS = {"reddit.com", "redd.it"}
REDDIT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# How many top-level comments to fold into the body. Reddit returns them already
# sorted by the listing's default ("confidence"/top), so we just take the first N
# real ones. Keeps discussion threads useful without burying the post itself.
REDDIT_MAX_COMMENTS = 8

SHARE_SENDER_EMAIL = "share@theclawcast.com"
SHARE_SENDER_DOMAIN = "share"
SHARE_FROM_NAME = "Shared by you"

_WHITESPACE_PATTERN = re.compile(r"\s+")
# UTI / MIME hints the endpoint dispatches on. Kept here so callers don't have
# to know the extractor names; pass the kind string we recognize and we pick
# the right extractor.
SUPPORTED_KINDS = {"url", "pdf", "epub", "docx", "text"}


class SharedItemError(Exception):
    """Raised when a share can't be processed (oversize, unsupported format,
    extraction returned nothing usable). The endpoint maps this to HTTP 400
    with the message text."""


def normalize_extracted_text(text: str) -> str:
    """Collapse runs of whitespace and trim. Truncate at MAX_EXTRACTED_CHARS
    with a visible sentinel so a downstream prompt can tell the body was cut."""
    if not text:
        return ""
    cleaned = _WHITESPACE_PATTERN.sub(" ", text).strip()
    if len(cleaned) > MAX_EXTRACTED_CHARS:
        cleaned = cleaned[:MAX_EXTRACTED_CHARS].rstrip() + " [truncated]"
    return cleaned


def _check_size(blob: bytes) -> None:
    if len(blob) > MAX_UPLOAD_BYTES:
        raise SharedItemError(
            f"Upload too large ({len(blob)} bytes; max {MAX_UPLOAD_BYTES})"
        )


# ----------------------------------------------------------------------------
# URL extraction
# ----------------------------------------------------------------------------


class _ArticleHTMLExtractor(HTMLParser):
    """Minimal HTML→text walker tuned for article pages.

    Skips <script>/<style>/<noscript>/<nav>/<footer>/<aside> subtrees.
    Captures the page title and og:title / og:description meta fallbacks.
    Body text is the concatenation of all text inside <article>, <main>, or
    (failing those) <body>.
    """

    _SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "aside", "header"}
    _PREFERRED_BODY_TAGS = ("article", "main")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._in_article = 0
        self._in_main = 0
        self._in_body = 0
        self.title: str = ""
        self.og_title: str = ""
        self.og_description: str = ""
        self._article_chunks: list[str] = []
        self._main_chunks: list[str] = []
        self._body_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "meta":
            attr_map = {k.lower(): (v or "") for k, v in attrs}
            prop = attr_map.get("property") or attr_map.get("name") or ""
            content = attr_map.get("content") or ""
            if prop.lower() == "og:title" and not self.og_title:
                self.og_title = content.strip()
            elif prop.lower() == "og:description" and not self.og_description:
                self.og_description = content.strip()
            return
        if tag == "article":
            self._in_article += 1
        elif tag == "main":
            self._in_main += 1
        elif tag == "body":
            self._in_body += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            return
        if tag == "article" and self._in_article > 0:
            self._in_article -= 1
        elif tag == "main" and self._in_main > 0:
            self._in_main -= 1
        elif tag == "body" and self._in_body > 0:
            self._in_body -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self.title += data
            return
        if self._in_article > 0:
            self._article_chunks.append(data)
        elif self._in_main > 0:
            self._main_chunks.append(data)
        elif self._in_body > 0:
            self._body_chunks.append(data)

    def best_body(self) -> str:
        if self._article_chunks:
            return "".join(self._article_chunks)
        if self._main_chunks:
            return "".join(self._main_chunks)
        return "".join(self._body_chunks)


UrlFetcher = Callable[[str], tuple[bytes, str]]


def _fetch_url(url: str, user_agent: str) -> tuple[bytes, str]:
    """Return (body_bytes, content_type). Raises SharedItemError on failure."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": user_agent},
            timeout=URL_FETCH_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise SharedItemError(f"Could not fetch URL: {exc}") from exc
    if response.status_code >= 400:
        raise SharedItemError(
            f"URL fetch returned HTTP {response.status_code}"
        )
    return response.content, response.headers.get("Content-Type", "")


def _default_url_fetcher(url: str) -> tuple[bytes, str]:
    return _fetch_url(url, URL_FETCH_USER_AGENT)


def _reddit_url_fetcher(url: str) -> tuple[bytes, str]:
    return _fetch_url(url, REDDIT_USER_AGENT)


def _host_matches(netloc: str, suffixes: set[str]) -> bool:
    """True if the host equals one of `suffixes` or is a subdomain of it
    (so www.reddit.com and old.reddit.com both match "reddit.com")."""
    host = netloc.lower().split(":", 1)[0]
    return any(host == s or host.endswith("." + s) for s in suffixes)


def extract_from_url(
    url: str,
    fetcher: Optional[UrlFetcher] = None,
) -> tuple[str, str]:
    """Fetch a URL and return (title, body_text). Falls back to og:title /
    og:description / the URL host if no <title> or article text is found."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SharedItemError("Only http(s) URLs are supported")
    if _host_matches(parsed.netloc, REDDIT_HOSTS):
        return extract_from_reddit(url, fetcher=fetcher)
    fetch = fetcher or _default_url_fetcher
    body_bytes, content_type = fetch(url)
    _check_size(body_bytes)

    # Trust the URL's content-type for branching: PDFs sometimes ship with
    # http(s) URLs (Arxiv, news PDF links). Treat those as PDFs.
    content_type_lower = (content_type or "").lower()
    if "application/pdf" in content_type_lower or url.lower().endswith(".pdf"):
        title, body = extract_from_pdf(body_bytes)
        return (title or parsed.netloc, body)

    return _parse_html_article(body_bytes, url, parsed.netloc)


def _parse_html_article(body_bytes: bytes, url: str, fallback_title: str) -> tuple[str, str]:
    """Run the article HTML extractor over raw bytes and apply the title/body
    fallbacks. Split out so Reddit (and other site-specific paths) can reuse it
    without re-entering extract_from_url's host routing."""
    try:
        html_text = body_bytes.decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover — decode("utf-8", errors=...) shouldn't raise
        raise SharedItemError(f"Could not decode URL response: {exc}") from exc

    parser = _ArticleHTMLExtractor()
    try:
        parser.feed(html_text)
    except Exception:
        logger.warning("HTML parse failed for %s; falling back to raw strip", url, exc_info=True)

    title = (parser.title or parser.og_title or fallback_title).strip()
    body = parser.best_body() or parser.og_description
    if not body.strip():
        logger.info(
            "URL share returned empty body after extraction (likely paywall or JS-heavy page): url=%s",
            url,
        )
        body = parser.og_description or ""
    return (title, normalize_extracted_text(body))


def _old_reddit_url(url: str) -> str:
    """Rewrite a Reddit URL to old.reddit.com, dropping query/fragment.

    The modern site (www/np/new reddit) and the public .json API both sit behind
    an anti-bot wall ("snooserv") that 403s server/datacenter requests regardless
    of User-Agent. old.reddit.com still serves fully server-rendered HTML, so we
    target it and parse the markup directly. A redd.it short link is just the
    post id (redd.it/<id>); old.reddit.com/comments/<id> redirects to the
    canonical permalink, which requests follows."""
    parsed = urlsplit(url)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host == "redd.it" or host.endswith(".redd.it"):
        post_id = parsed.path.strip("/").split("/")[0]
        return urlunsplit((parsed.scheme, "old.reddit.com", f"/comments/{post_id}", "", ""))
    netloc = "old.reddit.com" if host.endswith("reddit.com") else parsed.netloc
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


class _OldRedditExtractor(HTMLParser):
    """Pull the post body and top-level comments out of an old.reddit.com page.

    Post selftext and every comment body render as <div class="md"> blocks. The
    subreddit sidebar (rules, description) is also full of <div class="md">, so
    we suppress anything inside <div class="side"> or the footer. A block that
    closes before we've seen the first comment is the post; everything after is a
    comment. Title comes from <title> ("Post title : Subreddit")."""

    _SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._div_stack: list[tuple[bool, bool]] = []  # (is_skip_region, is_md)
        self._region_skip_depth = 0
        self._md_depth = 0
        self._buf: list[str] = []
        self._seen_comment = False
        self.title: str = ""
        self.post_body: str = ""
        self.comments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if attr_map.get("data-type") == "comment":
            self._seen_comment = True
        if tag == "div":
            cls = attr_map.get("class", "")
            classes = set(cls.split())
            is_skip = ("side" in classes) or cls.startswith("footer")
            is_md = "md" in classes
            self._div_stack.append((is_skip, is_md))
            if is_skip:
                self._region_skip_depth += 1
            if is_md and self._region_skip_depth == 0:
                if self._md_depth == 0:
                    self._buf = []
                self._md_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            return
        if tag == "div" and self._div_stack:
            is_skip, is_md = self._div_stack.pop()
            if is_md and self._region_skip_depth == 0 and self._md_depth > 0:
                self._md_depth -= 1
                if self._md_depth == 0:
                    text = "".join(self._buf).strip()
                    if text:
                        if self._seen_comment:
                            self.comments.append(text)
                        else:
                            self.post_body = text
            if is_skip and self._region_skip_depth > 0:
                self._region_skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self.title += data
            return
        if self._md_depth > 0 and self._region_skip_depth == 0:
            self._buf.append(data)


def _clean_reddit_title(raw: str, subreddit: str) -> str:
    """old.reddit's <title> is "Post title : Subreddit". Strip the suffix.

    When the subreddit is known from the URL we match it exactly; otherwise
    (e.g. a redd.it short link) we drop a trailing " : <name>" where <name> looks
    like a subreddit (no spaces, valid sub-name chars)."""
    title = raw.strip()
    if subreddit and title.endswith(f" : {subreddit}"):
        return title[: -len(f" : {subreddit}")].strip()
    return re.sub(r"\s:\s[A-Za-z0-9_]{1,21}$", "", title).strip()


def extract_from_reddit(
    url: str,
    fetcher: Optional[UrlFetcher] = None,
) -> tuple[str, str]:
    """Fetch a Reddit post via old.reddit.com and return (title, body).

    Body is the post's selftext followed by up to REDDIT_MAX_COMMENTS top-level
    comments. Link/image posts have no selftext, so for those the comments carry
    the discussion. If the page has no recognizable post markup (e.g. a subreddit
    listing or user page), falls back to the generic article extractor."""
    fetch = fetcher or _reddit_url_fetcher
    fetch_url = _old_reddit_url(url)
    body_bytes, _content_type = fetch(fetch_url)
    _check_size(body_bytes)

    html_text = body_bytes.decode("utf-8", errors="replace")
    parser = _OldRedditExtractor()
    try:
        parser.feed(html_text)
    except Exception:
        logger.warning("old.reddit parse failed for %s; falling back to generic", url, exc_info=True)
        return _parse_html_article(body_bytes, url, urlsplit(url).netloc)

    # Derive the subreddit from the path (/r/<sub>/...) to clean the title.
    path_parts = [p for p in urlsplit(url).path.split("/") if p]
    subreddit = path_parts[1] if len(path_parts) >= 2 and path_parts[0].lower() == "r" else ""
    title = _clean_reddit_title(parser.title, subreddit)

    if not parser.post_body and not parser.comments:
        logger.info("old.reddit page had no post markup; falling back to generic: url=%s", url)
        return _parse_html_article(body_bytes, url, urlsplit(url).netloc)

    parts: list[str] = []
    if parser.post_body:
        parts.append(parser.post_body)
    if parser.comments:
        parts.append("Top comments:")
        parts.extend(parser.comments[:REDDIT_MAX_COMMENTS])

    title = title or urlsplit(url).netloc
    return (title, normalize_extracted_text("\n\n".join(parts)))


# ----------------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------------


def extract_from_pdf(blob: bytes) -> tuple[Optional[str], str]:
    _check_size(blob)
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover — declared in pyproject
        raise SharedItemError("PDF support not installed") from exc
    try:
        reader = PdfReader(io.BytesIO(blob))
    except Exception as exc:
        raise SharedItemError(f"Could not read PDF: {exc}") from exc
    title: Optional[str] = None
    try:
        meta = reader.metadata
        if meta and meta.get("/Title"):
            title = str(meta["/Title"]).strip() or None
    except Exception:
        pass
    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            logger.warning("PDF page text extraction failed", exc_info=True)
    body = normalize_extracted_text("\n".join(chunks))
    if not body:
        raise SharedItemError(
            "PDF contains no extractable text (scanned image? try OCR before sharing)"
        )
    return (title, body)


# ----------------------------------------------------------------------------
# EPUB
# ----------------------------------------------------------------------------


def extract_from_epub(blob: bytes) -> tuple[Optional[str], str]:
    _check_size(blob)
    try:
        from ebooklib import epub, ITEM_DOCUMENT
    except ImportError as exc:  # pragma: no cover
        raise SharedItemError("EPUB support not installed") from exc
    try:
        book = epub.read_epub(io.BytesIO(blob))
    except Exception as exc:
        raise SharedItemError(f"Could not read EPUB: {exc}") from exc
    title: Optional[str] = None
    try:
        titles = book.get_metadata("DC", "title")
        if titles:
            title = (titles[0][0] or "").strip() or None
    except Exception:
        pass
    chunks: list[str] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        try:
            html_bytes = item.get_content()
            parser = _ArticleHTMLExtractor()
            parser.feed(html_bytes.decode("utf-8", errors="replace"))
            chunks.append(parser.best_body())
        except Exception:
            logger.warning("EPUB chapter extraction failed", exc_info=True)
    body = normalize_extracted_text("\n".join(chunks))
    if not body:
        raise SharedItemError("EPUB contains no extractable text")
    return (title, body)


# ----------------------------------------------------------------------------
# DOCX
# ----------------------------------------------------------------------------


def extract_from_docx(blob: bytes) -> tuple[Optional[str], str]:
    _check_size(blob)
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise SharedItemError("DOCX support not installed") from exc
    try:
        doc = Document(io.BytesIO(blob))
    except Exception as exc:
        raise SharedItemError(f"Could not read DOCX: {exc}") from exc
    title: Optional[str] = None
    try:
        core_title = doc.core_properties.title
        if core_title:
            title = core_title.strip() or None
    except Exception:
        pass
    chunks = [para.text for para in doc.paragraphs if para.text]
    body = normalize_extracted_text("\n".join(chunks))
    if not body:
        raise SharedItemError("DOCX contains no text")
    return (title, body)


# ----------------------------------------------------------------------------
# Plain text
# ----------------------------------------------------------------------------


def extract_from_plain_text(blob: bytes) -> tuple[Optional[str], str]:
    _check_size(blob)
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        text = blob.decode("utf-8", errors="replace")
    body = normalize_extracted_text(text)
    if not body:
        raise SharedItemError("Shared text is empty")
    # First non-empty line, capped at 120 chars, becomes a synthetic title.
    first_line = next(
        (line.strip() for line in text.splitlines() if line.strip()),
        "",
    )
    title = first_line[:120] if first_line else None
    return (title, body)


# ----------------------------------------------------------------------------
# Item construction
# ----------------------------------------------------------------------------


def build_shared_item(
    *,
    user_id: str,
    title: Optional[str],
    body_text: str,
    article_url: Optional[str],
    received_at: Optional[datetime] = None,
) -> InboundEmailItem:
    """Build a deterministic, dedupe-safe InboundEmailItem with kind=share.

    The id is derived from (user_id, article_url, title, first-1000-chars-of-body)
    so re-sharing the same URL or pasting the same blob twice doesn't create
    duplicates — the second POST returns the existing item_id.
    """
    seed_parts = [article_url or "", title or "", body_text[:1000]]
    seed = "|".join(seed_parts)
    digest = hashlib.sha256(f"{user_id}:{seed}".encode("utf-8")).hexdigest()
    return InboundEmailItem(
        id=digest[:32],
        user_id=user_id,
        kind="share",
        message_id=None,
        from_email=SHARE_SENDER_EMAIL,
        from_name=SHARE_FROM_NAME,
        sender_domain=SHARE_SENDER_DOMAIN,
        subject=(title or "Shared item")[:200],
        body_text=body_text,
        article_url=article_url,
        received_at=received_at or utc_now(),
    )
