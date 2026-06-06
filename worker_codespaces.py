import os, sys, json, time, requests, random, re, glob, warnings, traceback, subprocess
from datetime import datetime, timedelta
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

warnings.filterwarnings("ignore")

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://pwa-gqoh.onrender.com/")
if not DASHBOARD_URL.endswith("/"):
    DASHBOARD_URL += "/"

CODESPACE_NAME = os.environ.get("CODESPACE_NAME")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

# ---------- Helper functions (same as before) ----------
def send_log(msg):
    print(msg)
    try:
        requests.post(DASHBOARD_URL + "api/log", json={"message": msg}, timeout=5)
    except:
        pass

def download_token():
    r = requests.get(DASHBOARD_URL + "api/token")
    if r.status_code == 200:
        with open("token.json", "w") as f:
            f.write(r.text)
        return True
    send_log("❌ No token on dashboard.")
    return False

def get_settings():
    r = requests.get(DASHBOARD_URL + "api/settings")
    return r.json()

# ... (include all V1 helper functions: load_processed, mark_processed, find_images, etc.)
# They are identical to the Colab / Actions worker.

def delete_codespace():
    if not CODESPACE_NAME or not GITHUB_TOKEN:
        return
    repo = os.environ.get("GITHUB_REPOSITORY", "Armansmite/Youtube-quote")
    url = f"https://api.github.com/repos/{repo}/codespaces/{CODESPACE_NAME}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    try:
        resp = requests.delete(url, headers=headers)
        if resp.status_code == 202:
            print("✅ Codespace deletion initiated.")
        else:
            print(f"⚠️ Could not delete codespace: {resp.text}")
    except Exception as e:
        print(f"❌ Deletion error: {e}")

def main():
    send_log("🚀 Codespace worker started.")

    # Download token
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
    max_videos = settings.get("max_videos", 0) or None
    slots = settings.get("slots", ["05:30", "11:30", "17:30", "23:30"])
    base_tags = settings.get("base_tags", "shorts, quotes, motivation, wisdom").split(",")
    description_extra = settings.get("description_extra", "")
    category_id = settings.get("category_id", "22")
    total_duration = settings.get("total_duration", 7)
    fade_duration = settings.get("fade_duration", 2)
    max_quote_len = settings.get("max_quote_len", 50)

    slot_tuples = [(int(h), int(m)) for h, m in (s.split(":") for s in slots)]

    # Dynamically import config
    sys.path.insert(0, os.getcwd())
    config_module = __import__(f"configs.{active_config}", fromlist=["create_video"])
    create_video_fn = config_module.create_video

    # Process quotes (exact same loop as before, calling create_video_fn)
    # ...

    send_log("🏁 Finished. Codespace will now shut down.")
    delete_codespace()

if __name__ == "__main__":
    main()
