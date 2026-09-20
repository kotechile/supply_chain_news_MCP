"""FastMCP Server exposing Supply Chain & IT Intelligence to LLM clients."""

import json
import logging
from typing import Optional
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import get_config
from app.db import (
    get_db_stats,
    get_recent_documents,
    init_db,
    search_documents,
    search_vendor_evaluations,
)
from app.ingest.newsroom_crawler import crawl_all_newsrooms
from app.ingest.podcast_watcher import watch_all_podcasts
from app.ingest.reprint_agent import run_reprint_discovery

logger = logging.getLogger(__name__)

# Ensure DB is initialized
init_db()

config = get_config()
mcp_cfg = config.get("mcp", {})

mcp = FastMCP(
    name=mcp_cfg.get("name", "supply-chain-intel"),
)


@mcp.tool()
def search_intelligence(query: str, source_type: Optional[str] = None, limit: int = 5) -> str:
    """Search across Gartner, Deloitte, Accenture, and vendor advisory intelligence.

    Args:
        query: Search keywords, technology, or topic (e.g., 'WMS automation', 'resilience', 'generative AI supply chain')
        source_type: Optional filter by source: 'newsroom', 'podcast', or 'vendor_reprint'
        limit: Max number of results to return (default: 5)
    """
    results = search_documents(query=query, source_type=source_type, limit=limit)
    if not results:
        return f"No intelligence found matching query: '{query}'."

    output = [f"### 🔍 Found {len(results)} Intelligence Items for '{query}':\n"]
    for r in results:
        output.append(f"#### [{r['source_name']}] {r['title']}")
        output.append(f"- **Type:** {r['source_type'].capitalize()} | **Published:** {r.get('published_at', 'N/A')}")
        output.append(f"- **URL:** {r['url']}")
        if r.get("topics"):
            output.append(f"- **Topics:** {', '.join(r['topics'])}")
        output.append(f"- **Executive Brief:**\n{r.get('summary', 'No summary available.')}\n")

        metrics = r.get("key_metrics", [])
        if metrics:
            output.append("- **Key Metrics & Recommendations:**")
            for m in metrics[:3]:
                output.append(f"  * `{m.get('metric')}`: {m.get('context')}")
            output.append("")
        output.append("---\n")

    return "\n".join(output)


@mcp.tool()
def get_latest_insights(source_type: Optional[str] = None, days_back: int = 14, limit: int = 5) -> str:
    """Retrieve the most recent advisory articles and executive briefings.

    Args:
        source_type: Optional filter: 'newsroom', 'podcast', or 'vendor_reprint'
        days_back: How many days back to look (default: 14)
        limit: Maximum results (default: 5)
    """
    results = get_recent_documents(source_type=source_type, days_back=days_back, limit=limit)
    if not results:
        return f"No recent insights found within the last {days_back} days."

    output = [f"### 📰 Latest {len(results)} Advisory Insights (Past {days_back} Days):\n"]
    for r in results:
        output.append(f"#### [{r['source_name']}] {r['title']}")
        output.append(f"- **Type:** {r['source_type']} | **Date:** {r.get('published_at', 'N/A')}")
        output.append(f"- **Link:** {r['url']}")
        output.append(f"- **Summary:** {r.get('summary', '')}\n")
    return "\n".join(output)


@mcp.tool()
def get_vendor_evaluations(vendor_name: Optional[str] = None, technology: Optional[str] = None, limit: int = 10) -> str:
    """Query extracted vendor rankings and evaluations from Gartner Magic Quadrants and Forrester Waves.

    Args:
        vendor_name: Filter by vendor (e.g. 'Kinaxis', 'SAP', 'Blue Yonder', 'Manhattan Associates')
        technology: Filter by software category (e.g. 'Supply Chain Planning', 'Warehouse Management', 'TMS')
        limit: Maximum results (default: 10)
    """
    evals = search_vendor_evaluations(vendor_name=vendor_name, technology=technology, limit=limit)
    if not evals:
        return "No vendor evaluations found matching criteria."

    output = [f"### 📊 Vendor Quadrant Evaluations ({len(evals)} results):\n"]
    for ev in evals:
        output.append(f"#### {ev['vendor_name']} — **{ev['placement']}**")
        output.append(f"- **Report:** {ev['report_title']} ({ev.get('year') or 'Latest'})")
        output.append(f"- **Reprint Source:** {ev['url']}")

        strengths = ev.get("strengths", [])
        if strengths:
            output.append("- **Strengths:**")
            for s in strengths[:3]:
                output.append(f"  * {s}")

        cautions = ev.get("cautions", [])
        if cautions:
            output.append("- **Cautions:**")
            for c in cautions[:3]:
                output.append(f"  * {c}")
        output.append("")

    return "\n".join(output)


@mcp.tool()
def get_podcast_takeaways(topic: Optional[str] = None, limit: int = 5) -> str:
    """Retrieve executive podcasts and interviews (Gartner, Deloitte) with episode audio links and takeaways.

    Args:
        topic: Keyword to filter podcasts (e.g. 'inventory', 'AI', 'logistics')
        limit: Maximum results (default: 5)
    """
    if topic:
        results = search_documents(query=topic, source_type="podcast", limit=limit)
    else:
        results = get_recent_documents(source_type="podcast", days_back=60, limit=limit)

    if not results:
        return "No podcast episodes found matching topic."

    output = [f"### 🎙️ Podcast Intelligence & Executive Takeaways ({len(results)} episodes):\n"]
    for r in results:
        output.append(f"#### [{r['source_name']}] {r['title']}")
        output.append(f"- **Episode Link:** {r['url']}")
        output.append(f"- **Takeaway Brief:** {r.get('summary')}")
        metrics = r.get("key_metrics", [])
        if metrics:
            output.append("- **Highlighted Metrics:**")
            for m in metrics:
                output.append(f"  * {m.get('metric')}: {m.get('context')}")
        output.append("")

    return "\n".join(output)


@mcp.tool()
def trigger_pipeline_refresh(source_type: Optional[str] = "all") -> str:
    """Trigger an on-demand background refresh of intelligence feeds.

    Args:
        source_type: 'all', 'newsrooms', 'podcasts', or 'reprints'
    """
    stats = {}
    if source_type in ("all", "newsrooms"):
        stats["newsrooms"] = crawl_all_newsrooms(max_items_per_feed=5)
    if source_type in ("all", "podcasts"):
        stats["podcasts"] = watch_all_podcasts(max_items_per_feed=3)
    if source_type in ("all", "reprints"):
        stats["reprints"] = run_reprint_discovery()

    return f"Pipeline refresh complete. New items ingested:\n```json\n{json.dumps(stats, indent=2)}\n```"


@mcp.tool()
def get_pipeline_stats() -> str:
    """Return database counts and indexing health."""
    stats = get_db_stats()
    return f"Intelligence Database Health & Statistics:\n```json\n{json.dumps(stats, indent=2)}\n```"


# --- Custom HTTP Routes for n8n Webhooks & Health Monitoring ---

@mcp.custom_route("/health", methods=["GET"])
async def http_health(request: Request) -> JSONResponse:
    """Health check endpoint for Coolify."""
    return JSONResponse({"status": "healthy", "service": "public-news-mcp"})


@mcp.custom_route("/api/stats", methods=["GET"])
async def http_stats(request: Request) -> JSONResponse:
    """Return intelligence statistics as JSON."""
    return JSONResponse(get_db_stats())


@mcp.custom_route("/api/insights/recent", methods=["GET"])
async def http_recent_insights(request: Request) -> JSONResponse:
    """Return recent advisory items as JSON for n8n briefings."""
    days_back = int(request.query_params.get("days_back", 1))
    limit = int(request.query_params.get("limit", 10))
    results = get_recent_documents(days_back=days_back, limit=limit)
    return JSONResponse({"count": len(results), "items": results})


@mcp.custom_route("/api/crawl/newsrooms", methods=["POST"])
async def http_crawl_newsrooms(request: Request) -> JSONResponse:
    """Trigger newsroom crawl via HTTP (called by n8n)."""
    max_items = int(request.query_params.get("max", 10))
    stats = crawl_all_newsrooms(max_items_per_feed=max_items)
    return JSONResponse({"status": "completed", "ingested": stats})


@mcp.custom_route("/api/crawl/podcasts", methods=["POST"])
async def http_watch_podcasts(request: Request) -> JSONResponse:
    """Trigger podcast check via HTTP (called by n8n)."""
    max_items = int(request.query_params.get("max", 5))
    stats = watch_all_podcasts(max_items_per_feed=max_items)
    return JSONResponse({"status": "completed", "ingested": stats})


@mcp.custom_route("/api/crawl/reprints", methods=["POST"])
async def http_discover_reprints(request: Request) -> JSONResponse:
    """Trigger vendor reprint discovery via HTTP."""
    stats = run_reprint_discovery()
    return JSONResponse({"status": "completed", "result": stats})


# ASGI app for Uvicorn deployment in Coolify / Docker
app = mcp.http_app()


if __name__ == "__main__":
    mcp.run()

