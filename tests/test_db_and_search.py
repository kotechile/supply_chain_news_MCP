"""Tests for database layer, FTS5 search, and deduplication."""

import os
import tempfile
import pytest
from app.db import (
    document_exists,
    get_connection,
    get_db_stats,
    get_recent_documents,
    init_db,
    insert_document,
    insert_vendor_evaluation,
    search_documents,
    search_vendor_evaluations,
)


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


def test_insert_and_fts_search(temp_db):
    doc_id = insert_document(
        source_type="newsroom",
        source_name="Gartner Newsroom",
        url="https://www.gartner.com/test-article",
        title="Gartner Announces Top 25 Supply Chains of 2025",
        raw_content="Leading global companies are leveraging artificial intelligence and digital twins for resilient logistics networks.",
        summary="Executive summary highlighting AI adoption in supply chains.",
        key_metrics=[{"metric": "18% efficiency increase", "context": "Through AI adoption"}],
        topics=["Supply Chain", "AI", "Logistics"],
        db_path=temp_db,
    )

    assert doc_id is not None
    assert document_exists("https://www.gartner.com/test-article", db_path=temp_db)

    # Test FTS5 search for "logistics"
    results = search_documents("logistics", db_path=temp_db)
    assert len(results) == 1
    assert results[0]["title"] == "Gartner Announces Top 25 Supply Chains of 2025"
    assert "Supply Chain" in results[0]["topics"]
    assert results[0]["key_metrics"][0]["metric"] == "18% efficiency increase"

    # Test FTS search for "artificial intelligence"
    results = search_documents('"artificial intelligence"', db_path=temp_db)
    assert len(results) == 1


def test_deduplication_and_update(temp_db):
    url = "https://newsroom.accenture.com/sample"
    insert_document(
        source_type="newsroom",
        source_name="Accenture",
        url=url,
        title="Initial Title",
        raw_content="Initial content text.",
        summary="Initial summary",
        db_path=temp_db,
    )

    # Insert updated content for same URL
    insert_document(
        source_type="newsroom",
        source_name="Accenture",
        url=url,
        title="Updated Title",
        raw_content="Updated content text.",
        summary="Updated summary",
        db_path=temp_db,
    )

    stats = get_db_stats(db_path=temp_db)
    assert stats["total_documents"] == 1

    results = search_documents("Updated", db_path=temp_db)
    assert len(results) == 1
    assert results[0]["title"] == "Updated Title"


def test_vendor_evaluations(temp_db):
    doc_id = insert_document(
        source_type="vendor_reprint",
        source_name="Gartner Reprint",
        url="https://www.kinaxis.com/gartner-mq-scp.pdf",
        title="Magic Quadrant for Supply Chain Planning",
        raw_content="Report details for Kinaxis RapidResponse...",
        summary="Gartner Magic Quadrant reprint hosted by Kinaxis.",
        db_path=temp_db,
    )

    insert_vendor_evaluation(
        document_id=doc_id,
        report_title="Magic Quadrant for Supply Chain Planning",
        vendor_name="Kinaxis",
        placement="Leader",
        strengths=["Concurrent planning capabilities", "RapidResponse platform scalability"],
        cautions=["Licensing model complexity"],
        year=2025,
        db_path=temp_db,
    )

    evals = search_vendor_evaluations(vendor_name="Kinaxis", db_path=temp_db)
    assert len(evals) == 1
    assert evals[0]["vendor_name"] == "Kinaxis"
    assert evals[0]["placement"] == "Leader"
    assert "Concurrent planning capabilities" in evals[0]["strengths"]
