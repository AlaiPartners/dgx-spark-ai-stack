#!/bin/bash
# Install llama.cpp from specified path

set -e

LLAMA_CPP_PATH="${1:-}"
BUILD_DIR="${BUILD_DIR:-./build}"

if [ -z "$LLAMA_CPP_PATH" ]; then
    echo "Usage: $0 <path-to-llama.cpp>"
    echo "Example: $0 /path/to/llama.cpp"
    exit 1
fi

if [ ! -d "$LLAMA_CPP_PATH" ]; then
    echo "Error: llama.cpp directory not found: $LLAMA_CPP_PATH"
    exit 1
fi

echo "Installing llama.cpp from: $LLAMA_CPP_PATH"

# Build llama.cpp
cd "$LLAMA_CPP_PATH"
mkdir -p build
cd build

echo "Configuring build..."
cmake .. -DCMAKE_BUILD_TYPE=Release -DLLAMA_CUBLAS=ON

echo "Building..."
cmake --build . --config Release -j$(nproc)

echo "✓ Build complete"
echo "Server binary: $LLAMA_CPP_PATH/build/bin/llama-server"
