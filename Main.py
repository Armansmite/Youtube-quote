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

from flask import Flask, request, jsonify, send_file

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from pyngrok import ngrok

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "total_duration": 7,
    "fade_duration": 2,
    "max_quote_len": 50,
    "slots": "5,30;11,30;17,30;23,30",
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
    global_state["log"] = []
    add_log("Starting bot...")
    threading.Thread(target=bot_process).start()
    return jsonify({"status": "started"})

@app.route("/api/log", methods=["GET"])
def get_log():
    return jsonify(global_state["log"])

def bot_process():
    # Placeholder – replace with real logic
    add_log("Bot process placeholder - replace with full code.")
    pass

# ----------------------------------------------------------------------
# Full HTML Frontend (complete)
# ----------------------------------------------------------------------
HTML_CONTENT = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>YouTube Shorts Bot</title>
<style>
  :root {
    --bg: #0f0f1a;
    --surface: #1a1a2e;
    --primary: #6c63ff;
    --primary-hover: #5a52d5;
    --danger: #f50057;
    --text: #eaeaea;
    --muted: #888;
    --border-radius: 12px;
    --shadow: 0 4px 20px rgba(0,0,0,0.4);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    font-family: 'Segoe UI', system-ui, sans-serif;
    color: var(--text);
    display: flex;
    justify-content: center;
    padding: 20px;
    min-height: 100vh;
  }
  .container {
    width: 100%;
    max-width: 900px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  h1 { text-align: center; font-weight: 600; font-size: 2rem; margin-bottom: 10px; }
  .tabs {
    display: flex;
    gap: 10px;
    background: var(--surface);
    padding: 5px;
    border-radius: var(--border-radius);
  }
  .tab {
    flex: 1;
    padding: 10px;
    text-align: center;
    cursor: pointer;
    border-radius: 8px;
    font-weight: 500;
    transition: background 0.2s;
  }
  .tab.active { background: var(--primary); color: white; }
  .tab:not(.active):hover { background: rgba(108,99,255,0.2); }
  .panel {
    background: var(--surface);
    border-radius: var(--border-radius);
    padding: 25px;
    box-shadow: var(--shadow);
    display: none;
  }
  .panel.active { display: block; }
  .card {
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 20px;
  }
  .row {
    display: flex;
    gap: 20px;
    flex-wrap: wrap;
  }
  .col { flex: 1; min-width: 200px; }
  label {
    display: block;
    margin-bottom: 6px;
    font-weight: 500;
    color: var(--muted);
  }
  input, textarea, select, button {
    background: #2a2a3c;
    border: 1px solid #3a3a4c;
    border-radius: 6px;
    color: white;
    padding: 10px 14px;
    font-size: 0.95rem;
    width: 100%;
    transition: 0.2s;
  }
  input:focus, textarea:focus { outline: none; border-color: var(--primary); }
  button {
    background: var(--primary);
    border: none;
    cursor: pointer;
    font-weight: 600;
    letter-spacing: 0.5px;
  }
  button:hover { background: var(--primary-hover); }
  button.secondary { background: var(--danger); }
  button.secondary:hover { background: #c51162; }
  .log-box {
    background: #0a0a15;
    border-radius: 8px;
    padding: 15px;
    height: 300px;
    overflow-y: auto;
    font-family: monospace;
    font-size: 0.85rem;
    white-space: pre-wrap;
    line-height: 1.5;
  }
  .status-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-weight: 600;
    font-size: 0.8rem;
  }
  .badge-green { background: #00c853; color: white; }
  .badge-yellow { background: #ffd600; color: black; }
  .badge-red { background: #ff1744; color: white; }
  .inline { display: flex; gap: 10px; align-items: center; }
  .mt-1 { margin-top: 10px; }
  .mt-2 { margin-top: 20px; }
  .file-upload {
    border: 2px dashed #3a3a4c;
    border-radius: 8px;
    padding: 20px;
    text-align: center;
    cursor: pointer;
    transition: 0.2s;
  }
  .file-upload:hover { border-color: var(--primary); }
</style>
</head>
<body>
<div class="container">
  <h1>🎬 YouTube Shorts Bot</h1>
  <div class="tabs">
    <div class="tab active" onclick="switchTab('settings')">⚙️ Settings</div>
    <div class="tab" onclick="switchTab('auth')">🔐 Auth</div>
    <div class="tab" onclick="switchTab('run')">🚀 Run</div>
    <div class="tab" onclick="switchTab('export')">📦 Import/Export</div>
  </div>

  <!-- Settings Panel -->
  <div id="panel-settings" class="panel active">
    <div class="card">
      <div class="row">
        <div class="col">
          <label>Duration (seconds)</label>
          <input type="number" id="total_duration" value="7" min="5" max="15">
        </div>
        <div class="col">
          <label>Fade-in (seconds)</label>
          <input type="number" id="fade_duration" value="2" min="0.5" max="3" step="0.1">
        </div>
        <div class="col">
          <label>Max quote length</label>
          <input type="number" id="max_quote_len" value="50" min="30" max="100">
        </div>
      </div>
    </div>
    <div class="card">
      <label>Upload Slots (UTC) – hour,min;...</label>
      <input type="text" id="slots" value="5,30;11,30;17,30;23,30">
    </div>
    <div class="card">
      <label>Base Tags (comma separated)</label>
      <input type="text" id="base_tags" value="shorts, quotes, motivation, wisdom">
    </div>
    <div class="card">
      <label>Extra Description Line</label>
      <textarea id="description_extra" rows="2">💡 Quote of the day | Motivational quotes | Motivational speech | Motivational video | Understanding politics</textarea>
    </div>
    <div class="card">
      <label>Category ID</label>
      <input type="text" id="category_id" value="22">
    </div>
    <button onclick="saveSettings()">💾 Save Settings</button>
  </div>

  <!-- Auth Panel -->
  <div id="panel-auth" class="panel">
    <div class="card">
      <h3>1. Upload client_secret.json</h3>
      <div class="file-upload" id="dropzone">
        <p>Drag & drop or click to upload</p>
        <input type="file" id="client_secret_file" accept=".json" hidden>
      </div>
      <button onclick="document.getElementById('client_secret_file').click()">📁 Choose File</button>
      <span id="uploadStatus" class="mt-1"></span>
    </div>
    <div class="card">
      <h3>2. Authorize</h3>
      <div class="inline mt-1">
        <input type="text" id="auth_url" readonly placeholder="Authorization URL will appear here...">
        <button onclick="copyAuthUrl()">📋 Copy</button>
      </div>
      <div class="inline mt-1">
        <input type="text" id="auth_code" placeholder="Paste the code here...">
        <button onclick="authenticate()">🔑 Authenticate</button>
      </div>
      <span id="authStatus" class="mt-1"></span>
    </div>
    <div class="card" id="downloadConfigCard" style="display:none;">
      <h3>✅ Authenticated! Download your config file:</h3>
      <button onclick="downloadConfigAfterAuth()">📥 Download Config</button>
      <p class="mt-1" style="color:var(--muted);">Next time, just go to Import/Export and upload this file – no need to repeat steps 1 & 2.</p>
    </div>
    <div class="card">
      <h3>3. Token Status</h3>
      <div id="tokenStatus" class="status-badge badge-red">Not authenticated</div>
    </div>
  </div>

  <!-- Run Panel -->
  <div id="panel-run" class="panel">
    <button onclick="startBot()" style="margin-bottom:20px;">▶️ Start Processing</button>
    <div class="log-box" id="logBox"></div>
  </div>

  <!-- Import/Export Panel -->
  <div id="panel-export" class="panel">
    <div class="card">
      <h3>Export Configuration</h3>
      <button onclick="exportConfig()">📥 Download Config File</button>
    </div>
    <div class="card mt-2">
      <h3>Import Configuration</h3>
      <input type="file" id="import_file" accept=".json">
      <button onclick="importConfig()" class="mt-1">📤 Restore Config</button>
      <span id="importStatus" class="mt-1"></span>
    </div>
  </div>
</div>

<script>
  function switchTab(tab) {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('panel-' + tab).classList.add('active');
    event.target.classList.add('active');
  }

  document.getElementById('client_secret_file').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    fetch('/api/auth/upload_client_secret', { method: 'POST', body: formData })
      .then(r => r.json())
      .then(data => {
        if (data.auth_url) {
          document.getElementById('auth_url').value = data.auth_url;
          document.getElementById('uploadStatus').innerHTML = '<span class="status-badge badge-green">✅ Loaded</span>';
        } else {
          document.getElementById('uploadStatus').innerHTML = '<span class="status-badge badge-red">❌ Error: ' + data.error + '</span>';
        }
      });
  });

  document.getElementById('dropzone').addEventListener('click', () => document.getElementById('client_secret_file').click());

  function copyAuthUrl() {
    const input = document.getElementById('auth_url');
    input.select();
    document.execCommand('copy');
  }

  let latestConfig = null;

  function authenticate() {
    const code = document.getElementById('auth_code').value.trim();
    if (!code) return alert('Paste the code first');
    fetch('/api/auth/authenticate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code})
    })
    .then(r => r.json())
    .then(data => {
      if (data.status === 'authenticated') {
        document.getElementById('authStatus').innerHTML = '<span class="status-badge badge-green">✅ Authenticated</span>';
        latestConfig = data.config;
        document.getElementById('downloadConfigCard').style.display = 'block';
        updateTokenStatus();
      } else {
        document.getElementById('authStatus').innerHTML = '<span class="status-badge badge-red">❌ ' + data.error + '</span>';
      }
    });
  }

  function downloadConfigAfterAuth() {
    if (!latestConfig) return;
    const blob = new Blob([JSON.stringify(latestConfig, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'shorts_bot_config.json';
    a.click();
  }

  function updateTokenStatus() {
    fetch('/api/auth/status')
      .then(r => r.json())
      .then(data => {
        const el = document.getElementById('tokenStatus');
        if (data.status === 'valid') {
          el.className = 'status-badge badge-green';
          el.textContent = 'Token valid';
        } else if (data.status === 'expired_refreshable') {
          el.className = 'status-badge badge-yellow';
          el.textContent = 'Expired (refreshable)';
        } else {
          el.className = 'status-badge badge-red';
          el.textContent = 'Not authenticated';
        }
      });
  }
  setInterval(updateTokenStatus, 30000);
  updateTokenStatus();

  function saveSettings() {
    const settings = {
      total_duration: parseFloat(document.getElementById('total_duration').value),
      fade_duration: parseFloat(document.getElementById('fade_duration').value),
      max_quote_len: parseInt(document.getElementById('max_quote_len').value),
      slots: document.getElementById('slots').value,
      base_tags: document.getElementById('base_tags').value,
      description_extra: document.getElementById('description_extra').value,
      category_id: document.getElementById('category_id').value
    };
    fetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(settings)
    }).then(() => alert('Settings saved!'));
  }

  function startBot() {
    fetch('/api/run', { method: 'POST' })
      .then(() => {
        document.getElementById('logBox').textContent = 'Starting bot...\n';
        pollLog();
      });
  }

  function pollLog() {
    fetch('/api/log')
      .then(r => r.json())
      .then(lines => {
        document.getElementById('logBox').textContent = lines.join('\n');
        if (!lines.includes('Finished.') && !lines.includes('ERROR')) {
          setTimeout(pollLog, 2000);
        }
      });
  }

  function exportConfig() {
    fetch('/api/export')
      .then(r => r.json())
      .then(data => {
        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'shorts_bot_config.json';
        a.click();
      });
  }

  function importConfig() {
    const fileInput = document.getElementById('import_file');
    const file = fileInput.files[0];
    if (!file) return alert('Select a file first');
    const reader = new FileReader();
    reader.onload = function(e) {
      try {
        const config = JSON.parse(e.target.result);
        fetch('/api/import', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(config)
        })
        .then(r => r.json())
        .then(data => {
          if (data.status === 'imported') {
            document.getElementById('importStatus').innerHTML = '<span class="status-badge badge-green">✅ Config restored</span>';
            if (data.settings) {
              document.getElementById('total_duration').value = data.settings.total_duration;
              document.getElementById('fade_duration').value = data.settings.fade_duration;
              document.getElementById('max_quote_len').value = data.settings.max_quote_len;
              document.getElementById('slots').value = data.settings.slots;
              document.getElementById('base_tags').value = data.settings.base_tags;
              document.getElementById('description_extra').value = data.settings.description_extra;
              document.getElementById('category_id').value = data.settings.category_id;
            }
            updateTokenStatus();
          } else {
            document.getElementById('importStatus').innerHTML = '<span class="status-badge badge-red">❌ Import failed</span>';
          }
        });
      } catch(e) {
        alert('Invalid JSON file');
      }
    };
    reader.readAsText(file);
  }
</script>
</body>
</html>
"""

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
    with open("index.html", "w") as f:
        f.write("<script>window.location.href='/frontend';</script>")
    threading.Thread(target=start_ngrok, daemon=True).start()
    time.sleep(2)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
