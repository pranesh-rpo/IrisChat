#!/bin/bash

# IrisChat - Custom Model Builder
# Creates the 'iris' model from the Modelfile

echo "🧠 Building Iris's Brain..."

# 1. Check for Ollama
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama is not installed!"
    exit 1
fi

# 2. Pull Base Model (Llama 3.2 3B - Fast & Smart)
echo "📥 Pulling base model (llama3.2:3b)..."
ollama pull llama3.2:3b

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
