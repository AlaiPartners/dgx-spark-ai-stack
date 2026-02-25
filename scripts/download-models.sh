#!/bin/bash
# Download vision models for llama.cpp

set -e

MODEL="${1:-granite-vision-3.3-2b}"
QUANT="${2:-Q4_K_M}"
MODELS_DIR="${MODELS_DIR:-./models}"

mkdir -p "$MODELS_DIR"

case "$MODEL" in
  granite-vision-3.3-2b)
    REPO="ibm-granite/granite-vision-3.3-2b-GGUF"
    FILE="granite-vision-3.3-2b-${QUANT}.gguf"
    DIR="${MODELS_DIR}/granite-vision-3.3-2b"
    MM_PROJ_REPO="ibm-granite/granite-vision-3.3-2b-GGUF"
    MM_PROJ_FILE="mmproj-model-f16.gguf"
    ;;
  granite-vision-3.2-2b)
    REPO="bartowski/ibm-granite_granite-vision-3.2-2b-GGUF"
    FILE="ibm-granite_granite-vision-3.2-2b-${QUANT}.gguf"
    DIR="${MODELS_DIR}/granite-vision-3.2-2b"
    MM_PROJ_REPO="bartowski/ibm-granite_granite-vision-3.2-2b-GGUF"
    MM_PROJ_FILE="mmproj-model-f16.gguf"
    ;;
  llava-1.5-7b)
    REPO="mys/ggml_llava-v1.5-7b"
    FILE="ggml-model-${QUANT,,}.gguf"
    DIR="${MODELS_DIR}/llava-1.5-7b"
    MM_PROJ_REPO="mys/ggml_llava-v1.5-7b"
    MM_PROJ_FILE="mmproj-model-f16.gguf"
    ;;
  llava-1.5-13b)
    REPO="mys/ggml_llava-v1.5-13b"
    FILE="ggml-model-${QUANT,,}.gguf"
    DIR="${MODELS_DIR}/llava-1.5-13b"
    MM_PROJ_REPO="mys/ggml_llava-v1.5-13b"
    MM_PROJ_FILE="mmproj-model-f16.gguf"
    ;;
  *)
    echo "Unknown model: $MODEL"
    echo "Available: granite-vision-3.3-2b, granite-vision-3.2-2b, llava-1.5-7b, llava-1.5-13b"
    exit 1
    ;;
esac

echo "Downloading $MODEL ($QUANT)..."
mkdir -p "$DIR"

if ! command -v huggingface-cli &> /dev/null; then
    echo "Installing huggingface-hub..."
    pip install -q huggingface-hub
fi

echo "Downloading model..."
huggingface-cli download "$REPO" "$FILE" --local-dir "$DIR" --local-dir-use-symlinks False

echo "Downloading multimodal projector..."
huggingface-cli download "$MM_PROJ_REPO" "$MM_PROJ_FILE" --local-dir "$DIR" --local-dir-use-symlinks False

echo "✓ Complete: $DIR/$FILE"
echo "✓ Projector: $DIR/$MM_PROJ_FILE"
