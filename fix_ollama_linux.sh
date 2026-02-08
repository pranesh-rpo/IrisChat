#!/bin/bash

# IrisChat - Ollama Fixer for Linux
# 1. Finds Ollama binary (Snap or Standard).
# 2. STOPS and DISABLES all conflicting services.
# 3. Creates ONE single authoritative systemd service.
# 4. Forces 0.0.0.0 binding.

echo "Starting Ollama Fix..."

# 1. Detect Binary
OLLAMA_PATH=$(which ollama)
if [ -z "$OLLAMA_PATH" ]; then
    echo "Ollama not found! Please install it first."
    exit 1
fi
echo "Found Ollama at: $OLLAMA_PATH"

# 2. Stop EVERYTHING related to Ollama
echo "Stopping all Ollama processes and services..."
sudo pkill ollama 2>/dev/null
sudo systemctl stop ollama 2>/dev/null
sudo systemctl disable ollama 2>/dev/null
sudo systemctl stop snap.ollama.ollama.service 2>/dev/null
sudo systemctl disable snap.ollama.ollama.service 2>/dev/null
sudo systemctl stop snap.ollama.service 2>/dev/null
sudo systemctl disable snap.ollama.service 2>/dev/null

if systemctl list-unit-files | grep -q snap.ollama.ollama.service; then
    echo "Masking Snap service to prevent conflicts..."
    sudo systemctl mask snap.ollama.ollama.service
fi

# 3. Create ONE Authoritative Service (using Environment= to avoid quoting issues)
SERVICE_FILE="/etc/systemd/system/ollama.service"
echo "Creating clean $SERVICE_FILE..."

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
ExecStart=/usr/bin/env OLLAMA_HOST=0.0.0.0 OLLAMA_ORIGINS=* $OLLAMA_PATH serve
User=root
Group=root
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

# 4. Reload and Start
echo "Starting new Ollama service..."
sudo systemctl daemon-reload
sudo systemctl unmask ollama 2>/dev/null
sudo systemctl enable ollama
sudo systemctl restart ollama

# 5. Configure Firewall
echo "Configuring Firewall..."
if command -v ufw > /dev/null && sudo ufw status | grep -q "Status: active"; then
    sudo ufw allow 11434/tcp
    sudo ufw reload
else
    if ! sudo iptables -C INPUT -p tcp --dport 11434 -j ACCEPT 2>/dev/null; then
        sudo iptables -I INPUT -p tcp --dport 11434 -j ACCEPT
    fi
fi

# 6. Verify
echo "Done! Checking Port 11434 (Should be 0.0.0.0)..."
sleep 2
if command -v ss > /dev/null; then
    sudo ss -tulpn | grep 11434
else
    netstat -tulpn | grep 11434
fi

echo ""
echo "If you see 0.0.0.0:11434 above, Ollama is ready!"
echo "Set OLLAMA_BASE_URL=http://172.17.0.1:11434 in Coolify and redeploy."
