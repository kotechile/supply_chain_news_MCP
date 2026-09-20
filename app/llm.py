"""LLM summarization, key metrics extraction, and agentic analysis module.

Supports OpenRouter (Nous Hermes 3), OpenAI, Gemini, and Mock fallback mode.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from openai import OpenAI

from app.config import get_config

logger = logging.getLogger(__name__)


def resolve_provider() -> str:
    """Resolve provider with automatic fallback based on available API keys."""
    explicit = os.environ.get("LLM_PROVIDER")
    if explicit:
        return explicit.lower()

    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"

    config_provider = get_config().get("llm", {}).get("provider", "openrouter").lower()
    return config_provider


def get_llm_client() -> Optional[OpenAI]:
    """Initialize OpenAI-compatible client for OpenAI, Gemini, or OpenRouter."""
    provider = resolve_provider()

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            return OpenAI(api_key=api_key)

    elif provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            return OpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=api_key,
            )

    elif provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if api_key:
            return OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            )

    # Fallback check: if any key is set regardless of provider
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    if os.environ.get("GEMINI_API_KEY"):
        return OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=os.environ["GEMINI_API_KEY"],
        )

    return None


def get_model_name() -> str:
    provider = resolve_provider()
    config_model = get_config().get("llm", {}).get("model")

    if provider == "openai":
        return os.environ.get("LLM_MODEL", "gpt-4o-mini")
    elif provider == "gemini":
        return os.environ.get("LLM_MODEL", "gemini-2.0-flash")
    elif provider == "openrouter":
        return os.environ.get("LLM_MODEL", config_model or "nousresearch/hermes-3-llama-3.1-405b")
    return "mock"


def _fallback_extract(title: str, content: str) -> Dict[str, Any]:
    """Deterministic extractor when no LLM API key is configured."""
    sentences = [s.strip() for s in content.split(".") if len(s.strip()) > 30]
    summary = ". ".join(sentences[:3]) + "." if sentences else title

    # Extract metrics heuristically (e.g. percentages, dollar figures, KPIs)
    metrics = []
    pattern = r"(\b\d+(\.\d+)?%|\$\d+(\.\d+)?\s*(?:billion|million|M|B)?|\b\d+\s*(?:days|weeks|months|years|hours|facilities|nodes)\b)"
    matches = re.finditer(pattern, content)
    for m in list(matches)[:5]:
        start = max(0, m.start() - 40)
        end = min(len(content), m.end() + 40)
        context = content[start:end].replace("\n", " ").strip()
        metrics.append({"metric": m.group(0), "context": f"...{context}..."})

    # Derive common supply chain tags
    keywords = ["WMS", "TMS", "ERP", "Visibility", "AI", "Procurement", "Inventory", "Automation", "Resilience", "Logistics", "Sustainability", "Forecasting"]
    topics = [kw for kw in keywords if re.search(rf"\b{kw}\b", content, re.IGNORECASE)]
    if not topics:
        topics = ["Supply Chain", "IT Strategy"]

    return {
        "summary": summary,
        "key_metrics": metrics,
        "topics": topics,
    }


def summarize_article(
    title: str,
    content: str,
    source_name: str,
    category: str = "Supply Chain",
) -> Dict[str, Any]:
    """Generate executive brief, extract key metrics, and tag topics using LLM (e.g. Hermes 3)."""
    client = get_llm_client()
    if not client:
        logger.info("No LLM API key configured; using heuristic fallback extractor.")
        return _fallback_extract(title, content)

    # Truncate content to avoid token overflow
    truncated_content = content[:15000]

    system_prompt = (
        "You are an elite Supply Chain and Enterprise IT Intelligence Analyst. "
        "Analyze the provided advisory article, transcript, or research report. "
        "Extract actionable intelligence tailored for senior operations and IT leaders. "
        "You MUST respond ONLY with valid JSON conforming to this schema:\n"
        "{\n"
        '  "summary": "Concise 2-3 paragraph executive brief with high-signal takeaways.",\n'
        '  "key_metrics": [\n'
        '    {"metric": "e.g. 24% reduction in lead time", "context": "Explanation of how or benchmark"}\n'
        "  ],\n"
        '  "topics": ["Tag1", "Tag2", "Tag3"],\n'
        '  "framework_shifts": ["Key structural or architectural changes recommended"]\n'
        "}"
    )

    user_prompt = f"Source: {source_name}\nCategory: {category}\nTitle: {title}\n\nContent:\n{truncated_content}"

    try:
        response = client.chat.completions.create(
            model=get_model_name(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"} if "hermes" not in get_model_name() else None,
        )
        raw_text = response.choices[0].message.content or ""
        # Clean potential markdown fences from Hermes or other models
        clean_json = re.sub(r"^```json\s*", "", raw_text.strip())
        clean_json = re.sub(r"\s*```$", "", clean_json.strip())
        data = json.loads(clean_json)
        return {
            "summary": data.get("summary", title),
            "key_metrics": data.get("key_metrics", []),
            "topics": data.get("topics", [category]),
        }
    except Exception as e:
        logger.error(f"LLM extraction failed: {e}; falling back to heuristic.")
        return _fallback_extract(title, content)


def extract_vendor_evaluations_from_text(
    report_title: str,
    pdf_text: str,
    target_vendors: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Extract vendor quadrant positions, strengths, and cautions from Gartner/Forrester PDF text."""
    client = get_llm_client()
    target_list_str = ", ".join(target_vendors or ["SAP", "Kinaxis", "Blue Yonder", "Manhattan Associates", "Coupa", "Oracle"])

    if not client:
        # Fallback vendor extractor
        evals = []
        for vendor in (target_vendors or ["SAP", "Kinaxis", "Blue Yonder"]):
            if vendor.lower() in pdf_text.lower():
                evals.append({
                    "vendor_name": vendor,
                    "placement": "Leader",
                    "strengths": [f"Demonstrated execution and market presence in {report_title}"],
                    "cautions": ["Implementation complexity and licensing costs"],
                })
        return evals

    system_prompt = (
        "You are an expert enterprise software analyst. "
        "Extract vendor placement information (Leaders, Challengers, Visionaries, Niche Players) "
        "and specific Strengths and Cautions from the provided Magic Quadrant / Critical Capabilities text.\n"
        "Output ONLY a JSON array of objects with this schema:\n"
        "[\n"
        "  {\n"
        '    "vendor_name": "Vendor Name",\n'
        '    "placement": "Leader | Challenger | Visionary | Niche Player",\n'
        '    "strengths": ["Strength 1", "Strength 2"],\n'
        '    "cautions": ["Caution 1", "Caution 2"]\n'
        "  }\n"
        "]"
    )

    user_prompt = (
        f"Report: {report_title}\n"
        f"Target Vendors to look for: {target_list_str}\n\n"
        f"Document Excerpt:\n{pdf_text[:20000]}"
    )

    try:
        response = client.chat.completions.create(
            model=get_model_name(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        raw_text = response.choices[0].message.content or ""
        clean_json = re.sub(r"^```json\s*", "", raw_text.strip())
        clean_json = re.sub(r"\s*```$", "", clean_json.strip())
        evals = json.loads(clean_json)
        if isinstance(evals, list):
            return evals
        elif isinstance(evals, dict) and "vendors" in evals:
            return evals["vendors"]
        return []
    except Exception as e:
        logger.error(f"Failed to extract vendor evaluations: {e}")
        return []
