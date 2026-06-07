#!/bin/bash
set -e

echo "Setting up environment..."

# Always install required packages
pip install moviepy pillow google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client requests > /dev/null 2>&1

if [ -n "$DASHBOARD_URL" ]; then
    echo "🚀 Bot trigger detected. Starting worker..."
    python worker_codespaces.py
else
    echo "✨ Normal dev environment. No worker auto‑run."
fi
