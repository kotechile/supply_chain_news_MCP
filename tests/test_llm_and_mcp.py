"""Tests for LLM fallback extraction and FastMCP tools."""

import os
import tempfile
import pytest
from app.db import init_db, insert_document, insert_vendor_evaluation
from app.llm import _fallback_extract
from app.mcp_server import (
    get_latest_insights,
    get_pipeline_stats,
    get_podcast_takeaways,
    get_vendor_evaluations,
    search_intelligence,
)


def test_fallback_extract_metrics():
    text = (
        "Accenture research reveals that companies deploying AI in procurement achieve a 25% cost reduction "
        "and save $1.2 million annually. The typical deployment takes 6 months across 14 facilities. "
        "Key investments are targeted towards WMS and supply chain visibility."
    )
    result = _fallback_extract("Accenture Study", text)

    assert "summary" in result
    assert len(result["key_metrics"]) >= 2
    metrics_found = [m["metric"] for m in result["key_metrics"]]
    assert any("25%" in m for m in metrics_found)
    assert any("WMS" in t or "Visibility" in t for t in result["topics"])


def test_mcp_tools_flow():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)

    # Monkeypatch config db path
    from app import db
    original_get_db_path = db.get_db_path
    db.get_db_path = lambda: db_path

    try:
        # Seed test data
        doc_id = insert_document(
            source_type="podcast",
            source_name="The Gartner Supply Chain Podcast",
            url="https://feeds.megaphone.fm/episode-101",
            title="Navigating Disruptions with Autonomous Planning",
            raw_content="In this episode, Thomas O'Connor discusses autonomous planning in WMS networks.",
            summary="Discussion on autonomous supply chain systems and operational resilience.",
            key_metrics=[{"metric": "30% cycle reduction", "context": "In fulfillment times"}],
            topics=["Autonomous", "WMS", "Disruption"],
            enclosure_url="https://traffic.megaphone.fm/ep101.mp3",
            db_path=db_path,
        )

        insert_vendor_evaluation(
            document_id=doc_id,
            report_title="Critical Capabilities for WMS",
            vendor_name="Manhattan Associates",
            placement="Leader",
            strengths=["Manhattan Active WMS cloud-native architecture"],
            cautions=["High licensing tier"],
            db_path=db_path,
        )

        # Test tool 1: search_intelligence
        search_res = search_intelligence("autonomous planning")
        assert "The Gartner Supply Chain Podcast" in search_res
        assert "Autonomous" in search_res

        # Test tool 2: get_podcast_takeaways
        pod_res = get_podcast_takeaways()
        assert "Navigating Disruptions" in pod_res

        # Test tool 3: get_vendor_evaluations
        eval_res = get_vendor_evaluations(vendor_name="Manhattan")
        assert "Manhattan Associates" in eval_res
        assert "Leader" in eval_res

        # Test tool 4: get_pipeline_stats
        stats_res = get_pipeline_stats()
        assert "total_documents" in stats_res

    finally:
        db.get_db_path = original_get_db_path
        if os.path.exists(db_path):
            os.unlink(db_path)
