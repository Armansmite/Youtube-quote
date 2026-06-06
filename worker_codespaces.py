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

# Log to both dashboard and local file
LOG_FILE = "/tmp/worker.log"

def send_log(msg):
    print(msg, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{datetime.utcnow().isoformat()}] {msg}\n")
    except:
        pass
    try:
        requests.post(os.environ["DASHBOARD_URL"].rstrip("/") + "/api/log",
                      json={"message": msg}, timeout=5)
    except:
        pass

# Start logging immediately
send_log("🚀 Worker started. Log file at /tmp/worker.log")

# ... (include all other helper functions exactly as before, no changes)

def main():
    try:
        # ... (your existing main logic, unchanged)
        # Ensure every important step calls send_log(...)
    except Exception as e:
        send_log(f"❌ Fatal error: {traceback.format_exc()}")

if __name__ == "__main__":
    main()
