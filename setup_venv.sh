#!/bin/bash
# Setup virtualenv for add_model.py

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "Creating virtualenv..."
    python3 -m venv venv
fi

echo "Activating virtualenv and installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "✓ Virtualenv ready!"
echo ""
echo "To use add_model.py:"
echo "  source venv/bin/activate"
echo "  python add_model.py --help"
