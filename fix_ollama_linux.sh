#!/bin/bash

# IrisChat - Ollama Fixer for Linux (Nuclear Option)
# 1. Finds Ollama binary (Snap or Standard).
# 2. STOPS and DISABLES all conflicting services (Snap or Manual).
# 3. Creates ONE single authoritative systemd service.
# 4. Forces 0.0.0.0 binding.

echo "🔧 Starting Ollama Fix (Nuclear Option)..."

# 1. Detect Binary
OLLAMA_PATH=$(which ollama)
if [ -z "$OLLAMA_PATH" ]; then
    echo "❌ Ollama not found! Please install it first."
    exit 1
fi
echo "✅ Found Ollama at: $OLLAMA_PATH"

# 2. Stop EVERYTHING related to Ollama
echo "🛑 Stopping all Ollama processes and services..."
sudo pkill ollama
sudo systemctl stop ollama 2>/dev/null
sudo systemctl disable ollama 2>/dev/null

# Try to stop common Snap service names
sudo systemctl stop snap.ollama.ollama.service 2>/dev/null
sudo systemctl disable snap.ollama.ollama.service 2>/dev/null
sudo systemctl stop snap.ollama.service 2>/dev/null
sudo systemctl disable snap.ollama.service 2>/dev/null

# Mask the Snap service to prevent it from auto-starting and conflicting
if systemctl list-unit-files | grep -q snap.ollama.ollama.service; then
    echo "   - Masking Snap service to prevent conflicts..."
    sudo systemctl mask snap.ollama.ollama.service
fi

# 3. Create ONE Authoritative Service
SERVICE_FILE="/etc/systemd/system/ollama.service"
echo "📝 Creating clean $SERVICE_FILE..."

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=Ollama Service (Custom)
After=network-online.target

[Service]
ExecStart=/bin/bash -c "OLLAMA_HOST=0.0.0.0 OLLAMA_ORIGINS=* exec $OLLAMA_PATH serve"
User=root
Group=root
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

# 4. Reload and Start
echo "🔄 Starting new Ollama service..."
sudo systemctl daemon-reload
sudo systemctl unmask ollama 2>/dev/null # Just in case
sudo systemctl enable ollama
sudo systemctl restart ollama

# 5. Configure Firewall
echo "🛡️ Configuring Firewall..."
if command -v ufw > /dev/null && sudo ufw status | grep -q "Status: active"; then
    sudo ufw allow 11434/tcp
    sudo ufw reload
else
    # Check if rule exists before adding
    if ! sudo iptables -C INPUT -p tcp --dport 11434 -j ACCEPT 2>/dev/null; then
        sudo iptables -I INPUT -p tcp --dport 11434 -j ACCEPT
    fi
fi

# 6. Ensure Docker daemon adds host.docker.internal for Linux containers
DOCKER_DAEMON_JSON="/etc/docker/daemon.json"
if command -v docker > /dev/null; then
    echo "🐳 Configuring Docker host-gateway mapping..."
    if [ -f "$DOCKER_DAEMON_JSON" ]; then
        # Check if host-gateway-ip is already configured
        if ! grep -q "host-gateway-ip" "$DOCKER_DAEMON_JSON" 2>/dev/null; then
            echo "   - Note: Add '--add-host=host.docker.internal:host-gateway' to your container run options"
            echo "   - Or set OLLAMA_BASE_URL to http://172.17.0.1:11434 in Coolify"
        fi
    fi
fi

# 7. Verify
echo "✅ Done."
echo "🔍 Checking Port 11434 (Should be 0.0.0.0)..."
sleep 2
if command -v ss > /dev/null; then
    sudo ss -tulpn | grep 11434
else
    netstat -tulpn | grep 11434
fi
