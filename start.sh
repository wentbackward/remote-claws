#!/usr/bin/env bash
# Remote Claws - start server
set -e
cd "$(dirname "$0")"

if [ ! -f ".venv/bin/activate" ]; then
    echo "Creating venv..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e .
    playwright install chromium
else
    source .venv/bin/activate
fi

if [ ! -f ".remote-claws-auth.json" ]; then
    echo "No auth token found - running setup..."
    remote-claws-setup
fi

echo ""
echo "Starting Remote Claws..."
remote-claws
