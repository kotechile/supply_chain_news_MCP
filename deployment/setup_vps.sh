#!/usr/bin/env bash
set -e

echo "=== Setting up Supply Chain & IT Intelligence MCP on VPS ==="

TARGET_DIR="/opt/public-news-mcp"

# 1. Update and install prerequisites
apt-get update
apt-get install -y python3 python3-venv python3-pip git curl

# 2. Setup directory
if [ ! -d "$TARGET_DIR" ]; then
    echo "Creating directory $TARGET_DIR..."
    mkdir -p "$TARGET_DIR"
    cp -r . "$TARGET_DIR"
fi

cd "$TARGET_DIR"

# 3. Virtual environment setup
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 4. Initialize Database
echo "Initializing SQLite database..."
.venv/bin/python -m app.cli init-db

# 5. Setup Systemd Services
echo "Configuring systemd services..."
cp deployment/intel-mcp.service /etc/systemd/system/
cp deployment/intel-scheduler.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable intel-mcp
systemctl enable intel-scheduler

echo "=========================================================="
echo "Setup Complete!"
echo "1. Edit $TARGET_DIR/.env with your API keys"
echo "2. Start services:"
echo "   systemctl start intel-mcp"
echo "   systemctl start intel-scheduler"
echo "3. Connect Claude/Cursor over SSH with:"
echo "   ssh user@your-vps \"$TARGET_DIR/.venv/bin/python -m app.mcp_server\""
echo "=========================================================="
