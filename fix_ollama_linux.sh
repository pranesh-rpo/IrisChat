#!/bin/bash

# IrisChat - Ollama Fixer for Linux
# Removes snap ollama (ignores env vars), installs standard ollama,
# and forces 0.0.0.0 binding so Docker containers can reach it.

echo "=== IrisChat Ollama Fix ==="

# 1. Remove snap ollama if installed (snap ignores OLLAMA_HOST)
if snap list ollama &>/dev/null; then
    echo "Removing snap version of Ollama (it ignores OLLAMA_HOST)..."
    sudo snap remove ollama
fi

# 2. Stop any existing ollama services
echo "Stopping existing Ollama services..."
sudo pkill ollama 2>/dev/null
sudo systemctl stop ollama 2>/dev/null
sudo systemctl disable ollama 2>/dev/null

# 3. Install Ollama the standard way (if not already at /usr/local/bin)
if [ ! -f /usr/local/bin/ollama ]; then
    echo "Installing Ollama (standard method)..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama already installed at /usr/local/bin/ollama"
fi

# 4. Create systemd service with 0.0.0.0 binding
SERVICE_FILE="/etc/systemd/system/ollama.service"
echo "Creating $SERVICE_FILE with 0.0.0.0 binding..."

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
Environment=OLLAMA_HOST=0.0.0.0
Environment=OLLAMA_ORIGINS=*
ExecStart=/usr/local/bin/ollama serve
User=root
Group=root
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

# 5. Start ollama
echo "Starting Ollama..."
sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl restart ollama

# 6. Firewall
echo "Opening port 11434..."
if command -v ufw > /dev/null && sudo ufw status | grep -q "Status: active"; then
    sudo ufw allow 11434/tcp
    sudo ufw reload
else
    if ! sudo iptables -C INPUT -p tcp --dport 11434 -j ACCEPT 2>/dev/null; then
        sudo iptables -I INPUT -p tcp --dport 11434 -j ACCEPT
    fi
fi

# 7. Verify
echo ""
echo "Waiting for Ollama to start..."
sleep 3

if command -v ss > /dev/null; then
    LISTEN_OUTPUT=$(sudo ss -tulpn | grep 11434)
else
    LISTEN_OUTPUT=$(netstat -tulpn | grep 11434)
fi

echo "$LISTEN_OUTPUT"

if echo "$LISTEN_OUTPUT" | grep -qE "(0\.0\.0\.0|\*):11434"; then
    echo ""
    echo "SUCCESS! Ollama is listening on 0.0.0.0:11434"
    echo "Set OLLAMA_BASE_URL=http://172.17.0.1:11434 in Coolify and redeploy."
else
    echo ""
    echo "WARNING: Ollama is NOT on 0.0.0.0:11434. Check: sudo journalctl -u ollama -n 20"
fi
