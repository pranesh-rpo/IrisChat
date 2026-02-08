#!/bin/bash

# Fix for Ollama on Linux VPS
# 1. Stops running Ollama processes
# 2. Creates the systemd service file if missing
# 3. Configures it to listen on 0.0.0.0 (Required for Docker/Coolify)

set -e

echo "🔧 Starting Ollama Fix..."

# 1. Find Ollama Binary
OLLAMA_BIN=$(which ollama)
if [ -z "$OLLAMA_BIN" ]; then
    echo "❌ Ollama not found! Please install it first."
    exit 1
fi
echo "✅ Found Ollama at: $OLLAMA_BIN"

# 2. Stop existing processes
echo "🛑 Stopping any running Ollama instances..."
sudo pkill ollama || true
# Wait a moment
sleep 2

# 3. Create Service File
echo "📝 Creating /etc/systemd/system/ollama.service..."
sudo bash -c "cat <<EOF > /etc/systemd/system/ollama.service
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
ExecStart=$OLLAMA_BIN serve
User=root
Group=root
Restart=always
RestartSec=3
Environment=\"OLLAMA_HOST=0.0.0.0\"

[Install]
WantedBy=default.target
EOF"

# 4. Reload and Start
echo "🔄 Reloading systemd and starting Ollama..."
sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl start ollama

echo "✅ Success! Ollama is now running on 0.0.0.0:11434"
echo "🔍 Verification: netstat -tulpn | grep ollama"
