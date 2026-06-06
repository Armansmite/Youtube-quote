#!/bin/bash
set -e

if [ "$TRIGGER_WORKER" = "true" ]; then
    echo "🚀 Starting YouTube Shorts Bot (Codespaces worker)"
    pip install moviepy pillow google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client requests > /dev/null 2>&1
    python worker_codespaces.py
    exit 0
fi

echo "✨ Dev environment ready. No worker auto‑run."
