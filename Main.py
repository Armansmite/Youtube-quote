import os
import json
import pickle
import base64
import io
import logging
import traceback
import threading
import time
import random
import re
import glob
import warnings
from datetime import datetime, timedelta

os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["ALSA_CARD"] = "dummy"
warnings.filterwarnings("ignore")

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip

from flask import Flask, request, jsonify, send_file, Response

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from pyngrok import ngrok

# ----------------------------------------------------------------------
# YOUR COLAB NOTEBOOK URL (set correctly)
# ----------------------------------------------------------------------
COLAB_URL = "https://colab.research.google.com/drive/1U505-nHazAkHB2VVRtqTxDjzrDG_hWTZ?authuser=1#scrollTo=56uU71i-4sup"

# ----------------------------------------------------------------------
# Default settings
# ----------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "total_duration": 7,
    "fade_duration": 2,
    "max_quote_len": 50,
    "slots": ["05:30", "11:30", "17:30", "23:30"],
    "base_tags": "shorts, quotes, motivation, wisdom",
    "description_extra": "💡 Quote of the day | Motivational quotes | Motivational speech | Motivational video | Understanding politics",
    "category_id": "22"
}

QUOTE_FILE = "quote.txt"
PROCESSED_FILE = "processed.txt"
IMAGE_DIR = "image"
MUSIC_DIR = "music"
OUTPUT_PREFIX = "output"
OUTPUT_EXT = ".mp4"
VIDEO_SIZE = (1080, 1920)
FPS = 30
FONT_FILE = "Garamond.ttf"

# ----------------------------------------------------------------------
# Helper functions (unchanged)
# ----------------------------------------------------------------------
def load_processed():
    if not os.path.exists(PROCESSED_FILE):
        return set()
    with open(PROCESSED_FILE, "r") as f:
        return {int(line) for line in f.read().splitlines() if line.strip().isdigit()}

def mark_processed(line_num):
    with open(PROCESSED_FILE, "a") as f:
        f.write(f"{line_num}\n")

def get_next_output_index():
    existing = glob.glob(f"{OUTPUT_PREFIX}_*.mp4")
    max_idx = 0
    for fname in existing:
        m = re.match(rf"{OUTPUT_PREFIX}_(\d+){OUTPUT_EXT}", os.path.basename(fname))
        if m:
            idx = int(m.group(1))
            if idx > max_idx:
                max_idx = idx
    return max_idx + 1

def find_images(subject):
    folder = IMAGE_DIR
    if not os.path.isdir(folder):
        return []
    patterns = [
        os.path.join(folder, f"{subject}_*.jpg"),
        os.path.join(folder, f"{subject}_*.JPG"),
        os.path.join(folder, f"{subject}_*.jpeg"),
        os.path.join(folder, f"{subject}_*.JPEG"),
        os.path.join(folder, f"{subject}_*.png"),
        os.path.join(folder, f"{subject}_*.PNG"),
    ]
    images = []
    for pat in patterns:
        images.extend(glob.glob(pat))
    return images

def find_music(subject):
    folder = MUSIC_DIR
    if not os.path.isdir(folder):
        return []
    patterns = [
        os.path.join(folder, f"{subject}_*.mp3"),
        os.path.join(folder, f"{subject}_*.MP3"),
        os.path.join(folder, f"{subject}_*.m4a"),
        os.path.join(folder, f"{subject}_*.M4A"),
    ]
    music = []
    for pat in patterns:
        music.extend(glob.glob(pat))
    return music

def load_font(size):
    if os.path.isfile(FONT_FILE):
        try:
            return ImageFont.truetype(FONT_FILE, size)
        except Exception:
            pass
    system_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/georgia.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Georgia.ttf",
    ]
    for path in system_fonts:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

def split_quote_two_lines(quote):
    words = quote.split()
    if len(words) <= 1:
        return [quote]
    best_split = None
    for i in range(len(words) - 1, 0, -1):
        first = " ".join(words[:i])
        second = " ".join(words[i:])
        if len(first) >= len(second):
            if best_split is None or (len(first) > len(second) and len(best_split[0]) == len(best_split[1])):
                best_split = (first, second)
            if len(first) > len(second):
                break
    if best_split is None:
        return [quote]
    return list(best_split)

def best_font_size(lines, max_width):
    font_path = FONT_FILE if os.path.isfile(FONT_FILE) else None
    low, high = 10, 200
    best = low
    while low <= high:
        mid = (low + high) // 2
        try:
            font = ImageFont.truetype(font_path, mid) if font_path else load_font(mid)
        except Exception:
            font = load_font(mid)
        draw = ImageDraw.Draw(Image.new("RGB", (1,1)))
        fits = True
        for line in lines:
            bbox = draw.textbbox((0,0), line, font=font)
            if (bbox[2] - bbox[0]) > max_width:
                fits = False
                break
        if fits:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best

def draw_text_with_stroke(draw, text, xy, font, text_color, stroke_color, stroke_width):
    x, y = xy
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_color)
    draw.text((x, y), text, font=font, fill=text_color)

def build_text_frame(image, quote, writer):
    img = image.copy()
    draw = ImageDraw.Draw(img)
    max_width = VIDEO_SIZE[0] - 2 * 100
    lines = split_quote_two_lines(quote)
    quote_size = best_font_size(lines, max_width)
    quote_font = load_font(quote_size)
    writer_size = max(int(quote_size * 0.6), 12)
    writer_font = load_font(writer_size)
    line_height = quote_font.getbbox("Ag")[3] - quote_font.getbbox("Ag")[1]
    total_height = line_height * len(lines) + (len(lines)-1)*10
    start_y = 700 - total_height // 2
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0,0), line, font=quote_font)
        line_w = bbox[2] - bbox[0]
        line_x = (VIDEO_SIZE[0] - line_w) // 2
        line_y = start_y + i * (line_height + 10)
        draw_text_with_stroke(draw, line, (line_x, line_y),
                              quote_font, (255,255,255), (0,0,0), 4)
    writer_text = f"- {writer}"
    writer_bbox = draw.textbbox((0,0), writer_text, font=writer_font)
    writer_w = writer_bbox[2] - writer_bbox[0]
    writer_x = (VIDEO_SIZE[0] - writer_w) // 2
    writer_y = start_y + total_height + 30
    draw_text_with_stroke(draw, writer_text, (writer_x, writer_y),
                          writer_font, (255,255,255), (0,0,0), 4)
    return img

def create_video(quote, writer, subject, image_path, music_path, output_video, output_thumb,
                 total_duration, fade_duration):
    pil_img = Image.open(image_path).convert("RGB")
    target_w, target_h = VIDEO_SIZE
    img_w, img_h = pil_img.size
    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    pil_img = pil_img.crop((left, top, left + target_w, top + target_h))

    final_frame = build_text_frame(pil_img, quote, writer)
    final_frame.save(output_thumb, "JPEG", quality=90)

    img_array = np.array(final_frame)
    img_clip = ImageClip(img_array).set_duration(total_duration).fadein(fade_duration)

    audio_clip = AudioFileClip(music_path)
    if audio_clip.duration > total_duration:
        audio_clip = audio_clip.subclip(0, total_duration)

    final_video = img_clip.set_audio(audio_clip)
    final_video.write_videofile(
        output_video,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile="temp-audio.m4a",
        remove_temp=True,
        verbose=False,
        logger=None,
    )
    final_video.close()
    audio_clip.close()
    img_clip.close()

# ----------------------------------------------------------------------
# Flask app
# ----------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

global_state = {
    "settings": DEFAULT_SETTINGS.copy(),
    "credentials": None,
    "flow": None,
    "log": []
}

def add_log(msg):
    global_state["log"].append(msg)
    if len(global_state["log"]) > 200:
        global_state["log"] = global_state["log"][-200:]

# --- Static PWA files (created automatically) ---
def create_pwa_files():
    with open("app.html", "w") as f:
        f.write(APP_HTML)
    with open("manifest.json", "w") as f:
        f.write(MANIFEST_JSON)
    with open("sw.js", "w") as f:
        f.write(SW_JS)

# --- Routes for PWA ---
@app.route("/app.html")
def serve_app():
    return send_file("app.html")

@app.route("/manifest.json")
def serve_manifest():
    return send_file("manifest.json")

@app.route("/sw.js")
def serve_sw():
    return send_file("sw.js")

# --- Original API routes (unchanged) ---
@app.route("/")
def index():
    return send_file("index.html")

@app.route("/frontend")
def frontend():
    return HTML_CONTENT

@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        data = request.get_json()
        global_state["settings"] = data
        return jsonify({"status": "ok"})
    return jsonify(global_state["settings"])

@app.route("/api/auth/upload_client_secret", methods=["POST"])
def upload_client_secret():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    filepath = "/tmp/client_secret.json"
    file.save(filepath)
    try:
        flow = InstalledAppFlow.from_client_secrets_file(filepath, [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly"
        ])
        flow.redirect_uri = "http://localhost:8080"
        auth_url, _ = flow.authorization_url(prompt="consent")
        global_state["flow"] = flow
        return jsonify({"auth_url": auth_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/auth/authenticate", methods=["POST"])
def authenticate():
    raw = request.get_json().get("code", "")
    if "code=" in raw:
        raw = raw.split("code=")[1].split("&")[0]
    if not global_state.get("flow"):
        return jsonify({"error": "No client_secret uploaded"}), 400
    try:
        global_state["flow"].fetch_token(code=raw)
        creds = global_state["flow"].credentials
        service = build("youtube", "v3", credentials=creds)
        service.channels().list(part="id", mine=True).execute()
        global_state["credentials"] = creds
        settings = global_state["settings"]
        creds_bytes = pickle.dumps(creds)
        config = {
            "settings": settings,
            "credentials_b64": base64.b64encode(creds_bytes).decode("utf-8")
        }
        return jsonify({"status": "authenticated", "config": config})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/auth/status", methods=["GET"])
def auth_status():
    creds = global_state.get("credentials")
    if not creds:
        return jsonify({"status": "none"})
    if creds.valid:
        return jsonify({"status": "valid"})
    elif creds.expired and creds.refresh_token:
        return jsonify({"status": "expired_refreshable"})
    else:
        return jsonify({"status": "invalid"})

@app.route("/api/export", methods=["GET"])
def export_config():
    settings = global_state["settings"]
    creds = global_state.get("credentials")
    creds_bytes = pickle.dumps(creds) if creds else b""
    payload = {
        "settings": settings,
        "credentials_b64": base64.b64encode(creds_bytes).decode("utf-8")
    }
    return jsonify(payload)

@app.route("/api/import", methods=["POST"])
def import_config():
    data = request.get_json()
    settings = data.get("settings", DEFAULT_SETTINGS.copy())
    global_state["settings"] = settings
    creds_b64 = data.get("credentials_b64")
    if creds_b64:
        creds_bytes = base64.b64decode(creds_b64)
        global_state["credentials"] = pickle.loads(creds_bytes)
    return jsonify({"status": "imported", "settings": settings})

@app.route("/api/run", methods=["POST"])
def run_bot():
    data = request.get_json() or {}
    max_videos = data.get("max_videos", None)
    global_state["log"] = []
    add_log("Starting bot...")
    threading.Thread(target=bot_process, args=(max_videos,)).start()
    return jsonify({"status": "started"})

@app.route("/api/log", methods=["GET"])
def get_log():
    return jsonify(global_state["log"])

# ----------------------------------------------------------------------
# Bot process (with token refresh)
# ----------------------------------------------------------------------
def bot_process(max_videos=None):
    try:
        settings = global_state["settings"]
        creds = global_state.get("credentials")

        if not creds:
            add_log("ERROR: No credentials stored. Please authenticate in the Auth tab first.")
            return

        if creds.expired and creds.refresh_token:
            add_log("Token expired – attempting to refresh...")
            try:
                creds.refresh(Request())
                global_state["credentials"] = creds
                add_log("Token refreshed successfully.")
            except Exception as e:
                add_log(f"ERROR: Could not refresh token: {e}")
                add_log("Please re‑authenticate in the Auth tab.")
                return

        if not creds.valid:
            add_log("ERROR: Invalid credentials. Please re‑authenticate.")
            return

        slot_list = []
        for slot_str in settings.get("slots", ["05:30"]):
            h, m = map(int, slot_str.split(":"))
            slot_list.append((h, m))

        base_tags = [t.strip() for t in settings.get("base_tags", "shorts,quotes").split(",") if t.strip()]
        total_duration = settings.get("total_duration", 7)
        fade_duration = settings.get("fade_duration", 2)
        max_quote_len = settings.get("max_quote_len", 50)
        description_extra = settings.get("description_extra", "")
        category_id = settings.get("category_id", "22")

        if not os.path.exists(QUOTE_FILE):
            add_log(f"ERROR: {QUOTE_FILE} not found.")
            return

        processed = load_processed()
        add_log(f"Already processed: {sorted(processed)}")

        with open(QUOTE_FILE, "r") as f:
            lines = f.readlines()

        to_process = []
        for idx, line in enumerate(lines, start=1):
            if idx in processed:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if all(k in data for k in ("qoute", "writer", "subject")):
                    to_process.append((idx, line, data))
            except:
                add_log(f"Line {idx}: invalid JSON, skipping.")

        if not to_process:
            add_log("No unprocessed lines. Exiting.")
            return

        service = build("youtube", "v3", credentials=creds)

        def get_scheduled_times():
            channel_response = service.channels().list(part="contentDetails", mine=True).execute()
            uploads_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            video_ids = []
            next_page_token = None
            while True:
                playlist_response = service.playlistItems().list(
                    part="snippet", playlistId=uploads_id, maxResults=50, pageToken=next_page_token
                ).execute()
                video_ids.extend([item["snippet"]["resourceId"]["videoId"] for item in playlist_response["items"]])
                next_page_token = playlist_response.get("nextPageToken")
                if not next_page_token:
                    break
            if not video_ids:
                return set()
            times = set()
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i:i+50]
                vid_response = service.videos().list(part="status", id=",".join(batch)).execute()
                for item in vid_response["items"]:
                    status = item["status"]
                    if status.get("privacyStatus") == "private" and "publishAt" in status:
                        dt = datetime.strptime(status["publishAt"].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                        if dt > datetime.utcnow():
                            times.add(dt)
            return times

        occupied = get_scheduled_times()
        add_log(f"Found {len(occupied)} scheduled slots.")

        def next_free_slot(occ, slots):
            now = datetime.utcnow()
            day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            while True:
                for h, m in slots:
                    candidate = day.replace(hour=h, minute=m, second=0, microsecond=0)
                    if candidate > now and candidate not in occ:
                        return candidate
                day += timedelta(days=1)

        next_slot = next_free_slot(occupied, slot_list)
        add_log(f"First free slot: {next_slot.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        videos_processed = 0
        for line_idx, line, data in to_process:
            if max_videos is not None and videos_processed >= max_videos:
                add_log(f"Reached max videos limit ({max_videos}). Stopping.")
                break

            quote = data["qoute"]
            writer = data["writer"]
            subject = data["subject"]

            if len(quote) > max_quote_len:
                add_log(f"Line {line_idx}: quote too long, marking processed.")
                mark_processed(line_idx)
                continue

            imgs = find_images(subject)
            if not imgs:
                add_log(f"Line {line_idx}: no images for subject '{subject}'. Skipping.")
                continue
            musics = find_music(subject)
            if not musics:
                add_log(f"Line {line_idx}: no music for subject '{subject}'. Skipping.")
                continue

            image_path = random.choice(imgs)
            music_path = random.choice(musics)

            next_idx = get_next_output_index()
            video_name = f"{OUTPUT_PREFIX}_{next_idx:03d}{OUTPUT_EXT}"
            thumb_name = f"{OUTPUT_PREFIX}_{next_idx:03d}_thumb.jpg"
            video_path = os.path.join(os.getcwd(), video_name)
            thumb_path = os.path.join(os.getcwd(), thumb_name)

            try:
                create_video(quote, writer, subject, image_path, music_path,
                             video_path, thumb_path, total_duration, fade_duration)
                add_log(f"Created {video_name}")
            except Exception as e:
                add_log(f"Line {line_idx}: creation failed - {e}. Skipping.")
                continue

            try:
                title = f"{quote} – {writer}"[:100]
                description = (
                    f"{quote} – {writer}\n\n"
                    f"✨ Topic: {subject}\n"
                    f"{description_extra}\n"
                    f"🔖 #quotes #{subject} #motivation #wisdom\n\n"
                    f"🎵 Music from YouTube Audio Library\n"
                    f"📌 Subscribe for daily quotes"
                )
                tags = list(set(base_tags + [subject, writer]))

                body = {
                    "snippet": {
                        "title": title,
                        "description": description,
                        "tags": tags,
                        "categoryId": category_id
                    },
                    "status": {
                        "privacyStatus": "private",
                        "selfDeclaredMadeForKids": False,
                    },
                }
                publish_str = next_slot.strftime("%Y-%m-%dT%H:%M:%SZ")
                body["status"]["publishAt"] = publish_str

                media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
                request_obj = service.videos().insert(part="snippet,status", body=body, media_body=media)
                response = None
                while response is None:
                    status, response = request_obj.next_chunk()
                add_log(f"Uploaded & scheduled at {publish_str}")

                mark_processed(line_idx)
                occupied.add(next_slot)
                next_slot = next_free_slot(occupied, slot_list)
                videos_processed += 1

            except Exception as e:
                add_log(f"Line {line_idx}: upload failed - {e}. Stopping.")
                break

        add_log("Finished.")
    except Exception as e:
        add_log(f"Unexpected error: {traceback.format_exc()}")

# ----------------------------------------------------------------------
# PWA static files (as Python strings)
# ----------------------------------------------------------------------
APP_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Shorts Bot</title>
  <link rel="manifest" href="/manifest.json">
  <meta name="theme-color" content="#0a0a1a">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Inter', sans-serif; background: #0a0a1a; color: white; height: 100vh; display: flex; flex-direction: column; }
    .tabs { display: flex; background: #1a1a2e; }
    .tab { flex: 1; padding: 15px; text-align: center; font-weight: 600; cursor: pointer; border-bottom: 3px solid transparent; transition: 0.3s; }
    .tab.active { border-bottom-color: #7c5dfa; background: rgba(124,93,250,0.1); }
    .panel { flex: 1; display: none; padding: 20px; overflow: hidden; }
    .panel.active { display: flex; flex-direction: column; }
    iframe { flex: 1; border: none; width: 100%; border-radius: 12px; margin-top: 10px; }
    button { background: #7c5dfa; color: white; border: none; padding: 14px; border-radius: 10px; font-weight: 600; cursor: pointer; transition: 0.3s; }
    button:hover { background: #6a4cf0; }
    input { background: #2a2a3c; border: 1px solid #3a3a4c; border-radius: 8px; color: white; padding: 12px; width: 100%; }
    .splash { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: #0a0a1a; display: flex; align-items: center; justify-content: center; z-index: 100; transition: opacity 0.5s; }
    .splash.hidden { opacity: 0; pointer-events: none; }
    .logo { font-size: 3rem; font-weight: 700; background: linear-gradient(135deg, #7c5dfa, #00d4aa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  </style>
</head>
<body>
  <div id="splash" class="splash">
    <div class="logo">🎬 Shorts Bot</div>
  </div>

  <div class="tabs">
    <div class="tab active" onclick="switchTab('colab')">🧪 Colab</div>
    <div class="tab" onclick="switchTab('dashboard')">📊 Dashboard</div>
  </div>

  <div id="panel-colab" class="panel active">
    <p style="margin-bottom:10px;">Open your Colab notebook to start the bot:</p>
    <button onclick="openColab()">Open Colab Notebook</button>
    <p style="font-size:0.8rem; color:#aaa; margin-top:10px;">After running the notebook, switch to the Dashboard tab to control the bot.</p>
  </div>

  <div id="panel-dashboard" class="panel">
    <div style="display:flex; gap:10px; align-items:center;">
      <input type="text" id="ngrokUrl" placeholder="https://xxxx.ngrok-free.app" style="flex:1;">
      <button onclick="loadDashboard()" style="white-space:nowrap;">Load</button>
    </div>
    <iframe id="dashboardFrame" style="display:none; flex:1;"></iframe>
  </div>

  <script>
    const COLAB_URL = "''' + COLAB_URL + '''";

    window.addEventListener('load', () => {
      setTimeout(() => {
        document.getElementById('splash').classList.add('hidden');
      }, 800);
    });

    const savedUrl = localStorage.getItem('ngrokUrl');
    if (savedUrl) {
      document.getElementById('ngrokUrl').value = savedUrl;
    }

    function switchTab(tab) {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      document.getElementById('panel-' + tab).classList.add('active');
      event.target.classList.add('active');
    }

    function openColab() {
      window.open(COLAB_URL, '_blank');
    }

    function loadDashboard() {
      let url = document.getElementById('ngrokUrl').value.trim();
      if (!url) return alert('Paste your ngrok URL first.');
      if (!url.startsWith('http')) url = 'https://' + url;
      localStorage.setItem('ngrokUrl', url);
      const frame = document.getElementById('dashboardFrame');
      frame.src = url;
      frame.style.display = 'block';
    }
  </script>
</body>
</html>'''

MANIFEST_JSON = '''{
  "name": "YouTube Shorts Bot",
  "short_name": "Shorts Bot",
  "start_url": "/app.html",
  "display": "standalone",
  "background_color": "#0a0a1a",
  "theme_color": "#0a0a1a",
  "icons": [{
    "src": "https://via.placeholder.com/192x192/7c5dfa/ffffff?text=SB",
    "sizes": "192x192",
    "type": "image/png"
  }]
}'''

SW_JS = '''
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open('shorts-v1').then(cache => {
      return cache.addAll(['/app.html', '/manifest.json']);
    })
  );
});
self.addEventListener('fetch', e => {
  e.respondWith(
    caches.match(e.request).then(response => response || fetch(e.request))
  );
});
'''

# ----------------------------------------------------------------------
# Start server with ngrok
# ----------------------------------------------------------------------
def start_ngrok():
    ngrok.kill()
    ngrok.set_auth_token("2t2YZZLCmN25PUCkkeimIhlluPI_59QsciAqHfriV4LvvKejQ")
    public_url = ngrok.connect(5000)
    print(f" * ngrok tunnel: {public_url}")
    return public_url

if __name__ == "__main__":
    create_pwa_files()
    with open("index.html", "w") as f:
        f.write("<script>window.location.href='/frontend';</script>")
    threading.Thread(target=start_ngrok, daemon=True).start()
    time.sleep(2)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
