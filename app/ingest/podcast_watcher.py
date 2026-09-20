"""Podcast watcher: monitors RSS audio enclosures, transcribes or extracts takeaways."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import feedparser

from app.config import get_config
from app.db import document_exists, insert_document
from app.llm import summarize_article

logger = logging.getLogger(__name__)


def extract_enclosure_audio_url(entry: Any) -> Optional[str]:
    """Find audio download/stream URL from podcast RSS enclosure."""
    enclosures = entry.get("enclosures", [])
    for enc in enclosures:
        if enc.get("type", "").startswith("audio/") or enc.get("href", "").endswith((".mp3", ".m4a", ".aac")):
            return enc.get("href")

    # Check media content
    media_content = entry.get("media_content", [])
    for media in media_content:
        if media.get("type", "").startswith("audio/"):
            return media.get("url")

    return None


def watch_podcast_feed(source: Dict[str, Any], max_items: int = 5, db_path: Optional[str] = None) -> List[str]:
    """Watch a single podcast feed for new episodes."""
    source_name = source["name"]
    feed_url = source["url"]
    category = source.get("category", "Podcast")
    default_tags = source.get("tags", [])

    logger.info(f"Checking podcast feed: {source_name} ({feed_url})")
    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        logger.error(f"Failed to parse podcast feed {feed_url}: {e}")
        return []

    ingested_ids = []

    for entry in feed.entries[:max_items]:
        link = entry.get("link") or entry.get("id")
        audio_url = extract_enclosure_audio_url(entry)
        primary_url = link or audio_url

        if not primary_url or document_exists(primary_url, db_path=db_path):
            continue

        title = entry.get("title", "Untitled Episode")
        published_at = entry.get("published", entry.get("updated", datetime.now(timezone.utc).isoformat()))

        # Content in podcast RSS feeds is often in summary, subtitle, or content:encoded
        content = ""
        if "content" in entry and entry.content:
            content = entry.content[0].value
        elif "summary" in entry:
            content = entry.summary
        elif "subtitle" in entry:
            content = entry.subtitle

        logger.info(f"New podcast episode discovered: {title}")

        # Ingest and summarize episode insights
        brief_data = summarize_article(
            title=title,
            content=content,
            source_name=source_name,
            category=category,
        )

        all_topics = list(set(default_tags + ["Podcast", "Executive Interview"] + brief_data.get("topics", [])))

        doc_id = insert_document(
            source_type="podcast",
            source_name=source_name,
            url=primary_url,
            title=title,
            raw_content=content,
            summary=brief_data.get("summary", ""),
            key_metrics=brief_data.get("key_metrics", []),
            topics=all_topics,
            published_at=published_at,
            enclosure_url=audio_url,
            db_path=db_path,
        )
        ingested_ids.append(doc_id)

    logger.info(f"Podcast feed '{source_name}' processed: {len(ingested_ids)} new episodes ingested.")
    return ingested_ids


def watch_all_podcasts(max_items_per_feed: int = 5, db_path: Optional[str] = None) -> Dict[str, int]:
    """Watch all podcast feeds configured in config.yaml."""
    config = get_config()
    podcasts_cfg = config.get("ingest", {}).get("podcasts", {})
    if not podcasts_cfg.get("enabled", True):
        logger.info("Podcasts ingestion is disabled.")
        return {}

    sources = podcasts_cfg.get("sources", [])
    stats = {}
    for src in sources:
        ingested = watch_podcast_feed(src, max_items=max_items_per_feed, db_path=db_path)
        stats[src["name"]] = len(ingested)

    return stats
