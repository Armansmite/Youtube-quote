#!/bin/bash
set -x   # print every command for debugging
exec > /tmp/setup.log 2>&1   # redirect all output to a file

echo "TRIGGER_WORKER=$TRIGGER_WORKER"

if [ "$TRIGGER_WORKER" = "true" ]; then
    echo "🚀 Installing dependencies..."
    pip install moviepy pillow google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client requests
    echo "🚀 Running worker..."
    python worker_codespaces.py
    echo "🚀 Worker finished."
else
    echo "✨ Normal dev environment. No worker auto‑run."
fi
