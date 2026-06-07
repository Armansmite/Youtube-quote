import os, sys, json, time, requests, random, re, glob, warnings, traceback
from datetime import datetime, timedelta
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

warnings.filterwarnings("ignore")

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "").rstrip("/") + "/"
CODESPACE_NAME = os.environ.get("CODESPACE_NAME")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "Armansmite/Youtube-quote")

LOG_FILE = "/tmp/worker.log"

def send_log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.utcnow().isoformat()}] {msg}\n")
    try:
        requests.post(DASHBOARD_URL + "api/log", json={"message": msg}, timeout=5)
    except:
        pass

# Send a log immediately to prove the worker is running
send_log("🚀 Worker started inside Codespace")

# ... (all the other functions: download_token, get_settings, helpers, etc.)
# They must be exactly the same as in your previous working worker.

def main():
    try:
        if not download_token():
            send_log("❌ No token on dashboard")
            return
        # ... rest of processing
        send_log("🏁 Finished")
    except Exception as e:
        send_log(f"❌ Error: {traceback.format_exc()}")

if __name__ == "__main__":
    main()
