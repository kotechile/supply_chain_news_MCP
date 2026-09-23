# 🌐 Public Advisory & Industry Intelligence MCP

An automated intelligence gathering pipeline and Model Context Protocol (MCP) server for **Supply Chain & IT Systems**. 

Harvests, synthesizes, and indexes free advisory research from **Gartner**, **Deloitte**, **Accenture**, and **Vendor Reprints** across podcasts, newsrooms, and un-gated PDF research documents.

---

## 🏗️ Architecture

```
[Podcast RSS] ──> Audio / Show Notes ────┐
[Newsroom RSS] ──> Trafilatura / Jina ───┼──> LLM Structurer (Hermes 3 / Gemini) ──> SQLite (FTS5 BM25)
[Vendor Reprints] ──> PyMuPDF / PDF ─────┘                                                ▲
                                                                                          │
                                                                   ┌──────────────────────┴──────────────────────┐
                                                                   │ FastMCP Server (stdio / sse)               │
                                                                   │ ├── search_intelligence                    │
                                                                   │ ├── get_latest_insights                    │
                                                                   │ ├── get_vendor_evaluations                 │
                                                                   │ ├── get_podcast_takeaways                  │
                                                                   │ └── trigger_pipeline_refresh               │
                                                                   └──────────────────────▲──────────────────────┘
                                                                                          │
                                                                             [Claude / Cursor / Client]
```

---

## 🚀 Quick Start

### 1. Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env and insert your LLM API key (OpenRouter / OpenAI / Gemini / DeepSeek)
```

### 2. Initialize Database & Run Ingestion
```bash
# Initialize SQLite database schema and FTS5 indexes
python -m app.cli init-db

# Run full ingestion across all sources
python -m app.cli run-all

# Or run individual collectors:
python -m app.cli crawl-newsrooms
python -m app.cli watch-podcasts
python -m app.cli discover-reprints
```

### 3. Query via CLI
```bash
# Search intelligence documents
python -m app.cli search "WMS automation"

# Search extracted vendor evaluations (Magic Quadrants)
python -m app.cli search-vendor --tech "Supply Chain Planning"

# Check database statistics
python -m app.cli stats
```

---

## 🔌 Connecting to MCP Clients (Claude Desktop, Cursor, etc.)

### Method 1: Remote Stdio over SSH (Recommended for VPS)
No open web ports required! Your local desktop client directly connects to the VPS through an SSH session.

Add this to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "supply-chain-intel": {
      "command": "ssh",
      "args": [
        "-i", "~/.ssh/id_rsa",
        "root@your-vps-ip",
        "/opt/public-news-mcp/.venv/bin/python",
        "-m", "app.mcp_server"
      ]
    }
  }
}
```

### Method 2: Local Development
```json
{
  "mcpServers": {
    "supply-chain-intel": {
      "command": "/Users/youruser/.../PUBLIC NEWS MCP/.venv/bin/python",
      "args": ["-m", "app.mcp_server"]
    }
  }
}
```

---

## 🛠️ MCP Tools Exposed

| Tool | Description | Example Arguments |
| :--- | :--- | :--- |
| `search_intelligence` | BM25 full-text search across all articles, podcasts, and reprints | `{"query": "inventory resilience", "limit": 5}` |
| `get_latest_insights` | Returns recent advisory briefings from the last $N$ days | `{"days_back": 14, "source_type": "newsroom"}` |
| `get_vendor_evaluations` | Queries extracted Magic Quadrant rankings, strengths, and cautions | `{"technology": "Supply Chain Planning", "vendor_name": "Kinaxis"}` |
| `get_podcast_takeaways` | Retrieves executive podcast episodes, audio links, and highlighted metrics | `{"topic": "automation"}` |
| `trigger_pipeline_refresh`| Triggers background feed crawl on demand | `{"source_type": "all"}` |
| `get_pipeline_stats` | Returns database record counts and health | `{}` |

---

## ⚙️ Orchestration Options

### Option A: Standalone Background Daemon on VPS
Run `python -m app.scheduler` as a systemd service:
```bash
sudo cp deployment/intel-mcp.service /etc/systemd/system/
sudo cp deployment/intel-scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now intel-scheduler
```

### Option B: n8n Workflow Automation
Import the pre-built workflows located in `n8n/workflows/`:
1. `rss_watcher.json`: Schedules RSS crawling every 6 hours with automatic retries and deduplication.
2. `daily_briefing.json`: Pulls daily executive briefs and dispatches them to a Telegram or Slack channel.

Or spin up n8n via Docker Compose:
```bash
cd deployment
docker compose up -d
```
Access n8n at `http://<your-vps-ip>:5678`.
