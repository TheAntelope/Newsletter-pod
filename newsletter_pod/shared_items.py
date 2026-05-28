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
from urllib.parse import urlsplit

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


def _default_url_fetcher(url: str) -> tuple[bytes, str]:
    """Return (body_bytes, content_type). Raises SharedItemError on failure."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": URL_FETCH_USER_AGENT},
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


def extract_from_url(
    url: str,
    fetcher: Optional[UrlFetcher] = None,
) -> tuple[str, str]:
    """Fetch a URL and return (title, body_text). Falls back to og:title /
    og:description / the URL host if no <title> or article text is found."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SharedItemError("Only http(s) URLs are supported")
    fetch = fetcher or _default_url_fetcher
    body_bytes, content_type = fetch(url)
    _check_size(body_bytes)

    # Trust the URL's content-type for branching: PDFs sometimes ship with
    # http(s) URLs (Arxiv, news PDF links). Treat those as PDFs.
    content_type_lower = (content_type or "").lower()
    if "application/pdf" in content_type_lower or url.lower().endswith(".pdf"):
        title, body = extract_from_pdf(body_bytes)
        return (title or parsed.netloc, body)

    try:
        html_text = body_bytes.decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover — decode("utf-8", errors=...) shouldn't raise
        raise SharedItemError(f"Could not decode URL response: {exc}") from exc

    parser = _ArticleHTMLExtractor()
    try:
        parser.feed(html_text)
    except Exception:
        logger.warning("HTML parse failed for %s; falling back to raw strip", url, exc_info=True)

    title = (parser.title or parser.og_title or parsed.netloc).strip()
    body = parser.best_body() or parser.og_description
    if not body.strip():
        logger.info(
            "URL share returned empty body after extraction (likely paywall or JS-heavy page): url=%s",
            url,
        )
        body = parser.og_description or ""
    return (title, normalize_extracted_text(body))


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
