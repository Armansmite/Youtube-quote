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

DASHBOARD_URL = os.environ["DASHBOARD_URL"].rstrip("/") + "/"

def send_log(msg):
    print(msg)
    try:
        requests.post(DASHBOARD_URL + "api/log", json={"message": msg}, timeout=5)
    except:
        pass

def download_token():
    send_log("📥 Downloading token...")
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
# They are identical to the previous workers – just copy them here.

def main():
    send_log("🚀 GitHub Actions worker started.")
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
    # ... rest of processing, exactly like the previous workers
    send_log("🏁 Finished.")

if __name__ == "__main__":
    main()
