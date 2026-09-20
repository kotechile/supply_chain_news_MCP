"""Standalone scheduler using APScheduler for running ingestion jobs on a VPS."""

import logging
import time
from apscheduler.schedulers.blocking import BlockingScheduler

from app.config import get_config
from app.db import init_db
from app.ingest.newsroom_crawler import crawl_all_newsrooms
from app.ingest.podcast_watcher import watch_all_podcasts
from app.ingest.reprint_agent import run_reprint_discovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def job_crawl_newsrooms():
    logger.info("Executing scheduled newsroom crawl...")
    stats = crawl_all_newsrooms(max_items_per_feed=10)
    logger.info(f"Newsroom crawl finished: {stats}")


def job_watch_podcasts():
    logger.info("Executing scheduled podcast check...")
    stats = watch_all_podcasts(max_items_per_feed=5)
    logger.info(f"Podcast check finished: {stats}")


def job_discover_reprints():
    logger.info("Executing scheduled vendor reprint discovery...")
    stats = run_reprint_discovery()
    logger.info(f"Reprint discovery finished: {stats}")


def start_scheduler():
    init_db()
    config = get_config()
    sched_cfg = config.get("scheduler", {})

    news_hours = sched_cfg.get("newsroom_interval_hours", 6)
    pod_hours = sched_cfg.get("podcast_interval_hours", 12)
    reprint_days = sched_cfg.get("reprints_interval_days", 7)

    scheduler = BlockingScheduler()

    # Initial warm-up run on startup
    logger.info("Running initial startup ingestion checks...")
    try:
        job_crawl_newsrooms()
        job_watch_podcasts()
    except Exception as e:
        logger.error(f"Startup ingestion error: {e}")

    # Register intervals
    scheduler.add_job(job_crawl_newsrooms, "interval", hours=news_hours, id="job_newsrooms")
    scheduler.add_job(job_watch_podcasts, "interval", hours=pod_hours, id="job_podcasts")
    scheduler.add_job(job_discover_reprints, "interval", days=reprint_days, id="job_reprints")

    logger.info(
        f"Scheduler started. Newsrooms: every {news_hours}h | "
        f"Podcasts: every {pod_hours}h | Reprints: every {reprint_days}d."
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler shutting down.")


if __name__ == "__main__":
    start_scheduler()
