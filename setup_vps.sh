#!/bin/bash

# IrisChat VPS One-Click Setup Script
# Works on Ubuntu/Debian

set -e # Exit on error

echo "🚀 Starting IrisChat VPS Setup..."

# 1. Update System
echo "📦 Updating system packages..."
sudo apt-get update && sudo apt-get install -y curl git python3-pip

# 2. Install Docker (if not present)
if ! command -v docker &> /dev/null; then
    echo "🐳 Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh
    # Add current user to docker group
    sudo usermod -aG docker $USER
    echo "⚠️  You may need to log out and back in for Docker permissions to take effect."
else
    echo "✅ Docker is already installed."
fi

# 3. Install Ollama (if not present)
if ! command -v ollama &> /dev/null; then
    echo "🦙 Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "✅ Ollama is already installed."
fi

# 4. Pull AI Model
echo "🧠 Pulling Gemma 2:2b Model (this might take a minute)..."
# Start ollama in background if not running
if ! pgrep -x "ollama" > /dev/null; then
    ollama serve &
    OLLAMA_PID=$!
    sleep 5 # Wait for it to start
fi

ollama pull gemma2:2b

# 5. Setup Configuration
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cp .env.example .env
    echo "⚠️  PLEASE EDIT .env NOW! Add your TELEGRAM_BOT_TOKEN."
    read -p "Enter your Telegram Bot Token (or press Enter to skip and edit manually): " TOKEN
    if [ ! -z "$TOKEN" ]; then
        sed -i "s|TELEGRAM_BOT_TOKEN=|TELEGRAM_BOT_TOKEN=$TOKEN|g" .env
        echo "✅ Token saved."
    fi
else
    echo "✅ .env file exists."
fi

# 6. Start the Bot
echo "🚀 Building and Starting IrisChat..."
# Use docker compose plugin or standalone
if docker compose version &> /dev/null; then
    sudo docker compose up --build -d
else
    sudo docker-compose up --build -d
fi

echo "✨ Deployment Complete! IrisChat is running."
echo "Logs: docker logs -f irischat"
