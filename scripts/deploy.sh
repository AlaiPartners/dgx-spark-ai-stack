#!/bin/bash
# Simple deployment script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

# Load .env file if it exists
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Check for required environment variables
if [ -z "$LLAMA_CPP_PATH" ]; then
    echo "Error: LLAMA_CPP_PATH not set"
    echo "Set it in .env or export it: export LLAMA_CPP_PATH=/path/to/llama.cpp"
    exit 1
fi

# Set models directory (use MODELS_DIR from .env or default to ./models)
MODELS_DIR="${MODELS_DIR:-./models}"

# Create necessary directories (only create logs and nginx/logs, respect existing MODELS_DIR)
mkdir -p logs nginx/logs
# Only create MODELS_DIR if it doesn't exist and it's a relative path
if [[ "$MODELS_DIR" != /* ]] && [ ! -d "$MODELS_DIR" ]; then
    mkdir -p "$MODELS_DIR"
fi

# Check if vision model exists (any quantization)
if [ ! -f "$MODELS_DIR/granite-vision-3.3-2b/granite-vision-3.3-2b-Q8_0.gguf" ] && \
   [ ! -f "$MODELS_DIR/granite-vision-3.3-2b/granite-vision-3.3-2b-Q4_K_M.gguf" ] && \
   [ -z "$(find "$MODELS_DIR/granite-vision-3.3-2b" -name "granite-vision-3.3-2b-*.gguf" 2>/dev/null | head -1)" ]; then
    echo "Vision model not found. Downloading default (Q4_K_M) to $MODELS_DIR..."
    MODELS_DIR="$MODELS_DIR" ./scripts/download-models.sh granite-vision-3.3-2b Q4_K_M
else
    echo "Vision model found in $MODELS_DIR/granite-vision-3.3-2b/"
fi

# Create Docker volumes if they don't exist
docker volume create open-webui 2>/dev/null || true
docker volume create open-webui-ollama 2>/dev/null || true

# Copy llama.cpp to build context
echo "Preparing llama.cpp for build..."
if [ ! -d "$LLAMA_CPP_PATH" ]; then
    echo "Error: llama.cpp directory not found: $LLAMA_CPP_PATH"
    exit 1
fi

# Copy llama.cpp to build context
rm -rf ./llama.cpp
# Remove trailing slash if present to ensure proper directory copy
LLAMA_CPP_PATH_CLEAN="${LLAMA_CPP_PATH%/}"
# Copy directory contents into llama.cpp directory
mkdir -p ./llama.cpp
cp -r "$LLAMA_CPP_PATH_CLEAN"/. ./llama.cpp/

# Prepare llama-swap for build
echo "Preparing llama-swap for build..."
if [ -n "$LLAMA_SWAP_PATH" ]; then
    # Use specified llama-swap path
    if [ ! -d "$LLAMA_SWAP_PATH" ]; then
        echo "Error: llama-swap directory not found: $LLAMA_SWAP_PATH"
        exit 1
    fi
    echo "Using llama-swap from: $LLAMA_SWAP_PATH"
    rm -rf ./llama-swap
    LLAMA_SWAP_PATH_CLEAN="${LLAMA_SWAP_PATH%/}"
    mkdir -p ./llama-swap
    cp -r "$LLAMA_SWAP_PATH_CLEAN"/. ./llama-swap/
else
    # Clone llama-swap if not present in build context
    if [ ! -d "./llama-swap" ]; then
        echo "Cloning llama-swap repository..."
        git clone https://github.com/mostlygeek/llama-swap.git ./llama-swap
    else
        echo "llama-swap directory exists, updating..."
        cd ./llama-swap && git pull && cd ..
    fi
fi

# Build and start services
echo "Building and starting services..."
docker compose build
docker compose up -d

echo "✓ Deployment complete"
echo ""
echo "Services:"
echo "  - Open WebUI: http://localhost:3000"
echo "  - Docling: http://localhost:5001"
echo "  - llama.cpp: http://localhost:8001"
echo "  - Nginx: http://localhost"
echo ""
echo "View logs: docker compose logs -f"
