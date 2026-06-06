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

# ---------- Log ----------
def send_log(msg):
    print(msg)
    try:
        requests.post(DASHBOARD_URL + "api/log", json={"message": msg}, timeout=5)
    except Exception as e:
        print(f"Failed to send log: {e}")

# Send an immediate log to confirm connectivity
send_log("🚀 Worker started, connecting to dashboard...")

# ---------- Helper functions (same as before) ----------
def download_token():
    send_log("📥 Downloading token from dashboard...")
    r = requests.get(DASHBOARD_URL + "api/token")
    if r.status_code == 200:
        with open("token.json", "w") as f:
            f.write(r.text)
        send_log("✅ token.json saved.")
        return True
    send_log("❌ No token found on dashboard.")
    return False

def get_settings():
    r = requests.get(DASHBOARD_URL + "api/settings")
    if r.status_code != 200:
        raise Exception("Could not fetch settings")
    return r.json()

# ... (keep all other V1 helper functions exactly as before: load_processed, mark_processed, etc.)
# (Copy the entire set of helpers from the previous worker_codespaces.py, no changes needed.)

# ---------- Dynamic config import ----------
def get_config_module(active_config):
    sys.path.insert(0, os.getcwd())
    return __import__(f"configs.{active_config}", fromlist=["create_video"])

# ---------- Delete Codespace (only on clean finish) ----------
def delete_codespace():
    if not CODESPACE_NAME or not GITHUB_TOKEN:
        return
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/codespaces/{CODESPACE_NAME}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    requests.delete(url, headers=headers)

# ---------- Main (with error handling) ----------
def main():
    try:
        send_log("🔍 Checking environment...")
        # Check if DASHBOARD_URL is set
        if not DASHBOARD_URL or DASHBOARD_URL == "/":
            send_log("❌ DASHBOARD_URL is empty or invalid.")
            return

        if not download_token():
            return

        with open("token.json", "r") as f:
            creds = Credentials.from_authorized_user_info(json.load(f))

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds.valid:
            send_log("❌ Invalid token.")
            return

        settings = get_settings()
        active_config = settings.get("active_config", "classic")
        # ... (rest of processing, same as before)
        send_log("🏁 Finished. Deleting Codespace.")
        delete_codespace()
    except Exception as e:
        send_log(f"❌ Unexpected error: {traceback.format_exc()}")
        send_log("🔒 Codespace kept alive for debugging. Check the terminal output.")
        # Do NOT delete the codespace – leave it running

if __name__ == "__main__":
    main()
