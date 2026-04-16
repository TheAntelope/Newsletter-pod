from __future__ import annotations

from xml.etree import ElementTree as ET

from .models import EpisodeRecord
from .utils import format_rfc2822

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)


def build_feed_xml(
    title: str,
    description: str,
    author: str,
    language: str,
    feed_url: str,
    image_url: str | None,
    episodes: list[EpisodeRecord],
    media_url_builder,
) -> str:
    rss = ET.Element("rss", attrib={"version": "2.0", "xmlns:itunes": ITUNES_NS})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = language
    ET.SubElement(channel, "link").text = feed_url
    ET.SubElement(channel, "itunes:author").text = author
    ET.SubElement(channel, "itunes:summary").text = description
    ET.SubElement(channel, "itunes:explicit").text = "false"

    owner = ET.SubElement(channel, "itunes:owner")
    ET.SubElement(owner, "itunes:name").text = author

    if image_url:
        ET.SubElement(channel, "itunes:image", attrib={"href": image_url})

    for episode in episodes:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = episode.title
        ET.SubElement(item, "description").text = episode.description
        ET.SubElement(item, "guid").text = episode.id
        ET.SubElement(item, "pubDate").text = format_rfc2822(episode.published_at)
        ET.SubElement(item, "itunes:author").text = author
        ET.SubElement(item, "itunes:summary").text = episode.description
        ET.SubElement(item, "itunes:explicit").text = "false"

        if episode.duration_seconds is not None:
            ET.SubElement(item, "itunes:duration").text = str(episode.duration_seconds)

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
