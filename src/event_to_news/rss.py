"""
RSS 2.0 feed generator.

Converts a list of FeedItems into a valid RSS 2.0 XML document using feedgen.
"""

from __future__ import annotations

from datetime import timezone

from feedgen.feed import FeedGenerator

from .models import FeedItem


def build_rss(
    slug: str,
    title: str,
    description: str,
    base_url: str,
    items: list[FeedItem],
) -> bytes:
    """
    Build an RSS 2.0 XML document from a list of FeedItems.

    Returns the document as UTF-8 encoded bytes.
    """
    feed_url = f"{base_url.rstrip('/')}/feed/{slug}"

    fg = FeedGenerator()
    fg.id(feed_url)
    fg.title(title or slug)
    fg.description(description or title or slug)
    fg.link(href=feed_url, rel="self")
    fg.language("fr")  # configurable in future

    for item in items:
        fe = fg.add_entry(order="append")
        fe.id(item.id)
        fe.title(item.title)
        fe.content(item.content, type="html")

        # Ensure the datetime is timezone-aware
        pub = item.published
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        fe.published(pub)
        fe.updated(pub)

        if item.link:
            fe.link(href=item.link)

        if item.author:
            fe.author({"name": item.author})

        if item.category:
            fe.category({"term": item.category})

    return fg.rss_str(pretty=True)
