#!/bin/bash

# IrisChat - Custom Model Builder
# Creates the 'iris' model from the Modelfile

echo "🧠 Building Iris's Brain..."

# 1. Check for Ollama
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama is not installed!"
    exit 1
fi

# 2. Pull Base Model (Gemma 2 2B is efficient and smart)
echo "📥 Pulling base model (gemma2:2b)..."
ollama pull gemma2:2b

# 3. Create 'iris' model
echo "🔨 Creating 'iris' model from Modelfile..."
ollama create iris -f Modelfile

# 4. Verify
if ollama list | grep -q "iris"; then
    echo "✅ 'iris' model created successfully!"
    echo "👉 Please update your .env file: OLLAMA_MODEL=iris"
else
    echo "❌ Failed to create model."
fi
