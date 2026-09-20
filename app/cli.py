"""Unified CLI for the Supply Chain & IT Intelligence Pipeline and MCP Server."""

import argparse
import json
import logging
import sys
from app.db import (
    get_db_stats,
    init_db,
    search_documents,
    search_vendor_evaluations,
)
from app.ingest.newsroom_crawler import crawl_all_newsrooms, crawl_feed
from app.ingest.podcast_watcher import watch_all_podcasts
from app.ingest.reprint_agent import run_reprint_discovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("intel-cli")


def main():
    parser = argparse.ArgumentParser(
        prog="intel-mcp",
        description="Supply Chain & IT advisory intelligence harvester and FastMCP server",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # init-db
    subparsers.add_parser("init-db", help="Initialize SQLite database schema and FTS5 indexes")

    # crawl-newsrooms
    p_news = subparsers.add_parser("crawl-newsrooms", help="Crawl advisory newsrooms (Gartner, Accenture, Deloitte)")
    p_news.add_argument("--max", type=int, default=10, help="Max items per feed")

    # watch-podcasts
    p_pod = subparsers.add_parser("watch-podcasts", help="Watch podcast feeds for new episodes")
    p_pod.add_argument("--max", type=int, default=5, help="Max episodes per feed")

    # discover-reprints
    subparsers.add_parser("discover-reprints", help="Run vendor reprint discovery for Magic Quadrants")

    # run-all
    subparsers.add_parser("run-all", help="Run all ingestions (newsrooms, podcasts, reprints)")

    # test-feed
    p_test = subparsers.add_parser("test-feed", help="Test ingestion on a single RSS feed URL")
    p_test.add_argument("url", help="RSS feed URL to test")
    p_test.add_argument("--name", default="Custom Feed", help="Name of source")
    p_test.add_argument("--category", default="Test", help="Category name")

    # search
    p_search = subparsers.add_parser("search", help="Perform BM25 search on local intelligence DB")
    p_search.add_argument("query", help="Search keywords")
    p_search.add_argument("--type", choices=["newsroom", "podcast", "vendor_reprint"], help="Filter by source type")
    p_search.add_argument("--limit", type=int, default=5, help="Number of results")

    # search-vendor
    p_vsearch = subparsers.add_parser("search-vendor", help="Search vendor evaluations / Magic Quadrants")
    p_vsearch.add_argument("--vendor", help="Vendor name (e.g. Kinaxis, SAP)")
    p_vsearch.add_argument("--tech", help="Technology category (e.g. Supply Chain Planning)")

    # stats
    subparsers.add_parser("stats", help="Show database counts and indexing health")

    # serve-mcp
    p_mcp = subparsers.add_parser("serve-mcp", help="Start the FastMCP server")
    p_mcp.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="MCP transport mode")
    p_mcp.add_argument("--host", default="0.0.0.0", help="Host for SSE transport")
    p_mcp.add_argument("--port", type=int, default=8080, help="Port for SSE transport")

    # run-scheduler
    subparsers.add_parser("run-scheduler", help="Start background polling scheduler daemon")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "init-db":
        init_db()
        print("✅ Database initialized successfully.")

    elif args.command == "crawl-newsrooms":
        init_db()
        stats = crawl_all_newsrooms(max_items_per_feed=args.max)
        print(f"✅ Ingested newsrooms: {json.dumps(stats, indent=2)}")

    elif args.command == "watch-podcasts":
        init_db()
        stats = watch_all_podcasts(max_items_per_feed=args.max)
        print(f"✅ Ingested podcasts: {json.dumps(stats, indent=2)}")

    elif args.command == "discover-reprints":
        init_db()
        stats = run_reprint_discovery()
        print(f"✅ Reprints processed: {json.dumps(stats, indent=2)}")

    elif args.command == "run-all":
        init_db()
        n_stats = crawl_all_newsrooms(max_items_per_feed=10)
        p_stats = watch_all_podcasts(max_items_per_feed=5)
        r_stats = run_reprint_discovery()
        print(f"✅ Ingestion complete:\nNewsrooms: {n_stats}\nPodcasts: {p_stats}\nReprints: {r_stats}")

    elif args.command == "test-feed":
        init_db()
        src = {"name": args.name, "url": args.url, "category": args.category}
        ids = crawl_feed(src, max_items=3)
        print(f"✅ Processed {len(ids)} items from {args.url}")

    elif args.command == "search":
        results = search_documents(query=args.query, source_type=args.type, limit=args.limit)
        print(f"🔍 Found {len(results)} items for '{args.query}':\n")
        for r in results:
            print(f"- [{r['source_name']}] {r['title']}")
            print(f"  Type: {r['source_type']} | Link: {r['url']}")
            print(f"  Summary: {r['summary'][:200]}...\n")

    elif args.command == "search-vendor":
        results = search_vendor_evaluations(vendor_name=args.vendor, technology=args.tech)
        print(f"📊 Found {len(results)} vendor evaluations:\n")
        for ev in results:
            print(f"- {ev['vendor_name']}: {ev['placement']} in '{ev['report_title']}'")
            print(f"  Strengths: {', '.join(ev['strengths'][:2])}")
            print(f"  Cautions: {', '.join(ev['cautions'][:2])}\n")

    elif args.command == "stats":
        stats = get_db_stats()
        print("📈 Intelligence Database Stats:")
        print(json.dumps(stats, indent=2))

    elif args.command == "serve-mcp":
        from app.mcp_server import mcp
        if args.transport == "sse":
            mcp.run(transport="sse", host=args.host, port=args.port)
        else:
            mcp.run(transport="stdio")

    elif args.command == "run-scheduler":
        from app.scheduler import start_scheduler
        start_scheduler()


if __name__ == "__main__":
    main()
