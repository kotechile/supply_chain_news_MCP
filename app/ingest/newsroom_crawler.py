"""Crawler for advisory newsrooms (Gartner, Accenture, Deloitte, Supply Chain Dive)."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import feedparser
import httpx
import trafilatura

from app.config import get_config
from app.db import document_exists, insert_document
from app.llm import summarize_article

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_article_content(url: str, timeout: float = 15.0) -> Optional[str]:
    """Extract clean article markdown using Trafilatura, with Jina Reader fallback."""
    try:
        with httpx.Client(headers=DEFAULT_HEADERS, timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                # 1. Primary extractor: Trafilatura (fast, local, clean)
                extracted = trafilatura.extract(
                    resp.text,
                    url=url,
                    include_links=True,
                    include_tables=True,
                    output_format="markdown",
                )
                if extracted and len(extracted.strip()) > 300:
                    return extracted

            # 2. Fallback for client-side rendered SPAs: Jina Reader API
            jina_url = f"https://r.jina.ai/{url}"
            jina_resp = client.get(jina_url, timeout=20.0)
            if jina_resp.status_code == 200 and len(jina_resp.text.strip()) > 200:
                return jina_resp.text
    except Exception as e:
        logger.warning(f"Failed to fetch/extract content from {url}: {e}")

    return None


def crawl_feed(source: Dict[str, Any], max_items: int = 10, db_path: Optional[str] = None) -> List[str]:
    """Crawl a single RSS newsroom feed and ingest unseen articles."""
    source_name = source["name"]
    feed_url = source["url"]
    category = source.get("category", "General")
    default_tags = source.get("tags", [])

    logger.info(f"Checking feed: {source_name} ({feed_url})")
    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        logger.error(f"Failed to parse RSS feed {feed_url}: {e}")
        return []

    ingested_ids = []

    for entry in feed.entries[:max_items]:
        link = entry.get("link")
        if not link or document_exists(link, db_path=db_path):
            continue

        title = entry.get("title", "Untitled")
        published_at = entry.get("published", entry.get("updated", datetime.now(timezone.utc).isoformat()))

        logger.info(f"New article discovered: {title} ({link})")

        # Fetch and extract full text
        content = fetch_article_content(link)
        if not content:
            # Fallback to feed summary if page fetch fails
            content = entry.get("summary", "")

        if not content or len(content.strip()) < 50:
            logger.warning(f"Skipping article due to insufficient content: {link}")
            continue

        # Generate summary and key metrics via LLM
        brief_data = summarize_article(
            title=title,
            content=content,
            source_name=source_name,
            category=category,
        )

        all_topics = list(set(default_tags + brief_data.get("topics", [])))

        # Store in SQLite
        doc_id = insert_document(
            source_type="newsroom",
            source_name=source_name,
            url=link,
            title=title,
            raw_content=content,
            summary=brief_data.get("summary", ""),
            key_metrics=brief_data.get("key_metrics", []),
            topics=all_topics,
            published_at=published_at,
            db_path=db_path,
        )
        ingested_ids.append(doc_id)

    logger.info(f"Feed '{source_name}' processed: {len(ingested_ids)} new articles ingested.")
    return ingested_ids


def crawl_all_newsrooms(max_items_per_feed: int = 10, db_path: Optional[str] = None) -> Dict[str, int]:
    """Crawl all newsrooms configured in config.yaml."""
    config = get_config()
    newsrooms_cfg = config.get("ingest", {}).get("newsrooms", {})
    if not newsrooms_cfg.get("enabled", True):
        logger.info("Newsrooms ingestion is disabled.")
        return {}

    sources = newsrooms_cfg.get("sources", [])
    stats = {}
    for src in sources:
        ingested = crawl_feed(src, max_items=max_items_per_feed, db_path=db_path)
        stats[src["name"]] = len(ingested)

    return stats
