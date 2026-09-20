"""Agentic finder for Gartner Magic Quadrant & Forrester Wave vendor PDF reprints.

Uses SERP / Google Search or direct landing page inspection to locate un-gated PDFs,
extract text via PyPDF, and extract vendor placement matrices using Hermes / LLM.
"""

import io
import logging
import os
import re
from typing import Any, Dict, List, Optional
import httpx
from pypdf import PdfReader

from app.config import get_config
from app.db import document_exists, insert_document, insert_vendor_evaluation
from app.llm import extract_vendor_evaluations_from_text, summarize_article

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.9,*/*;q=0.8",
}


def search_google_custom_search(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    """Search Google via Custom Search JSON API for indexed PDF files or vendor landing pages."""
    api_key = os.environ.get("GOOGLE_SEARCH_API_KEY")
    cx = os.environ.get("GOOGLE_SEARCH_ENGINE_ID")

    if not api_key or not cx:
        logger.info("Google Search API key or Engine ID not configured; skipping SERP query.")
        return []

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": min(num_results, 10),
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                items = []
                for item in data.get("items", []):
                    items.append({
                        "title": item.get("title", ""),
                        "link": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })
                return items
    except Exception as e:
        logger.error(f"Google Custom Search failed for query '{query}': {e}")

    return []


def discover_ungated_pdf_url(page_url: str) -> Optional[str]:
    """Inspect a vendor landing page and uncover un-gated direct PDF asset links.

    Many HubSpot, Marketo, or custom vendor landing pages expose the final PDF
    download link directly in the HTML or client-side redirect script without
    enforcing server-side auth.
    """
    if page_url.lower().endswith(".pdf"):
        return page_url

    try:
        with httpx.Client(headers=DEFAULT_HEADERS, timeout=15.0, follow_redirects=True) as client:
            resp = client.get(page_url)
            if resp.status_code != 200:
                return None

            html = resp.text

            # 1. Direct PDF links in anchor tags
            pdf_links = re.findall(r'href=["\'](https?://[^"\']+\.pdf(?:\?[^"\']*)?)["\']', html, re.IGNORECASE)
            for link in pdf_links:
                if "gartner" in link.lower() or "reprint" in link.lower() or "report" in link.lower():
                    return link

            # 2. Look for cloud asset links (S3, CloudFront, HubSpot, Marketo)
            asset_patterns = [
                r'["\'](https?://[^"\']*(?:s3\.amazonaws\.com|cloudfront\.net|hubspotusercontent|marketo)[^"\']+\.pdf)["\']',
                r'(?:pdfUrl|downloadUrl|assetUrl|redirectUrl)\s*[:=]\s*["\'](https?://[^"\']+\.pdf)["\']',
            ]
            for pat in asset_patterns:
                match = re.search(pat, html, re.IGNORECASE)
                if match:
                    return match.group(1)

            # 3. If any .pdf link exists on the page
            if pdf_links:
                return pdf_links[0]
    except Exception as e:
        logger.warning(f"Error inspecting page {page_url} for PDF: {e}")

    return None


def download_and_extract_pdf_text(pdf_url: str, max_pages: int = 35) -> Optional[str]:
    """Download PDF and extract text using PyPDF."""
    try:
        with httpx.Client(headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True) as client:
            resp = client.get(pdf_url)
            if resp.status_code != 200:
                logger.warning(f"Failed to download PDF {pdf_url}: HTTP {resp.status_code}")
                return None

            pdf_file = io.BytesIO(resp.content)
            reader = PdfReader(pdf_file)
            total_pages = len(reader.pages)
            pages_to_read = min(total_pages, max_pages)

            extracted_text = []
            for i in range(pages_to_read):
                page_text = reader.pages[i].extract_text()
                if page_text:
                    extracted_text.append(f"--- PAGE {i+1} ---\n{page_text}")

            full_text = "\n\n".join(extracted_text)
            logger.info(f"Extracted {len(full_text)} characters from {pages_to_read} pages of {pdf_url}")
            return full_text
    except Exception as e:
        logger.error(f"Error reading PDF from {pdf_url}: {e}")
        return None


def process_vendor_reprint(
    pdf_url: str,
    report_title: str,
    target_vendors: Optional[List[str]] = None,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Process a discovered vendor reprint PDF, extract text, summarize, and extract evaluations."""
    if document_exists(pdf_url, db_path=db_path):
        logger.info(f"PDF already indexed: {pdf_url}")
        return None

    full_text = download_and_extract_pdf_text(pdf_url)
    if not full_text or len(full_text.strip()) < 500:
        logger.warning(f"Insufficient text extracted from PDF: {pdf_url}")
        return None

    # Summarize report
    brief_data = summarize_article(
        title=report_title,
        content=full_text,
        source_name="Gartner / Vendor Reprint",
        category="Analyst Research",
    )

    # Extract vendor evaluation matrix (Leaders, Challengers, Strengths, Cautions)
    evaluations = extract_vendor_evaluations_from_text(
        report_title=report_title,
        pdf_text=full_text,
        target_vendors=target_vendors,
    )

    # Insert document
    doc_id = insert_document(
        source_type="vendor_reprint",
        source_name="Gartner Reprint",
        url=pdf_url,
        title=report_title,
        raw_content=full_text[:30000],  # store primary text
        summary=brief_data.get("summary", ""),
        key_metrics=brief_data.get("key_metrics", []),
        topics=list(set(["Magic Quadrant", "Vendor Evaluation", "Supply Chain IT"] + brief_data.get("topics", []))),
        enclosure_url=pdf_url,
        db_path=db_path,
    )

    # Insert individual vendor placements
    for ev in evaluations:
        insert_vendor_evaluation(
            document_id=doc_id,
            report_title=report_title,
            vendor_name=ev.get("vendor_name", "Unknown"),
            placement=ev.get("placement", "Niche Player"),
            strengths=ev.get("strengths", []),
            cautions=ev.get("cautions", []),
            db_path=db_path,
        )

    logger.info(f"Indexed vendor reprint '{report_title}' ({len(evaluations)} vendor evaluations).")
    return doc_id


def run_reprint_discovery(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Run discovery for vendor reprints based on config queries."""
    config = get_config()
    reprints_cfg = config.get("ingest", {}).get("vendor_reprints", {})
    if not reprints_cfg.get("enabled", True):
        logger.info("Vendor reprint ingestion is disabled.")
        return {"processed": 0}

    queries = reprints_cfg.get("search_queries", [])
    target_vendors = reprints_cfg.get("target_vendors", [])

    processed_count = 0
    for query in queries:
        logger.info(f"Running search for vendor reprints: {query}")
        results = search_google_custom_search(query, num_results=3)

        for res in results:
            link = res["link"]
            title = res["title"]

            pdf_url = discover_ungated_pdf_url(link)
            if pdf_url:
                doc_id = process_vendor_reprint(
                    pdf_url=pdf_url,
                    report_title=title,
                    target_vendors=target_vendors,
                    db_path=db_path,
                )
                if doc_id:
                    processed_count += 1

    return {"processed": processed_count}
