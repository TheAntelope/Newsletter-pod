from __future__ import annotations

from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from .models import EpisodeRecord
from .utils import format_rfc2822

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("atom", ATOM_NS)


def build_feed_xml(
    title: str,
    description: str,
    author: str,
    language: str,
    feed_url: str,
    image_url: str | None,
    episodes: list[EpisodeRecord],
    media_url_builder,
    owner_email: str = "vincemartin1991@gmail.com",
    category: str = "News",
) -> str:
    rss = ET.Element(
        "rss",
        attrib={
            "version": "2.0",
            "xmlns:itunes": ITUNES_NS,
            "xmlns:atom": ATOM_NS,
        },
    )
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = language
    ET.SubElement(channel, "link").text = feed_url
    ET.SubElement(channel, "lastBuildDate").text = format_rfc2822(
        datetime.now(timezone.utc)
    )

    ET.SubElement(
        channel,
        "atom:link",
        attrib={"href": feed_url, "rel": "self", "type": "application/rss+xml"},
    )

    ET.SubElement(channel, "itunes:author").text = author
    ET.SubElement(channel, "itunes:summary").text = description
    ET.SubElement(channel, "itunes:explicit").text = "false"
    ET.SubElement(channel, "itunes:type").text = "episodic"
    ET.SubElement(channel, "itunes:category", attrib={"text": category})

    owner = ET.SubElement(channel, "itunes:owner")
    ET.SubElement(owner, "itunes:name").text = author
    ET.SubElement(owner, "itunes:email").text = owner_email

    if image_url:
        ET.SubElement(channel, "itunes:image", attrib={"href": image_url})
        image = ET.SubElement(channel, "image")
        ET.SubElement(image, "url").text = image_url
        ET.SubElement(image, "title").text = title
        ET.SubElement(image, "link").text = feed_url

    for episode in episodes:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = episode.title
        ET.SubElement(item, "description").text = episode.description
        ET.SubElement(item, "guid", attrib={"isPermaLink": "false"}).text = episode.id
        ET.SubElement(item, "pubDate").text = format_rfc2822(episode.published_at)
        ET.SubElement(item, "itunes:author").text = author
        ET.SubElement(item, "itunes:summary").text = episode.description
        ET.SubElement(item, "itunes:explicit").text = "false"

        if episode.duration_seconds is not None:
            ET.SubElement(item, "itunes:duration").text = str(episode.duration_seconds)

        if image_url:
            ET.SubElement(item, "itunes:image", attrib={"href": image_url})

        ET.SubElement(
            item,
            "enclosure",
            attrib={
                "url": media_url_builder(episode),
                "length": str(episode.audio_size_bytes),
                "type": episode.audio_mime_type,
            },
        )

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")
