"""Database storage and full-text search layer using SQLite and FTS5."""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_config


def get_db_path() -> str:
    config = get_config()
    return config.get("storage", {}).get("db_path", "data/intelligence.db")


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def generate_doc_id(url: str) -> str:
    """Generate deterministic SHA256 ID from URL."""
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:24]


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables and FTS5 full-text search indexes."""
    conn = get_connection(db_path)
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,       -- 'newsroom', 'podcast', 'vendor_reprint'
            source_name TEXT NOT NULL,       -- e.g. 'Gartner Supply Chain Podcast'
            url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            published_at TEXT,
            raw_content TEXT,                -- Full article markdown, transcript, or PDF text
            summary TEXT,                    -- Executive brief
            key_metrics TEXT,                -- JSON string of metrics/recommendations
            topics TEXT,                     -- JSON array of tags
            enclosure_url TEXT,              -- Audio stream or PDF asset link
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_docs_source_type ON documents(source_type);
        CREATE INDEX IF NOT EXISTS idx_docs_published_at ON documents(published_at);
        CREATE INDEX IF NOT EXISTS idx_docs_url ON documents(url);

        CREATE TABLE IF NOT EXISTS vendor_evaluations (
            id TEXT PRIMARY KEY,
            document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
            report_title TEXT NOT NULL,
            year INTEGER,
            vendor_name TEXT NOT NULL,
            placement TEXT NOT NULL,         -- 'Leader', 'Challenger', 'Visionary', 'Niche Player'
            strengths TEXT,                  -- JSON array
            cautions TEXT,                   -- JSON array
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_vendor_name ON vendor_evaluations(vendor_name);
        CREATE INDEX IF NOT EXISTS idx_vendor_placement ON vendor_evaluations(placement);

        -- Virtual FTS5 table for full-text search
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            id UNINDEXED,
            title,
            summary,
            raw_content,
            source_name,
            topics,
            tokenize = 'porter unicode61'
        );

        -- Triggers to keep FTS index synchronized with documents table
        CREATE TRIGGER IF NOT EXISTS trg_docs_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts (id, title, summary, raw_content, source_name, topics)
            VALUES (new.id, new.title, new.summary, new.raw_content, new.source_name, new.topics);
        END;

        CREATE TRIGGER IF NOT EXISTS trg_docs_ad AFTER DELETE ON documents BEGIN
            DELETE FROM documents_fts WHERE id = old.id;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_docs_au AFTER UPDATE ON documents BEGIN
            DELETE FROM documents_fts WHERE id = old.id;
            INSERT INTO documents_fts (id, title, summary, raw_content, source_name, topics)
            VALUES (new.id, new.title, new.summary, new.raw_content, new.source_name, new.topics);
        END;
        """)
    conn.close()


def document_exists(url: str, db_path: Optional[str] = None) -> bool:
    """Check if a document URL has already been processed."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM documents WHERE url = ?", (url,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def insert_document(
    source_type: str,
    source_name: str,
    url: str,
    title: str,
    raw_content: str,
    summary: str = "",
    key_metrics: Optional[List[Dict[str, Any]]] = None,
    topics: Optional[List[str]] = None,
    published_at: Optional[str] = None,
    enclosure_url: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Insert or update a document in the database."""
    doc_id = generate_doc_id(url)
    metrics_json = json.dumps(key_metrics or [], ensure_ascii=False)
    topics_json = json.dumps(topics or [], ensure_ascii=False)

    conn = get_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO documents (
                id, source_type, source_name, url, title, published_at,
                raw_content, summary, key_metrics, topics, enclosure_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                raw_content = excluded.raw_content,
                summary = excluded.summary,
                key_metrics = excluded.key_metrics,
                topics = excluded.topics,
                enclosure_url = excluded.enclosure_url,
                published_at = COALESCE(excluded.published_at, documents.published_at)
            """,
            (
                doc_id,
                source_type,
                source_name,
                url,
                title,
                published_at,
                raw_content,
                summary,
                metrics_json,
                topics_json,
                enclosure_url,
            ),
        )
    conn.close()
    return doc_id


def insert_vendor_evaluation(
    document_id: str,
    report_title: str,
    vendor_name: str,
    placement: str,
    strengths: Optional[List[str]] = None,
    cautions: Optional[List[str]] = None,
    year: Optional[int] = None,
    db_path: Optional[str] = None,
) -> str:
    eval_id = hashlib.sha256(f"{document_id}_{vendor_name}_{report_title}".encode("utf-8")).hexdigest()[:24]
    strengths_json = json.dumps(strengths or [], ensure_ascii=False)
    cautions_json = json.dumps(cautions or [], ensure_ascii=False)

    conn = get_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO vendor_evaluations (
                id, document_id, report_title, year, vendor_name, placement, strengths, cautions
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                placement = excluded.placement,
                strengths = excluded.strengths,
                cautions = excluded.cautions
            """,
            (
                eval_id,
                document_id,
                report_title,
                year,
                vendor_name,
                placement,
                strengths_json,
                cautions_json,
            ),
        )
    conn.close()
    return eval_id


def search_documents(
    query: str,
    source_type: Optional[str] = None,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Perform BM25 full-text search with optional source filtering."""
    conn = get_connection(db_path)
    cur = conn.cursor()

    # Clean and prepare FTS query (escape quotes, support phrase queries)
    clean_query = query.replace('"', '""').strip()
    if not clean_query:
        return []

    if source_type:
        sql = """
            SELECT d.id, d.source_type, d.source_name, d.url, d.title, d.published_at,
                   d.summary, d.key_metrics, d.topics, d.created_at,
                   bm25(documents_fts) AS rank
            FROM documents_fts
            JOIN documents d ON d.id = documents_fts.id
            WHERE documents_fts MATCH ? AND d.source_type = ?
            ORDER BY rank
            LIMIT ?
        """
        cur.execute(sql, (clean_query, source_type, limit))
    else:
        sql = """
            SELECT d.id, d.source_type, d.source_name, d.url, d.title, d.published_at,
                   d.summary, d.key_metrics, d.topics, d.created_at,
                   bm25(documents_fts) AS rank
            FROM documents_fts
            JOIN documents d ON d.id = documents_fts.id
            WHERE documents_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        cur.execute(sql, (clean_query, limit))

    results = []
    for row in cur.fetchall():
        item = dict(row)
        item["key_metrics"] = json.loads(item["key_metrics"]) if item.get("key_metrics") else []
        item["topics"] = json.loads(item["topics"]) if item.get("topics") else []
        results.append(item)

    conn.close()
    return results


def get_recent_documents(
    source_type: Optional[str] = None,
    days_back: int = 7,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch the most recently ingested intelligence documents."""
    conn = get_connection(db_path)
    cur = conn.cursor()

    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")

    if source_type:
        sql = """
            SELECT id, source_type, source_name, url, title, published_at,
                   summary, key_metrics, topics, created_at
            FROM documents
            WHERE source_type = ? AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        cur.execute(sql, (source_type, cutoff_date, limit))
    else:
        sql = """
            SELECT id, source_type, source_name, url, title, published_at,
                   summary, key_metrics, topics, created_at
            FROM documents
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        cur.execute(sql, (cutoff_date, limit))

    results = []
    for row in cur.fetchall():
        item = dict(row)
        item["key_metrics"] = json.loads(item["key_metrics"]) if item.get("key_metrics") else []
        item["topics"] = json.loads(item["topics"]) if item.get("topics") else []
        results.append(item)

    conn.close()
    return results


def search_vendor_evaluations(
    vendor_name: Optional[str] = None,
    technology: Optional[str] = None,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query extracted vendor evaluations (e.g. Magic Quadrants)."""
    conn = get_connection(db_path)
    cur = conn.cursor()

    params: List[Any] = []
    conditions: List[str] = []

    if vendor_name:
        conditions.append("vendor_name LIKE ?")
        params.append(f"%{vendor_name}%")
    if technology:
        conditions.append("report_title LIKE ?")
        params.append(f"%{technology}%")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT v.id, v.report_title, v.year, v.vendor_name, v.placement,
               v.strengths, v.cautions, d.url, d.source_name
        FROM vendor_evaluations v
        JOIN documents d ON d.id = v.document_id
        {where_clause}
        ORDER BY v.year DESC, v.placement ASC
        LIMIT ?
    """
    params.append(limit)
    cur.execute(sql, tuple(params))

    results = []
    for row in cur.fetchall():
        item = dict(row)
        item["strengths"] = json.loads(item["strengths"]) if item.get("strengths") else []
        item["cautions"] = json.loads(item["cautions"]) if item.get("cautions") else []
        results.append(item)

    conn.close()
    return results


def get_db_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Return counts and health of the database."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT source_type, COUNT(*) as count FROM documents GROUP BY source_type")
    doc_counts = {row["source_type"]: row["count"] for row in cur.fetchall()}

    cur.execute("SELECT COUNT(*) as count FROM vendor_evaluations")
    eval_count = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) as count FROM documents")
    total_docs = cur.fetchone()["count"]

    conn.close()
    return {
        "total_documents": total_docs,
        "by_source_type": doc_counts,
        "vendor_evaluations": eval_count,
    }
