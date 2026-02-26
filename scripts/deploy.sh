#!/bin/bash
# Deployment script for Spark Deploy
# Sets up two llama.cpp instances (vision and text) with SSL-enabled Nginx

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

# Set models directory (use MODELS_DIR from .env or default to ./models)
MODELS_DIR="${MODELS_DIR:-./models}"
# Expand $HOME if present
MODELS_DIR=$(echo "$MODELS_DIR" | sed "s|\$HOME|$HOME|g")

# Create necessary directories
mkdir -p logs nginx/logs nginx/ssl
# Only create MODELS_DIR if it doesn't exist and it's a relative path
if [[ "$MODELS_DIR" != /* ]] && [ ! -d "$MODELS_DIR" ]; then
    mkdir -p "$MODELS_DIR"
fi

echo "=== Checking Models ==="

# Check if vision model exists (any quantization)
VISION_MODEL_FOUND=false
if [ -d "$MODELS_DIR/granite-vision-3.3-2b" ]; then
    if find "$MODELS_DIR/granite-vision-3.3-2b" -name "granite-vision-3.3-2b-*.gguf" -type f 2>/dev/null | grep -q .; then
        VISION_MODEL_FOUND=true
        echo "✓ Vision model found in $MODELS_DIR/granite-vision-3.3-2b/"
    fi
fi

if [ "$VISION_MODEL_FOUND" = false ]; then
    echo "Vision model not found. Downloading default (Q4_K_M) to $MODELS_DIR..."
    MODELS_DIR="$MODELS_DIR" ./scripts/download-models.sh granite-vision-3.3-2b Q4_K_M
fi

# Check if text model exists (llama-3.1-8b-instruct)
TEXT_MODEL_FOUND=false
if [ -d "$MODELS_DIR/llama-3.1-8b-instruct" ]; then
    if find "$MODELS_DIR/llama-3.1-8b-instruct" -name "*.gguf" -type f 2>/dev/null | grep -q .; then
        TEXT_MODEL_FOUND=true
        echo "✓ Text model found in $MODELS_DIR/llama-3.1-8b-instruct/"
    fi
fi

if [ "$TEXT_MODEL_FOUND" = false ]; then
    echo "Text model (llama-3.1-8b-instruct) not found."
    echo "You can download it using: python3 add_model.py"
    echo "Or manually download to: $MODELS_DIR/llama-3.1-8b-instruct/"
    read -p "Continue without text model? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "=== Setting up SSL Certificates ==="

# Generate self-signed certificate if it doesn't exist
if [ ! -f "nginx/ssl/cert.pem" ] || [ ! -f "nginx/ssl/key.pem" ]; then
    echo "Generating self-signed SSL certificate..."
    
    if command -v openssl &> /dev/null; then
        openssl genrsa -out nginx/ssl/key.pem 2048
        openssl req -new -x509 -key nginx/ssl/key.pem -out nginx/ssl/cert.pem -days 365 \
            -subj "/C=US/ST=State/L=City/O=SparkDeploy/CN=localhost"
        chmod 600 nginx/ssl/key.pem
        chmod 644 nginx/ssl/cert.pem
        echo "✓ Self-signed certificate generated"
    else
        echo "⚠ Warning: openssl not found. SSL certificates not generated."
        echo "  Please generate certificates manually (see nginx/ssl/README.md)"
        echo "  Or install openssl and run this script again."
    fi
else
    echo "✓ SSL certificates found in nginx/ssl/"
fi

echo ""
echo "=== Creating Docker Volumes ==="

# Create Docker volumes if they don't exist
docker volume create open-webui 2>/dev/null || true
docker volume create open-webui-ollama 2>/dev/null || true
docker volume create docling-models 2>/dev/null || true
docker volume create docling-easyocr 2>/dev/null || true

echo "✓ Docker volumes ready"

echo ""
echo "=== Starting Services ==="

# Pull latest images and start services
echo "Pulling latest images..."
docker compose pull

echo "Starting services..."
docker compose up -d

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Services:"
echo "  - Open WebUI: https://localhost (or http://localhost:3000 direct)"
echo "  - Docling UI: http://localhost:5001"
echo "  - llamacpp-vision: Internal (port 8001) - Granite Vision 3.3-2B"
echo "  - llamacpp-llama: Internal (port 8001) - Llama 3.1 8B Instruct"
echo "  - Nginx: https://localhost (HTTP redirects to HTTPS)"
echo ""
echo "Note: Self-signed certificates will show a browser warning."
echo "      Click 'Advanced' → 'Proceed to localhost' to continue."
echo ""
echo "View logs: docker compose logs -f [service-name]"
echo "Check status: docker compose ps"
